"""How long the project takes with a stated team, as a tab beside the graph it prices.

A strip across the top holds what the whole page is priced with: the focus factor, the
calendar-or-project-days lens, the colour map the milestones are shaded from, and Export.
Under it the page is split at a seam, the answer taking the wider side. On the left, what
you set: the staffing picker (one heatmap of every team, clicking a tile re-asks the
question), the **start dates** — the project's own and, for each milestone, the
sequence's day or a date of its own — and the **milestones** in one list, each with its
swatch, where it lands and how much of it has landed, led by *All milestones*, the whole
plan on one line. On the right, what that answers: a banner when something needs saying
(steps counted as zero, with the button that goes and sizes them; a plan that cannot be
dated), a calendar with every milestone's stretch of work lit in its shade, and under it
**three plots on one time axis** (``chart.py``): the plan now against what actually
landed, the plan as it stood on the basis day against the plan now, and each milestone's
landing then and now with an arrow between them — by steps or by estimated days, the
toggle above them, against the project's start or any day picked beside it. Picking a
milestone on the left highlights it on the right, in the calendar and in every plot, and
fades the rest; nothing is hidden by a pick. Calendar days and project days are two
lenses on one simulation, so they are a toggle over one grid rather than two tables side
by side. Nothing on the page explains itself; the tooltips do.

The simulation is the domain's (``phases`` over ``parallel_finish``); this module renders
it and stores only assumptions — the focus factor, the palette, the team a tile click
chooses, and a milestone's date and colour (see ``schedule.py`` beside this file) — plus
the one thing that cannot be derived: the day's progress, which ``recorder.py`` writes
into the project's history whenever the plan settles on something new. The estimate,
agent-step, status, milestone and start-date readers arrive as functions on the Deps, so
this module never learns what an estimate is stored as or what marks a step for an agent
— the same seams the progression board uses; and the way to the Estimates tab is a
callback too, so the banner's button opens it without this module naming that one.

**Robust before pretty.** The model refuses to create a cycle, but a file edited by hand
can carry one; then nothing can be dated, and the page says which steps wait on each
other instead of drawing a calendar over a broken walk. Every graph change — an edge, an
estimate, a milestone marked or dated — re-runs the report, so the calendar is never a
picture of a plan that has since changed.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, QLocale, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QDateEdit,
    QFileDialog,
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

from dplanner.cli.report.sheets import csv_rows
from dplanner.core.fsio import write_csv
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
from dplanner.framework.toolbar import CONTROL_GAP, ActionToolbar, control_bar
from dplanner.framework.undo import UndoService
from dplanner.modules.time_estimates.chart import ChartData, ProgressChart, Segment
from dplanner.modules.time_estimates.cli import Readers
from dplanner.modules.time_estimates.milestones import (
    ALL_KEY,
    ALL_LABEL,
    DATE_FORMAT,
    MilestoneEntry,
    MilestoneList,
    PalettePicker,
    StartDates,
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
    expected,
    idle,
    landings,
    read_history,
    span_of,
    tally,
)
from dplanner.modules.time_estimates.recorder import ProgressRecorder
from dplanner.modules.time_estimates.report import milestones_table
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
from dplanner.modules.time_estimates.view import Banner, FocusBar, MatrixView
from dplanner.theme.icons import close_icon

TIME_KIND = "time"
REFRESH_DELAY_MS = 500

PANEL_MARGIN = 16
CAPTION_GAP = 6
BLOCK_GAP = 12
BUTTON_GAP = 4

# Where the seam falls to begin with; the splitter keeps the proportion after. The left
# holds the staffing grid and the two lists and nothing wider, so the calendar gets the rest.
LEFT_WIDTH = 440
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
    # What each estimate was before, and the key a row prints: the change report the CSV
    # and the terminal print, read off the steps themselves.
    estimate_history: Callable[[Step], list[tuple[date, float]]]
    step_key: Callable[[Step], str]
    # When the project's work begins, and how a date picked here re-dates it — whoever
    # owns start dates answers both, one undoable command per pick.
    start_of: Callable[[ProjectId], date]
    set_start: Callable[[ProjectId, date], None]
    # The banner's way to the unsized steps: whoever owns estimates opens its list on them.
    estimate_missing: Callable[[ProjectId], None]
    parent: QWidget  # The window: owns the progress recorder.


def _team(humans: int, agents: int) -> str:
    people = f"{humans} {'person' if humans == 1 else 'people'}"
    return f"{people} + {agents} {'agent' if agents == 1 else 'agents'}"


def _step_context(step_id: StepId) -> Context:
    """A context naming exactly one step — what a row's double-click runs a verb against."""
    return Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step_id)),)})


def _caption(text: str, parent: QWidget) -> QLabel:
    caption = QLabel(text, parent)
    caption.setObjectName("InspectorCaption")
    return caption


