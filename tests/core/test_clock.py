"""The clock: the machine's day until pinned, and a signal when the day it answers moves."""

from datetime import date

from dplanner.core.clock import Clock


def test_an_unpinned_clock_answers_the_machines_day():
    assert Clock().today() == date.today()


def test_a_pin_fixes_the_day_and_says_so_once():
    clock = Clock()
    heard: list[date] = []
    clock.day_changed.connect(heard.append)
    clock.pin(date(2026, 9, 21))
    clock.pin(date(2026, 9, 21))
    assert clock.today() == date(2026, 9, 21) and heard == [date(2026, 9, 21)]
    clock.pin(None)
    assert clock.today() == date.today() and heard == [date(2026, 9, 21), date.today()]


def test_a_check_announces_only_a_day_that_moved():
    class Machine(Clock):
        """A machine whose day the test turns."""

        day = date(2026, 9, 21)

        def today(self) -> date:
            return self.day

    clock = Machine()
    heard: list[date] = []
    clock.day_changed.connect(heard.append)
    clock.check()
    assert heard == []
    clock.day = date(2026, 9, 22)
    clock.check()
    clock.check()
    assert heard == [date(2026, 9, 22)]
