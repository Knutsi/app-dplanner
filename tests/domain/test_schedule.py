"""The schedule: the order walk, carrying estimates instead of counting hops.

Plain pytest, no ``qapp`` — ``domain/`` loads no Qt, and this file exercising it without one
is what proves it beyond the import check.
"""

from datetime import date

import pytest

from dplanner.domain.model import Library, Project, Step
from dplanner.domain.ordering import placed
from dplanner.domain.schedule import (
    as_weeks,
    format_date,
    format_days,
    next_working_day,
    schedule,
    working_days_after,
)

# 2026-09-07 is a Monday; 2026-09-12 a Saturday.
MONDAY = date(2026, 9, 7)
SATURDAY = date(2026, 9, 12)


@pytest.fixture
def project():
    """Four steps in a chain, so the topological order is the order they were added."""
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    for title in ("A", "B", "C", "D"):
        library.add_child(project.id, Step(title=title))
    for waiting, before in zip(project.steps[1:], project.steps, strict=False):
        library.set_edges(waiting.id, "requires", [before.id])
    return library, project


def days_of(estimates):
    return lambda step: estimates.get(step.title)


# -- the calendar --------------------------------------------------------------------------------


def test_a_weekend_start_rolls_forward_to_the_monday():
    assert next_working_day(SATURDAY) == date(2026, 9, 14)
    assert next_working_day(MONDAY) == MONDAY


def test_five_days_from_a_monday_finishes_on_the_friday():
    """The start is working day one, so five days is Monday through Friday — not next week."""
    assert working_days_after(MONDAY, 5) == date(2026, 9, 11)


def test_a_sixth_day_lands_on_the_next_monday():
    assert working_days_after(MONDAY, 6) == date(2026, 9, 14)


def test_half_a_day_still_lands_on_a_date():
    assert working_days_after(MONDAY, 0.5) == MONDAY


def test_a_week_is_five_working_days():
    assert as_weeks(10) == 2.0
    assert format_days(7) == "7d"
    assert format_days(8) == "1.6w"
    assert format_days(0.5) == "0.5d"
    assert format_days(None) == ""


# -- how a date reads ------------------------------------------------------------------------


def test_this_year_needs_no_year():
    """A schedule is read for *when*; the year is the part that is usually obvious."""
    assert format_date(date(2026, 9, 23), today=date(2026, 8, 26)) == "23 September"
    assert format_date(date(2026, 1, 1), today=date(2026, 12, 31)) == "1 January"


def test_another_year_says_so_and_abbreviates():
    """The month shortens when the year arrives, so the column does not double in width."""
    assert format_date(date(2027, 2, 14), today=date(2026, 8, 26)) == "14 Feb '27"
    assert format_date(date(2025, 12, 31), today=date(2026, 1, 1)) == "31 Dec '25"
    assert format_date(date(2100, 3, 5), today=date(2026, 1, 1)) == "5 Mar '00"


def test_the_months_do_not_come_from_the_locale():
    """``strftime`` would spell these differently on a Norwegian machine, and a test that
    passes only where it was written is worse than no test."""
    assert [format_date(date(2026, m, 1), today=date(2026, 1, 1)) for m in (5, 9, 12)] == [
        "1 May",
        "1 September",
        "1 December",
    ]


# -- the walk ------------------------------------------------------------------------------------


