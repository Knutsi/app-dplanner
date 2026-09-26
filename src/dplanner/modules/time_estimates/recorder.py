"""Writing the day's progress into the project's history whenever the plan settles.

The chart beside the calendar needs the past — where the plan stood and what it promised
on earlier days — and the past cannot be derived, so it is recorded. This is the recorder:
it hears every change to the library, waits for the burst to settle, takes the day's
snapshot of every project and, **only when it differs from the last row recorded**, writes
it. A window open on a plan that nobody touches writes nothing; a status set from the
terminal, adopted by the window, writes one row for the day.

**The write is applied directly, never pushed onto the undo stack**, the PR refresher's
rule: a record of what the plan looked like is not a user decision, and Ctrl+Z after
marking a step done must undo the status, not delete the day's row — which the next
settle would then simply write again with the status undone. It carries an origin of its
own so every view treats it as a foreign change, and it never loops: its own write changes
nothing the snapshot reads, so the settle it triggers finds the same row and writes
nothing. ``dplanner progress record`` is the same write for a plan driven from the
terminal; ``progress.py`` owns the shape both use. A snapshot somebody *saved* is a
different thing — a user decision, pushed through the undo stack by the tab and written
by ``dplanner progress save`` — and every write here carries the saved list along as it
is stored, so a settle never loses one.
"""

from collections.abc import Callable
from datetime import date

from PySide6.QtCore import QObject

from dplanner.core.clock import Clock
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Project, ProjectId, Step
from dplanner.framework.debounce import SETTLE_MS, Debounced, DebounceService
from dplanner.modules.time_estimates.progress import (
    HISTORY_ID,
    Snapshot,
    read_history,
    read_saved,
    recorded,
    take,
    write_history,
)
from dplanner.modules.time_estimates.schedule import (
    read_efficiency,
    read_start,
    read_team,
    schedule_facts,
)

# The recorder's origin: no view claims it, so every surface repaints — a chart reading
# the history included.
RECORD_ORIGIN: object = object()


class ProgressRecorder(QObject):
    """One per build; started by the module, stopped when the build is discarded."""

    def __init__(
        self,
        library: Library,
        debounce: DebounceService,
        *,
        days_for: Callable[[Step], float | None],
        is_agent: Callable[[Step], bool],
        status_for: Callable[[Step], str],
        since_for: Callable[[Step], date | None],
        is_marker: Callable[[Step], bool],
        is_milestone: Callable[[Step], bool],
        start_of: Callable[[ProjectId], date],
        clock: Clock,
        parent: QObject,
    ) -> None:
        super().__init__(parent)
        self._product = library
        self._clock = clock
        self._days_for = days_for
        self._is_agent = is_agent
        self._status_for = status_for
        self._since_for = since_for
        self._is_marker = is_marker
        self._is_milestone = is_milestone
        self._start_of = start_of
        self._settle = Debounced(self.record_all, SETTLE_MS, parent=self, service=debounce)
        self._unsubscribes: list[Callable[[], None]] = []

    def start(self) -> None:
        """Record the state the window opened on, then follow every change."""
        library = self._product
        signals = (
            library.structure_changed,
            library.edges_changed,
            library.module_data_changed,
            library.text_edited,
        )
        self._unsubscribes = [signal.connect(self._on_change) for signal in signals]
        # A turned day can re-date the plan with nothing edited — an undated project starts
        # today — so it is heard like an edit, and written only if the plan moved.
        self._unsubscribes.append(self._clock.day_changed.connect(self._on_change))
        self._settle.trigger()

    def stop(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self._settle.cancel()

    def snapshot(self, project: Project, today: date | None = None) -> Snapshot | None:
        humans, agents = read_team(project)
        day = today or self._clock.today()
        facts = schedule_facts(
            project,
            day,
            is_agent=self._is_agent,
            status_for=self._status_for,
            since_for=self._since_for,
            is_marker=self._is_marker,
        )
        return take(
            self._product,
            project,
            self._days_for,
            self._is_agent,
            self._status_for,
            self._since_for,
            humans=humans,
            agents=agents,
            start=self._start_of(project.id),
            efficiency=read_efficiency(project),
            is_milestone=self._is_milestone,
            start_for=read_start,
            today=day,
            facts=facts,
        )

    def record_all(self) -> None:
        """Every project's day, written where it changed."""
        for project in list(self._product.projects):
            self.record(project)

    def record(self, project: Project) -> bool:
        """Write ``project``'s day if it differs from the last row; True when it did."""
        if not self._product.has(project.id):
            return False
        now = self.snapshot(project)
        if now is None:
            return False
        rows = recorded(read_history(project), now)
        if rows is None:
            return False
        SetModuleDataCommand(
            project.id,
            HISTORY_ID,
            write_history(rows, read_saved(project)),
            view_origin=RECORD_ORIGIN,
            label="",
        ).redo(self._product)
        return True

    def _on_change(self, *_args: object) -> None:
        self._settle.trigger()
