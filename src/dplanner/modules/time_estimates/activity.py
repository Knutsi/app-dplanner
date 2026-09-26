"""The Time tab: when the plan lands with its team, how that moved, and the work behind it.

**Four figures lead**, each meaning in its tooltip: where the work lands — or ✓ and the day
it was done — how far that moved against the plan compared with, how much of the work is
done, and how many steps nobody has sized (a click opens the Estimates tab on them). Under
them a strip holds, in the order they are reached for: the **pages** — *Milestones* (where
each lands against the plan compared with, ``shift_view.py``), *Work* (the scope and the
work done on one scale, ``work_view.py``) and *Calendar* (six months with the stretches lit,
``months.py``); what the plan is **compared with**; **History**; the **Budget** — who
works on it and how much of their day, from today on (``budget.py``); **Adjust for
Efficiency**; *Save Snapshot…*, ⋯ for the milestone colours, and Export.

*Adjust for Efficiency* re-dates people's remaining steps at the focus their finished steps
actually ran at (``Readers.pace``), once there is enough to go on. It is the reader's way of
looking — a per-user preference (``user_config``), never stored with the plan — so it
reaches the page alone: the recorder, a saved snapshot and the report keep the plan as its
stored focus dates it.

Everything on the page is one :class:`~dplanner.modules.time_estimates.present.Presented`,
read after a quiet spell from the plan dated for its stored team (``Readers.snapshot``, the
recorder's own call) and the recorded history — the report draws the same. **History**
(``history.py``) reads an earlier day's record in the live plan's place, and while it looks
back every writer on the page is greyed, saying why; a host may grey them for a reason of
its own (:meth:`TimeEstimatesActivity.set_read_only` — the simulator, whose world is not
this page's to change). A milestone picked on one page is held in full ink on the others;
nothing is hidden by a pick. A plan a hand-edited file has looped says which steps wait on
each other instead of being dated.

A milestone's own start date and colour are not set here: they are the milestone's, on its
Details tab (``section.py``).
"""

from collections.abc import Sequence
from datetime import date
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QDate, QLocale, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import NodeId, Project, StepId
from dplanner.domain.ordering import cyclic
from dplanner.domain.schedule import format_date, format_days, short_date
from dplanner.framework.activity import EntityActivity, follow_project
from dplanner.framework.context import (
    SCOPE_SELECTION,
    Context,
    ContextNode,
    Uri,
    activity_uri,
    selection_uri,
)
from dplanner.framework.debounce import Debounced
from dplanner.framework.popover import PopoverButton
from dplanner.framework.segmented import Segmented
from dplanner.framework.signalling import StatusLine, UpdatingIndicator
from dplanner.framework.table import DATE_FORMAT
from dplanner.framework.toolbar import Toolbar
from dplanner.framework.user_config import get_global, set_global
from dplanner.framework.widgets import EmptyState, GlyphButton, caption, quiet
from dplanner.modules.time_estimates.budget import BudgetButton
from dplanner.modules.time_estimates.history import BACK_TO_TODAY, HistoryButton
from dplanner.modules.time_estimates.months import Band, MonthsView
from dplanner.modules.time_estimates.present import Presented, moved_words, names_of, present
from dplanner.modules.time_estimates.progress import (
    AT_START,
    HISTORY_ID,
    Pick,
    Snapshot,
    read_history,
    read_saved,
    saved_with,
    saved_without,
    write_history,
)
from dplanner.modules.time_estimates.schedule import (
    MODULE_ID,
    PACE_AFTER,
    PACE_STEPS,
    REMAINDER_COLOR,
    as_planned,
    read_efficiency,
    read_palette,
    read_team,
    write_project,
)
from dplanner.modules.time_estimates.shift_view import ShiftView
from dplanner.modules.time_estimates.snapshots import SaveSnapshotDialog, SnapshotPicker
from dplanner.modules.time_estimates.work_view import WorkView
from dplanner.theme.cards import title_font
from dplanner.theme.icons import PALETTE_STRIP, camera_icon, close_icon, palette_strip_icon
from dplanner.theme.palettes import PALETTES, Palette
from dplanner.theme.tokens import CAPTION_GAP, DENSE_GAP, FIELD_GAP, PANEL_MARGIN, SECTION_GAP