def _toggle(parent: QWidget, label: str, tip: str = "") -> QToolButton:
    button = QToolButton(parent)
    button.setObjectName("ToolbarButton")
    button.setText(label)
    button.setToolTip(tip)
    button.setCheckable(True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class TimeEstimatesActivity(EntityActivity):
    """One project's staffing picker, start dates and milestones on the left, the
    calendar and the plots they date on the right, under one strip of controls."""

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

        # -- the strip: what the whole page is priced with -------------------------------
        strip = QWidget()
        strip_row = QHBoxLayout(strip)
        strip_row.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, 0)
        strip_row.setSpacing(CONTROL_GAP)
        self.controls = control_bar(strip)
        self.focus_bar = FocusBar(deps.library, deps.undo, project_id, self.controls)
        self.controls.addWidget(self.focus_bar)
        self.controls.addSeparator()
        self._lenses = QButtonGroup(strip)
        self._lenses.setExclusive(True)
        self.calendar_button = _toggle(
            self.controls, "Calendar days", "Working days on the calendar, at the human focus"
        )
        self.project_button = _toggle(
            self.controls, "Project days", "Days of full-time work, whatever the focus"
        )
        for index, button in enumerate((self.calendar_button, self.project_button)):
            self._lenses.addButton(button, index)
            self.controls.addWidget(button)
        self.calendar_button.setChecked(True)
        self._lenses.idClicked.connect(self._on_lens)
        self.controls.addSeparator()
        palette_caption = QLabel("Milestone colours", self.controls)
        palette_caption.setObjectName("ToolbarLabel")
        self.controls.addWidget(palette_caption)
        self.palette_picker = PalettePicker(self.controls)
        self.palette_picker.setToolTip("The colour map the milestones are shaded from")
        self.palette_picker.palette_picked.connect(self._on_palette_changed)
        self.controls.addWidget(self.palette_picker)
        strip_row.addWidget(self.controls, 1)
        # Export's arrow renders File ▸ Export — the milestones' CSV, the plan's page, the
        # PDF, the workbook — the same entries, never a copy, found where the numbers are.
        self.toolbar = ActionToolbar(
            deps.actions,
            deps.context,
            ("report.html",),
            {"report.html": "Export"},
            strip,
            menus={"report.html": ("File", "Export")},
        )
        strip_row.addWidget(self.toolbar)

        # -- left: what you set --------------------------------------------------------------
        settings = QWidget()
        left = QVBoxLayout(settings)
        left.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        left.setSpacing(CAPTION_GAP)

        self.matrix = MatrixView(settings)
        self.matrix.tooltip_for = self._tooltip
        self.matrix.scenario_changed.connect(self._on_team_picked)
        left.addWidget(self.matrix, 0, Qt.AlignmentFlag.AlignLeft)

        left.addSpacing(BLOCK_GAP)
        self.dates_caption = _caption("Start dates", settings)
        left.addWidget(self.dates_caption)
        self.start_dates = StartDates(settings)
        self.start_dates.project_changed.connect(self._on_start_picked)
        self.start_dates.start_changed.connect(self._on_start_changed)
        left.addWidget(self.start_dates)

        left.addSpacing(BLOCK_GAP)
        self.milestones_caption = _caption("Milestones", settings)
        left.addWidget(self.milestones_caption)
        self.milestones = MilestoneList(settings)
        self.milestones.picked.connect(self._on_picked)
        self.milestones.activated.connect(self._on_activated)
        self.milestones.color_changed.connect(self._on_color_changed)
        left.addWidget(self.milestones)
        left.addStretch(1)

        # -- right: what it answers ----------------------------------------------------------
        answer = QWidget()
        right = QVBoxLayout(answer)
        right.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        right.setSpacing(CAPTION_GAP)

        # What changes with the data: a plan that cannot be dated, steps counted as zero.
        self.banner = Banner(answer)
        self.banner.acted.connect(lambda: deps.estimate_missing(self.project_id))
        right.addWidget(self.banner)

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
        self.months.day_picked.connect(self._on_start_picked)
        right.addWidget(self.months)

        # -- progress: the plan against what landed, and the day it is compared with -------
        right.addSpacing(BLOCK_GAP)
        self.progress_bar = QWidget(answer)
        progress_row = QHBoxLayout(self.progress_bar)
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(BUTTON_GAP)
        self._measures = QButtonGroup(answer)
        self._measures.setExclusive(True)
        self.steps_button = _toggle(self.progress_bar, "By steps", "Done steps over steps")
        self.days_button = _toggle(
            self.progress_bar,
            "By days",
            "Estimated days of done steps over the estimated days of all",
        )
        for index, button in enumerate((self.steps_button, self.days_button)):
            self._measures.addButton(button, index)
            progress_row.addWidget(button)
        self.steps_button.setChecked(True)
        self._measures.idClicked.connect(self._on_measure)
        progress_row.addStretch(1)
        # The basis: the plan the scope is compared against — the start unless picked.
        basis_caption = QLabel("Plan at", self.progress_bar)
        basis_caption.setObjectName("ToolbarLabel")
        progress_row.addWidget(basis_caption)
        progress_row.addSpacing(BUTTON_GAP)
        self.basis = QDateEdit(self.progress_bar)
        self.basis.setCalendarPopup(True)
        self.basis.setLocale(QLocale(QLocale.Language.English))
        self.basis.setDisplayFormat(DATE_FORMAT)
        self.basis.setKeyboardTracking(False)
        self.basis.setToolTip("The day to compare the plan against — the start by default")
        self.basis.dateChanged.connect(self._on_basis)
        progress_row.addWidget(self.basis)
        self.basis_reset = QToolButton(self.progress_bar)
        self.basis_reset.setAutoRaise(True)
        self.basis_reset.setIcon(close_icon(self.progress_bar.palette().text().color().name()))
        self.basis_reset.setToolTip("Back to the project's start")
        self.basis_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.basis_reset.clicked.connect(lambda: self._set_basis(None))
        progress_row.addWidget(self.basis_reset)
        right.addWidget(self.progress_bar)

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
        frame = QWidget()
        framed = QVBoxLayout(frame)
        framed.setContentsMargins(0, 0, 0, 0)
        framed.setSpacing(0)
        framed.addWidget(strip)
        framed.addWidget(self.split, 1)
        self._widget = frame

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
        self.toolbar.dispose()

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
        """The plan today, stretch by stretch, for the selected team — what the plots and
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

    def _on_start_picked(self, when: date) -> None:
        """A day clicked in the calendar or set in the table: the project's start."""
        if self._report is None or when == self._deps.start_of(self.project_id):
            return
        self._deps.set_start(self.project_id, when)  # the model change refreshes the tab

    def _on_picked(self, key: str) -> None:
        """A milestone is held in full ink; *All milestones* or the remainder shows all
        alike."""
        self._picked = None if key == ALL_KEY or not key else key
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
            self.matrix,
            self.dates_caption,
            self.start_dates,
            self.milestones_caption,
            self.milestones,
            self.pager,
            self.months,
            self.progress_bar,
            self.chart,
        ):
            widget.setVisible(datable)
        if report is None:
            self.banner.say("No steps yet")
            return
        if report.cycle:
            names = ", ".join(step.title or "an untitled step" for step in report.cycle)
            self.banner.say(
                f"These steps wait on each other, so nothing can be dated: {names}. "
                "Unlink one to time the plan."
            )
            return
        if report.unestimated:
            count = f"{report.unestimated} step{'s' if report.unestimated != 1 else ''}"
            self.banner.say(f"{count} unestimated · counted as 0d", action="Estimate missing")
        else:
            self.banner.say("")
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
        entries = self._entries(stretches, now, calendar)
        self.start_dates.show_entries(entries, report.start)
        self.milestones.show_entries(entries, self._picked or ALL_KEY, found=found)
        self._render_progress(stretches, now)

    def _render_progress(self, stretches: list[tuple[Phase, QColor]], now: Snapshot) -> None:
        """The three plots over the whole plan, the picked milestone held in full ink."""
        history = read_history(self._project())
        basis = self.basis_day
        then = baseline(history, basis)
        self._loading_basis = True
        try:
            self.basis.setDate(QDate(basis.year, basis.month, basis.day))
        finally:
            self._loading_basis = False
        self.basis_reset.setVisible(self._basis is not None)
        segments = []
        for phase, shade in stretches:
            key = phase.milestone.id if phase.milestone else ""
            segments.append(
                Segment(
                    key=key,
                    label=self._label(phase, stretches),
                    color=shade,
                    now=span_of(now, key),
                    then=span_of(then, key),
                )
            )
        self.chart.show_data(
            ChartData(
                today=now.day,
                expected=tuple(expected(now, None, by_days=self._by_days)),
                actual=tuple(actual(history, now, None, by_days=self._by_days)),
                baseline=tuple(expected(then, None, by_days=self._by_days)) if then else (),
                baseline_day=then.day if then is not None else None,
                finish=now.landing(None),
                baseline_finish=then.landing(None) if then is not None else None,
                by_days=self._by_days,
                idle=tuple(idle(now, None)),
                segments=tuple(segments),
                emphasis=self._picked,
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
        self, stretches: list[tuple[Phase, QColor]], now: Snapshot, calendar: Cell
    ) -> list[MilestoneEntry]:
        """The whole first — when there is a milestone to set it against — then every
        stretch in sequence."""
        found = [
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
                # Toward the milestone: everything through its stretch.
                landed=now.toward(phase.milestone.id if phase.milestone else None),
                by_days=self._by_days,
            )
            for phase, color in stretches
        ]
        if any(entry.is_milestone for entry in found):
            found.insert(
                0,
                MilestoneEntry(
                    key=ALL_KEY,
                    label=ALL_LABEL,
                    title="",
                    color=QColor(WHOLE_COLOR),
                    chosen=False,
                    start=None,
                    default_start=self._report.start if self._report else date.today(),
                    finish=calendar.finish,
                    days=calendar.days,
                    steps=sum(len(phase.steps) for phase, _ in stretches),
                    asked=None,
                    landed=now.toward(None),
                    by_days=self._by_days,
                ),
            )
        return found

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
        readers = Readers(
            deps.days_for,
            deps.is_agent,
            deps.status_for,
            lambda dated: deps.start_of(dated.id),
            deps.milestone_label,
            deps.estimate_history,
            deps.step_key,
        )
        table = milestones_table(deps.library, project, readers)
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
