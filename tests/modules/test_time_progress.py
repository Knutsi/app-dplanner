"""How far the plan has come, derived, and the history that remembers where it stood.

No ``qapp`` fixture: ``progress.py`` is Qt-free by rule, and this file proves it works
without one.
"""

from datetime import date

import pytest

from dplanner.domain.model import Library, Project, Step
from dplanner.modules.time_estimates.progress import (
    Delta,
    Landing,
    Snapshot,
    Stretch,
    Tally,
    actual,
    baseline,
    changes_since,
    delta,
    delta_words,
    expected,
    read_history,
    recorded,
    take,
    write_history,
)

MONDAY = date(2026, 9, 7)
NOBODY = None  # is_agent: nobody; every step is human work.


def is_agent(_step):
    return False


@pytest.fixture
def plan():
    """A → B (milestone v1) → C → D (milestone v2), 1/2/3/4 days, B and D done — wait,
    only A and B done: v1 is landed, v2 has nothing of its own landed yet."""
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    for title in ("A", "B", "C", "D"):
        library.add_child(project.id, Step(title=title))
    for waiting, before in zip(project.steps[1:], project.steps, strict=False):
        library.set_edges(waiting.id, "requires", [before.id])
    return library, project


DAYS = {"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0}


def days_for(step):
    return DAYS.get(step.title)


def milestones(*titles):
    return lambda step: step.title in titles


def done(*titles):
    return lambda step: "done" if step.title in titles else "pending"


def snapshot(plan, *, finished=("A", "B"), closing=("B", "D"), today=date(2026, 9, 10)) -> Snapshot:
    library, project = plan
    found = take(
        library,
        project,
        days_for,
        is_agent,
        done(*finished),
        humans=1,
        agents=1,
        start=MONDAY,
        efficiency=1.0,
        is_milestone=milestones(*closing),
        start_for=lambda _s: None,
        today=today,
    )
    assert found is not None
    return found


def key_of(plan, title):
    _library, project = plan
    return next(step.id for step in project.steps if step.title == title)


# -- the tally -----------------------------------------------------------------------------------


def test_a_snapshot_tallies_each_stretch_in_sequence(plan):
    now = snapshot(plan)
    v1, v2 = now.stretches
    assert v1.key == key_of(plan, "B") and v1.tally == Tally(2, 2, 3.0, 3.0)
    assert (v1.start, v1.finish) == (MONDAY, date(2026, 9, 9))
    assert v2.key == key_of(plan, "D") and v2.tally == Tally(2, 0, 7.0, 0.0)
    assert (v2.start, v2.finish) == (date(2026, 9, 10), date(2026, 9, 18))


def test_progress_toward_a_milestone_is_cumulative_through_it(plan):
    now = snapshot(plan)
    assert now.toward(key_of(plan, "B")) == Tally(2, 2, 3.0, 3.0)
    assert now.toward(key_of(plan, "D")) == Tally(4, 2, 10.0, 3.0)
    assert now.toward(None) == Tally(4, 2, 10.0, 3.0)
    assert now.toward(key_of(plan, "D")).share(by_days=False) == 0.5
    assert now.toward(key_of(plan, "D")).share(by_days=True) == 0.3
    assert now.landing(None) == date(2026, 9, 18)
    assert now.toward("nobody") == Tally() and not now.has("nobody")


def test_nothing_to_be_a_share_of_is_none_not_zero():
    assert Tally().share(by_days=False) is None
    assert Tally(steps=2, days=0.0).share(by_days=True) is None


def test_a_stepless_or_looped_project_has_no_snapshot(plan):
    library, project = plan
    empty = Project(title="Empty")
    library.add_child(library.id, empty)

    def taken(target):
        return take(
            library,
            target,
            days_for,
            is_agent,
            done(),
            humans=1,
            agents=1,
            start=MONDAY,
            efficiency=1.0,
            is_milestone=milestones("B", "D"),
            start_for=lambda _s: None,
            today=date(2026, 9, 10),
        )

    assert taken(empty) is None
    a, _b, _c, d = project.steps
    a.edges["requires"] = [d.id]  # A loop, written behind the model's back.
    assert taken(project) is None


# -- the curves ----------------------------------------------------------------------------------


def test_a_stretch_records_what_lands_on_each_date(plan):
    now = snapshot(plan)
    v1, v2 = now.stretches
    assert v1.landings == (Landing(MONDAY, 1, 1.0), Landing(date(2026, 9, 9), 1, 2.0))
    assert v2.landings == (Landing(date(2026, 9, 14), 1, 3.0), Landing(date(2026, 9, 18), 1, 4.0))


def test_the_expected_curve_is_the_simulations_own_landings(plan):
    now = snapshot(plan)
    assert expected(now, None, by_days=False) == [
        (MONDAY, 0.0),
        (MONDAY, 0.25),  # A lands on day one
        (date(2026, 9, 9), 0.5),  # B on the third
        (date(2026, 9, 14), 0.75),  # C: three days from the 10th
        (date(2026, 9, 18), 1.0),
    ]
    assert expected(now, key_of(plan, "B"), by_days=True) == [
        (MONDAY, 0.0),
        (MONDAY, 1 / 3),
        (date(2026, 9, 9), 1.0),
    ]
    assert expected(now, "nobody", by_days=False) == []


def test_the_actual_curve_is_every_recorded_day_then_today(plan):
    earlier = snapshot(plan, finished=(), today=date(2026, 9, 8))
    then = snapshot(plan, finished=("A",), today=date(2026, 9, 9))
    now = snapshot(plan)
    key = key_of(plan, "D")
    assert actual([earlier, then], now, key, by_days=False) == [
        (date(2026, 9, 8), 0.0),
        (date(2026, 9, 9), 0.25),
        (date(2026, 9, 10), 0.5),
    ]
    # A day recorded before the milestone existed says nothing about it.
    before = snapshot(plan, finished=(), closing=("B",), today=date(2026, 9, 7))
    assert actual([before, then], now, key, by_days=True)[0] == (date(2026, 9, 9), 0.1)
    # Today's live reading replaces its own record rather than doubling it.
    assert actual([then, snapshot(plan, finished=("A",))], now, key, by_days=False)[-1] == (
        date(2026, 9, 10),
        0.5,
    )


def test_the_baseline_is_the_last_record_on_or_before_the_basis(plan):
    first = snapshot(plan, finished=(), today=date(2026, 9, 7))
    later = snapshot(plan, finished=("A",), today=date(2026, 9, 9))
    assert baseline([first, later], date(2026, 9, 8)) is first
    assert baseline([first, later], date(2026, 9, 9)) is later
    # A project older than its history compares against the first day recorded.
    assert baseline([first, later], date(2026, 9, 1)) is first
    assert baseline([], date(2026, 9, 7)) is None


def test_the_delta_says_what_was_added_and_how_the_landing_moved(plan):
    library, project = plan
    key = key_of(plan, "D")
    then = snapshot(plan, finished=(), today=date(2026, 9, 7))
    library.add_child(project.id, Step(title="E"))
    _a, _b, c, d, e = project.steps
    library.set_edges(d.id, "requires", [c.id, e.id])  # E joins v2's stretch
    DAYS["E"] = 5.0
    try:
        now = snapshot(plan, finished=("A",))
        moved = delta(then, now, key)
        assert moved == Delta(1, 5.0, date(2026, 9, 18), date(2026, 9, 25))
        assert moved.shift == 5 and not moved.unchanged
        assert delta_words(moved, then.day) == (
            "since 7 September: +1 step, +5d, lands 5 working days later (was 18 September)"
        )
        still = delta(then, now, key_of(plan, "B"))  # v1 did not move
        assert still is not None and still.unchanged
        assert delta_words(still, then.day) == "unchanged since 7 September"
        assert delta(then, now, "nobody") is None
    finally:
        del DAYS["E"]


def test_the_change_report_names_steps_born_and_re_estimated_after_the_basis(plan):
    library, project = plan
    a, b, _c, _d = project.steps
    library.add_child(project.id, Step(title="E", created="2026-09-10T09:00:00+00:00"))
    for step in (a, b):
        step.created = "2026-09-01T09:00:00+00:00"
    history = {a.id: [(date(2026, 9, 12), 3.0)], b.id: [(date(2026, 9, 2), 1.0)]}
    changes = changes_since(project, date(2026, 9, 7), days_for, lambda s: history.get(s.id, []))
    assert [(step.title, days) for step, days in changes.added] == [("E", None)]
    assert [(step.title, when, was, days) for step, when, was, days in changes.estimates] == [
        ("A", date(2026, 9, 12), 3.0, 1.0)
    ]
    assert changes.since == date(2026, 9, 7)
    assert changes.lines(lambda step: f"S{step.title}") == [
        "added since 7 September: SE",
        "re-estimated since 7 September: SA 3d → 1d on 12 September",
    ]
    assert changes_since(project, date(2026, 9, 30), days_for, lambda _s: []).lines(str) == []


# -- the history on disk -------------------------------------------------------------------------


def test_the_history_round_trips_with_absence_for_the_defaults(plan):
    now = snapshot(plan, closing=("B",))
    entry = write_history([now])
    (row,) = entry["days"]
    assert row["day"] == "2026-09-10"
    assert row["stretches"][0] == {
        "milestone": key_of(plan, "B"),
        "steps": 2,
        "done": 2,
        "days": 3.0,
        "done_days": 3.0,
        "start": "2026-09-07",
        "finish": "2026-09-09",
        "landings": [
            {"date": "2026-09-07", "steps": 1, "days": 1.0},
            {"date": "2026-09-09", "steps": 1, "days": 2.0},
        ],
    }
    assert "milestone" not in row["stretches"][1]  # the work after the last milestone
    project = Project(title="P")
    project.module_data["progress_history"] = entry
    assert read_history(project) == [now]
    assert write_history([]) == {}


def test_unreadable_rows_read_as_absent():
    project = Project(title="P")
    project.module_data["progress_history"] = {
        "format": 1,
        "days": [
            {"day": "soon", "stretches": []},
            {"day": "2026-09-10", "stretches": [{"start": "never"}]},
            {
                "day": "2026-09-11",
                "stretches": [{"start": "2026-09-07", "steps": True, "landings": [{"x": 1}]}],
            },
            "junk",
        ],
    }
    (row,) = read_history(project)
    assert row == Snapshot(
        date(2026, 9, 11), (Stretch("", Tally(0, 0, 0.0, 0.0), date(2026, 9, 7), None),)
    )


def test_recording_writes_only_when_the_day_says_something_new(plan):
    first = snapshot(plan, finished=(), today=date(2026, 9, 7))
    assert recorded([], first) == [first]
    # The same state on a later day is nothing new; last-wins within a day.
    assert recorded([first], snapshot(plan, finished=(), today=date(2026, 9, 8))) is None
    later = snapshot(plan, finished=("A",), today=date(2026, 9, 7))
    assert recorded([first], later) == [later]
    next_day = snapshot(plan, finished=("A", "B"), today=date(2026, 9, 8))
    assert recorded([first, later], next_day) == [first, later, next_day]
    assert recorded([first, later, next_day], next_day) is None


def test_a_milestone_whose_start_is_later_opens_a_gap_the_plan_holds_flat(plan):
    """D's own start date holds its stretch back past B's landing: the span is idle, each
    milestone is marked where it lands, and the expected line holds flat from B's landing
    to the day work resumes. A weekend between two stretches is not a gap."""
    from dplanner.modules.time_estimates.progress import idle, marks

    library, project = plan
    later = date(2026, 9, 21)
    now = take(
        library,
        project,
        days_for,
        is_agent,
        done("A", "B"),
        humans=1,
        agents=1,
        start=MONDAY,
        efficiency=1.0,
        is_milestone=milestones("B", "D"),
        start_for=lambda step: later if step.title == "D" else None,
        today=date(2026, 9, 10),
    )
    assert now is not None
    b, d = key_of(plan, "B"), key_of(plan, "D")
    assert idle(now, None) == [(date(2026, 9, 9), later)]
    assert idle(now, b) == []
    assert [milestone for _, milestone in marks(now, None)] == [b, d]
    assert marks(now, b) == [(date(2026, 9, 9), b)]
    curve = expected(now, None, by_days=False)
    assert (date(2026, 9, 9), 0.5) in curve and (later, 0.5) in curve
    assert idle(snapshot(plan), None) == []
