"""Debug ▸ Time Simulation: the real Time tab over a plan played out a day at a time.

The simulator (``simulation/``) plays one of the scenarios the model was designed against —
a team working a synthetic plan while something happens to it — and records it as the
window would have. This tab shows it: a strip to pick the scenario, the seed, which days the
window was open, and a re-budget from the day shown; a slider over the days, marked with the
days the recorder wrote a row, the snapshots saved on purpose and the day each milestone
really landed; what happened that day; and under it all, **the Time tab itself**, the one
the window opens, over a library of its own.

**A scratch world, sharing nothing that holds state.** The embedded tab is built from the
root's own recipe for its deps (``TimeSimulationDeps.time_deps``) over a library, an undo
stack, a context, a clock and a debounce service that are this tab's alone; it shares only
the verbs, which run against its own context and name steps the window's library does not
have. It is never activated, so it never speaks for the user. Moving the slider restores the
day into that one library (``replay.restore``), pins the clock to it and flushes the tab's
rebuild at once, so every day is drawn while the days play. Nothing is simulated until the
tab is first shown: a restored Debug tab costs nothing at startup.

The embedded tab's writers are greyed (``set_read_only``): the simulator writes that plan, and
a Budget change there would be undone by the next day restored — the re-budget above is the
one that changes the world, and *Plan edits* the one that adds a wait before a step not yet
started, from the day shown, as a person would on the canvas. *Hold the Axes Still* draws
every day against the reach of the whole run (``hold_reach``), so playing the days moves only
the lines.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta

from PySide6.QtCore import QDate, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from dplanner.core.clock import Clock
from dplanner.domain.model import Library
from dplanner.domain.schedule import WEEKDAYS, Wait, format_date, short_date
from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.activity import ActivityBase
from dplanner.framework.context import Context, ContextService, activity_uri
from dplanner.framework.debounce import DebounceService
from dplanner.framework.table import DATE_FORMAT
from dplanner.framework.tabs import TabHost
from dplanner.framework.toolbar import Toolbar
from dplanner.framework.widgets import note
from dplanner.modules.time_estimates.activity import TimeEstimatesActivity
from dplanner.modules.time_estimates.cli import Readers
from dplanner.modules.time_estimates.module import TimeEstimatesDeps
from dplanner.modules.time_estimates.simulation.edits import (
    Budget,
    WaitEdit,
    budget_of,
    rebudget,
)
from dplanner.modules.time_estimates.simulation.frames import StepState, Writers
from dplanner.modules.time_estimates.simulation.replay import Replay, restore
from dplanner.modules.time_estimates.simulation.scenarios import SCENARIOS, scenario_by_id
from dplanner.modules.time_estimates.simulation.simulate import Setup, Simulated, simulate
from dplanner.modules.time_estimates.simulation.timeline import CADENCES
from dplanner.modules.time_estimates.simulation.world import wait_title
from dplanner.theme.icons import (
    chevron_left_icon,
    chevron_right_icon,
    clock_icon,
    eraser_icon,
    frame_icon,
    gauge_icon,
    play_icon,
)
from dplanner.theme.tokens import CAPTION_GAP, PANEL_MARGIN, SECONDARY_ALPHA

SIMULATION_KIND = "time-simulation"
SIMULATED = "The simulator writes this plan — re-budget it from the strip above"
# How long each day is shown while the days play.
PLAY_MS = 220
# The day a new run opens on: two weeks in, so there is some history to read.
OPENS_AFTER = timedelta(days=14)
TICKS_HEIGHT = 14
FOCUS_STEP = 5  # Percent: the focus a person gives, as the Budget will offer it.


@dataclass(frozen=True)
class TimeSimulationDeps:
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    readers: Readers
    writers: Writers
    # The Time tab's deps over a scratch library, clock and debounce service — the root's
    # own recipe, so the embedded tab is the real one and never a copy.
    time_deps: Callable[[Library, Clock, DebounceService], TimeEstimatesDeps]


class TimeSimulationModule:
    id = "time_simulation"

    def __init__(self, deps: TimeSimulationDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.tabs.register_factory(SIMULATION_KIND, lambda _target: TimeSimulationActivity(deps))
        deps.actions.register(
            ActionSpec(
                id="debug.time_simulation",
                label="Time &Simulation",
                menu="Debug",
                group="simulation",
                order=10,
                tip="The Time tab over a plan played out day by day — the scenarios the "
                "forecast was designed against, to scrub, replay and re-budget",
                run=self._open,
            )
        )

    def _open(self, _context: Context) -> None:
        self._deps.tabs.open(SIMULATION_KIND)


class _Ticks(QWidget):
    """Marks under the day slider: the days the recorder wrote a row, the snapshots saved on
    purpose, and the day each milestone really landed, in its own shade."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedHeight(TICKS_HEIGHT)
        self._count = 0
        self._rows: Sequence[int] = ()
        self._saved: Sequence[int] = ()
        self._landed: Sequence[tuple[int, str]] = ()

    def show_marks(
        self,
        count: int,
        rows: Sequence[int],
        saved: Sequence[int],
        landed: Sequence[tuple[int, str]],
    ) -> None:
        self._count, self._rows, self._saved, self._landed = count, rows, saved, landed
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        if self._count < 2:
            return
        painter = QPainter(self)
        ink = self.palette().text().color()
        secondary = QColor(ink)
        secondary.setAlpha(SECONDARY_ALPHA)
        inset = TICKS_HEIGHT / 2  # Where a slider's handle centre can reach.
        span = self.width() - 2 * inset
        half = TICKS_HEIGHT / 2

        def at(index: int) -> float:
            return inset + span * index / (self._count - 1)

        for index in self._rows:
            painter.fillRect(QRectF(at(index) - 0.5, 0, 1, half - 2), secondary)
        for index in self._saved:
            painter.fillRect(QRectF(at(index) - 1, 0, 2, TICKS_HEIGHT), ink)
        for index, color in self._landed:
            painter.fillRect(QRectF(at(index) - 2, half, 4, half), QColor(color))
        painter.end()


