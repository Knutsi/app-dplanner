"""The window's side of the clock: noticing that the day has turned.

A :class:`~dplanner.core.clock.Clock` announces a new day only when somebody asks it to
check. The window asks at local midnight, re-arming for the next one each time, and again
whenever the application becomes active — a timer is paused while the machine sleeps, so a
laptop opened the next morning would otherwise show yesterday until the next midnight.
"""

from datetime import datetime, timedelta

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QGuiApplication

from dplanner.core.clock import Clock

# A moment past midnight, so a timer that fires a few milliseconds early still lands on the
# new day.
_SLACK = timedelta(seconds=1)


def ms_to_midnight(now: datetime) -> int:
    """How long from ``now`` until just after the next local midnight."""
    midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    return int((midnight + _SLACK - now).total_seconds() * 1000)


class DayWatch(QObject):
    def __init__(self, clock: Clock, parent: QObject) -> None:
        super().__init__(parent)
        self._clock = clock
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._turn)
        app = QGuiApplication.instance()
        if isinstance(app, QGuiApplication):
            app.applicationStateChanged.connect(self._on_state)
        self._arm()

    def _arm(self) -> None:
        self._timer.start(ms_to_midnight(datetime.now()))

    def _turn(self) -> None:
        self._clock.check()
        self._arm()

    def _on_state(self, state: Qt.ApplicationState) -> None:
        if state == Qt.ApplicationState.ApplicationActive:
            self._turn()
