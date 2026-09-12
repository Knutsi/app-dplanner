"""Coalescing: a burst of changes costs one rebuild, and the newest state always wins.

The model's signals arrive synchronously, one per mutation, and a view that rebuilt on each
paid for a paste of forty steps forty times and for a typed sentence once per keystroke.
A :class:`Debounced` wraps the rebuild: ``trigger()`` restarts a single-shot timer, so
within a burst the older triggers simply never run — at most one run is pending per view,
always over the latest state, and nothing queues up behind anything. A zero delay means
"once this event-loop turn is over" (a composite command's forty signals become one
rebuild, and a title still updates as it is typed); a real delay means "after a quiet
spell", which is what a table or a calendar wants. It is the timer ``AutosaveService`` and
the assets tab already hand-rolled, written once.

**Immediate mode is what the test suite runs in.** Hundreds of tests assert on a view the
line after they push a command, and a deferred rebuild would fail every one of them for no
finding. So the :class:`DebounceService` every ``Debounced`` registers with carries one
switch: immediate, and ``trigger()`` runs the action inline — which is exactly the
behaviour every view had before it was coalesced. The suite's ``session`` fixture sets it;
the timer path is tested once, here, and once per conversion.

**A run is a ``refresh`` span in the journal**, named for the view's method and carrying
how many triggers it folded — "this rebuild replaced 37 signals" is the number that says
whether coalescing earned its place. The timer is parented to the view's widget, so a
discarded build takes it; the service's ``cancel_all`` is belt and braces for the same.
"""

from collections.abc import Callable
from weakref import WeakValueDictionary

from PySide6.QtCore import QObject, QTimer
from shiboken6 import isValid

from dplanner.core.telemetry import current, describe_slot

# After a quiet spell of this long a table, a list or a board rebuilds. The assets tab's
# number; below what reads as lag on a rebuild nobody is waiting for.
SETTLE_MS = 300
# How many times a settle re-runs what the last round made pending before giving up: two
# rebuilds that trigger each other would otherwise never settle.
SETTLE_ROUNDS = 8


class DebounceService:
    """Every live :class:`Debounced` in one build: settle them all, or drop them all."""

    def __init__(self) -> None:
        self.immediate = False
        # In registration order — the order the build made its views — so a settle is the
        # same run every time. A set's order moved with every allocation in the process,
        # and a rebuild that triggers another (the progress recorder writing after a change,
        # which the Time tab then hears) was flushed before it or after it by chance.
        self._live: WeakValueDictionary[int, Debounced] = WeakValueDictionary()
        self._registered = 0

    def register(self, debounced: "Debounced") -> None:
        self._registered += 1
        self._live[self._registered] = debounced

    def set_immediate(self, immediate: bool) -> None:
        """Run every trigger inline from now on — what a test wants; anything pending runs
        first, so nothing is lost between the two regimes."""
        self.immediate = immediate
        if immediate:
            self.flush_all()

    def flush_all(self) -> None:
        """Run whatever is pending, now — and whatever that made pending, until nothing is:
        the deterministic settle for a test or a quit."""
        for _round in range(SETTLE_ROUNDS):
            pending = self.pending()
            if not pending:
                return
            for debounced in pending:
                debounced.flush()

    def cancel_all(self) -> None:
        for debounced in self._alive():
            debounced.cancel()

    def pending(self) -> list["Debounced"]:
        return [debounced for debounced in self._alive() if debounced.pending()]

    def _alive(self) -> list["Debounced"]:
        # A Debounced whose C++ side went with its parent is still a Python object until
        # the weak set notices; asking it anything would raise.
        return [debounced for debounced in list(self._live.values()) if isValid(debounced)]


class Debounced(QObject):
    """One coalesced action: ``trigger()`` as often as you like, it runs once."""

    def __init__(
        self,
        action: Callable[[], None],
        delay_ms: int = SETTLE_MS,
        *,
        parent: QObject | None,
        service: DebounceService | None = None,
    ) -> None:
        super().__init__(parent)
        self._action = action
        self._service = service
        self._delay_ms = delay_ms
        self._folded = 0  # Triggers since the last run — what one run stood for.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._run)
        # The journal names a slot for what it wraps, and a signal connected to this sees
        # the trigger; ``__wrapped__`` on it is how the view's own method gets the credit.
        self.name = describe_slot(action)

        def trigger() -> None:
            self._folded += 1
            if self._service is not None and self._service.immediate:
                self._timer.stop()
                self._run()
                return
            self._timer.start()  # Restarts: within a burst the older trigger never runs.

        trigger.__wrapped__ = action  # type: ignore[attr-defined]
        self.trigger: Callable[[], None] = trigger
        if service is not None:
            service.register(self)

    def flush(self) -> None:
        """Run a pending action now; nothing pending is nothing to do."""
        if self._timer.isActive():
            self._timer.stop()
            self._run()

    def cancel(self) -> None:
        self._timer.stop()
        self._folded = 0

    def pending(self) -> bool:
        return self._timer.isActive()

    def _run(self) -> None:
        folded, self._folded = self._folded, 0
        with current().span("refresh", self.name, coalesced=folded, delay_ms=self._delay_ms):
            self._action()
