"""How long the project takes with a stated team, as a tab beside the graph it prices.

A strip across the top holds what the whole page is priced with: the focus factor, the
calendar-or-project-days lens, the colour map the milestones are shaded from, **which two
snapshots the plots compare** — a *then* and a *now*, each a picker naming the plan it
reads, with *Save snapshot…* beside them — and Export.
Under it the page is split at a seam, the answer taking the wider side. On the left, the
staffing picker (one heatmap of every team, clicking a tile re-asks the question) and,
under it, **the milestones in one list** — a row each, in the order the graph lands them:
its swatch, its label and the step's full title, when it begins (the sequence's day or a
date of its own, set right there), where it lands, how long its stretch takes and how much
of it has landed. *All milestones* leads the list, the whole plan on one line, and its
beginning is the project's own start. The list scrolls under the staffing grid rather than
taking it off the page. On the right, what all that answers: a banner when something needs
saying (steps counted as zero, with the button that goes and sizes them; a plan that cannot
be dated), a calendar with every milestone's stretch of work lit in its shade, and under it
**the plots, a page at a time** (``chart.py``): *Milestone shifts* — each milestone's
landing then and now with an arrow between them; *Progress* — the plan now against what
actually landed, and the plan then against the plan now; *Volume* — the total of
estimated days the plan came to on each recorded day, and what was still ahead. All by
estimated days, all measured between the two snapshots the strip names. The plots take
whatever height the window has left, up to a ceiling of their own, and *⤢* beside the
page toggles opens every page at once in a window of its own, fed the same record.
Picking a milestone on the left highlights it on the right, in the calendar and in every
plot, and fades the rest; nothing is hidden by a pick. Calendar days and project days are
two lenses on one simulation, so they are a toggle over one grid rather than two tables
side by side. A change to the plan re-runs the whole page after a quiet spell, and the
strip says *Recalculating…* until it has. Nothing on the page explains itself; the
tooltips do.

The simulation is the domain's (``phases`` over ``parallel_finish``); this module renders
it and stores only assumptions — the focus factor, the palette, the team a tile click
chooses, and a milestone's date and colour (see ``schedule.py`` beside this file) — plus
the one thing that cannot be derived: the day's progress, which ``recorder.py`` writes
into the project's history whenever the plan settles on something new, and the snapshots
a person saves on purpose (``snapshots.py``), pushed through the undo stack. The estimate,
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
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, QLocale, Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QDateEdit,
    QDialog,
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
from dplanner.framework.toolbar import ActionToolbar, control_bar
from dplanner.framework.undo import UndoService
from dplanner.modules.time_estimates.chart import (
    PAGES,
    PROGRESS_PAGE,
    ChartData,
    ChartDialog,
    ProgressChart,
    Segment,
)
from dplanner.modules.time_estimates.cli import Readers
from dplanner.modules.time_estimates.milestones import (
    ALL_KEY,
    ALL_LABEL,
    DATE_FORMAT,
    MilestoneEntry,
    MilestoneList,
    PalettePicker,
)
from dplanner.modules.time_estimates.months import Band, MonthsView
from dplanner.modules.time_estimates.progress import (
    AT_START,
    HISTORY_ID,
    LIVE,
    Pick,
    Snapshot,
    Stretch,
    actual,
    expected,
    idle,
    landings,
    pick_words,
    read_history,
    read_saved,
    remaining,
    resolve,
    saved_with,
    saved_without,
    span_of,
    tally,
    volume,
    write_history,
)
from dplanner.modules.time_estimates.progress import (
    DATA_FORMAT as HISTORY_FORMAT,
)
from dplanner.modules.time_estimates.recorder import ProgressRecorder
from dplanner.modules.time_estimates.report import milestones_table
from dplanner.modules.time_estimates.schedule import (
    DATA_FORMAT,
    MODULE_ID,
    WHOLE_COLOR,
    Cell,
    TimeReport,
    milestone_colors,
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
from dplanner.modules.time_estimates.snapshots import SaveSnapshotDialog, SnapshotPicker
from dplanner.modules.time_estimates.view import Banner, FocusBar, MatrixView
from dplanner.theme.tokens import CONTROL_GAP

TIME_KIND = "time"
REFRESH_DELAY_MS = 500

PANEL_MARGIN = 16
CAPTION_GAP = 6
BLOCK_GAP = 12
BUTTON_GAP = 4

# Where the seam falls to begin with; the splitter keeps the proportion after. The left
# holds the staffing grid and the milestone list and nothing wider, so the calendar gets
# the rest.
LEFT_WIDTH = 440
RIGHT_WIDTH = 560

# What the stretch with no milestone is called: after the last milestone, or all there is.
REMAINDER_LABEL = "Remaining work"
WHOLE_LABEL = "All work"

# What each page of the plots answers, for its toggle.
PAGE_TIPS = {
    "shift": "Where each milestone's landing moved between the two snapshots",
    "progress": "What has landed against what the plan promised, and how the plan itself moved",
    "volume": "How much work the plan came to on each recorded day, and how much was still ahead",
}


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


def _to_date(picked: QDate) -> date:
    return date(picked.year(), picked.month(), picked.day())


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
        # Which two plans the plots compare: the plan at the project's start against the
        # live plan unless picked otherwise — a way of looking, never stored.
        self._then: Pick = AT_START
        self._now: Pick = LIVE
        self._loading_day = False
        # The plots as data, and the window showing them larger while one is open: the
        # dialog is fed the same record, so a plan that changes redraws in both.
        self._plots: ChartData | None = None
        self._expanded: ChartDialog | None = None
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
        self.controls.addSeparator()
        # -- which two plans the plots compare ---------------------------------------------
        compare_caption = QLabel("Compare", self.controls)
        compare_caption.setObjectName("ToolbarLabel")
        self.controls.addWidget(compare_caption)
        self.then_picker = SnapshotPicker(AT_START, self.controls)
        self.then_picker.picked.connect(self._on_then_picked)
        self.then_picker.forget.connect(self._on_forget)
        self.controls.addWidget(self.then_picker)
        self.then_day = self._day_edit(self._on_then_day)
        self.then_day_action = self.controls.addWidget(self.then_day)
        with_caption = QLabel("with", self.controls)
        with_caption.setObjectName("ToolbarLabel")
        self.controls.addWidget(with_caption)
        self.now_picker = SnapshotPicker(LIVE, self.controls)
        self.now_picker.picked.connect(self._on_now_picked)
        self.now_picker.forget.connect(self._on_forget)
        self.controls.addWidget(self.now_picker)
        self.now_day = self._day_edit(self._on_now_day)
        self.now_day_action = self.controls.addWidget(self.now_day)
        self.save_snapshot = QToolButton(self.controls)
        self.save_snapshot.setObjectName("ToolbarButton")
        self.save_snapshot.setText("Save snapshot…")
        self.save_snapshot.setToolTip(
            "Keep the plan as it stands today, under a title, to compare against later"
        )
        self.save_snapshot.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_snapshot.clicked.connect(self._on_save_snapshot)
        self.controls.addWidget(self.save_snapshot)
        strip_row.addWidget(self.controls, 1)
        # A change to the plan re-runs the page after a quiet spell; until it has, the
        # strip says so rather than showing a picture of a plan that has since changed.
        self.recalculating = QLabel("Recalculating…", strip)
        self.recalculating.setObjectName("ToolbarLabel")
        self.recalculating.hide()
        strip_row.addWidget(self.recalculating)
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
        self.milestones_caption = _caption("Milestones", settings)
        left.addWidget(self.milestones_caption)
        self.milestones = MilestoneList(settings)
        self.milestones.picked.connect(self._on_picked)
        self.milestones.activated.connect(self._on_activated)
        self.milestones.color_changed.connect(self._on_color_changed)
        self.milestones.project_changed.connect(self._on_start_picked)
        self.milestones.start_changed.connect(self._on_start_changed)
        # The list scrolls under the staffing grid rather than taking it off the top of
        # the page: the grid is the question the whole page answers, and a plan with
        # thirty milestones would scroll it away exactly when it is being compared.
        self.milestone_scroll = QScrollArea(settings)
        self.milestone_scroll.setWidget(self.milestones)
        self.milestone_scroll.setWidgetResizable(True)
        self.milestone_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.milestone_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.milestone_scroll.setMinimumWidth(self.milestones.minimumSizeHint().width())
        left.addWidget(self.milestone_scroll, 1)

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

        # -- the plots: a page at a time -------------------------------------------------------
        right.addSpacing(BLOCK_GAP)
        self.progress_bar = QWidget(answer)
        progress_row = QHBoxLayout(self.progress_bar)
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(BUTTON_GAP)
        self._pages = QButtonGroup(answer)
        self._pages.setExclusive(True)
        self.page_buttons: dict[str, QToolButton] = {}
        for index, (page, label) in enumerate(PAGES):
            button = _toggle(self.progress_bar, label, PAGE_TIPS[page])
            self._pages.addButton(button, index)
            progress_row.addWidget(button)
            self.page_buttons[page] = button
        self.page_buttons[PROGRESS_PAGE].setChecked(True)
        self._pages.idClicked.connect(self._on_page)
        progress_row.addStretch(1)
        self.expand = QToolButton(self.progress_bar)
        self.expand.setObjectName("ToolbarButton")
        self.expand.setText("⤢")
        self.expand.setToolTip("Open every page of the plots in a window of their own")
        self.expand.setCursor(Qt.CursorShape.PointingHandCursor)
        self.expand.clicked.connect(self._on_expand)
        progress_row.addWidget(self.expand)
        right.addWidget(self.progress_bar)

        # The plots take the height the window has left — nothing else here asks to
        # stretch — and whatever is over their ceiling falls to the bottom of the page
        # rather than into the gaps above them.
        self.chart = ProgressChart(answer, page=PROGRESS_PAGE)
        right.addWidget(self.chart, 1)
        right.addStretch(0)

        # -- the seam ------------------------------------------------------------------------
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        # Only the answer side scrolls whole: the left half pins the grid and scrolls
        # its list inside itself.
        self.split.addWidget(settings)
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
            follow_project(self._product, self.project_id, self._on_change),
        ]
        self._refresh()

    def _day_edit(self, on_change: Callable[[QDate], None]) -> QDateEdit:
        """The day a *Day…* pick reads, shown beside its picker only while that is the
        pick."""
        edit = QDateEdit(self.controls)
        edit.setCalendarPopup(True)
        edit.setLocale(QLocale(QLocale.Language.English))
        edit.setDisplayFormat(DATE_FORMAT)
        edit.setKeyboardTracking(False)
        edit.setToolTip("The plan as recorded on this day")
        edit.dateChanged.connect(on_change)
        return edit

    @staticmethod
    def _scrolling(page: QWidget) -> QScrollArea:
        """The answer side scrolls whole when the window is short, and never sideways —
        the calendar takes the width it is given. The other half pins the staffing grid
        and scrolls its list inside itself instead."""
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
    def then_pick(self) -> Pick:
        """Which plan the plots compare against."""
        return self._then

    @property
    def now_pick(self) -> Pick:
        """Which plan stands for now."""
        return self._now

    @property
    def page(self) -> str:
        return self.chart.page

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

    def _on_page(self, chosen: int) -> None:
        self.chart.show_page(PAGES[chosen][0])

    def _on_change(self, *_args: object) -> None:
        self.recalculating.show()
        self._refresh_soon.trigger()

    def _on_then_picked(self, pick: Pick) -> None:
        """A way of looking, not a plan fact: view state, re-rendered, never stored."""
        self._then = pick
        self._render()

    def _on_now_picked(self, pick: Pick) -> None:
        self._now = pick
        self._render()

    def _on_then_day(self, picked: QDate) -> None:
        if not self._loading_day:
            self._on_then_picked(Pick("day", day=_to_date(picked)))

    def _on_now_day(self, picked: QDate) -> None:
        if not self._loading_day:
            self._on_now_picked(Pick("day", day=_to_date(picked)))

    def _on_save_snapshot(self) -> None:
        """The plan as it stands today, kept under a title: a decision, so one undoable
        write — the recorder's automatic day is not touched by it."""
        if not self._product.has(self.project_id):
            return
        project = self._project()
        saved = read_saved(project)
        dialog = SaveSnapshotDialog([row.title for row in saved], self._deps.parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.save_snapshot_as(*dialog.values())

    def save_snapshot_as(self, title: str, note: str = "") -> None:
        """What the dialog does on Save — and what a test calls in its place."""
        project = self._project()
        now = self.snapshot()
        if now is None:
            return
        entry = write_history(
            read_history(project), saved_with(read_saved(project), now, title, note)
        )
        self._deps.undo.push(
            SetModuleDataCommand(self.project_id, HISTORY_ID, entry, label="Save Snapshot")
        )

    def _on_forget(self, title: str) -> None:
        if not self._product.has(self.project_id):
            return
        project = self._project()
        entry = write_history(read_history(project), saved_without(read_saved(project), title))
        if entry == project.module_data.get(HISTORY_ID, {}):
            return
        self._deps.undo.push(
            SetModuleDataCommand(self.project_id, HISTORY_ID, entry, label="Forget Snapshot")
        )

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

    def _on_expand(self) -> None:
        """Every page of the plots in a window of their own — the same data, more room.
        Modal, because it is a way of looking at what the tab already shows and nothing
        to work beside."""
        dialog = ChartDialog(self._plots, title=self.title, parent=self._deps.parent)
        self._expanded = dialog
        try:
            dialog.exec()
        finally:
            self._expanded = None

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

    def _milestone_colors(self) -> dict[StepId, str]:
        """The project's one deal — the same dict every other surface in the window reads."""
        return milestone_colors(self._deps.library, self._project(), self._is_milestone)

    def _refresh(self) -> None:
        self.recalculating.hide()
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
            self.milestones_caption,
            self.milestone_scroll,
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
            QColor(hex_color)
            for hex_color in phase_colors(calendar.phases, self._milestone_colors())
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
        self.milestones.show_entries(entries, self._picked or ALL_KEY, found=found)
        self._render_progress(stretches, now)

    def _render_progress(self, stretches: list[tuple[Phase, QColor]], live: Snapshot) -> None:
        """The plots over the whole plan between the two picked snapshots, the picked
        milestone held in full ink."""
        project = self._project()
        history = read_history(project)
        saved = read_saved(project)
        start = self._deps.start_of(self.project_id)

        def found(pick: Pick) -> Snapshot | None:
            return resolve(pick, history=history, saved=saved, live=live, start=start)

        now = found(self._now)
        if now is None:  # The saved snapshot it read was forgotten: back to the live plan.
            self._now = LIVE
            now = live
        then = found(self._then)
        basis = pick_words(self._then, then, now.day)
        as_of = "" if self._now.kind == "now" else pick_words(self._now, now, live.day)
        self.then_picker.show_pick(self._then, then, saved, basis, now.day)
        self.now_picker.show_pick(self._now, now, saved, as_of or "the plan now", live.day)
        self._show_day(self.then_day_action, self.then_day, self._then)
        self._show_day(self.now_day_action, self.now_day, self._now)
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
        self._plots = ChartData(
            today=now.day,
            expected=tuple(expected(now, None)),
            actual=tuple(actual(history, now, None)),
            baseline=tuple(expected(then, None)) if then else (),
            basis=basis,
            as_of=as_of,
            finish=now.landing(None),
            baseline_finish=then.landing(None) if then is not None else None,
            idle=tuple(idle(now, None)),
            segments=tuple(segments),
            emphasis=self._picked,
            volume=tuple(volume(history, now)),
            remaining=tuple(remaining(history, now)),
            marks=tuple((row.day, row.title) for row in saved),
        )
        self.chart.show_data(self._plots)
        if self._expanded is not None and isValid(self._expanded):
            self._expanded.show_data(self._plots)

    def _show_day(self, action: QAction, edit: QDateEdit, pick: Pick) -> None:
        """A *Day…* pick shows its field beside the picker, loaded with the day and never
        reading its own load as a pick."""
        action.setVisible(pick.kind == "day")
        if pick.kind == "day" and pick.day is not None:
            self._loading_day = True
            try:
                edit.setDate(QDate(pick.day.year, pick.day.month, pick.day.day))
            finally:
                self._loading_day = False

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
        stretch in sequence. The row that leads the list carries the project's own start,
        whichever row that is: the whole when there are milestones, the one stretch there
        is when there are none."""
        start = self._deps.start_of(self.project_id)
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
                    start=start,
                    default_start=start,
                    finish=calendar.finish,
                    days=calendar.days,
                    steps=sum(len(phase.steps) for phase, _ in stretches),
                    asked=None,
                    sets_project=True,
                    landed=now.toward(None),
                ),
            )
        elif found:
            found[0] = replace(found[0], start=start, default_start=start, sets_project=True)
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
