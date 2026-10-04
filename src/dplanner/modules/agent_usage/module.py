"""What agent runs consumed, in the running application: the Expenditure tab and the sweep.

**The ledger is read, never kept here.** Each run's record lives in its project's ledger
(``domain/ledger.py``); the launch writes it and the run tracker marks its end
(``aspect.py``'s ``launch_record`` and ``end``), and a *harvest* (``harvest.py``) reads what
the agent CLI says it consumed back into it. This module's share is the window's half of
the harvest — **the sweep**, at start, every few minutes and whenever a run ends, through a
``TaskRunner``, started only when a run of this machine is due — and the one surface that
reads the ledger whole.

**Expenditure** is the order read for what it consumed: each step's agent runs, in tokens,
against what its estimate predicted (``expenditure.py`` has its columns and words,
``domain/expenditure.py`` the walk). The rows are the Order tab's — ``framework/step_table``'s
``StepTable``, the same switches and gestures — because what was spent is read in the order
the work is done.

The id is the retired per-step ``agent_usage`` aspect's, and so is the format this module
declares: what is still on a step is absorbed into the ledger at every open, the window's as
well as the CLI's.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QVBoxLayout, QWidget

from dplanner.core.fsio import write_csv
from dplanner.domain.agents import AgentHarness
from dplanner.domain.expenditure import Rate, Row, Spent, expenditure, models_in
from dplanner.domain.model import Library, NodeId, ProjectId, StepId
from dplanner.domain.ordering import placed
from dplanner.domain.store import LibraryStore
from dplanner.framework.action_menu import build_menu
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.activity import (
    EntityActivity,
    follow_project,
    follow_project_tabs,
    project_tab_title,
)
from dplanner.framework.context import (
    SCOPE_SELECTION,
    Context,
    ContextNode,
    ContextService,
    Uri,
    activity_uri,
    selection_uri,
)
from dplanner.framework.debounce import Debounced, DebounceService
from dplanner.framework.signalling import UpdatingIndicator
from dplanner.framework.step_selection import focused_project
from dplanner.framework.step_table import StepTable
from dplanner.framework.tabs import TabHost
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.toolbar import ActionToolbar
from dplanner.framework.widgets import EmptyState, captioned, note
from dplanner.modules.agent_usage import harvest
from dplanner.modules.agent_usage.aspect import (
    DATA_FORMAT,
    MODULE_ID,
    ledger_dir,
    ledger_stamp,
    step_spent,
    token_rate,
)
from dplanner.modules.agent_usage.expenditure import (
    EXPENDITURE_KIND,
    columns,
    export_rows,
    rate_words,
    row_cells,
)
from dplanner.modules.agent_usage.expenditure import (
    volume_words as spent_words,
)
from dplanner.planning.estimate import start_of
from dplanner.planning.kinds import key_of, works_nobody
from dplanner.planning.milestone import read as milestone_label
from dplanner.planning.schedule import schedule
from dplanner.theme.icons import spark_icon

PANEL_MARGIN = 16
CAPTION_GAP = 6
BLOCK_GAP = 12
SWITCH_GAP = 16
# How often the Expenditure tab looks at the ledger: another process writes it.
LEDGER_POLL_MS = 2000
SWEEP_MS = 5 * 60 * 1000


def _step_context(step_id: StepId) -> Context:
    """A context naming exactly one step — what a row's double-click runs a verb against."""
    return Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step_id)),)})


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


def _rate(deps: AgentUsageDeps, project_id: ProjectId) -> Rate | None:
    """Tokens of work per estimated day, learned from the library's finished steps."""
    return token_rate(deps.store, deps.library, project_id, lambda s: deps.step_done(s.id))


