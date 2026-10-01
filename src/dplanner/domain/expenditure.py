"""What a project's steps consumed in tokens, in the order they can be done, and what was
expected of them.

The Expenditure tab is this walk. Like ``schedule.py`` it is handed functions, never
schemas: what each step spent (``spent_for`` — the ledger's records, summed per model by
whoever reads them), its estimate in days (``days_for``), whether it is finished
(``done_for``). Nothing is stored; the answer is as fresh as the ledger and the graph.

**Tokens, never money.** A token's price depends on the plan, the tier, the mode and the
region, and on a subscription nothing is spent at all. The counts are the vendors' own and
add across vendors; a cost is somebody else's derivation over them.

**What was expected is learned, and from elsewhere when it can be.** The expected tokens of a
step are its estimate times a *rate* — tokens of work (fresh input and output; cache reads
are context, not work) per estimated day — measured over finished steps that carry both an
estimate and recorded runs (:func:`learned_rate`). Learned from the very steps it is then
compared with, the running offset would end at 0% by construction, so the caller measures
it on the library's *other* projects first and falls back to this one only when nothing
else has history (:class:`Rate` says which it is).
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from dplanner.domain.agents import Tokens, summed
from dplanner.domain.model import Step
from dplanner.domain.ordering import Placed

# Where a rate was learned: the library's other projects, or this project's own steps.
ELSEWHERE = "elsewhere"
HERE = "here"


@dataclass(frozen=True)
class Spent:
    """What one step's agent runs consumed, per model."""

    runs: int = 0
    models: Mapping[str, Tokens] = field(default_factory=dict)

    @property
    def tokens(self) -> Tokens:
        return summed(self.models.values())


@dataclass(frozen=True)
class Rate:
    """Tokens of work per estimated day, and over how many finished steps it was learned."""

    per_day: float
    steps: int
    source: str = HERE


@dataclass(frozen=True)
class Row:
    place: Placed
    spent: Spent
    running: int  # Tokens of work spent on this step and every step before it.
    expected: float | None  # This step's expected tokens of work; None when not estimated.
    running_expected: float  # Expected tokens of work up to and including this step.
    # Running spent against running expected, as a fraction (0.08 is 8% over), on a finished
    # step with something expected so far; None anywhere else.
    offset: float | None


def learned_rate(
    steps: Iterable[Step],
    spent_for: Callable[[Step], Spent],
    days_for: Callable[[Step], float | None],
    done_for: Callable[[Step], bool],
    source: str = HERE,
) -> Rate | None:
    """Tokens of work per estimated day over the finished steps that have both an estimate
    and recorded runs; None when there are none."""
    days, worked, counted = 0.0, 0, 0
    for step in steps:
        estimate = days_for(step)
        spent = spent_for(step)
        if not done_for(step) or not estimate or not spent.runs:
            continue
        days += estimate
        worked += spent.tokens.worked
        counted += 1
    if not counted or days <= 0:
        return None
    return Rate(worked / days, counted, source)


def expenditure(
    order: Sequence[Placed],
    spent_for: Callable[[Step], Spent],
    days_for: Callable[[Step], float | None],
    done_for: Callable[[Step], bool],
    rate: Rate | None,
) -> list[Row]:
    """Each step in order with what it spent, what was expected, and the running offset."""
    rows: list[Row] = []
    running, running_expected = 0, 0.0
    for place in order:
        spent = spent_for(place.step)
        running += spent.tokens.worked
        days = days_for(place.step)
        expected = days * rate.per_day if rate is not None and days is not None else None
        running_expected += expected or 0.0
        offset = (
            (running - running_expected) / running_expected
            if done_for(place.step) and running_expected > 0
            else None
        )
        rows.append(Row(place, spent, running, expected, running_expected, offset))
    return rows


def totals(rows: Sequence[Row]) -> Tokens:
    return summed(row.spent.tokens for row in rows)


def models_in(rows: Sequence[Row]) -> list[str]:
    """Every model any step used, most work first — the per-model columns' order."""
    work: dict[str, int] = {}
    for row in rows:
        for model, counts in row.spent.models.items():
            work[model] = work.get(model, 0) + counts.worked
    return sorted(work, key=lambda model: (-work[model], model))


def spent_by_step(
    records: Iterable[tuple[str, Mapping[str, Tokens]]],
) -> dict[str, Spent]:
    """Each step's runs folded into one :class:`Spent`, from ``(step id, models)`` pairs."""
    folded: dict[str, Spent] = {}
    for step_id, models in records:
        before = folded.get(step_id, Spent())
        merged = dict(before.models)
        for model, counts in models.items():
            merged[model] = merged.get(model, Tokens()) + counts
        folded[step_id] = Spent(before.runs + 1, merged)
    return folded
