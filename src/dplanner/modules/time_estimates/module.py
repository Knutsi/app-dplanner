"""How long the project takes with a stated team, as a tab beside the graph it prices.

The page is split down the middle. On the left, what you set: the focus factor, the
staffing picker (one heatmap of every team, clicking a tile re-asks the question), and
the colour map the milestones are shaded from. On the right, what that answers: a
calendar with every milestone's stretch of work lit in its shade, and under it the
milestones in one list — each with its swatch, where it begins (the sequence's day, or a
date of its own, set right there) and where it lands. Calendar days and project days are
two lenses on one simulation, so they are a toggle over one grid rather than two tables
side by side. Nothing on the page explains itself; the tooltips do.

The simulation is the domain's (``phases`` over ``parallel_finish``); this module renders
it and stores only assumptions — the focus factor, the palette, and a milestone's date
and colour (see ``schedule.py`` beside this file). The estimate, agent-step, milestone and
start-date readers arrive as functions on the Deps, so this module never learns what an
estimate is stored as or what marks a step for an agent — the same seams the progression
board uses.

**Robust before pretty.** The model refuses to create a cycle, but a file edited by hand
can carry one; then nothing can be dated, and the page says which steps wait on each
other instead of drawing a calendar over a broken walk. Every graph change — an edge, an
estimate, a milestone marked or dated — re-runs the report, so the calendar is never a
picture of a plan that has since changed.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, NodeId, Project, ProjectId, Step, StepId
from dplanner.domain.schedule import Phase, format_date, format_days
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.activity import EntityActivity, follow_entity_tabs, follow_project
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
from dplanner.framework.tabs import TabHost
from dplanner.framework.undo import UndoService
from dplanner.modules.time_estimates.milestones import (
    MilestoneEntry,
    MilestoneList,
    PalettePicker,
)
from dplanner.modules.time_estimates.months import Band, MonthsView
from dplanner.modules.time_estimates.schedule import (
    EFFICIENCY_KEY,
    MODULE_ID,
    Cell,
    TimeReport,
    phase_colors,
    read_color,
    read_efficiency,
    read_palette,
    read_start,
    time_report,
    write_milestone,
    write_project,
)
from dplanner.modules.time_estimates.view import FocusBar, MatrixView

TIME_KIND = "time"
REFRESH_DELAY_MS = 500

PANEL_MARGIN = 16
CAPTION_GAP = 6
BLOCK_GAP = 12
BUTTON_GAP = 4

# The seam falls at the middle to begin with; the splitter keeps the proportion after.
HALF = 480

# What the stretch with no milestone is called: after the last milestone, or all there is.
REMAINDER_LABEL = "Remaining work"
WHOLE_LABEL = "All work"


@dataclass(frozen=True)
class TimeEstimatesDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    debounce: DebounceService
    # Estimates, agent-ness and milestones through the aspects' Qt-free readers — the
    # matrix never learns what any of them is stored as.
    days_for: Callable[[Step], float | None]
    is_agent: Callable[[Step], bool]
    milestone_label: Callable[[Step], str]
    # When the project's work begins, and how a calendar click re-dates it — whoever
    # owns start dates answers both, one undoable command per click.
    start_of: Callable[[ProjectId], date]
    set_start: Callable[[ProjectId, date], None]


def _team(humans: int, agents: int) -> str:
    people = f"{humans} {'person' if humans == 1 else 'people'}"
    return f"{people} + {agents} {'agent' if agents == 1 else 'agents'}"


def _step_context(step_id: StepId) -> Context:
    """A context naming exactly one step — what a row's double-click runs a verb against."""
    return Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step_id)),)})


