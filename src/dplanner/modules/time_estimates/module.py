"""How long the project takes with a stated team, as a tab beside the graph it prices.

The page leads with the answer: a landing date for the selected team, then one heatmap of
every staffing (clicking a tile re-asks the question), then a computed sentence saying
what the grid means — which axis still buys time, and where the dependency floor is.
Calendar days and project days are two lenses on one simulation, so they are a toggle
over one grid rather than two tables side by side.

The simulation is the domain's (``parallel_finish``); this module renders it and stores
exactly one thing — the focus factor (see ``schedule.py`` beside this file). The
estimate, agent-step and start-date readers arrive as functions on the Deps, so this
module never learns what an estimate is stored as or what marks a step for an agent —
the same seams the progression board uses.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.model import Library, NodeId, Project, ProjectId, Step
from dplanner.domain.schedule import format_date, format_day_count, format_days
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.activity import EntityActivity, follow_entity_tabs
from dplanner.framework.context import Context, ContextService, Uri, activity_uri
from dplanner.framework.tabs import TabHost
from dplanner.framework.undo import UndoService
from dplanner.modules.time_estimates.months import MonthsView
from dplanner.modules.time_estimates.schedule import (
    MODULE_ID,
    Cell,
    TimeReport,
    read_efficiency,
    time_report,
)
from dplanner.modules.time_estimates.view import FLOOR_TOLERANCE, FocusBar, MatrixView

TIME_KIND = "time"

PANEL_MARGIN = 16
CAPTION_GAP = 6
BLOCK_GAP = 12
BUTTON_GAP = 4

# The headline is the one loud thing on the page: the answer, a few points up.
HEADLINE_POINTS = 5


@dataclass(frozen=True)
class TimeEstimatesDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    # Estimates and agent-ness through the aspects' Qt-free readers — the matrix never
    # learns what either is stored as.
    days_for: Callable[[Step], float | None]
    is_agent: Callable[[Step], bool]
    # When the project's work begins, and how a calendar click re-dates it — whoever
    # owns start dates answers both, one undoable command per click.
    start_of: Callable[[ProjectId], date]
    set_start: Callable[[ProjectId, date], None]


def _team(humans: int, agents: int) -> str:
    people = f"{humans} {'person' if humans == 1 else 'people'}"
    return f"{people} + {agents} {'agent' if agents == 1 else 'agents'}"


class TimeEstimatesActivity(EntityActivity):
    """One project's staffing heatmap, led by the selected team's landing date."""

    def __init__(self, deps: TimeEstimatesDeps, project_id: NodeId) -> None:
        super().__init__(deps.context, "project", project_id)
        self._deps = deps
        self._product = deps.library
        self.project_id = project_id
        self._report: TimeReport | None = None
        self._calendar_lens = True

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(CAPTION_GAP)

        caption = QLabel("Time Estimates", page)
        caption.setObjectName("InspectorCaption")
        layout.addWidget(caption)

        layout.addSpacing(BLOCK_GAP)
        self.focus_bar = FocusBar(deps.library, deps.undo, project_id, page)
        layout.addWidget(self.focus_bar)

        layout.addSpacing(BLOCK_GAP)
        self.lens_bar = QWidget(page)
        lens_row = QHBoxLayout(self.lens_bar)
        lens_row.setContentsMargins(0, 0, 0, 0)
        lens_row.setSpacing(BUTTON_GAP)
        self._lenses = QButtonGroup(page)
        self._lenses.setExclusive(True)
        self.calendar_button = self._lens_button("Calendar days")
        self.project_button = self._lens_button("Project days")
        for index, button in enumerate((self.calendar_button, self.project_button)):
            self._lenses.addButton(button, index)
            lens_row.addWidget(button)
        lens_row.addStretch(1)
        self.calendar_button.setChecked(True)
        self._lenses.idClicked.connect(self._on_lens)
        layout.addWidget(self.lens_bar)

        self.matrix = MatrixView(page)
        self.matrix.tooltip_for = self._tooltip
        self.matrix.scenario_changed.connect(self._render)
        layout.addWidget(self.matrix, 0, Qt.AlignmentFlag.AlignLeft)

        # The result reads below the choice: pick a tile, the landing date answers under it,
        # and the months show the same answer as a lit span on a real calendar.
        layout.addSpacing(BLOCK_GAP)
        self.headline = QLabel(page)
        loud = QFont(self.headline.font())
        loud.setPointSizeF(loud.pointSizeF() + HEADLINE_POINTS)
        loud.setWeight(QFont.Weight.DemiBold)
        self.headline.setFont(loud)
        layout.addWidget(self.headline)
        self.detail = QLabel(page)
        self.detail.setObjectName("InspectorNote")
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)

        layout.addSpacing(BLOCK_GAP)
        pager = QWidget(page)
        pager_row = QHBoxLayout(pager)
        pager_row.setContentsMargins(0, 0, 0, 0)
        pager_row.setSpacing(BUTTON_GAP)
        self.earlier = self._pager_button(pager, Qt.ArrowType.LeftArrow, "Earlier months")
        self.later = self._pager_button(pager, Qt.ArrowType.RightArrow, "Later months")
        pager_row.addWidget(self.earlier)
        pager_row.addWidget(self.later)
        pager_row.addStretch(1)
        layout.addWidget(pager)
        self.pager = pager

        self.months = MonthsView(page)
        self.months.day_picked.connect(self._on_day_picked)
        layout.addWidget(self.months, 0, Qt.AlignmentFlag.AlignLeft)

        layout.addSpacing(BLOCK_GAP)
        self.insight = QLabel(page)
        self.insight.setObjectName("InspectorNote")
        self.insight.setWordWrap(True)
        layout.addWidget(self.insight)

        self.unestimated_note = QLabel(page)
        self.unestimated_note.setObjectName("InspectorNote")
        self.unestimated_note.setWordWrap(True)
        layout.addWidget(self.unestimated_note)

        self.agent_note = QLabel(
            "No agent steps — agent capacity does not change these numbers. Mark steps for "
            "agent execution under Step ▸ Type.",
            page,
        )
        self.agent_note.setObjectName("InspectorNote")
        self.agent_note.setWordWrap(True)
        layout.addWidget(self.agent_note)

        layout.addStretch(1)

        # The grid and the months are fixed-size drawings, so a small window scrolls the
        # page rather than clipping them or squeezing the text below into them.
        scroller = QScrollArea()
        scroller.setWidget(page)
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        self._widget = scroller
        self._unsubscribes = [
            self._product.structure_changed.connect(lambda *_a: self._refresh()),
            self._product.edges_changed.connect(lambda *_a: self._refresh()),
            self._product.module_data_changed.connect(lambda *_a: self._refresh()),
            # A separate agent instruction is prose, and carrying one marks the step as
            # agent work — so a text edit can move a step between pools.
            self._product.text_edited.connect(lambda *_a: self._refresh()),
        ]
        self._refresh()

    def _lens_button(self, label: str) -> QToolButton:
        button = QToolButton(self.lens_bar)
        button.setObjectName("ToolbarButton")
        button.setText(label)
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _pager_button(self, parent: QWidget, arrow: Qt.ArrowType, tip: str) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName("ToolbarButton")
        button.setArrowType(arrow)
        button.setToolTip(tip)
        button.setAutoRepeat(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        step = -1 if arrow == Qt.ArrowType.LeftArrow else 1
        button.clicked.connect(lambda: self.months.page(step))
        return button

    # -- the activity contract -----------------------------------------------------------------

    @property
    def uri(self) -> Uri:
        return activity_uri(TIME_KIND, self.project_id)

    @property
    def title(self) -> str:
        return f"{self._project().title or 'Untitled project'} — Time Estimates"

    @property
    def widget(self) -> QWidget:
        return self._widget

    def close(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self.focus_bar.dispose()

    # -- internals -----------------------------------------------------------------------------

    def _project(self) -> Project:
        return self._product.project(self.project_id)

    def _on_lens(self, chosen: int) -> None:
        self._calendar_lens = chosen == 0
        self._render()

    def _on_day_picked(self, when: date) -> None:
        if self._report is None or when == self._report.start:
            return
        self._deps.set_start(self.project_id, when)  # the model change refreshes the tab

    def _refresh(self) -> None:
        if not self._product.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        deps = self._deps
        project = self._project()
        self._report = time_report(
            self._product,
            project,
            deps.days_for,
            deps.is_agent,
            start=deps.start_of(self.project_id),
            efficiency=read_efficiency(project),
        )
        self._render()

    def _render(self) -> None:
        report = self._report
        has_report = report is not None
        for widget in (self.lens_bar, self.matrix, self.pager, self.months, self.insight):
            widget.setVisible(has_report)
        if report is None:
            self.headline.setText("No steps yet")
            self.detail.setText("The matrix appears with the first one.")
            self.unestimated_note.setVisible(False)
            self.agent_note.setVisible(False)
            return
        cells = report.calendar if self._calendar_lens else report.parallel
        floor = report.calendar_floor if self._calendar_lens else report.floor
        collapse = not report.has_agent_steps
        self.matrix.show_cells(cells, floor, collapse)

        selected = self.matrix.selection
        calendar = self._cell(report.calendar, selected)
        if calendar.finish is not None:
            self.headline.setText(f"Lands {format_date(calendar.finish)}")
        else:
            self.headline.setText("Nothing estimated yet")
        self.detail.setText(f"{_team(*selected)} · {format_days(calendar.days)} of calendar time")
        self.months.show_span(report.start, calendar.finish)

        self.insight.setText(self._insight(report, cells, floor))
        self.unestimated_note.setVisible(report.unestimated > 0)
        self.unestimated_note.setText(
            f"{report.unestimated} step{'s' if report.unestimated != 1 else ''} "
            "unestimated — they run as zero days here."
        )
        self.agent_note.setVisible(collapse)

    @staticmethod
    def _cell(cells: tuple[Cell, ...], seat: tuple[int, int]) -> Cell:
        return next(cell for cell in cells if (cell.humans, cell.agents) == seat)

    def _tooltip(self, cell: Cell) -> str:
        report = self._report
        assert report is not None  # tiles exist only while a report is shown
        seat = (cell.humans, cell.agents)
        calendar = self._cell(report.calendar, seat)
        project_time = self._cell(report.parallel, seat)
        lines = [
            _team(*seat),
            f"{format_days(project_time.days)} of project time",
            f"{format_days(calendar.days)} of calendar time at {report.efficiency:.0%} focus",
        ]
        if calendar.finish is not None:
            lines.append(f"lands {format_date(calendar.finish)}")
        return "\n".join(lines)

    @staticmethod
    def _insight(report: TimeReport, cells: tuple[Cell, ...], floor: float) -> str:
        """The grid's takeaway in one breath: the effort split, then what staffing buys."""
        # The prose formatter, not the column one: "9.75 days of work", never "1.95w".
        effort = (
            f"{format_day_count(report.total_days)} of work — "
            f"{format_day_count(report.human_days)} human, "
            f"{format_day_count(report.agent_days)} agent."
        )
        fastest = min(cell.days for cell in cells)
        slowest = max(cell.days for cell in cells)
        if slowest - fastest <= FLOOR_TOLERANCE:
            return (
                f"{effort} Staffing does not change this plan — "
                "the dependency chain sets the pace."
            )
        team = min(
            (cell for cell in cells if cell.days - fastest <= FLOOR_TOLERANCE),
            key=lambda cell: (cell.humans + cell.agents, cell.humans),
        )
        who = _team(team.humans, team.agents)
        if fastest - floor <= FLOOR_TOLERANCE:
            return (
                f"{effort} {who} reaches the {format_days(floor)} dependency floor — "
                "more capacity changes nothing."
            )
        return (
            f"{effort} {who} is fastest here at {format_days(fastest)}; "
            f"the dependencies alone would allow {format_days(floor)}."
        )


class TimeEstimatesModule:
    id = MODULE_ID

    def __init__(self, deps: TimeEstimatesDeps) -> None:
        self._deps = deps

    def open(self, project_id: NodeId, *, preview: bool = False) -> None:
        self._deps.tabs.open(TIME_KIND, project_id, preview=preview)

    def register(self) -> None:
        deps = self._deps

        def factory(target: str | None) -> TimeEstimatesActivity:
            assert target is not None
            return TimeEstimatesActivity(deps, target)

        deps.tabs.register_factory(TIME_KIND, factory)
        deps.actions.register(
            ActionSpec(
                id="time.open",
                label="Show &Time Estimates",
                menu="Project",
                group="open",
                order=40,
                tip="How long the project takes with people and agents in parallel",
                state=self._on_a_project,
                run=self._open,
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