class TimeSimulationActivity(ActivityBase):
    def __init__(self, deps: TimeSimulationDeps) -> None:
        self._deps = deps
        self.uri = activity_uri(SIMULATION_KIND)
        self.title = "Time Simulation"
        self._setup = Setup()
        self._simulated: Simulated | None = None
        self._index = 0
        self._inner: TimeEstimatesActivity | None = None
        self._syncing = False
        # The scratch world: one library the embedded tab shows, its own clock and its own
        # rebuilds, flushed at once so every day is drawn.
        self._shown = Replay("Simulated plan", deps.writers, deps.readers)
        self.clock = Clock()
        self.debounce = DebounceService()

        self.widget = QWidget()
        page = QVBoxLayout(self.widget)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)

        strip = QWidget(self.widget)
        strip_row = QHBoxLayout(strip)
        strip_row.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, 0)
        self.controls = Toolbar(strip)
        self.earlier = self.controls.add_verb("A Day Earlier", chevron_left_icon, self._earlier)
        self.play = self.controls.add_verb(
            "Play the Days", play_icon, self._on_play, checkable=True
        )
        self.later = self.controls.add_verb("A Day Later", chevron_right_icon, self._later)
        self.controls.add_divider()
        self.scenario = QComboBox(self.controls)
        self.scenario.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for index, one in enumerate(SCENARIOS):
            self.scenario.addItem(one.name, one.id)
            self.scenario.setItemData(index, f"Breaks: {one.breaks}", Qt.ItemDataRole.ToolTipRole)
        self.scenario.currentIndexChanged.connect(self._on_scenario)
        self.controls.add_widget(self.scenario)
        self.seed = QSpinBox(self.controls)
        self.seed.setRange(1, 999)
        self.seed.setPrefix("seed ")
        self.seed.setToolTip("Which plan and which luck: the same seed plays the same days")
        self.seed.setKeyboardTracking(False)
        self.seed.valueChanged.connect(self._on_seed)
        self.controls.add_widget(self.seed)
        self.cadence = QComboBox(self.controls)
        self.cadence.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.cadence.setToolTip("Which days the window was open, so the recorder wrote a row")
        for key, label in CADENCES:
            self.cadence.addItem(label, key)
        self.cadence.currentIndexChanged.connect(self._on_cadence)
        self.controls.add_widget(self.cadence)
        self.controls.add_divider()
        # Named before the count, as the seed is: "people 1" reads right at any number.
        self.people = self._spin(1, 3, "people ", "People on the plan from the day shown")
        self.agents = self._spin(1, 4, "agents ", "Coding agents on the plan from the day shown")
        self.focus = self._spin(10, 100, "focus ", "How much of a person's day the plan gets")
        self.focus.setSuffix("%")
        self.focus.setSingleStep(FOCUS_STEP)
        self.rebudget = self.controls.add_verb(
            "Re-budget From This Day",
            gauge_icon,
            self._on_rebudget,
            tip="The team and focus beside it from the day shown on — the world changes "
            "with it, as a Budget change in the window would",
        )
        self.clear = self.controls.add_verb("Clear Plan Edits", eraser_icon, self._on_clear)
        self.controls.add_divider()
        self.hold = self.controls.add_verb(
            "Hold the Axes Still",
            frame_icon,
            self._hold_axes,
            checkable=True,
            tip="Draw every day against the whole run's reach, so playing the days moves only "
            "the lines",
        )
        self.hold.setChecked(True)
        strip_row.addWidget(self.controls, 1)
        page.addWidget(strip)

        # Plan edits: a wait before a step not yet started, made on the day shown.
        edits = QWidget(self.widget)
        edits_row = QHBoxLayout(edits)
        edits_row.setContentsMargins(PANEL_MARGIN, CAPTION_GAP, PANEL_MARGIN, 0)
        self.edits = Toolbar(edits)
        before = QLabel("Wait before", self.edits)
        before.setObjectName("ToolbarLabel")
        self.edits.add_widget(before)
        self.wait_before = QComboBox(self.edits)
        self.wait_before.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.wait_before.setToolTip("The step that waits: it starts once the wait is over")
        self.edits.add_widget(self.wait_before)
        self.wait_kind = QComboBox(self.edits)
        self.wait_kind.addItem("until", "until")
        self.wait_kind.addItem("for working days", "days")
        self.wait_kind.currentIndexChanged.connect(lambda _index: self._show_wait_kind())
        self.edits.add_widget(self.wait_kind)
        self.wait_until = QDateEdit(self.edits)
        self.wait_until.setCalendarPopup(True)
        self.wait_until.setDisplayFormat(DATE_FORMAT)
        self.edits.add_widget(self.wait_until)
        self.wait_days = QSpinBox(self.edits)
        self.wait_days.setRange(1, 60)
        self.wait_days.setValue(3)
        self.edits.add_widget(self.wait_days)
        self.add_wait = self.edits.add_verb(
            "Add the Wait",
            clock_icon,
            self._on_add_wait,
            tip="A wait before the step chosen, made on the day shown",
        )
        self.waits_made = note("", self.edits)
        self.edits.add_widget(self.waits_made)
        edits_row.addWidget(self.edits, 1)
        page.addWidget(edits)

        days = QWidget(self.widget)
        days_column = QVBoxLayout(days)
        days_column.setContentsMargins(PANEL_MARGIN, CAPTION_GAP, PANEL_MARGIN, 0)
        days_column.setSpacing(0)
        self.day_words = note("", days)
        days_column.addWidget(self.day_words)
        self.slider = QSlider(Qt.Orientation.Horizontal, days)
        self.slider.valueChanged.connect(self._on_slider)
        days_column.addWidget(self.slider)
        self.ticks = _Ticks(days)
        days_column.addWidget(self.ticks)
        days_column.addSpacing(CAPTION_GAP)
        self.happened = note("", days)
        days_column.addWidget(self.happened)
        page.addWidget(days)

        self._host = QVBoxLayout()
        page.addLayout(self._host, 1)  # Before it is filled: a parentless layout leaks.

        self._timer = QTimer(self.widget)
        self._timer.setInterval(PLAY_MS)
        self._timer.timeout.connect(self._step)
        self._sync_controls()

    def _spin(self, least: int, most: int, prefix: str, tip: str) -> QSpinBox:
        spin = QSpinBox(self.controls)
        spin.setRange(least, most)
        spin.setPrefix(prefix)
        spin.setToolTip(tip)
        self.controls.add_widget(spin)
        return spin

    # -- the activity contract -----------------------------------------------------------------

    def on_activated(self) -> None:
        """Build on the first showing, never before: a restored Debug tab costs nothing."""
        if self._inner is None:
            self._resimulate(keep_day=False)
            inner = TimeEstimatesActivity(
                self._deps.time_deps(self._shown.library, self.clock, self.debounce),
                self._shown.project.id,
            )
            self._inner = inner
            self._host.addWidget(inner.widget)
            inner.set_read_only(SIMULATED)
            self._hold_axes()

    def close(self) -> None:
        self._timer.stop()
        if self._inner is not None:
            self._inner.close()
            self._inner = None
        self.controls.dispose()

    # -- what the tests read off the tab -------------------------------------------------------

    @property
    def inner(self) -> TimeEstimatesActivity | None:
        """The embedded Time tab, once the simulation has been shown."""
        return self._inner

    @property
    def simulated(self) -> Simulated | None:
        return self._simulated

    @property
    def library(self) -> Library:
        """The scratch library the embedded tab shows."""
        return self._shown.library

    @property
    def day(self) -> date | None:
        found = self._simulated
        return found.timeline.days[self._index].day if found is not None else None

    # -- the days ------------------------------------------------------------------------------

    def show_day(self, index: int) -> None:
        """Restore day ``index`` into the scratch world and draw the tab over it at once."""
        found = self._simulated
        if found is None:
            return
        self._index = max(0, min(index, len(found.timeline.days) - 1))
        played = found.timeline.days[self._index]
        restore(self._shown.library, self._shown.project, found.recorded.days[self._index])
        self.clock.pin(played.day)
        self.debounce.flush_all()
        self._sync_controls()

    def _on_slider(self, index: int) -> None:
        if not self._syncing:
            self.show_day(index)

    def _earlier(self) -> None:
        self.show_day(self._index - 1)

    def _later(self) -> None:
        self.show_day(self._index + 1)

    def _on_play(self) -> None:
        if not self.play.isChecked():
            self._timer.stop()
            return
        found = self._simulated
        if found is not None and self._index >= len(found.timeline.days) - 1:
            self.show_day(0)
        self._timer.start()

    def _step(self) -> None:
        found = self._simulated
        if found is None or self._index >= len(found.timeline.days) - 1:
            self._timer.stop()
            self.play.setChecked(False)
            return
        self.show_day(self._index + 1)

    # -- what is simulated ---------------------------------------------------------------------

    def _on_scenario(self, index: int) -> None:
        if self._syncing:
            return
        scenario = scenario_by_id(self.scenario.itemData(index))
        self._setup = replace(self._setup, scenario=scenario.id, cadence=None, budgets=(), waits=())
        self._resimulate(keep_day=True)

    def _on_seed(self, seed: int) -> None:
        if not self._syncing:
            self._setup = replace(self._setup, seed=seed)
            self._resimulate(keep_day=True)

    def _on_cadence(self, index: int) -> None:
        if not self._syncing:
            self._setup = replace(self._setup, cadence=self.cadence.itemData(index))
            self._resimulate(keep_day=True)

    def _on_rebudget(self) -> None:
        found = self._simulated
        if found is None:
            return
        days = found.timeline.days
        before = budget_of(days[max(0, self._index - 1)].state)
        chosen = Budget(self.people.value(), self.agents.value(), self.focus.value() / 100)
        edits = rebudget(self._setup.budgets, days[self._index].day, chosen, before)
        self._setup = replace(self._setup, budgets=edits)
        self._resimulate(keep_day=True)

    def _on_clear(self) -> None:
        self._setup = replace(self._setup, budgets=(), waits=())
        self._resimulate(keep_day=True)

    def _on_add_wait(self) -> None:
        found, before = self._simulated, self.wait_before.currentData()
        if found is None or not before:
            return
        if self.wait_kind.currentData() == "days":
            wait = Wait(days=float(self.wait_days.value()))
        else:
            picked = self.wait_until.date()
            wait = Wait(until=date(picked.year(), picked.month(), picked.day()))
        made = WaitEdit(found.timeline.days[self._index].day, str(before), wait)
        self._setup = replace(self._setup, waits=(*self._setup.waits, made))
        self._resimulate(keep_day=True)

    def _show_wait_kind(self) -> None:
        by_date = self.wait_kind.currentData() == "until"
        self.edits.set_shown(self.wait_until, by_date)
        self.edits.set_shown(self.wait_days, not by_date)

    def _resimulate(self, *, keep_day: bool) -> None:
        """Play the setup again, on the same day where it still has one — a re-budget shows
        its day moved — or two weeks into the work."""
        day = self.day if keep_day else None
        found = simulate(self._setup, self._deps.writers, self._deps.readers)
        self._simulated = found
        timeline = found.timeline
        shown = timeline.index_of(day) if day is not None else None
        if shown is None:
            shown = timeline.index_of(timeline.begin + OPENS_AFTER)
        self._syncing = True
        self.slider.setRange(0, len(timeline.days) - 1)
        self._syncing = False
        index_of = {played.day: index for index, played in enumerate(timeline.days)}
        colors = found.colors
        self.ticks.show_marks(
            len(timeline.days),
            [index_of[row.day] for row in found.recorded.rows if row.day in index_of],
            [index_of[row.day] for row in found.recorded.saved if row.day in index_of],
            [
                (index_of[landed], colors[step_id])
                for step_id, landed in timeline.finished.items()
                if step_id in colors and landed in index_of
            ],
        )
        self.show_day(shown if shown is not None else len(timeline.days) - 1)
        self._hold_axes()

    def _hold_axes(self) -> None:
        """The whole run's records as the reach the embedded tab's axes hold — or none."""
        found, inner = self._simulated, self._inner
        if found is not None and inner is not None:
            inner.hold_reach(found.recorded.rows if self.hold.isChecked() else ())

    def _sync_controls(self) -> None:
        """Every control says what is shown: the setup, the day, the budget standing on it."""
        self._syncing = True
        setup = self._setup
        scenario = scenario_by_id(setup.scenario)
        self.scenario.setCurrentIndex(self.scenario.findData(scenario.id))
        self.scenario.setToolTip(f"Breaks: {scenario.breaks}")
        self.seed.setValue(setup.seed)
        self.cadence.setCurrentIndex(self.cadence.findData(setup.cadence or scenario.cadence))
        found = self._simulated
        if found is not None:
            timeline = found.timeline
            played = timeline.days[self._index]
            self.slider.setValue(self._index)
            budget = budget_of(played.state)
            self.people.setValue(budget.humans)
            self.agents.setValue(budget.agents)
            self.focus.setValue(round(budget.efficiency * 100))
            self.day_words.setText(
                _day_words(played.day, timeline.begin, self._index, len(timeline.days))
            )
            self.happened.setText("; ".join(played.events) or "Nothing happened.")
            self._show_wait_choices(played.day, played.steps)
        first = found is None or self._index == 0
        last = found is None or self._index >= len(found.timeline.days) - 1
        self.earlier.setEnabled(not first)
        self.controls.set_tip(self.earlier, "This is the first day" if first else "")
        self.later.setEnabled(not last)
        self.controls.set_tip(self.later, "This is the last day" if last else "")
        edited = bool(setup.budgets or setup.waits)
        self.clear.setEnabled(edited)
        self.controls.set_tip(
            self.clear, "Back to the scenario's own" if edited else "Nothing is edited"
        )
        self._syncing = False

    def _show_wait_choices(self, day: date, steps: tuple[StepState, ...]) -> None:
        """The steps a wait can go before on ``day`` — those not yet started — and the waits
        made so far."""
        chosen = self.wait_before.currentData()
        self.wait_before.clear()
        for step in steps:
            if step.status == "pending" and step.wait is None:
                self.wait_before.addItem(f"S{step.number} {step.title}", step.id)
        at = self.wait_before.findData(chosen)
        self.wait_before.setCurrentIndex(max(0, at))
        waiting = self.wait_before.count() > 0
        self.add_wait.setEnabled(waiting)
        self.edits.set_tip(self.add_wait, "" if waiting else "Nothing left that has not started")
        week = day + timedelta(days=7)
        self.wait_until.setDate(QDate(week.year, week.month, week.day))
        self._show_wait_kind()
        numbers = {step.id: f"S{step.number}" for step in steps}
        self.waits_made.setText(
            "; ".join(
                f"{wait_title(made.wait)} before {numbers.get(made.before, made.before)} · made "
                f"{short_date(made.day, day)}"
                for made in self._setup.waits
            )
        )


def _day_words(day: date, begin: date, index: int, count: int) -> str:
    worked = (day - begin).days
    when = (
        f"day {worked + 1} since work began"
        if worked >= 0
        else f"{-worked} day{'' if worked == -1 else 's'} before work begins"
    )
    return f"{WEEKDAYS[day.weekday()]} {format_date(day, day)} — {when} · {index + 1} of {count}"
