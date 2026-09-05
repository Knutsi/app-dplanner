"""How long the project takes with a stated team, as a tab beside the graph it prices.

The page is split at a seam, the answer taking the wider side. On the left, what you
set: the focus factor and the staffing picker (one heatmap of every team, clicking a
tile re-asks the question). On the right, what that answers: a calendar with every
milestone's stretch of work lit in its shade — the colour map they are shaded from is
chosen in the strip above it, beside the month arrows — and under it the milestones in
one list, each with its swatch, where it begins (the sequence's day, or a date of its
own, set right there), where it lands and how much of it has landed. Under the list,
**progress toward the picked milestone** — all work when none is picked — as one chart
(``chart.py``): the plan as it stood on the basis day, the plan now, the band between
them that is the change since, and what actually landed — by steps or by estimated days,
the toggle above it, against the project's start or any day picked beside it.
Calendar days and project days are two lenses on one simulation, so they are a toggle
over one grid rather than two tables side by side. Nothing on the page explains itself;
the tooltips do.

The simulation is the domain's (``phases`` over ``parallel_finish``); this module renders
it and stores only assumptions — the focus factor, the palette, the team a tile click
chooses, and a milestone's date and colour (see ``schedule.py`` beside this file) — plus
the one thing that cannot be derived: the day's progress, which ``recorder.py`` writes
into the project's history whenever the plan settles on something new. The estimate,
agent-step, status, milestone and start-date readers arrive as functions on the Deps, so
this module never learns what an estimate is stored as or what marks a step for an agent
— the same seams the progression board uses.

**Robust before pretty.** The model refuses to create a cycle, but a file edited by hand
can carry one; then nothing can be dated, and the page says which steps wait on each
other instead of drawing a calendar over a broken walk. Every graph change — an edge, an
estimate, a milestone marked or dated — re-runs the report, so the calendar is never a
picture of a plan that has since changed.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import QDate, QLocale, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

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
from dplanner.modules.time_estimates.chart import ChartData, Mark, ProgressChart
from dplanner.modules.time_estimates.milestones import (
    DATE_FORMAT,
    MilestoneEntry,
    MilestoneList,
    PalettePicker,
)
from dplanner.modules.time_estimates.months import Band, MonthsView
from dplanner.modules.time_estimates.progress import (
    DATA_FORMAT as HISTORY_FORMAT,
)
from dplanner.modules.time_estimates.progress import (
    HISTORY_ID,
    Snapshot,
    Stretch,
    actual,
    baseline,
    changes_since,
    delta,
    delta_words,
    expected,
    idle,
    landings,
    marks,
    read_history,
    tally,
)
from dplanner.modules.time_estimates.recorder import ProgressRecorder
from dplanner.modules.time_estimates.schedule import (
    DATA_FORMAT,
    MODULE_ID,
    WHOLE_COLOR,
    Cell,
    TimeReport,
    phase_colors,
    read_color,
    read_efficiency,
    read_palette,
    read_start,
    read_team,
    time_report,
    write_milestone,
    write_project,
)
from dplanner.modules.time_estimates.view import FocusBar, MatrixView
from dplanner.theme.icons import close_icon

TIME_KIND = "time"
REFRESH_DELAY_MS = 500

PANEL_MARGIN = 16
CAPTION_GAP = 6
BLOCK_GAP = 12
BUTTON_GAP = 4

# Where the seam falls to begin with; the splitter keeps the proportion after. The left
# holds the focus and the staffing grid and nothing wider, so the calendar gets the rest.
LEFT_WIDTH = 400
RIGHT_WIDTH = 560

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
    # Where a step stands, through the status aspect's reader — what "landed" means here.
    status_for: Callable[[Step], str]
    # What each estimate was before, and the key a row prints: the change report behind
    # the chart's delta, read off the steps themselves.
    estimate_history: Callable[[Step], list[tuple[date, float]]]
    step_key: Callable[[Step], str]
    # When the project's work begins, and how a calendar click re-dates it — whoever
    # owns start dates answers both, one undoable command per click.
    start_of: Callable[[ProjectId], date]
    set_start: Callable[[ProjectId, date], None]
    parent: QWidget  # The window: owns the progress recorder.


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
        self._by_days = False
        self._basis: date | None = None  # None: the project's start.
        self._loading_basis = False
        self._syncing_team = False

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
        self.matrix.scenario_changed.connect(self._on_team_picked)
        left.addWidget(self.matrix, 0, Qt.AlignmentFlag.AlignLeft)

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
        # The colour map, on the same strip as the arrows, over the calendar it colours.
        self.palette_caption = QLabel("Milestone colours", self.pager)
        self.palette_caption.setObjectName("InspectorCaption")
        pager_row.addWidget(self.palette_caption)
        pager_row.addSpacing(CAPTION_GAP)
        self.palette_picker = PalettePicker(self.pager)
        self.palette_picker.setToolTip("The colour map the milestones are shaded from")
        self.palette_picker.palette_picked.connect(self._on_palette_changed)
        pager_row.addWidget(self.palette_picker)
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

        # -- progress: the picked milestone's promise against what landed -------------------
        right.addSpacing(BLOCK_GAP)
        self.progress_bar = QWidget(answer)
        progress_row = QHBoxLayout(self.progress_bar)
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(BUTTON_GAP)
        self.progress_caption = QLabel("Progress", self.progress_bar)
        self.progress_caption.setObjectName("InspectorCaption")
        progress_row.addWidget(self.progress_caption)
        progress_row.addSpacing(CAPTION_GAP)
        self.progress_figure = QLabel(self.progress_bar)
        progress_row.addWidget(self.progress_figure)
        progress_row.addStretch(1)
        self._measures = QButtonGroup(answer)
        self._measures.setExclusive(True)
        self.steps_button = self._measure_button("By steps", "Done steps over steps")
        self.days_button = self._measure_button(
            "By days", "Estimated days of done steps over the estimated days of all"
        )
        for index, button in enumerate((self.steps_button, self.days_button)):
            self._measures.addButton(button, index)
            progress_row.addWidget(button)
        self.steps_button.setChecked(True)
        self._measures.idClicked.connect(self._on_measure)
        right.addWidget(self.progress_bar)

        # The change since the basis, and the basis itself — the start unless picked.
        self.delta_bar = QWidget(answer)
        delta_row = QHBoxLayout(self.delta_bar)
        delta_row.setContentsMargins(0, 0, 0, 0)
        delta_row.setSpacing(BUTTON_GAP)
        self.delta_figure = QLabel(self.delta_bar)
        self.delta_figure.setObjectName("InspectorNote")
        self.delta_figure.setWordWrap(True)
        delta_row.addWidget(self.delta_figure, 1)
        self.basis_caption = QLabel("vs plan at", self.delta_bar)
        self.basis_caption.setObjectName("InspectorNote")
        delta_row.addWidget(self.basis_caption)
        self.basis = QDateEdit(self.delta_bar)
        self.basis.setCalendarPopup(True)
        self.basis.setLocale(QLocale(QLocale.Language.English))
        self.basis.setDisplayFormat(DATE_FORMAT)
        self.basis.setKeyboardTracking(False)
        self.basis.setToolTip("The day to compare the plan against — the start by default")
        self.basis.dateChanged.connect(self._on_basis)
        delta_row.addWidget(self.basis)
        self.basis_reset = QToolButton(self.delta_bar)
        self.basis_reset.setAutoRaise(True)
        self.basis_reset.setIcon(close_icon(self.delta_bar.palette().text().color().name()))
        self.basis_reset.setToolTip("Back to the project's start")
        self.basis_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.basis_reset.clicked.connect(lambda: self._set_basis(None))
        delta_row.addWidget(self.basis_reset)
        right.addWidget(self.delta_bar)

        self.chart = ProgressChart(answer)
        right.addWidget(self.chart)
        right.addStretch(1)

        # -- the seam ------------------------------------------------------------------------
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.addWidget(self._scrolling(settings))
        self.split.addWidget(self._scrolling(answer))
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([LEFT_WIDTH, RIGHT_WIDTH])
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

    def _measure_button(self, label: str, tip: str) -> QToolButton:
        button = QToolButton(self.progress_bar)
        button.setObjectName("ToolbarButton")
        button.setText(label)
        button.setToolTip(tip)
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

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

    @property
    def by_days(self) -> bool:
        return self._by_days

    @property
    def basis_day(self) -> date:
        """The day the plan is compared against: picked, else the project's start."""
        return self._basis or self._deps.start_of(self.project_id)

    def snapshot(self, today: date | None = None) -> Snapshot | None:
        """The plan today, stretch by stretch, for the selected team — what the chart and
        the rows' percentages are read from, and what the recorder writes."""
        if self._report is None or not self._report.calendar:
            return None
        return Snapshot(
            day=today or date.today(),
            stretches=tuple(
                Stretch(
                    key=phase.milestone.id if phase.milestone else "",
                    tally=tally(phase.steps, self._deps.days_for, self._deps.status_for),
                    start=phase.start,
                    finish=phase.finish,
                    landings=landings(phase, self._deps.days_for),
                )
                for phase in self._selected_cell().phases
            ),
        )

    # -- input ---------------------------------------------------------------------------------

    def _on_lens(self, chosen: int) -> None:
        self._calendar_lens = chosen == 0
        self._render()

    def _on_measure(self, chosen: int) -> None:
        self._by_days = chosen == 1
        self._render()

    def _on_basis(self, picked: QDate) -> None:
        if not self._loading_basis:
            self._set_basis(date(picked.year(), picked.month(), picked.day()))

    def _set_basis(self, when: date | None) -> None:
        """A way of looking, not a plan fact: view state, re-rendered, never stored."""
        self._basis = when
        self._render()

    def _on_team_picked(self) -> None:
        """A tile click is the project's staffing assumption: one undoable write, the
        focus spinbox's twin. The model change re-renders; a click on the stored team,
        or the render's own sync, writes nothing."""
        if self._syncing_team or not self._product.has(self.project_id):
            return
        project = self._project()
        entry = write_project(project, team=self.matrix.selection)
        if entry == project.module_data.get(MODULE_ID, {}):
            self._render()
            return
        self._deps.undo.push(
            SetModuleDataCommand(self.project_id, MODULE_ID, entry, label="Choose Team")
        )

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
        entry = write_project(project, palette_id=palette_id)
        if entry == project.module_data.get(MODULE_ID, {}):
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
        # The selection is the stored team — the nearest shown seat when the agent
        # columns are collapsed — and syncing it must not read as a click.
        self._syncing_team = True
        try:
            self.matrix.select_nearest(*read_team(self._project()))
        finally:
            self._syncing_team = False

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

        now = self.snapshot()
        assert now is not None  # a datable report has a calendar
        self.months.show_bands(report.start, self._bands(stretches))
        self.months.emphasise(self._picked)
        self.milestones.show_entries(
            self._entries(stretches, now),
            self._picked,
            found=found,
            finish=calendar.finish,
            days=calendar.days,
            share=now.toward(None).share(self._by_days),
        )
        self.notice.setVisible(report.unestimated > 0)
        self.notice.setText(
            f"{report.unestimated} step{'s' if report.unestimated != 1 else ''} "
            "unestimated · counted as 0d"
        )
        self._render_progress(calendar, stretches, now)

    def _render_progress(
        self, calendar: Cell, stretches: list[tuple[Phase, QColor]], now: Snapshot
    ) -> None:
        """The chart and its figure for the picked milestone — all work when none is."""
        key = self._picked
        label = WHOLE_LABEL
        color = QColor(WHOLE_COLOR)
        for phase, shade in stretches:
            if key is not None and phase.milestone is not None and phase.milestone.id == key:
                label, color = self._label(phase, stretches), shade
        self.progress_caption.setText(
            f"Progress toward {label}" if key is not None else "Progress, all work"
        )
        reached = now.toward(key)
        self.progress_figure.setText(
            f"{_percent(reached.share(False))} of steps · {_percent(reached.share(True))} of days"
        )
        self.progress_figure.setToolTip(
            f"{reached.done} of {reached.steps} steps done · "
            f"{format_days(reached.done_days)} of {format_days(reached.days)} estimated"
        )
        project = self._project()
        history = read_history(project)
        basis = self.basis_day
        then = baseline(history, basis)
        self._loading_basis = True
        try:
            self.basis.setDate(QDate(basis.year, basis.month, basis.day))
        finally:
            self._loading_basis = False
        self.basis_reset.setVisible(self._basis is not None)
        moved = delta(then, now, key) if then is not None else None
        if then is None:
            said, why = "no earlier plan recorded yet", ""
        elif moved is None:
            said, why = f"not in the plan on {format_date(then.day)}", ""
        else:
            said = delta_words(moved, then.day)
            # Why it moved: the steps born and the estimates changed after that record.
            changes = changes_since(
                project, then.day, self._deps.days_for, self._deps.estimate_history
            )
            why = "\n".join(changes.lines(self._deps.step_key))
        self.delta_figure.setText(said)
        self.delta_figure.setToolTip(why)
        # Every milestone through the scope, where the plan lands it, in its shade.
        shade_of = {
            phase.milestone.id: (self._label(phase, stretches), shade)
            for phase, shade in stretches
            if phase.milestone is not None
        }
        marked: list[Mark] = []
        for when, milestone in marks(now, key):
            if milestone in shade_of:
                name, shade = shade_of[milestone]
                marked.append((when, name, shade))
        self.chart.show_data(
            ChartData(
                label=label,
                color=color,
                today=now.day,
                expected=tuple(expected(now, key, by_days=self._by_days)),
                actual=tuple(actual(history, now, key, by_days=self._by_days)),
                baseline=tuple(expected(then, key, by_days=self._by_days)) if then else (),
                baseline_day=then.day if then is not None else None,
                finish=now.landing(key),
                baseline_finish=then.landing(key) if then is not None else None,
                by_days=self._by_days,
                marks=tuple(marked),
                idle=tuple(idle(now, key)),
            )
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

    def _entries(
        self, stretches: list[tuple[Phase, QColor]], now: Snapshot
    ) -> list[MilestoneEntry]:
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
                # Toward the milestone: everything through its stretch, the chart's scope.
                landed=now.toward(phase.milestone.id if phase.milestone else None),
                by_days=self._by_days,
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


def _percent(share: float | None) -> str:
    return "—" if share is None else f"{share:.0%}"


class TimeEstimatesModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: TimeEstimatesDeps) -> None:
        self._deps = deps
        self._recorder: ProgressRecorder | None = None

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
        # thing the chart cannot derive later.
        self._recorder = ProgressRecorder(
            deps.library,
            deps.debounce,
            days_for=deps.days_for,
            is_agent=deps.is_agent,
            status_for=deps.status_for,
            is_milestone=lambda step: bool(deps.milestone_label(step)),
            start_of=deps.start_of,
            parent=deps.parent,
        )
        self._recorder.start()
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
