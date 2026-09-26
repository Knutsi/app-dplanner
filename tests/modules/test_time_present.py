"""What the Time tab shows, as data — the figures, the burn-up, the marks and the scale the
window and the report both draw from.

No ``qapp`` fixture: ``present.py`` is Qt-free by rule, and this file proves it works without
one.
"""

from datetime import date, timedelta

from dplanner.modules.time_estimates.present import (
    Jump,
    Named,
    ScopeMark,
    burnup,
    change_words,
    landed_by,
    moved_words,
    nice_ceiling,
    present,
    reach_of,
    scope_marks,
)
from dplanner.modules.time_estimates.progress import (
    A_WEEK_AGO,
    AT_START,
    Landing,
    Pick,
    Snapshot,
    Stretch,
    Tally,
    resolve,
)

MONDAY = date(2026, 9, 7)
DAY = timedelta(days=1)


def row(day, *, steps=4, done=0, days=8.0, done_days=0.0, changed=0, finish=None, title=""):
    """One stretch's plan on ``day``: ``steps`` steps worth ``days``, landing ``finish``."""
    landing = finish or MONDAY + 9 * DAY
    return Snapshot(
        day,
        (
            Stretch(
                "",
                Tally(steps, done, days, done_days, changed),
                MONDAY,
                landing,
                (Landing(landing, steps, days),),
            ),
        ),
        title=title,
    )


def test_the_scale_takes_finer_steps_than_one_two_five():
    """Two stacked plots cannot afford half of each left empty."""
    values = (0.0, 1.0, 3.0, 12.0, 20.0, 41.0, 130.0)
    assert [nice_ceiling(value) for value in values] == [1.0, 1.0, 3.0, 15.0, 20.0, 50.0, 150.0]


def test_a_move_is_worded_with_its_arrow_and_a_true_minus():
    assert moved_words(3) == "▶ +3d"
    assert moved_words(-2) == "◀ \N{MINUS SIGN}2d"
    assert moved_words(0) == "± 0d"
    assert moved_words(None) == ""


def test_a_days_changes_are_marked_once_by_their_sum():
    """Days decide the way it went, and steps where the days did not move; a day that
    netted nothing has no mark at all."""
    marks = scope_marks(
        (
            Jump(MONDAY, 1, 2.0),
            Jump(MONDAY, 1, 1.0),
            Jump(MONDAY + DAY, -1, 0.0),
            Jump(MONDAY + 2 * DAY, 1, 2.0),
            Jump(MONDAY + 2 * DAY, -1, -2.0),
        )
    )
    assert marks == (
        ScopeMark(MONDAY, True, 2, 3.0),
        ScopeMark(MONDAY + DAY, False, -1, 0.0),
    )
    assert change_words(marks[0], MONDAY) == "+2 steps, +3d on 7 Sep"
    assert change_words(marks[1], MONDAY) == "\N{MINUS SIGN}1 step, +0d on 8 Sep"


def test_the_burnup_reads_the_recorded_days_and_tells_a_day_of_work_from_a_quiet_one():
    """The day shown replaces its own record; a day is active when a status changed on it,
    or — for a row written before DPlanner counted them — when the done count moved."""
    history = [
        row(MONDAY),
        row(MONDAY + DAY, changed=1),  # a step started: nothing done, still a day of work
        row(MONDAY + 2 * DAY, done=1, done_days=2.0),  # an old row: the count moved
        row(MONDAY + 3 * DAY, done=1, done_days=2.0, steps=5, days=10.0),  # scope grew
    ]
    now = row(MONDAY + 3 * DAY, done=1, done_days=2.0, steps=5, days=11.0)
    found = burnup(now, history, history[0], None)
    assert found.scope == (
        (MONDAY, 8.0),
        (MONDAY + DAY, 8.0),
        (MONDAY + 2 * DAY, 8.0),
        (MONDAY + 3 * DAY, 11.0),
    )
    assert found.done[-1] == (MONDAY + 3 * DAY, 2.0)
    assert found.active == (MONDAY + DAY, MONDAY + 2 * DAY)
    assert found.baseline == 8.0
    # Two changes on the day shown — the record, then the live plan — are one mark.
    assert found.marks == (ScopeMark(MONDAY + 3 * DAY, True, 1, 3.0),)
    assert found.promised[0] == (MONDAY, 0.0) and found.promised[-1][1] == 11.0


def test_a_scope_reads_done_from_the_first_record_that_had_it_done():
    history = [row(MONDAY), row(MONDAY + DAY, done=4, done_days=8.0)]
    now = row(MONDAY + 3 * DAY, done=4, done_days=8.0)
    assert landed_by(history, now, None) == MONDAY + DAY
    assert landed_by(history, row(MONDAY + 3 * DAY), None) is None


def test_the_axes_hold_the_reach_of_every_record():
    reach = reach_of([row(MONDAY, finish=MONDAY + 4 * DAY), row(MONDAY + DAY, days=12.0)])
    assert reach.first == MONDAY and reach.last == MONDAY + 9 * DAY and reach.days == 12.0


def test_a_week_ago_is_the_last_record_on_or_before_it():
    now = row(MONDAY + 14 * DAY)
    history = [row(MONDAY), row(MONDAY + 6 * DAY), row(MONDAY + 8 * DAY)]
    found = resolve(A_WEEK_AGO, history=history, saved=[], live=now, start=MONDAY)
    assert found is history[1]


def test_nothing_before_today_is_nothing_to_compare_with_but_a_snapshot_saved_today_is():
    """Today's own record is the plan now, never a plan to compare with; a snapshot saved
    earlier today is exactly one."""
    now = row(MONDAY, days=10.0)
    named = (Named("", "All work"),)
    alone = present(now, history=[row(MONDAY)], saved=[], pick=AT_START, start=MONDAY, named=named)
    assert not alone.compared and alone.basis == "" and alone.whole.moved is None
    kept = row(MONDAY, title="Kickoff", finish=MONDAY + 8 * DAY)
    against = present(
        now,
        history=[row(MONDAY)],
        saved=[kept],
        pick=Pick("saved", title="Kickoff"),
        start=MONDAY,
        named=named,
    )
    assert against.compared and against.whole.moved == 1
    assert against.burnup.baseline == 8.0
