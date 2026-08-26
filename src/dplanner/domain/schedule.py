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

**Serial, and in working days.** Steps run one after another down the topological order,
weekends are skipped, and a week is five working days. That is deliberately the simple
answer: a dependency-aware schedule, where independent branches run side by side, is the next
refinement and needs nothing here to move — only ``schedule`` to place a step after everything
it waits on rather than after its predecessor in the list.

**Nothing here is written to disk**, for ``ordering.py``'s reason: a stored date disagrees
with the estimate it came from the moment ``dplanner estimate set`` runs with no window open
to notice.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil

from dplanner.domain.model import Step
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


def schedule(
    order: Sequence[Placed],
    days_for: Callable[[Step], float | None],
    start: date | None = None,
) -> list[Scheduled]:
    """The order with a running total and a date against each step.

    Without a ``start`` the totals are still the answer to "how much work is in front of
    this" — the dates are simply the part that needs a calendar.
    """
    scheduled: list[Scheduled] = []
    accumulated = 0.0
    for place in order:
        days = days_for(place.step)
        if days is not None:
            accumulated += days
        finish = None
        if days is not None and start is not None and accumulated > 0:
            finish = working_days_after(start, accumulated)
        scheduled.append(Scheduled(place=place, days=days, accumulated=accumulated, finish=finish))
    return scheduled
