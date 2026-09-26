"""The pace so far: how fast people's finished steps ran against the plan — what *Adjust for
Efficiency* re-dates the rest at, once there is enough to go on.

No ``qapp`` fixture: ``schedule.py`` is Qt-free by rule.
"""

from datetime import date, timedelta

import pytest

from dplanner.domain.model import Step
from dplanner.modules.time_estimates.schedule import PACE_STEPS, as_planned, pace_so_far

MONDAY = date(2026, 9, 7)
THURSDAY = MONDAY + timedelta(days=3)
LATER = MONDAY + timedelta(days=9)  # Wednesday of the next week: seven working days on.


def pace(steps, *, today=LATER, agents=(), undone=(), unstamped=()):
    """Each step is ``(title, days given, started, done)``."""
    given = {title: days for title, days, _started, _done in steps}
    started = {title: day for title, _days, day, _done in steps}
    done = {title: day for title, _days, _started, day in steps}
    return pace_so_far(
        [Step(title=title) for title, *_rest in steps],
        lambda step: given[step.title],
        is_agent=lambda step: step.title in agents,
        status_for=lambda step: "" if step.title in undone else "done",
        started_for=lambda step: None if step.title in unstamped else started[step.title],
        since_for=lambda step: done[step.title],
        start=MONDAY,
        today=today,
    )


def three(days=2.0, finished=THURSDAY):
    """Three steps given ``days`` each, all started on the Monday and done by ``finished``."""
    return [(name, days, MONDAY, finished) for name in "ABC"]


def test_the_pace_is_the_days_given_over_the_days_taken_middle_to_middle():
    """Monday to Thursday is three working days middle to middle: 2 given, 3 taken."""
    assert pace(three()) == pytest.approx(2 / 3)
    assert pace(three(days=3.0)) == pytest.approx(1.0)


def test_there_is_no_pace_before_enough_days_and_enough_finished_steps():
    assert pace(three(), today=MONDAY + timedelta(days=4)) is None  # five working days in
    assert pace(three()[: PACE_STEPS - 1]) is None
    assert pace(three(), undone=("A",)) is None  # two finished
    assert pace(three(), unstamped=("B",)) is None  # a step with no start says nothing


def test_it_is_peoples_pace_alone():
    """An agent's step runs at its estimate, as the focus is people's alone."""
    agent = ("D", 9.0, MONDAY, MONDAY + timedelta(days=1))
    assert pace([*three(), agent], agents=("D",)) == pytest.approx(2 / 3)


def test_a_pace_is_believed_only_so_far_either_way():
    assert pace(three(days=0.1)) == 0.25
    assert pace(three(days=40.0)) == 4.0


def test_a_pace_within_a_tenth_of_the_plan_is_the_plans():
    assert as_planned(1.0) and as_planned(1.09) and as_planned(0.92)
    assert not as_planned(1.12) and not as_planned(0.85)
