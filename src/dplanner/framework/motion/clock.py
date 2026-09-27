"""One clock for a surface that moves, ticking at the display's rate and only while seen.

A hand-rolled ``QTimer`` ticks at whatever interval somebody typed (the canvas's live rings
step at 80 ms, twelve frames a second) and keeps ticking whether anyone is looking. This one
runs on Qt's own animation driver — the one every ``QPropertyAnimation`` shares, about sixty
ticks a second, which Qt itself pauses when nothing is animating — and hands each listener
the seconds since the last tick, so motion is measured in time and never in ticks.

**It runs only while it is wanted.** ``follow(widget)`` starts it when the widget is shown
and stops it when hidden, so a surface in a background tab costs nothing and a test that
never shows a window never starts it. ``step(dt)`` ticks by hand, which is how a test or a
render sets the time rather than waiting for it. A long gap between ticks — a stall, a laptop
lid — is taken as one short step rather than a leap.
"""

from PySide6.QtCore import QAbstractAnimation, QEvent, QObject
from PySide6.QtWidgets import QWidget

from dplanner.core.signals import Signal

# The longest step a tick may take: past it, the gap was not motion anyone watched.
MAX_STEP_S = 0.1


class _Frames(QAbstractAnimation):
    """An animation with no end, whose every update is one frame of the clock."""

    def __init__(self, clock: "FrameClock") -> None:
        super().__init__(clock)
        self._clock = clock
        self._last_ms = 0

    def duration(self) -> int:
        return -1

    def restart(self) -> None:
        self._last_ms = 0
        self.start()

    def updateCurrentTime(self, current_ms: int) -> None:  # noqa: N802 - Qt override
        gap = (current_ms - self._last_ms) / 1000.0
        self._last_ms = current_ms
        if gap > 0.0:
            self._clock.step(min(gap, MAX_STEP_S))


class FrameClock(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # Seconds since the previous tick.
        self.ticked: Signal[float] = Signal("motion.ticked")
        self._frames = _Frames(self)
        self._followed: QWidget | None = None

    def start(self) -> None:
        if not self.running():
            self._frames.restart()

    def stop(self) -> None:
        self._frames.stop()

    def running(self) -> bool:
        return self._frames.state() == QAbstractAnimation.State.Running

    def step(self, dt: float) -> None:
        """One tick of ``dt`` seconds — what the driver does, and what a test does by hand."""
        self.ticked.emit(dt)

    def follow(self, widget: QWidget) -> None:
        """Run while ``widget`` is on screen, and only then."""
        self._followed = widget
        widget.installEventFilter(self)
        if widget.isVisible():
            self.start()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        if watched is self._followed:
            if event.type() == QEvent.Type.Show:
                self.start()
            elif event.type() == QEvent.Type.Hide:
                self.stop()
        return super().eventFilter(watched, event)
