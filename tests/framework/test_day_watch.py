"""The window's day watch: it asks the clock at midnight and whenever the app comes back."""

from datetime import date, datetime

import pytest
from PySide6.QtCore import QObject, Qt

from dplanner.core.clock import Clock
from dplanner.framework.day_watch import DayWatch, ms_to_midnight


class _Machine(Clock):
    """A machine whose day the test turns."""

    day = date(2026, 9, 21)

    def today(self) -> date:
        return self.day


@pytest.fixture
def owner(app):
    parent = QObject()
    yield parent
    parent.deleteLater()


def test_the_timer_is_set_for_just_after_the_next_midnight():
    assert ms_to_midnight(datetime(2026, 9, 21, 23, 59, 0)) == 61_000
    assert ms_to_midnight(datetime(2026, 9, 21, 0, 0, 0)) == 86_401_000


def test_coming_back_to_the_app_asks_the_clock(owner):
    clock = _Machine()
    watch = DayWatch(clock, parent=owner)
    heard: list[date] = []
    clock.day_changed.connect(heard.append)
    clock.day = date(2026, 9, 22)  # the laptop slept through midnight
    watch._on_state(Qt.ApplicationState.ApplicationActive)
    assert heard == [date(2026, 9, 22)]
    watch._on_state(Qt.ApplicationState.ApplicationInactive)
    assert heard == [date(2026, 9, 22)]