def test_the_total_runs_serially_down_the_order(project):
    library, found = project
    rows = schedule(
        placed(library, found), days_of({"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0}), MONDAY
    )

    assert [row.accumulated for row in rows] == [1.0, 3.0, 6.0, 10.0]


def test_an_unestimated_step_advances_nothing_and_claims_no_date(project):
    """ "We have not estimated this" and "this is free" are different claims."""
    library, found = project
    rows = schedule(placed(library, found), days_of({"A": 2.0, "C": 3.0}), MONDAY)

    assert [row.days for row in rows] == [2.0, None, 3.0, None]
    assert [row.accumulated for row in rows] == [2.0, 2.0, 5.0, 5.0]
    assert [row.finish for row in rows] == [
        date(2026, 9, 8),
        None,
        date(2026, 9, 11),
        None,
    ]


def test_two_halves_land_on_the_first_day(project):
    """Rounding happens once, on the total — never per step, where it would accumulate."""
    library, found = project
    rows = schedule(placed(library, found), days_of({"A": 0.5, "B": 0.5}), MONDAY)

    assert rows[1].accumulated == 1.0
    assert rows[1].finish == MONDAY


def test_only_an_unestimated_step_lacks_a_date(project):
    """There is no "no start date" case any more — a project nobody dated starts today, so
    the only blank in the Date column is a step nobody has sized."""
    library, found = project
    rows = schedule(placed(library, found), days_of({"A": 3.0, "B": 1.0}), MONDAY)

    assert [row.accumulated for row in rows] == [3.0, 4.0, 4.0, 4.0]
    assert [row.finish is None for row in rows] == [False, False, True, True]


def test_a_weekend_start_dates_from_the_monday(project):
    library, found = project
    rows = schedule(placed(library, found), days_of({"A": 1.0}), SATURDAY)

    assert rows[0].finish == date(2026, 9, 14)


def test_a_project_with_no_steps_schedules_to_nothing():
    library = Library()
    empty = Project(title="Empty")
    library.add_child(library.id, empty)

    assert schedule(placed(library, empty), lambda _step: None, MONDAY) == []


def test_each_row_keeps_its_place_in_the_order(project):
    """The schedule carries the ordering's answer rather than renumbering the rows itself."""
    library, found = project
    rows = schedule(placed(library, found), days_of({}), MONDAY)

    assert [row.place.index for row in rows] == [1, 2, 3, 4]
    assert [row.place.wave for row in rows] == [1, 2, 3, 4]


# -- day counts as prose -----------------------------------------------------------------------


def test_one_day_is_singular_and_everything_else_plural():
    from dplanner.domain.schedule import format_day_count

    assert format_day_count(1) == "1 day"
    assert format_day_count(2.5) == "2.5 days"
    assert format_day_count(0) == "0 days"


# -- the critical path ---------------------------------------------------------------------------


def diamond():
    """A splits into B and C, which join at D — the shape that separates serial from path."""
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    for title in ("A", "B", "C", "D"):
        library.add_child(project.id, Step(title=title))
    a, b, c, d = project.steps
    library.set_edges(b.id, "requires", [a.id])
    library.set_edges(c.id, "requires", [a.id])
    library.set_edges(d.id, "requires", [b.id, c.id])
    return library, project


def test_the_path_takes_the_heavier_branch():
    from dplanner.domain.schedule import critical_path

    library, project = diamond()
    path = critical_path(library, project, days_of({"A": 1, "B": 2, "C": 10, "D": 1}))
    assert path is not None
    assert [step.title for step in path.steps] == ["A", "C", "D"]
    assert path.days == 12
    assert path.unestimated == 0


def test_unestimated_steps_on_the_path_are_counted_not_priced():
    from dplanner.domain.schedule import critical_path

    library, project = diamond()
    path = critical_path(library, project, days_of({"A": 1, "B": 2, "D": 1}))
    assert path is not None
    # C is free to the walk, so B's branch is the heavier one — and nothing on it is a guess.
    assert [step.title for step in path.steps] == ["A", "B", "D"]
    assert path.unestimated == 0
    heavy = critical_path(library, project, days_of({"A": 1, "D": 1}))
    assert heavy is not None and heavy.unestimated == 1  # whichever weightless branch won


def test_equal_branches_break_ties_by_project_order():
    from dplanner.domain.schedule import critical_path

    library, project = diamond()
    path = critical_path(library, project, days_of({"A": 1, "B": 3, "C": 3, "D": 1}))
    assert path is not None
    assert [step.title for step in path.steps] == ["A", "B", "D"]


def test_an_empty_project_has_no_path():
    from dplanner.domain.schedule import critical_path

    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    assert critical_path(library, project, days_of({})) is None
