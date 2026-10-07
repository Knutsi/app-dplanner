"""What agent runs consumed, in the running application: the Expenditure tab and the sweep.

**The ledger is read, never kept here.** Each run's record lives in its project's ledger
(``domain/ledger.py``); the launch writes it and the run tracker marks its end
(``aspect.py``'s ``launch_record`` and ``end``), and a *harvest* (``harvest.py``) reads what
the agent CLI says it consumed back into it. This module's share is the window's half of
the harvest — **the sweep**, at start, every few minutes and whenever a run ends, through a
``TaskRunner``, started only when a run of this machine is due — and the one surface that
reads the ledger whole. **The window's start also picks up this machine's lost headless
turns** (``agent_supervisor.supervisor.revive``): a reboot or a killed supervisor leaves a
run whose last turn never ended, and a new supervisor ends it ``failed``/``lost`` and
retries — read from the same records the sweep reads, once; a launch interrupted between
its record and its supervisor is started while its step is claimed and dropped once not.

**Expenditure** is the order read for what it consumed: each step's agent runs, in tokens,
against what its estimate predicted (``expenditure_activity.py`` has the tab, its columns and words,
``domain/expenditure.py`` the walk). The rows are the Order tab's — ``framework/step_table``'s
``StepTable``, the same switches and gestures — because what was spent is read in the order
the work is done.

The id is the retired per-step ``agent_usage`` aspect's, and so is the format this module
declares: what is still on a step is absorbed into the ledger at every open, the window's as
well as the CLI's.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFileDialog, QWidget

from dplanner.core.fsio import write_csv
from dplanner.domain.agents import AgentHarness
from dplanner.domain.model import Library, NodeId, StepId
from dplanner.domain.store import LibraryStore
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.activity import (
    follow_project_tabs,
)
from dplanner.framework.context import (
    Context,
    ContextService,
)
from dplanner.framework.debounce import DebounceService
from dplanner.framework.step_selection import focused_project
from dplanner.framework.tabs import TabHost
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.modules.agent_supervisor import supervisor
from dplanner.modules.agent_usage import harvest
from dplanner.modules.agent_usage.aspect import (
    DATA_FORMAT,
    MODULE_ID,
    ledger_dir,
)
from dplanner.modules.agent_usage.expenditure_activity import (
    EXPENDITURE_KIND,
    ExpenditureActivity,
    expenditure_of,
    export_rows,
    rate_of,
)
from dplanner.planning.kinds import key_of
from dplanner.theme.icons import spark_icon

SWEEP_MS = 5 * 60 * 1000


@dataclass(frozen=True)
class AgentUsageDeps:
    library: Library
    # Where each project keeps its ledger: the store's to know.
    store: LibraryStore
    actions: ActionRegistry
    context: ContextService
    parent: QWidget  # The CSV export's file dialog needs a window to parent on.
    debounce: DebounceService
    tabs: TabHost
    # Every agent CLI this build knows: a harvest asks the run's own for its records.
    harnesses: tuple[AgentHarness, ...] = ()
    # Runs the sweep off the GUI thread; None reads nothing back.
    tasks: TaskService | None = None
    # Told when a sweep has written what the runs consumed — the Agents browser says it.
    swept: Callable[[], None] = lambda: None
    # The row look the Order tab gives a step: the kinds its glyph is drawn from, its
    # milestone's shade, and whether it is finished — which also decides the steps a rate
    # is learned from. All from the composition root, as the Order tab's are.
    step_icons: Callable[[StepId], tuple[str, ...]] = field(default=lambda _step_id: ())
    milestone_color: Callable[[StepId], str] = field(default=lambda _step_id: "")
    step_done: Callable[[StepId], bool] = field(default=lambda _step_id: False)


class AgentUsageModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: AgentUsageDeps) -> None:
        self._deps = deps
        self._runner: TaskRunner | None = None
        self._sweep_again = False

    def open_expenditure(self, project_id: NodeId, *, preview: bool = False) -> None:
        self._deps.tabs.open(EXPENDITURE_KIND, project_id, preview=preview)

    def register(self) -> None:
        deps = self._deps

        def expenditure_factory(target: str | None) -> ExpenditureActivity:
            assert target is not None
            return ExpenditureActivity(deps, target)

        deps.tabs.register_factory(EXPENDITURE_KIND, expenditure_factory)
        deps.actions.register(
            ActionSpec(
                id="expenditure.open",
                label="E&xpenditure",
                menu="Go",
                group="views",
                order=27,
                icon=spark_icon,
                tip="What each step's agent runs consumed, in tokens, against what was expected",
                state=self._on_a_project,
                run=self._open_expenditure,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="expenditure.export",
                label="&Expenditure (CSV)…",
                menu="File",
                group="export",
                submenu="Export",
                order=15,
                tip="Write what the focused project's steps consumed to a CSV file:"
                " a row per step and model",
                state=self._on_a_project,
                run=self._export_expenditure,
            )
        )
        follow_project_tabs(deps.tabs, ExpenditureActivity, deps.library)
        supervisor.revive(self._ledger_dirs(), library=deps.store.library_path)
        if deps.tasks is not None:
            self._runner = TaskRunner(deps.tasks, deps.parent)
            self._runner.busy_changed.connect(self._on_sweep_busy)
            sweep_timer = QTimer(deps.parent)
            sweep_timer.setInterval(SWEEP_MS)
            sweep_timer.timeout.connect(self.sweep)
            sweep_timer.start()
        self.sweep()

    # -- the sweep -----------------------------------------------------------------------------

    def sweep(self) -> None:
        """Harvest every run of this machine that is due, in the background; a sweep asked
        for while one runs goes again once it is done, never queued twice."""
        if self._runner is None:
            return
        deps = self._deps
        dirs = self._ledger_dirs()
        if not harvest.anything_due(dirs):
            return
        harnesses = deps.harnesses

        def body() -> None:
            harvest.sweep(dirs, harnesses)

        if not self._runner.run("Reading agent usage", body, key="agent_run.sweep"):
            self._sweep_again = True

    def _ledger_dirs(self) -> list[Path]:
        deps = self._deps
        return [
            directory
            for project in deps.library.projects
            if (directory := ledger_dir(deps.store, project.id)) is not None
        ]

    def _on_sweep_busy(self, busy: bool) -> None:
        if busy:
            return
        self._deps.swept()
        if self._sweep_again:
            self._sweep_again = False
            self.sweep()

    # -- Expenditure ---------------------------------------------------------------------------

    def _on_a_project(self, context: Context) -> ActionState:
        return DISABLED if focused_project(context, self._deps.library) is None else ENABLED

    def _open_expenditure(self, context: Context) -> None:
        project = focused_project(context, self._deps.library)
        if project is not None:
            self.open_expenditure(project.id)

    def _export_expenditure(self, context: Context) -> None:
        deps = self._deps
        project = focused_project(context, deps.library)
        if project is None:
            return
        found = expenditure_of(deps, project.id, rate_of(deps, project.id))
        rows = export_rows(
            found, lambda step_id: key_of(deps.library.step(step_id)), deps.step_done
        )
        suggested = f"{project.title or 'Untitled project'} expenditure.csv"
        chosen, _filter = QFileDialog.getSaveFileName(
            deps.parent, "Export Expenditure", str(Path.home() / suggested), "CSV files (*.csv)"
        )
        if not chosen:
            return
        path = Path(chosen)
        write_csv(path if path.suffix.lower() == ".csv" else path.with_suffix(".csv"), rows)
