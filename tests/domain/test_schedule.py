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
    change_runs,
    format_date,
    format_days,
    next_working_day,
    schedule,
    share_at,
    volume_words,
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


def test_the_volume_of_a_set_of_steps_is_one_sentence():
    """The order tab, ``order show``, ``estimate rollup`` and the Estimates tab print this,
    so a total read in one place cannot disagree with the same total read in another."""
    assert volume_words(12, 7, 1) == "12 days over 7 steps, 1 unestimated"
    assert volume_words(1, 1, 0) == "1 day over 1 step"  # Neither plural is guessed at.
    assert volume_words(0, 3, 3) == "0 days over 3 steps, 3 unestimated"


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


# -- staffing between the brackets ---------------------------------------------------------------


def agents_named(*titles):
    return lambda step: step.title in titles


NOBODY = agents_named()


def loose(*sized):
    """Steps with no edges at all — pure contention, no graph."""
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    for title, _days in sized:
        library.add_child(project.id, Step(title=title))
    return library, project, days_of(dict(sized))


def test_one_worker_meets_the_serial_total_and_ample_workers_the_path():
    from dplanner.domain.schedule import critical_path, parallel_finish

    library, project = diamond()
    estimates = days_of({"A": 1, "B": 2, "C": 10, "D": 1})
    alone = parallel_finish(library, project, estimates, NOBODY, humans=1, agents=1)
    crowd = parallel_finish(library, project, estimates, NOBODY, humans=4, agents=1)
    path = critical_path(library, project, estimates)
    assert alone is not None and alone.days == 14.0  # one human, steps end to end
    assert crowd is not None and path is not None and crowd.days == path.days == 12.0


def test_neither_pool_takes_the_others_work():
    from dplanner.domain.schedule import parallel_finish

    library, project, estimates = loose(("H", 5.0), ("X", 1.0), ("Y", 1.0), ("Z", 1.0))
    is_agent = agents_named("X", "Y", "Z")
    lone = parallel_finish(library, project, estimates, is_agent, humans=1, agents=1)
    fleet = parallel_finish(library, project, estimates, is_agent, humans=1, agents=3)
    assert lone is not None and lone.days == 5.0  # agent work serialises under the human's 5d
    assert fleet is not None and fleet.days == 5.0  # more agents cannot shorten human work
    idle = parallel_finish(library, project, estimates, is_agent, humans=4, agents=1)
    assert idle is not None and idle.days == 5.0  # idle humans never pick up agent steps


def test_a_free_slot_takes_the_longest_remaining_chain_first():
    from dplanner.domain.schedule import parallel_finish

    # In project order: A 1d, D 2d, C 4d, B 5d requiring A. Greedy-by-index starts A and D
    # and lands at 8; taking the longest tail starts A and C, follows A with B, and lands
    # at 6 — the assertion that pins the priority rule.
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    for title in ("A", "D", "C", "B"):
        library.add_child(project.id, Step(title=title))
    a, _d, _c, b = project.steps
    library.set_edges(b.id, "requires", [a.id])
    estimates = days_of({"A": 1, "B": 5, "C": 4, "D": 2})
    pair = parallel_finish(library, project, estimates, NOBODY, humans=2, agents=1)
    assert pair is not None and pair.days == 6.0


def test_unestimated_steps_cost_nothing_and_are_all_counted():
    from dplanner.domain.schedule import parallel_finish

    library, project = diamond()
    finish = parallel_finish(
        library, project, days_of({"A": 1, "D": 1}), NOBODY, humans=2, agents=1
    )
    assert finish is not None
    assert finish.days == 2.0  # B and C run as zero days
    assert finish.unestimated == 2  # project-wide, not just the winning chain


def test_a_chain_of_unestimated_steps_terminates_at_zero(project):
    from dplanner.domain.schedule import parallel_finish

    library, found = project
    finish = parallel_finish(library, found, days_of({}), NOBODY, humans=1, agents=1)
    assert finish is not None
    assert finish.days == 0.0
    assert finish.unestimated == 4


def test_quarter_days_sum_exactly():
    from dplanner.domain.schedule import parallel_finish

    library, found, estimates = loose(("A", 0.25), ("B", 0.75), ("C", 0.25))
    finish = parallel_finish(library, found, estimates, NOBODY, humans=1, agents=1)
    assert finish is not None and finish.days == 1.25


