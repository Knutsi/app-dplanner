"""When the plan lands, as a tab beside the graph it dates — and the day's progress recorded.

The tab is ``activity.py``; this is the module that installs it: the Time tab's factory,
*Show Time Estimates* and *Export ▸ Milestones (CSV)*, the progress recorder that writes the
day's row into the project's history whenever the plan settles (``recorder.py``), and a
milestone's Schedule block on its Details tab (``section.py``) — its own start date and
colour.

The dating is the domain's (``phases`` over ``parallel_finish``), re-dated from what has
happened; this module stores only assumptions — the focus factor, the palette, the team,
and a milestone's date and colour (``schedule.py``) — plus the one thing that cannot be
derived: the recorded past (``progress.py``). The estimate, agent-step, status and
milestone readers arrive together as the root's :class:`Readers`, so this module never
learns what an estimate is stored as or what marks a step for an agent — the same seams the
CLI and the report are handed.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QWidget
from shiboken6 import isValid

from dplanner.cli.report.sheets import csv_rows
from dplanner.core.clock import Clock
from dplanner.core.fsio import write_csv
from dplanner.domain.model import Library, NodeId, ProjectId
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.activity import follow_entity_tabs
from dplanner.framework.context import Context, ContextService
from dplanner.framework.debounce import DebounceService
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.tabs import TabHost
from dplanner.framework.undo import UndoService
from dplanner.modules.time_estimates.activity import TIME_KIND, TimeEstimatesActivity
from dplanner.modules.time_estimates.cli import Readers
from dplanner.modules.time_estimates.progress import DATA_FORMAT as HISTORY_FORMAT
from dplanner.modules.time_estimates.progress import HISTORY_ID
from dplanner.modules.time_estimates.recorder import ProgressRecorder
from dplanner.modules.time_estimates.report import milestones_table
from dplanner.modules.time_estimates.schedule import DATA_FORMAT, MODULE_ID
from dplanner.modules.time_estimates.section import MilestoneScheduleSection

__all__ = ["TIME_KIND", "ProgressHistoryModule", "TimeEstimatesDeps", "TimeEstimatesModule"]


@dataclass(frozen=True)
class TimeEstimatesDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    debounce: DebounceService
    # Today: what every date on the page is read from, and what tells the tab and the
    # recorder that the day has turned.
    clock: Clock
    # Whether today is read at its end — a simulated day, which is over when it is shown —
    # or while it is still going, as the window reads it (``ScheduleFacts.day_over``).
    day_over: bool
    # Estimates, agent-ness, statuses, milestones and the start date through their owners'
    # Qt-free readers — the ones the CLI and the report are handed.
    readers: Readers
    # How a day picked on the calendar re-dates the plan — whoever owns start dates
    # answers, one undoable command per pick.
    set_start: Callable[[ProjectId, date], None]
    # The figure's way to the unsized steps: whoever owns estimates opens its list on them.
    estimate_missing: Callable[[ProjectId], None]
    # The Details tab's blocks, where a milestone's own start date and colour are set.
    details: InspectorSectionRegistry
    parent: QWidget  # The window: owns the progress recorder and the dialogs.


class TimeEstimatesModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: TimeEstimatesDeps) -> None:
        self._deps = deps
        self._recorder: ProgressRecorder | None = None

    def _export(self, context: Context) -> None:
        deps = self._deps
        project_id = context.focus_entity("project")
        if project_id is None or not deps.library.has(project_id):
            return
        project = deps.library.project(project_id)
        table = milestones_table(deps.library, project, deps.readers, deps.clock.today())
        if table is None:
            return
        suggested = f"{project.title or 'Untitled project'} milestones.csv"
        chosen, _filter = QFileDialog.getSaveFileName(
            deps.parent, "Export Milestones", str(Path.home() / suggested), "CSV files (*.csv)"
        )
        if not chosen:
            return
        path = Path(chosen)
        if path.suffix.lower() != ".csv":
            path = path.with_suffix(".csv")
        write_csv(path, csv_rows(table))

    def open(self, project_id: NodeId, *, preview: bool = False) -> None:
        self._deps.tabs.open(TIME_KIND, project_id, preview=preview)

    @property
    def recorder(self) -> ProgressRecorder | None:
        """The build's one recorder, while it lives — a test silences it through this."""
        return self._recorder if self._recorder is not None and isValid(self._recorder) else None

    def register(self) -> None:
        deps = self._deps

        def factory(target: str | None) -> TimeEstimatesActivity:
            assert target is not None
            return TimeEstimatesActivity(deps, target)

        deps.tabs.register_factory(TIME_KIND, factory)
        # The day's progress, written whenever the plan settles on something new — for
        # every project, whether or not its tab is open, because the history is the one
        # thing the page cannot derive later.
        self._recorder = ProgressRecorder(
            deps.library, deps.debounce, readers=deps.readers, clock=deps.clock, parent=deps.parent
        )
        self._recorder.start()
        deps.details.register(
            InspectorSection(
                id=f"{MODULE_ID}.details",
                label="Schedule",
                order=15,  # Beside the estimate (10), before the description (20).
                hint="Where the milestone's stretch begins, and the colour it wears.",
                factory=lambda: MilestoneScheduleSection(deps.library, deps.undo, deps.clock.today),
                shown_for=lambda step_id: (
                    step_id is not None
                    and deps.library.has(step_id)
                    and deps.readers.is_milestone(deps.library.step(step_id))
                ),
            )
        )
        deps.actions.register(
            ActionSpec(
                id="time.open",
                label="Show &Time Estimates",
                menu="Project",
                group="open",
                order=40,
                tip="When the plan lands with its team, how that moved, and the work behind it",
                state=self._on_a_project,
                run=self._open,
            )
        )
        # File ▸ Export ▸ Milestones (CSV): the milestones table the report shows, as data a
        # spreadsheet can compute with — beside the order list's CSV.
        deps.actions.register(
            ActionSpec(
                id="time.export",
                label="&Milestones (CSV)…",
                menu="File",
                group="export",
                submenu="Export",
                order=15,
                tip="Write the focused project's milestones — set date, landing, days — to CSV",
                state=self._on_a_project,
                run=self._export,
            )
        )
        follow_entity_tabs(
            deps.tabs,
            TimeEstimatesActivity,
            deps.library.has,
            closes_on=deps.library.structure_changed,
            retitles_on=deps.library.field_changed,
        )

    def _on_a_project(self, context: Context) -> ActionState:
        project_id = context.focus_entity("project")
        if project_id is None or not self._deps.library.has(project_id):
            return DISABLED
        return ENABLED

    def _open(self, context: Context) -> None:
        project_id = context.focus_entity("project")
        if project_id is not None:
            self.open(project_id)


class ProgressHistoryModule:
    """Declares the progress history's format only — ``DocsCompiledModule``'s shape.

    ``builder.py`` collects one ``data_format`` per module, and the history lives under an
    id of its own beside the assumptions, so the second format needs a second declarer.
    The recorder above and ``dplanner progress record`` write it; nothing to install.
    """

    id = HISTORY_ID
    data_format = HISTORY_FORMAT

    def register(self) -> None:
        return None