class ExpenditureActivity(EntityActivity):
    """One project's steps, in order, with what their agents consumed."""

    def __init__(self, deps: AgentUsageDeps, project_id: NodeId) -> None:
        super().__init__(deps.context, "project", project_id)
        self._deps = deps
        self._product = deps.library
        self.project_id = project_id
        self._models: tuple[str, ...] = ()
        self._stamp: object = None

        page = QWidget()
        self._widget = page
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(CAPTION_GAP)
        head = QHBoxLayout()
        layout.addLayout(head)
        head.addWidget(
            captioned(
                "Expenditure",
                page,
                hint="Tokens each step's agent runs consumed — the main agent and every"
                " subagent — in the order the work can be done, against what the step's"
                " estimate predicted. Fresh input and output are the work; cache reads are"
                " context read again, counted apart.",
            ),
            1,
        )
        self.toolbar = ActionToolbar(
            deps.actions,
            deps.context,
            ("expenditure.export",),
            {"expenditure.export": "Export"},
            page,
            menus={"expenditure.export": ("File", "Export")},
        )
        head.addWidget(self.toolbar)
        self.updating = UpdatingIndicator(page)
        head.addWidget(self.updating)
        self.volume = note("", page)
        layout.addWidget(self.volume)
        layout.addSpacing(BLOCK_GAP)

        switches = QWidget(page)
        switch_row = QHBoxLayout(switches)
        switch_row.setContentsMargins(0, 0, 0, 0)
        switch_row.setSpacing(SWITCH_GAP)
        self.show_steps = QCheckBox("Steps", switches)
        self.show_features = QCheckBox("Features", switches)
        for switch in (self.show_steps, self.show_features):
            switch.setChecked(True)
            switch.toggled.connect(self._on_kinds)
            switch_row.addWidget(switch)
        # One step may run on several models (a playbook's stages): a pair of columns each.
        self.by_model = QCheckBox("By model", switches)
        self.by_model.toggled.connect(lambda _on: self._refresh())
        switch_row.addWidget(self.by_model)
        switch_row.addStretch(1)
        layout.addWidget(switches)
        layout.addSpacing(CAPTION_GAP)

        self._layout = layout
        self.table = self._new_table(())
        layout.addWidget(self.table, 1)
        self.empty = EmptyState(parent=page, stands_in_for=self.table)
        layout.addWidget(self.empty, 1)

        self._refresh_soon = Debounced(self._refresh, parent=page, service=deps.debounce)
        self.updating.follow(self._refresh_soon)
        self._unsubscribes = [
            follow_project(self._product, self.project_id, self._refresh_soon.trigger),
        ]
        # An agent's harvest writes the ledger from another process, and nothing in the
        # model says so: the tab looks, cheaply, and rebuilds only when it changed.
        self._poll = QTimer(page)
        self._poll.setInterval(LEDGER_POLL_MS)
        self._poll.timeout.connect(self._check_ledger)
        self._poll.start()
        self._refresh()

    # -- the activity contract -----------------------------------------------------------------

    @property
    def uri(self) -> Uri:
        return activity_uri(EXPENDITURE_KIND, self.project_id)

    @property
    def title(self) -> str:
        return project_tab_title(self._product, self.project_id, "Expenditure")

    @property
    def widget(self) -> QWidget:
        return self._widget

    def on_activated(self) -> None:
        super().on_activated()
        self._publish(self.table.selected_step())

    def close(self) -> None:
        self._poll.stop()
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self.toolbar.dispose()

    # -- internals -----------------------------------------------------------------------------

    def _refresh(self) -> None:
        if not self._product.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        deps = self._deps
        self._stamp = ledger_stamp(deps.store, self.project_id)
        rate = _rate(deps, self.project_id)
        rows = expenditure_of(deps, self.project_id, rate)
        models = tuple(models_in(rows)) if self.by_model.isChecked() else ()
        if models != self._models:
            self._replace_table(models)
        by_step = {row.place.step.id: row for row in rows}
        self.table.show_steps(
            [row.place for row in rows],
            lambda place, fixed: row_cells(by_step[place.step.id], fixed, models),
        )
        self._on_kinds()
        work = [row.place.step for row in rows if not works_nobody(row.place.step)]
        finished = sum(deps.step_done(step.id) for step in work)
        self.volume.setText(spent_words(rows, finished, len(work)))
        self.volume.setToolTip(rate_words(rate))
        self.volume.setVisible(bool(rows))
        self.empty.say("" if rows else "Steps appear here in the order they can be done.")

    def _check_ledger(self) -> None:
        if not self._product.has(self.project_id):
            return
        if ledger_stamp(self._deps.store, self.project_id) != self._stamp:
            self._refresh_soon.trigger()

    def _new_table(self, models: Sequence[str]) -> StepTable:
        # Built parentless and adopted by the layout: a Table built as the child of a page
        # already on screen kept an 18-pixel header the stylesheet never padded
        # (NOTES-FOR-APPFRAME.md has the measurement).
        deps = self._deps
        table = StepTable(
            columns(models),
            lambda step_id: milestone_label(deps.library.step(step_id)),
            deps.step_icons,
            deps.milestone_color,
            lambda step_id: key_of(deps.library.step(step_id)),
            deps.step_done,
        )
        table.itemSelectionChanged.connect(lambda: self._publish(table.selected_step()))
        table.cellActivated.connect(self._on_activated)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._on_context_menu)
        return table

    def _replace_table(self, models: Sequence[str]) -> None:
        """A table's columns are its own from birth: another set of models is another one."""
        old = self.table
        self.table = self._new_table(models)
        self._layout.replaceWidget(old, self.table)
        self.empty.stands_in_for = self.table
        old.hide()
        old.deleteLater()
        self._models = tuple(models)

    def _on_kinds(self) -> None:
        self.table.show_kinds(
            steps=self.show_steps.isChecked(), features=self.show_features.isChecked()
        )

    def _publish(self, step_id: StepId | None) -> None:
        nodes = () if step_id is None else (ContextNode(selection_uri("step", step_id)),)
        self.publish_selection(nodes)

    def _on_activated(self, row: int, _column: int) -> None:
        step_id = self.table.step_at(row)
        if step_id is not None:
            self._deps.actions.run("steps.details", _step_context(step_id))

    def _on_context_menu(self, position: object) -> None:
        assert isinstance(position, QPoint)
        row = self.table.rowAt(position.y())
        if self.table.step_at(row) is None:
            return
        self.table.selectRow(row)
        menu = build_menu(self._deps.actions, self._deps.context, "Step", self.table)
        menu.exec(self.table.viewport().mapToGlobal(position))


def expenditure_of(deps: AgentUsageDeps, project_id: ProjectId, rate: Rate | None) -> list[Row]:
    """The project's order with what each step consumed — the tab's rows and the export's."""
    project = deps.library.project(project_id)
    order = placed(deps.library, project)
    days = {row.place.step.id: row.days for row in schedule(order, start_of(project))}
    spent = step_spent(deps.store, project_id)
    return expenditure(
        order,
        lambda step: spent.get(step.id, Spent()),
        lambda step: days.get(step.id),
        lambda step: deps.step_done(step.id),
        rate,
    )


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
        dirs = [
            directory
            for project in deps.library.projects
            if (directory := ledger_dir(deps.store, project.id)) is not None
        ]
        if not harvest.anything_due(dirs):
            return
        harnesses = deps.harnesses

        def body() -> None:
            harvest.sweep(dirs, harnesses)

        if not self._runner.run("Reading agent usage", body, key="agent_run.sweep"):
            self._sweep_again = True

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
        found = expenditure_of(deps, project.id, _rate(deps, project.id))
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