class TimeEstimatesActivity(EntityActivity):
    """One project's staffing picker and milestones on the left, the calendar they date
    on the right."""

    def __init__(self, deps: TimeEstimatesDeps, project_id: NodeId) -> None:
        super().__init__(deps.context, "project", project_id)
        self._deps = deps
        self._product = deps.library
        self.project_id = project_id
        self._report: TimeReport | None = None
        self._calendar_lens = True
        self._picked: StepId | None = None

        # -- left: what you set --------------------------------------------------------------
        settings = QWidget()
        left = QVBoxLayout(settings)
        left.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        left.setSpacing(CAPTION_GAP)

        self.focus_bar = FocusBar(deps.library, deps.undo, project_id, settings)
        left.addWidget(self.focus_bar)

        left.addSpacing(BLOCK_GAP)
        self.lens_bar = QWidget(settings)
        lens_row = QHBoxLayout(self.lens_bar)
        lens_row.setContentsMargins(0, 0, 0, 0)
        lens_row.setSpacing(BUTTON_GAP)
        self._lenses = QButtonGroup(settings)
        self._lenses.setExclusive(True)
        self.calendar_button = self._lens_button("Calendar days")
        self.project_button = self._lens_button("Project days")
        for index, button in enumerate((self.calendar_button, self.project_button)):
            self._lenses.addButton(button, index)
            lens_row.addWidget(button)
        lens_row.addStretch(1)
        self.calendar_button.setChecked(True)
        self._lenses.idClicked.connect(self._on_lens)
        left.addWidget(self.lens_bar)

        self.matrix = MatrixView(settings)
        self.matrix.tooltip_for = self._tooltip
        self.matrix.scenario_changed.connect(self._render)
        left.addWidget(self.matrix, 0, Qt.AlignmentFlag.AlignLeft)

        left.addSpacing(BLOCK_GAP)
        self.palette_caption = QLabel("Milestone colours", settings)
        self.palette_caption.setObjectName("InspectorCaption")
        left.addWidget(self.palette_caption)
        self.palette_picker = PalettePicker(settings)
        self.palette_picker.palette_picked.connect(self._on_palette_changed)
        left.addWidget(self.palette_picker, 0, Qt.AlignmentFlag.AlignLeft)
        left.addStretch(1)

        # -- right: what it answers ----------------------------------------------------------
        answer = QWidget()
        right = QVBoxLayout(answer)
        right.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        right.setSpacing(CAPTION_GAP)

        self.pager = QWidget(answer)
        pager_row = QHBoxLayout(self.pager)
        pager_row.setContentsMargins(0, 0, 0, 0)
        pager_row.setSpacing(BUTTON_GAP)
        self.earlier = self._pager_button(self.pager, Qt.ArrowType.LeftArrow, "Earlier months")
        self.later = self._pager_button(self.pager, Qt.ArrowType.RightArrow, "Later months")
        pager_row.addWidget(self.earlier)
        pager_row.addWidget(self.later)
        pager_row.addStretch(1)
        right.addWidget(self.pager)

        self.months = MonthsView(answer)
        self.months.day_picked.connect(self._on_day_picked)
        right.addWidget(self.months)

        right.addSpacing(BLOCK_GAP)
        self.milestones = MilestoneList(answer)
        self.milestones.picked.connect(self._on_picked)
        self.milestones.activated.connect(self._on_activated)
        self.milestones.start_changed.connect(self._on_start_changed)
        self.milestones.color_changed.connect(self._on_color_changed)
        right.addWidget(self.milestones)

        # What changes with the data: a plan that cannot be dated, steps counted as zero.
        self.notice = QLabel(answer)
        self.notice.setObjectName("InspectorNote")
        self.notice.setWordWrap(True)
        right.addWidget(self.notice)
        right.addStretch(1)

        # -- the seam ------------------------------------------------------------------------
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.addWidget(self._scrolling(settings))
        self.split.addWidget(self._scrolling(answer))
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([HALF, HALF])
        self._widget = self.split

        # After a quiet spell, not per signal: a refresh is two dozen schedule simulations
        # and a re-render of the matrix, the months and the milestones — the heaviest
        # reaction in the application, so its delay is the longest.
        self._refresh_soon = Debounced(
            self._refresh, REFRESH_DELAY_MS, parent=self.split, service=deps.debounce
        )
        self._unsubscribes = [
            # Every signal, this project only: a separate agent instruction is prose, and
            # carrying one marks the step as agent work — so a text edit can move a step
            # between pools — and a milestone's label and a step's title are what the
            # lists print.
            follow_project(self._product, self.project_id, self._refresh_soon.trigger),
        ]
        self._refresh()

    @staticmethod
    def _scrolling(page: QWidget) -> QScrollArea:
        """Each half scrolls on its own when the window is short; neither ever scrolls
        sideways — the calendar takes the width it is given."""
        scroller = QScrollArea()
        scroller.setWidget(page)
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroller.setMinimumWidth(page.minimumSizeHint().width())
        return scroller

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

    # -- what the tests read off the tab ------------------------------------------------------

    @property
    def picked(self) -> StepId | None:
        return self._picked

    @property
    def landing(self) -> date | None:
        """When the selected team lands the whole plan."""
        return self._selected_cell().finish if self._report and self._report.calendar else None

    # -- input ---------------------------------------------------------------------------------

    def _on_lens(self, chosen: int) -> None:
        self._calendar_lens = chosen == 0
        self._render()

    def _on_day_picked(self, when: date) -> None:
        if self._report is None or when == self._deps.start_of(self.project_id):
            return
        self._deps.set_start(self.project_id, when)  # the model change refreshes the tab

    def _on_picked(self, key: str) -> None:
        """A row picked twice is let go; a picked remainder row only lets go."""
        self._picked = None if key == self._picked or not key else key
        self._render()

    def _on_activated(self, step_id: str) -> None:
        if self._product.has(step_id):
            self._deps.actions.run("steps.details", _step_context(step_id))

    def _on_start_changed(self, step_id: str, when: date | None) -> None:
        if not self._product.has(step_id):
            return
        step = self._product.step(step_id)
        self._write_milestone(step, when, read_color(step), "Date Milestone")

    def _on_color_changed(self, step_id: str, color: str | None) -> None:
        if not self._product.has(step_id):
            return
        step = self._product.step(step_id)
        self._write_milestone(step, read_start(step), color, "Colour Milestone")

    def _on_palette_changed(self, palette_id: str) -> None:
        if not self._product.has(self.project_id):
            return
        project = self._project()
        # The focus factor rides along as stored — absent stays absent.
        stored = project.module_data.get(MODULE_ID, {})
        efficiency = read_efficiency(project) if EFFICIENCY_KEY in stored else None
        entry = write_project(efficiency, palette_id)
        if entry == stored:
            return
        self._deps.undo.push(
            SetModuleDataCommand(self.project_id, MODULE_ID, entry, label="Milestone Palette")
        )

    def _write_milestone(
        self, step: Step, when: date | None, color: str | None, label: str
    ) -> None:
        entry = write_milestone(when, color)
        if entry == step.module_data.get(MODULE_ID, {}):
            return
        self._deps.undo.push(SetModuleDataCommand(step.id, MODULE_ID, entry, label=label))

    # -- internals -----------------------------------------------------------------------------

    def _project(self) -> Project:
        return self._product.project(self.project_id)

    def _is_milestone(self, step: Step) -> bool:
        return bool(self._deps.milestone_label(step))

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
            is_milestone=self._is_milestone,
            start_for=read_start,
        )
        self._render()

    def _selected_cell(self) -> Cell:
        assert self._report is not None
        return self._cell(self._report.calendar, self.matrix.selection)

    def _render(self) -> None:
        report = self._report
        datable = report is not None and not report.cycle
        for widget in (
            self.lens_bar,
            self.matrix,
            self.palette_caption,
            self.palette_picker,
            self.pager,
            self.months,
            self.milestones,
        ):
            widget.setVisible(datable)
        if report is None:
            self.notice.setText("No steps yet")
            self.notice.setVisible(True)
            return
        if report.cycle:
            names = ", ".join(step.title or "an untitled step" for step in report.cycle)
            self.notice.setText(
                f"These steps wait on each other, so nothing can be dated: {names}. "
                "Unlink one to time the plan."
            )
            self.notice.setVisible(True)
            return
        cells = report.calendar if self._calendar_lens else report.parallel
        collapse = not report.has_agent_steps
        self.matrix.show_cells(cells, collapse)

        calendar = self._selected_cell()
        found = read_palette(self._project())
        self.palette_picker.show_palette(found)
        colors = [
            QColor(hex_color) for hex_color in phase_colors(calendar.phases, read_color, found)
        ]
        stretches = list(zip(calendar.phases, colors, strict=True))
        if self._picked is not None and not any(
            phase.milestone is not None and phase.milestone.id == self._picked
            for phase in calendar.phases
        ):
            self._picked = None  # The picked milestone is gone, or no longer one.

        self.months.show_bands(report.start, self._bands(stretches))
        self.months.emphasise(self._picked)
        self.milestones.show_entries(
            self._entries(stretches),
            self._picked,
            found=found,
            finish=calendar.finish,
            days=calendar.days,
        )
        self.notice.setVisible(report.unestimated > 0)
        self.notice.setText(
            f"{report.unestimated} step{'s' if report.unestimated != 1 else ''} "
            "unestimated · counted as 0d"
        )

    def _label(self, phase: Phase, stretches: list[tuple[Phase, QColor]]) -> str:
        if phase.milestone is None:
            alone = all(other.milestone is None for other, _ in stretches)
            return WHOLE_LABEL if alone else REMAINDER_LABEL
        return self._deps.milestone_label(phase.milestone) or phase.milestone.title

    def _bands(self, stretches: list[tuple[Phase, QColor]]) -> tuple[Band, ...]:
        return tuple(
            Band(
                key=phase.milestone.id if phase.milestone else "",
                label=self._label(phase, stretches),
                start=phase.start,
                finish=phase.finish,
                color=color,
                lands=phase.milestone is not None,
            )
            for phase, color in stretches
            if phase.finish is not None
        )

    def _entries(self, stretches: list[tuple[Phase, QColor]]) -> list[MilestoneEntry]:
        return [
            MilestoneEntry(
                key=phase.milestone.id if phase.milestone else "",
                label=self._label(phase, stretches),
                title=phase.milestone.title if phase.milestone else "",
                color=color,
                chosen=phase.milestone is not None and read_color(phase.milestone) is not None,
                start=phase.asked,
                default_start=phase.start,
                finish=phase.finish,
                days=float(phase.calendar_days),
                steps=len(phase.steps),
                asked=phase.asked if phase.pushed else None,
            )
            for phase, color in stretches
        ]

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
                tip="How long the project takes with people and agents in parallel, "
                "and when each milestone lands",
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
