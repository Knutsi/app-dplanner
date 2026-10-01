"""The expenditure walk: each step in order with what it spent, what its estimate predicted,
and how far the work so far is over or under."""

from dplanner.domain.agents import Tokens
from dplanner.domain.expenditure import (
    ELSEWHERE,
    Rate,
    Spent,
    expenditure,
    learned_rate,
    models_in,
    spent_by_step,
    totals,
)
from dplanner.domain.model import Step
from dplanner.domain.ordering import Placed

A, B, C, D = (Step(title=title) for title in "ABCD")
ORDER = [Placed(i + 1, 1, step) for i, step in enumerate((A, B, C, D))]
SPENT = {
    A.id: Spent(1, {"opus": Tokens(1000, 50_000, 1000)}),
    B.id: Spent(2, {"opus": Tokens(2000, 0, 1000), "haiku": Tokens(500, 0, 500)}),
    C.id: Spent(1, {"haiku": Tokens(100, 0, 100)}),
}
DAYS = {A.id: 1.0, B.id: 2.0, C.id: None, D.id: 1.0}
DONE = {A.id, B.id}


def _spent(step: Step) -> Spent:
    return SPENT.get(step.id, Spent())


def _days(step: Step) -> float | None:
    return DAYS[step.id]


def _done(step: Step) -> bool:
    return step.id in DONE


def test_the_rate_is_work_per_estimated_day_over_finished_estimated_steps_with_runs():
    """Cache reads are context read again, not work: A's 50k leave its rate alone."""
    rate = learned_rate([A, B, C, D], _spent, _days, _done)
    assert rate == Rate(per_day=(2000 + 4000) / 3.0, steps=2)
    assert learned_rate([C, D], _spent, _days, _done) is None
    assert learned_rate([A], _spent, _days, _done, ELSEWHERE).source == ELSEWHERE  # type: ignore[union-attr]


def test_the_walk_runs_totals_down_the_order_and_offsets_finished_rows():
    rate = Rate(per_day=1500.0, steps=9)
    a, b, c, d = expenditure(ORDER, _spent, _days, _done, rate)
    assert (a.running, b.running, c.running, d.running) == (2000, 6000, 6200, 6200)
    assert (a.expected, b.expected, c.expected, d.expected) == (1500.0, 3000.0, None, 1500.0)
    assert (a.running_expected, b.running_expected, d.running_expected) == (1500, 4500, 6000)
    # A finished row says how far the work so far is from what its estimates predicted;
    # a row nobody finished says nothing.
    assert a.offset == (2000 - 1500) / 1500 and b.offset == (6000 - 4500) / 4500
    assert c.offset is None and d.offset is None
    assert totals([a, b, c, d]) == Tokens(3600, 50_000, 2600)


def test_with_no_rate_nothing_is_expected_and_nothing_is_offset():
    rows = expenditure(ORDER, _spent, _days, _done, None)
    assert all(row.expected is None and row.offset is None for row in rows)
    assert rows[-1].running == 6200


def test_models_come_most_work_first_and_runs_fold_per_step():
    rows = expenditure(ORDER, _spent, _days, _done, None)
    assert models_in(rows) == ["opus", "haiku"]
    folded = spent_by_step(
        [
            ("s1", {"opus": Tokens(1, 2, 3)}),
            ("s1", {"opus": Tokens(1, 0, 0), "haiku": Tokens(0, 0, 9)}),
            ("s2", {}),
        ]
    )
    assert folded["s1"] == Spent(2, {"opus": Tokens(2, 2, 3), "haiku": Tokens(0, 0, 9)})
    assert folded["s2"] == Spent(1, {})
