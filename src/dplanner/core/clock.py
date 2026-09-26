"""Today, handed in rather than read off the machine.

A forecast is dated from today, so whatever reads the date decides what the Time tab says.
Read with ``date.today()`` where it is needed, the day could not be pinned by a test, set to a
simulated day by the Debug menu's simulator, or noticed turning by a window left open
overnight. So the day is a :class:`Clock`, one per window and one per CLI run:

- :meth:`today` is the day it answers — the machine's, or the one it was pinned to;
- :meth:`pin` fixes it, and ``None`` hands it back to the machine;
- :attr:`day_changed` fires when the answer moves on, carrying the new day. A pin moves it
  at once; the machine's day moves when somebody :meth:`check`s, which the window does at
  local midnight and whenever it becomes active again (a timer sleeps with the laptop).

Qt-free, so the CLI and the domain can hold one; the window's timer is
``framework/day_watch.py``.
"""

from datetime import date

from dplanner.core.signals import Signal


class Clock:
    def __init__(self, pinned: date | None = None) -> None:
        self._pinned = pinned
        self.day_changed: Signal[date] = Signal("day_changed")
        self._seen = self.today()

    def today(self) -> date:
        return self._pinned if self._pinned is not None else date.today()

    def pin(self, day: date | None) -> None:
        self._pinned = day
        self.check()

    def check(self) -> None:
        """Announce the day if it is not the one last announced."""
        day = self.today()
        if day != self._seen:
            self._seen = day
            self.day_changed.emit(day)
