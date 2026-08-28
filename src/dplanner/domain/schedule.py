"""When does the work land — the order walk, carrying estimates instead of counting hops.

``ordering.py`` answers "in what order can this be done"; this answers "and when". It is the
same walk: take the placed order, ask how many days each step is thought to take, and lay
them end to end from a start date.

**The domain never learns what an estimate is stored as.** ``days_for`` is a function the
caller supplies, so the module that owns the estimate aspect owns its schema, and this file
works for any other source of days somebody wires in later. That is the same seam
``ordering.py`` uses for the graph — plain functions over the model, no Qt — and it is what
lets the order table, ``dplanner schedule show``, ``--json`` and every report after them read
one implementation.

**Two named assumptions, no pretend precision.** ``schedule`` is serial — one worker, steps
end to end down the topological order, weekends skipped, a week is five working days.
``critical_path`` is the other bracket: unlimited workers, bounded only by the ``requires``
chains. Real staffing lands between the two, and a report that prints both labelled is
honest where a single number would be a guess wearing a date.

**Every plan has a start.** A project nobody has dated starts today — the caller resolves
that (see ``estimation/schedule.py``'s ``start_of``) and this file is simply handed a date.
"If you start now" is the useful answer to a plan with no date on it, and it means there is
one code path here rather than two.

**Nothing here is written to disk**, for ``ordering.py``'s reason: a stored date disagrees
with the estimate it came from the moment ``dplanner estimate set`` runs with no window open
to notice.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil

from dplanner.domain.model import Product, Project, Step, StepId
from dplanner.domain.ordering import Placed

WORKING_DAYS_PER_WEEK = 5
SATURDAY = 5  # date.weekday(): Monday is 0.

# Past this much work, days stop being the unit a person thinks in.
WEEKS_ABOVE_DAYS = 7.0

_ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class Scheduled:
    """One step's place in the plan: what it costs, what it has cost by then, and when.

    ``days`` is ``None`` for an unestimated step, and so is ``finish``. "We have not
    estimated this" and "this is free" are different claims — a date printed against a step
    nobody has sized would read as a promise, so the column stays empty and the gap shows.
    ``accumulated`` still carries the known work through that point.
    """

    place: Placed
    days: float | None
    accumulated: float
    finish: date | None


def next_working_day(when: date) -> date:
    """``when``, or the Monday after it if it lands on a weekend."""
    while when.weekday() >= SATURDAY:
        when += _ONE_DAY
    return when


def working_days_after(start: date, days: float) -> date:
    """The date working day ``days`` falls on, counting ``start`` as working day one.

    A fraction is still a day on a calendar — half a day of work lands on a date — so the
    count rounds up. A start on a weekend rolls forward to the Monday.
    """
    when = next_working_day(start)
    for _ in range(max(1, ceil(days)) - 1):
        when = next_working_day(when + _ONE_DAY)
    return when


MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
ABBREVIATION = 3  # "September" → "Sep". True of every month in English.


def format_date(when: date, today: date | None = None) -> str:
    """A date as a person reads it: "23 September", or "14 Feb '27" in another year.

    A schedule is read for *when*, and an ISO date makes the reader do the month arithmetic.
    The year is the part that is usually obvious, so it appears only when it is not — and
    when it does, the month abbreviates to keep the column from doubling in width.

    The month names are spelled out here rather than taken from ``strftime``, which is
    locale-dependent: the interface is English, and a date that read "23 september" on one
    machine and "23 September" on another would be a test that passes where it was written.

    ``today`` is a parameter so the rule can be tested without waiting for a year to pass;
    the default is the clock, because every caller means "now".
    """
    today = today or date.today()
    if when.year == today.year:
        return f"{when.day} {MONTHS[when.month - 1]}"
    return f"{when.day} {MONTHS[when.month - 1][:ABBREVIATION]} '{when.year % 100:02d}"


def as_weeks(days: float) -> float:
    """``days`` of work as working weeks. A week is five days, because a day is a working one."""
    return days / WORKING_DAYS_PER_WEEK


def format_days(days: float | None) -> str:
    """A day count as a person reads it: "3d", or "2.4w" once there are too many days.

    Here rather than in a view because the order table and ``dplanner schedule show`` render
    the same numbers, and a table that said "2.4w" where the terminal said "12d" would be two
    answers to one question — the argument ``ordering.placed()`` already makes for the index.
    """
    if days is None:
        return ""
    if days > WEEKS_ABOVE_DAYS:
        return f"{as_weeks(days):g}w"
    return f"{days:g}d"


def format_day_count(days: float) -> str:
    """A day count as prose: "1 day", "2.5 days" — for sentences, where ``format_days``
    feeds columns. The grammar lives here so no verb prints "1 days" again."""
    return f"{days:g} day" if days == 1 else f"{days:g} days"


def schedule(
    order: Sequence[Placed],
    days_for: Callable[[Step], float | None],
    start: date,
) -> list[Scheduled]:
    """The order with a running total and a date against each step."""
    scheduled: list[Scheduled] = []
    accumulated = 0.0
    for place in order:
        days = days_for(place.step)
        if days is not None:
            accumulated += days
        finish = working_days_after(start, accumulated) if days is not None else None
        scheduled.append(Scheduled(place=place, days=days, accumulated=accumulated, finish=finish))
    return scheduled


@dataclass(frozen=True)
class CriticalPath:
    """The longest days-weighted chain through a project's ``requires`` graph.

    The serial schedule answers "one worker, steps end to end"; this answers the other
    honest assumption — unlimited workers, dependency-bound — and the two bracket every
    real staffing in between.
    """

    days: float  # The chain's total; a floor no amount of staffing gets under.
    steps: tuple[Step, ...]  # The chain itself, first thing first.
    unestimated: int  # Steps on the chain counted as zero days — the floor's honesty.


def critical_path(
    product: Product,
    project: Project,
    days_for: Callable[[Step], float | None],
) -> CriticalPath | None:
    """None only when the project has no steps.

    ``ordering.depths()``'s walk, weighted by ``days_for`` instead of one per hop — and
    handed the function rather than a schema, so whoever owns the estimate keeps its
    shape. Ties break by project step order, the same rule every derivation here uses,
    so the answer changes when the graph or the estimates change and not otherwise.
    """
    if not project.steps:
        return None
    order = {step.id: index for index, step in enumerate(project.steps)}
    finishes: dict[StepId, float] = {}
    towards: dict[StepId, StepId | None] = {}

    def finish_of(step_id: StepId, seen: frozenset[StepId]) -> float:
        if step_id in finishes:
            return finishes[step_id]
        if step_id in seen:  # Defensive: a hand-edited file could still contain a cycle.
            return 0.0
        step = product.step(step_id)
        own = days_for(step) or 0.0
        waiting = step.edges.get("requires", [])
        resolved = sorted(
            (target for target in waiting if project.step(target) is not None),
            key=lambda target: order[target],
        )
        best: StepId | None = None
        upstream = 0.0
        for target in resolved:
            candidate = finish_of(target, seen | {step_id})
            if candidate > upstream:  # Strict: the earliest of equals keeps the tie.
                upstream, best = candidate, target
        finishes[step_id] = own + upstream
        towards[step_id] = best
        return finishes[step_id]

    for step in project.steps:
        finish_of(step.id, frozenset())
    last = max(project.steps, key=lambda step: (finishes[step.id], -order[step.id]))
    chain: list[Step] = []
    at: StepId | None = last.id
    while at is not None:
        chain.append(product.step(at))
        at = towards.get(at)
    chain.reverse()
    return CriticalPath(
        days=finishes[last.id],
        steps=tuple(chain),
        unestimated=sum(1 for step in chain if days_for(step) is None),
    )