if TYPE_CHECKING:
    from dplanner.modules.time_estimates.module import TimeEstimatesDeps

TIME_KIND = "time"
REFRESH_DELAY_MS = 500
NO_STEPS = "No steps yet — the tab dates a plan once it has some."
ADJUST = "Adjust for Efficiency"
ADJUST_KEY = "adjust_for_efficiency"  # user_config, under this module's id: a way of looking.
SAVE_SNAPSHOT_TIP = "Keep the plan as it stands today, under a title, to compare against later"
MILESTONES_PAGE, WORK_PAGE, CALENDAR_PAGE = "milestones", "work", "calendar"
PAGES = (
    (MILESTONES_PAGE, "Milestones", "Where each milestone lands against the plan compared with"),
    (WORK_PAGE, "Work", "The scope and the work done, on one scale in days"),
    (CALENDAR_PAGE, "Calendar", "Six months, each milestone's stretch in its colour"),
)


def _step_context(step_id: StepId) -> Context:
    """A context naming exactly one step — what a row's double-click runs a verb against."""
    return Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step_id)),)})


class PalettePicker(QComboBox):
    """The colour maps by name, each with its strip; ``palette_picked`` carries the id."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setIconSize(PALETTE_STRIP)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        for found in PALETTES:
            self.addItem(palette_strip_icon(found), found.name, found.id)

    def show_palette(self, found: Palette) -> None:
        self.blockSignals(True)
        self.setCurrentIndex(self.findData(found.id))
        self.blockSignals(False)


class TimeEstimatesActivity(EntityActivity):
    """One project's plan in time: the figures, the strip and a page at a time."""

    def __init__(self, deps: "TimeEstimatesDeps", project_id: NodeId) -> None:
        super().__init__(deps.context, "project", project_id)
        self._deps = deps
        self._library = deps.library
        self.project_id = project_id
        self._shown: Presented | None = None
        self._live: Snapshot | None = None
        # How fast people's finished steps ran (None too early), and the plan re-dated at it
        # when the reader adjusts for it — the page's alone.
        self._pace: float | None = None
        self._adjusted: Snapshot | None = None
        self._picked: str | None = None
        # What the plan is compared with: the plan at the project's start unless picked
        # otherwise — a way of looking, never stored.
        self._then: Pick = AT_START
        # The recorded day History shows in the live plan's place — None for today.
        self._as_of: date | None = None
        self._read_only = ""  # Why the host says nothing here may write, when it does.
        self._held: tuple[Snapshot, ...] = ()  # More plans the axes must hold still for.
        self._loading_day = False
        today = deps.clock.today()

        # -- the figures ---------------------------------------------------------------------
        figures = QWidget()
        row = QHBoxLayout(figures)
        row.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, 0)
        row.setSpacing(SECTION_GAP)
        big = title_font(QFont(figures.font()))
        self.landing_figure = self._figure(figures, big)
        self.moved_figure = self._figure(figures, big)
        self.done_figure = self._figure(figures, big)
        for label in (self.landing_figure, self.moved_figure, self.done_figure):
            row.addWidget(label)
        self.unsized = quiet(QPushButton(figures))
        self.unsized.clicked.connect(lambda: deps.estimate_missing(self.project_id))
        row.addWidget(self.unsized)
        row.addStretch(1)

        # -- the strip -----------------------------------------------------------------------
        strip = QWidget()
        strip_row = QHBoxLayout(strip)
        strip_row.setContentsMargins(PANEL_MARGIN, FIELD_GAP, PANEL_MARGIN, 0)
        strip_row.setSpacing(FIELD_GAP)
        self.controls = Toolbar(strip)
        self.pages = Segmented(PAGES, self.controls)
        self.pages.set_value(MILESTONES_PAGE)
        self.pages.picked.connect(self._on_page)
        self.controls.add_widget(self.pages)
        self.controls.add_divider()
        compared = QLabel("Compared with", self.controls)
        compared.setObjectName("ToolbarLabel")
        self.controls.add_widget(compared)
        self.then_picker = SnapshotPicker(today, self.controls)
        self.then_picker.picked.connect(self._on_then_picked)
        self.then_picker.forget.connect(self._on_forget)
        self.controls.add_widget(self.then_picker)
        self.then_day = QDateEdit(self.controls)
        self.then_day.setCalendarPopup(True)
        self.then_day.setLocale(QLocale(QLocale.Language.English))
        self.then_day.setDisplayFormat(DATE_FORMAT)
        self.then_day.setKeyboardTracking(False)
        self.then_day.setToolTip("The plan as recorded on this day")
        self.then_day.dateChanged.connect(self._on_then_day)
        self.controls.add_widget(self.then_day)
        self.controls.set_shown(self.then_day, False)
        self.history = HistoryButton(self.controls)
        self.history.moved.connect(self._on_history)
        self.controls.add_widget(self.history)
        self.back_to_today = GlyphButton("", close_icon, self.controls, tip=BACK_TO_TODAY)
        self.back_to_today.clicked.connect(self.history.back_to_today)
        self.controls.add_widget(self.back_to_today)
        self.controls.set_shown(self.back_to_today, False)
        self.controls.add_divider()
        self.budget = BudgetButton(self.controls)
        self.budget.chosen.connect(self._on_budget)
        self.controls.add_widget(self.budget)
        self.adjust = QToolButton(self.controls)
        self.adjust.setObjectName("ToolbarButton")
        self.adjust.setCheckable(True)
        self.adjust.setCursor(Qt.CursorShape.PointingHandCursor)
        self.adjust.setText(ADJUST)
        self.adjust.clicked.connect(lambda _checked: self._on_adjust())
        self.controls.add_widget(self.adjust)
        self.save_snapshot = self.controls.add_verb(
            "Save Snapshot…", camera_icon, self._on_save_snapshot, tip=SAVE_SNAPSHOT_TIP
        )
        self.more = PopoverButton("⋯", self.controls, tip="Milestone colours")
        self.more.popover.body.addWidget(caption("Milestone colours", self.more.popover))
        self.palette_picker = PalettePicker(self.more.popover)
        self.palette_picker.setToolTip("The map the milestones are shaded from")
        self.palette_picker.currentIndexChanged.connect(lambda _index: self._on_palette())
        self.more.popover.body.addWidget(self.palette_picker)
        self.controls.add_widget(self.more)
        # Export's arrow renders File ▸ Export — the plan's page, the PDF, the milestones'
        # CSV — the same entries, never a copy, found where the numbers are.
        self.controls.add_action(deps.actions, deps.context, "report.html", menu=("File", "Export"))
        strip_row.addWidget(self.controls, 1)
        # A change to the plan re-runs the page after a quiet spell; until it has, the strip
        # says so. At the far right, outside the strip, so folding it can never take it.
        self.updating = UpdatingIndicator(strip)
        strip_row.addWidget(self.updating)

        # -- the pages -----------------------------------------------------------------------
        self.problem = StatusLine()
        self.shifts = ShiftView()
        self.shifts.picked.connect(self._on_picked)
        self.shifts.activated.connect(self._on_activated)
        self.work = WorkView()
        self.months = MonthsView(today)
        self.months.day_picked.connect(self._on_start_picked)
        self.earlier = self._pager_button(Qt.ArrowType.LeftArrow, "Earlier months", -1)
        self.later = self._pager_button(Qt.ArrowType.RightArrow, "Later months", 1)
        calendar = QWidget()
        calendar_column = QVBoxLayout(calendar)
        calendar_column.setContentsMargins(0, 0, 0, 0)
        calendar_column.setSpacing(CAPTION_GAP)
        pager = QHBoxLayout()
        calendar_column.addLayout(pager)  # Before it is filled: a parentless layout leaks.
        pager.setSpacing(DENSE_GAP)
        pager.addWidget(self.earlier)
        pager.addWidget(self.later)
        pager.addStretch(1)
        calendar_column.addWidget(self.months)
        calendar_column.addStretch(1)
        self.stack = QStackedWidget()
        self._page_index: dict[str, int] = {}
        for page, widget in (
            (MILESTONES_PAGE, self.shifts),
            (WORK_PAGE, self.work),
            (CALENDAR_PAGE, calendar),
        ):
            self._page_index[page] = self.stack.addWidget(self._scrolling(widget))

        frame = QWidget()
        framed = QVBoxLayout(frame)
        framed.setContentsMargins(0, 0, 0, 0)
        framed.setSpacing(0)
        framed.addWidget(figures)
        framed.addWidget(strip)
        body = QWidget()
        body_column = QVBoxLayout(body)
        body_column.setContentsMargins(PANEL_MARGIN, SECTION_GAP, PANEL_MARGIN, PANEL_MARGIN)
        body_column.setSpacing(SECTION_GAP)
        body_column.addWidget(self.problem)
        body_column.addWidget(self.stack, 1)
        framed.addWidget(body, 1)
        # A project with no steps has nothing to date: the page says so where the pages
        # would be, and the figures and the strip stay.
        self.empty = EmptyState(parent=frame, stands_in_for=body)
        framed.addWidget(self.empty, 1)
        self._widget = frame

        # After a quiet spell, not per signal: the heaviest reaction in the window, so its
        # delay is the longest.
        self._refresh_soon = Debounced(
            self._refresh, REFRESH_DELAY_MS, parent=frame, service=deps.debounce
        )
        self.updating.follow(self._refresh_soon)
        # History's slider: the page follows it as it moves, once per event-loop turn.
        self._scrub = Debounced(self._render, 0, parent=frame, service=deps.debounce)
        self._unsubscribes = [
            follow_project(self._library, self.project_id, self._refresh_soon.trigger),
            # A turned day re-dates the plan like any change to it would.
            deps.clock.day_changed.connect(lambda _day: self._refresh_soon.trigger()),
        ]
        self._on_page(MILESTONES_PAGE)
        self._refresh()

    @staticmethod
    def _figure(parent: QWidget, font: QFont) -> QLabel:
        label = QLabel(parent)
        label.setFont(font)
        return label

    @staticmethod
    def _scrolling(page: QWidget) -> QScrollArea:
        """A page scrolls when the window is short, and never sideways — the plots take
        the width they are given."""
        scroller = QScrollArea()
        scroller.setWidget(page)
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return scroller

    def _pager_button(self, arrow: Qt.ArrowType, tip: str, step: int) -> QToolButton:
        button = QToolButton()
        button.setObjectName("ToolbarButton")
        button.setArrowType(arrow)
        button.setToolTip(tip)
        button.setAutoRepeat(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
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
        self.controls.dispose()

    # -- what the tests read off the tab ------------------------------------------------------

    @property
    def shown(self) -> Presented | None:
        """What the page draws — None while there is nothing to date."""
        return self._shown

    @property
    def page(self) -> str:
        return str(self.pages.value())

    @property
    def picked(self) -> StepId | None:
        return self._picked

    @property
    def landing(self) -> date | None:
        """Where the whole plan lands — the day it was done, once it is."""
        return self._shown.whole.end if self._shown is not None else None

    @property
    def then_pick(self) -> Pick:
        return self._then

    @property
    def pace(self) -> float | None:
        """How fast people's finished steps ran against the plan — None while too early."""
        return self._pace

    @property
    def adjusting(self) -> bool:
        """Whether the page's dates run at the pace so far right now."""
        return self._adjust_on() and self._pace is not None and self._as_of is None

    @property
    def as_of(self) -> date | None:
        """The recorded day History shows — None while the page shows today."""
        return self._as_of

    def writers_refusal(self) -> str:
        """Why nothing on the page may write right now — "" when it may."""
        if self._read_only:
            return self._read_only
        if self._as_of is not None:
            day = format_date(self._as_of, self._deps.clock.today())
            return f"Showing the plan as recorded {day} — back to today to change it"
        return ""

    # -- what a host may say -------------------------------------------------------------------

    def set_read_only(self, reason: str) -> None:
        """Grey every writer on the page, saying ``reason`` — "" hands them back."""
        self._read_only = reason
        self._show_writers()

    def hold_reach(self, rows: Sequence[Snapshot]) -> None:
        """Hold the axes still for ``rows`` as well — every plan a host will show here."""
        self._held = tuple(rows)
        self._render()

    def snapshot(self) -> Snapshot | None:
        """The plan today, stretch by stretch, for the stored team — what *Save Snapshot…*
        keeps and the recorder writes."""
        return self._live

    # -- input ---------------------------------------------------------------------------------

    def _on_page(self, page: object) -> None:
        self.stack.setCurrentIndex(self._page_index[str(page)])

    def _on_then_picked(self, pick: Pick) -> None:
        """A way of looking, not a plan fact: re-rendered, never stored."""
        self._then = pick
        self._render()

    @staticmethod
    def _adjust_on() -> bool:
        return bool(get_global(MODULE_ID, ADJUST_KEY, False))

    def _on_adjust(self) -> None:
        """The reader's preference flips — kept on across days, since the toggle waits out a
        day too early rather than switching itself off."""
        set_global(MODULE_ID, ADJUST_KEY, not self._adjust_on())
        self._refresh()

    def _on_history(self, day: object) -> None:
        """A day History reached: the page follows at once, and its writers stand down."""
        self._as_of = cast("date | None", day)
        self._scrub.trigger()

    def _on_then_day(self, picked: QDate) -> None:
        if not self._loading_day:
            self._on_then_picked(Pick("day", day=date(picked.year(), picked.month(), picked.day())))

    def _on_picked(self, key: object) -> None:
        """A milestone is held in full ink on every page; None shows them all alike."""
        self._picked = cast("str | None", key)
        self._render()

    def _on_activated(self, step_id: str) -> None:
        if self._library.has(step_id):
            self._deps.actions.run("steps.details", _step_context(step_id))

    def _on_start_picked(self, when: date) -> None:
        """A day clicked in the calendar: the project's start, one undoable write."""
        project = self._project()
        if self.writers_refusal():
            return
        if when != self._deps.readers.start_of(project, self._deps.clock.today()):
            self._deps.set_start(self.project_id, when)  # The model change refreshes the tab.

    def _on_budget(self, humans: int, agents: int, efficiency: float) -> None:
        """The team and the focus, from today on: one undoable write of the stored
        assumptions, which keep the focus work in flight ran at (``write_project``)."""
        project = self._project()
        team = (humans, agents)
        # Only what the pick changed: an assumption left at its default stays absent.
        entry = write_project(
            project,
            today=self._deps.clock.today(),
            efficiency=efficiency if efficiency != read_efficiency(project) else None,
            team=team if team != read_team(project) else None,
        )
        if entry != project.module_data.get(MODULE_ID, {}):
            self._deps.undo.push(
                SetModuleDataCommand(self.project_id, MODULE_ID, entry, label="Set Budget")
            )

    def _on_palette(self) -> None:
        project = self._project()
        entry = write_project(
            project,
            today=self._deps.clock.today(),
            palette_id=str(self.palette_picker.currentData()),
        )
        if entry != project.module_data.get(MODULE_ID, {}):
            self._deps.undo.push(
                SetModuleDataCommand(self.project_id, MODULE_ID, entry, label="Milestone Palette")
            )

    def _on_save_snapshot(self) -> None:
        """The plan as it stands today, kept under a title: a decision, so one undoable
        write — the recorder's automatic day is not touched by it."""
        if not self._library.has(self.project_id):
            return
        saved = read_saved(self._project())
        dialog = SaveSnapshotDialog([row.title for row in saved], self._deps.parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.save_snapshot_as(*dialog.values())

    def save_snapshot_as(self, title: str, note: str = "") -> None:
        """What the dialog does on Save — and what a test calls in its place."""
        project = self._project()
        now = self._live
        if now is None:
            return
        entry = write_history(
            read_history(project), saved_with(read_saved(project), now, title, note)
        )
        self._deps.undo.push(
            SetModuleDataCommand(self.project_id, HISTORY_ID, entry, label="Save Snapshot")
        )

    def _on_forget(self, title: str) -> None:
        if not self._library.has(self.project_id):
            return
        project = self._project()
        entry = write_history(read_history(project), saved_without(read_saved(project), title))
        if entry != project.module_data.get(HISTORY_ID, {}):
            self._deps.undo.push(
                SetModuleDataCommand(self.project_id, HISTORY_ID, entry, label="Forget Snapshot")
            )

    # -- the page ------------------------------------------------------------------------------

    def _project(self) -> Project:
        return self._library.project(self.project_id)

    def _refresh(self) -> None:
        if not self._library.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        deps = self._deps
        project = self._project()
        today = deps.clock.today()
        readers = deps.readers
        self._live = readers.snapshot(self._library, project, today, day_over=deps.day_over)
        self._pace = readers.pace(project, today) if self._live is not None else None
        pace = self._pace
        self._adjusted = (
            readers.snapshot(self._library, project, today, day_over=deps.day_over, pace=pace)
            if self._adjust_on() and pace is not None and not as_planned(pace)
            else None
        )
        self._render()

    def _render(self) -> None:
        deps = self._deps
        project = self._project()
        today = deps.clock.today()
        self.empty.say(NO_STEPS if not project.steps else "")
        self._show_budget(project, today)
        self.palette_picker.show_palette(read_palette(project))
        live = self._live
        cycle = cyclic(self._library, project) if live is None and project.steps else []
        if cycle:
            looped = ", ".join(step.title or "an untitled step" for step in cycle)
            self.problem.say(
                f"These steps wait on each other, so nothing can be dated: {looped}. "
                "Unlink one to date the plan.",
                "error",
            )
        else:
            self.problem.clear()
        self.stack.setVisible(live is not None)
        if live is None:
            self._shown = None
            self._show_figures()
            self._show_writers()
            return
        history, saved = read_history(project), read_saved(project)
        start = deps.readers.start_of(project, today)
        now = live
        if self._as_of is not None:
            now = next((row for row in history if row.day == self._as_of), live)
            if now is live:
                self._as_of = None  # The record is gone — an undo past it, a reload.
        adjusted = self._adjusted
        if self._as_of is None and adjusted is not None:
            now = adjusted
        names = names_of(self._library, project, now, deps.readers)
        shown = present(
            now,
            history=history,
            saved=saved,
            pick=self._then,
            start=start,
            named=names,
            reach_of_rows=(live, *((adjusted,) if adjusted else ()), *self._held),
        )
        self._shown = shown
        self.history.show_history([row.day for row in history], today, shown.day)
        self.controls.set_shown(self.back_to_today, self._as_of is not None)
        self._show_writers()
        self._show_adjust(project, today)
        if self._picked is not None and all(
            scope.key != self._picked for scope in shown.milestones
        ):
            self._picked = None  # The picked milestone is gone, or no longer one.
        self.then_picker.show_pick(self._then, shown.then, saved, shown.basis, shown.day)
        self._show_then_day()
        self._show_figures()
        day_word = "today" if self._as_of is None else short_date(shown.day, today)
        self.shifts.show_presented(shown, self._picked, day_word)
        self.work.show_presented(shown, day_word)
        by_key = {one.key: one for one in names}
        bands = tuple(
            Band(
                key=stretch.key,
                label=by_key[stretch.key].label if stretch.key in by_key else stretch.key,
                start=stretch.start,
                finish=stretch.finish,
                color=_color(by_key[stretch.key].color) if stretch.key in by_key else _color(""),
                lands=bool(stretch.key),
            )
            for stretch in now.stretches
            if stretch.finish is not None
        )
        self.months.show_bands(start, bands, shown.day)
        self.months.emphasise(self._picked)

    def _show_budget(self, project: Project, today: date) -> None:
        deps = self._deps
        self.budget.show_budget(
            read_team(project),
            read_efficiency(project),
            has_agent_steps=any(deps.readers.is_agent(step) for step in project.steps),
            today=today,
        )

    def _show_writers(self) -> None:
        """Every control that writes, enabled — or greyed, saying why nothing may."""
        why = self.writers_refusal()
        for control in (self.budget, self.more):
            control.setEnabled(not why)
        if why:
            self.budget.setToolTip(why)
            self.more.setToolTip(why)
        else:
            self.more.setToolTip("Milestone colours")
        self.save_snapshot.setEnabled(not why)
        self.save_snapshot.setToolTip(why or SAVE_SNAPSHOT_TIP)
        self.months.set_pickable(not why)

    def _show_adjust(self, project: Project, today: date) -> None:
        """The toggle's words carry the focus measured beside the Budget's planned one;
        greyed, and never shown pressed, before there is a pace and while History looks
        back."""
        pace = self._pace
        planned = read_efficiency(project)
        looking_back = self._as_of is not None
        self.adjust.setEnabled(pace is not None and not looking_back)
        self.adjust.setChecked(self.adjusting)
        if looking_back and self._as_of is not None:
            day = format_date(self._as_of, today)
            self.adjust.setText(ADJUST)
            self.adjust.setToolTip(f"Showing the plan as recorded {day} — back to today to adjust")
            return
        if pace is None:
            self.adjust.setText(ADJUST)
            self.adjust.setToolTip(
                f"Adjusting for efficiency needs {PACE_AFTER} working days of work and "
                f"{PACE_STEPS} finished steps"
            )
            return
        measured = planned * pace
        self.adjust.setText(f"{ADJUST} · {measured:.0%}")
        self.adjust.setToolTip(
            f"Finished steps ran at about the planned focus ({measured:.0%} against "
            f"{planned:.0%}): adjusting leaves the dates as they are"
            if as_planned(pace)
            else f"Finished steps ran at {measured:.0%} focus against the {planned:.0%} "
            f"planned, taking {1 / pace:.1f}\N{MULTIPLICATION SIGN} their estimates: adjust "
            "what is left to it"
        )

    def _show_then_day(self) -> None:
        """A *Day…* pick shows its field beside the picker, loaded with the day and never
        reading its own load as a pick."""
        self.controls.set_shown(self.then_day, self._then.kind == "day")
        if self._then.kind == "day" and self._then.day is not None:
            when = self._then.day
            self._loading_day = True
            try:
                self.then_day.setDate(QDate(when.year, when.month, when.day))
            finally:
                self._loading_day = False

    def _show_figures(self) -> None:
        """The four numbers, each saying what it is in its tooltip."""
        shown = self._shown
        deps = self._deps
        project = self._project()
        unsized = [
            step
            for step in project.steps
            if deps.readers.days_for(step) is None
            and not deps.readers.is_marker(step)
            and deps.readers.wait_of(step) is None
        ]
        # No record holds the unsized steps, so a look back cannot say how many there were.
        self.unsized.setVisible(bool(unsized) and self._as_of is None)
        self.unsized.setText(f"⚠ {len(unsized)} unsized")
        self.unsized.setToolTip(
            "No estimate, so counted as 0 days — click to size them:\n"
            + "\n".join(f"{deps.readers.key_of(step)} {step.title}" for step in unsized)
        )
        if shown is None:
            for label in (self.landing_figure, self.moved_figure, self.done_figure):
                label.clear()
            return
        whole = shown.whole
        if whole.landed_by is not None:
            self.landing_figure.setText(f"✓ {format_date(whole.landed_by, shown.day)}")
            self.landing_figure.setToolTip("All the work is done")
        elif whole.planned is not None:
            self.landing_figure.setText(format_date(whole.planned, shown.day))
            self.landing_figure.setToolTip(
                "Where the plan lands, re-dated from what has happened"
                + (", people's remaining steps at the pace so far" if self._adjusted else "")
            )
        else:
            self.landing_figure.setText("—")
            self.landing_figure.setToolTip("Nothing estimated, so nothing to date")
        moved = whole.moved
        self.moved_figure.setText(moved_words(moved))
        self.moved_figure.setToolTip(
            f"Working days the landing moved against {shown.basis}" if moved is not None else ""
        )
        share = whole.own.share()
        self.done_figure.setText(f"{share:.0%} done" if share is not None else "")
        self.done_figure.setToolTip(
            f"{format_days(whole.own.done_days) or '0d'} of {format_days(whole.own.days)} of "
            "estimated work done"
            if share is not None
            else ""
        )


def _color(hex_color: str) -> QColor:
    return QColor(hex_color or REMAINDER_COLOR)