def test_an_empty_project_has_no_makespan_and_an_empty_pool_is_refused():
    from dplanner.domain.schedule import parallel_finish

    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    assert parallel_finish(library, project, days_of({}), NOBODY, humans=1, agents=1) is None
    with pytest.raises(ValueError):
        parallel_finish(library, project, days_of({}), NOBODY, humans=0, agents=1)
    with pytest.raises(ValueError):
        parallel_finish(library, project, days_of({}), NOBODY, humans=1, agents=0)


# -- the plan in stretches -----------------------------------------------------------------------


def test_working_days_between_counts_both_ends_and_skips_the_weekend():
    from dplanner.domain.schedule import working_days_between

    assert working_days_between(MONDAY, MONDAY) == 1
    assert working_days_between(MONDAY, date(2026, 9, 11)) == 5
    assert working_days_between(MONDAY, date(2026, 9, 14)) == 6


def test_the_simulation_says_when_each_step_lands(project):
    """The makespan alone cannot draw an expected-progress curve; the per-step landings
    can — and a phase dates them from its own start."""
    from dplanner.domain.schedule import parallel_finish, phases

    library, plan = project
    a, b, c, d = plan.steps
    days = days_of({"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0})
    run = parallel_finish(library, plan, days, lambda _s: False, humans=1, agents=1)
    assert run is not None
    assert run.landings == {a.id: 1.0, b.id: 3.0, c.id: 6.0, d.id: 10.0}
    (only,) = phases(
        library,
        plan,
        days,
        lambda _s: False,
        humans=1,
        agents=1,
        start=MONDAY,
        is_milestone=lambda _s: False,
        start_for=lambda _s: None,
    )
    assert [only.landing_of(step.id) for step in plan.steps] == [
        MONDAY,
        date(2026, 9, 9),
        date(2026, 9, 14),
        date(2026, 9, 18),
    ]
    assert only.landing_of("nobody") == MONDAY  # unknown or weightless: the stretch's start


def test_a_subset_simulation_treats_edges_out_of_it_as_met(project):
    from dplanner.domain.schedule import parallel_finish

    library, plan = project
    _a, _b, c, d = plan.steps
    days = days_of({"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0})
    whole = parallel_finish(library, plan, days, lambda _s: False, humans=1, agents=1)
    later = parallel_finish(library, plan, days, lambda _s: False, humans=1, agents=1, among=(c, d))
    assert whole is not None and whole.days == 10.0
    assert later is not None and later.days == 7.0  # C no longer waits for B


def _stretches(library, plan, *, milestones, dated=None, start=MONDAY):
    from dplanner.domain.schedule import phases

    days = days_of({"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0})
    dated = dated or {}
    return phases(
        library,
        plan,
        days,
        lambda _s: False,
        humans=1,
        agents=1,
        start=start,
        is_milestone=lambda step: step.title in milestones,
        start_for=lambda step: dated.get(step.title),
    )


def test_without_milestones_the_plan_is_one_stretch_from_the_start(project):
    library, plan = project
    (only,) = _stretches(library, plan, milestones=())
    assert only.milestone is None
    assert [step.title for step in only.steps] == ["A", "B", "C", "D"]
    assert (only.days, only.start, only.finish) == (10.0, MONDAY, date(2026, 9, 18))
    assert only.calendar_days == 10


def test_milestones_run_in_sequence_each_from_the_day_after_the_last(project):
    """B closes A+B; D closes C+D. The second stretch begins the working day after the
    first lands, so the whole is the serial schedule cut in two."""
    library, plan = project
    first, second = _stretches(library, plan, milestones=("B", "D"))
    assert [s.title for s in first.steps] == ["A", "B"]
    assert (first.start, first.finish) == (MONDAY, date(2026, 9, 9))
    assert [s.title for s in second.steps] == ["C", "D"]
    assert (second.start, second.finish) == (date(2026, 9, 10), date(2026, 9, 18))
    assert not first.pushed and not second.pushed


def test_a_dated_milestone_begins_on_its_date_and_a_kept_one_says_so(project):
    library, plan = project
    _first, second = _stretches(
        library, plan, milestones=("B", "D"), dated={"D": date(2026, 9, 21)}
    )
    assert second.asked == date(2026, 9, 21) and second.start == date(2026, 9, 21)
    assert not second.pushed
    assert second.finish == date(2026, 9, 29)


def test_a_date_before_the_previous_landing_is_pushed_and_reported(project):
    library, plan = project
    _first, second = _stretches(library, plan, milestones=("B", "D"), dated={"D": date(2026, 9, 8)})
    assert second.asked == date(2026, 9, 8)
    assert second.start == date(2026, 9, 10)  # the sequence holds
    assert second.pushed


def test_the_first_milestone_may_be_dated_before_the_project_start(project):
    library, plan = project
    first, _second = _stretches(library, plan, milestones=("B", "D"), dated={"B": date(2026, 9, 5)})
    assert first.start == MONDAY  # a Saturday rolls to the Monday, which is the start
    assert not first.pushed
    earlier, _ = _stretches(library, plan, milestones=("B", "D"), dated={"B": date(2026, 9, 1)})
    assert earlier.start == date(2026, 9, 1)


def test_work_no_milestone_gathers_runs_last_without_one(project):
    library, plan = project
    _first, rest = _stretches(library, plan, milestones=("B",))
    assert rest.milestone is None
    assert [s.title for s in rest.steps] == ["C", "D"]
    assert rest.start == date(2026, 9, 10)


def test_a_stretch_with_nothing_estimated_has_no_landing_and_costs_no_days(project):
    from dplanner.domain.schedule import phases

    library, plan = project
    first, second = phases(
        library,
        plan,
        days_of({"C": 3.0, "D": 4.0}),
        lambda _s: False,
        humans=1,
        agents=1,
        start=MONDAY,
        is_milestone=lambda step: step.title in ("B", "D"),
        start_for=lambda _s: None,
    )
    assert first.finish is None and first.unestimated == 2
    assert first.calendar_days == 0
    assert second.start == MONDAY  # the next begins where the weightless one did


def test_a_loop_in_a_hand_edited_file_is_named():
    from dplanner.domain.ordering import cyclic

    library = Library()
    plan = Project(title="Loop")
    library.add_child(library.id, plan)
    for title in ("A", "B", "C", "D"):
        library.add_child(plan.id, Step(title=title))
    a, b, c, d = plan.steps
    library.set_edges(b.id, "requires", [a.id])
    library.set_edges(d.id, "requires", [c.id])
    assert cyclic(library, plan) == []
    # The model refuses a cycle; a file does not. Write one behind its back.
    a.edges["requires"] = [b.id]
    c.edges["requires"] = [b.id]
    assert [step.title for step in cyclic(library, plan)] == ["A", "B", "C", "D"]


# -- reading two plotted lines ---------------------------------------------------------------


def test_a_line_is_read_at_a_date_by_interpolating_between_its_corners():
    """What every chart drawing a plan does, and the one place it is rounded."""
    line = ((date(2026, 9, 1), 0.0), (date(2026, 9, 11), 1.0))
    assert share_at(line, date(2026, 9, 1)) == 0.0
    assert share_at(line, date(2026, 9, 6)) == pytest.approx(0.5)
    assert share_at(line, date(2026, 9, 30)) == 1.0  # held flat past the last point
    assert share_at(line, date(2026, 8, 20)) is None  # before it begins, it says nothing
    assert share_at((), date(2026, 9, 1)) is None
    assert share_at(((date(2026, 9, 1), 0.4),), date(2026, 8, 1)) == 0.4  # one point is flat


def test_two_plans_are_cut_into_runs_of_one_sign_at_the_day_they_cross():
    """The area between two plans changes colour where they meet, not at the next knot —
    so the fill says which way the plan moved on every day it did."""
    first, last = date(2026, 9, 1), date(2026, 9, 11)
    plan = ((first, 0.0), (last, 1.0))
    base = ((first, 0.4), (last, 0.6))
    runs = change_runs(plan, base)
    assert [sign for sign, _ in runs] == [-1, 1]  # the baseline leads, then the plan does
    (_, behind), (_, ahead) = runs
    crossing = behind[-1]
    assert crossing == ahead[0]  # the crossing belongs to both runs, so the fills meet
    assert crossing[1] == pytest.approx(crossing[2], abs=0.02)  # and the lines agree there
    assert date(2026, 9, 4) <= crossing[0] <= date(2026, 9, 6)


def test_two_plans_that_agree_are_one_run_of_no_sign():
    """A plan unchanged since the basis has no area to fill: the run is drawn as a line."""
    line = ((date(2026, 9, 1), 0.0), (date(2026, 9, 11), 1.0))
    (sign, run) = change_runs(line, line)[0]
    assert sign == 0 and len(run) == 2
    assert change_runs(line, ()) == []
