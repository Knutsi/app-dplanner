"""The axis of a chart over dates: which days it marks, and what each mark says.

Drawn by the report's figures (``drawings.py``) and the Time tab's plot alike, so a date read
off one is placed the same way on the other.
"""

from collections.abc import Iterator
from datetime import date, timedelta
from math import ceil

from dplanner.planning.dates import ABBREVIATION, MONTHS

Tick = tuple[date, str]  # A date on the axis and the label it wears.


def _day_label(when: date) -> str:
    return f"{when.day} {MONTHS[when.month - 1][:ABBREVIATION]}"


def _month_label(when: date) -> str:
    return MONTHS[when.month - 1][:ABBREVIATION]


def _with_years(ticks: list[Tick]) -> tuple[Tick, ...]:
    """The first mark of each new year carries the year, whatever the unit — thinned
    months may skip January, and a week may cross the boundary."""
    labelled: list[Tick] = []
    for index, (when, label) in enumerate(ticks):
        if index and when.year != ticks[index - 1][0].year:
            label = f"{label} '{when.year % 100:02d}"
        labelled.append((when, label))
    return tuple(labelled)


def _days(first: date, last: date) -> Iterator[date]:
    when = first
    while when <= last:
        yield when
        when += timedelta(days=1)


def _mondays(first: date, last: date) -> Iterator[date]:
    when = first + timedelta(days=(7 - first.weekday()) % 7)
    while when <= last:
        yield when
        when += timedelta(days=7)


def _month_starts(first: date, last: date) -> Iterator[date]:
    year, month = first.year, first.month
    if first.day != 1:
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    while date(year, month, 1) <= last:
        yield date(year, month, 1)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def axis_ticks(first: date, last: date, room: int) -> tuple[Tick, ...]:
    """The dates marked along the axis and their labels: every day, else every Monday,
    else every month's first — the finest unit whose marks fit ``room`` (how many labels
    the plot has width for) — and months thinned to every second, third… when even those
    do not. Calendar boundaries, never an even division of the span, because a reader
    places a point by the nearest mark. At least one mark, whatever the room."""
    days = list(_days(first, last))
    if len(days) <= room:
        return _with_years([(when, _day_label(when)) for when in days])
    mondays = list(_mondays(first, last))
    if mondays and len(mondays) <= room:
        return _with_years([(when, _day_label(when)) for when in mondays])
    months = list(_month_starts(first, last))
    every = max(1, ceil(len(months) / max(1, room)))
    ticks = _with_years([(when, _month_label(when)) for when in months[::every]])
    return ticks or ((first, _day_label(first)),)
