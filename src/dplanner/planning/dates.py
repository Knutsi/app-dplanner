"""Dates in words: how a day reads wherever DPlanner prints one.

The month names are spelled out here rather than taken from ``strftime``, which is
locale-dependent: the interface is English, and a date that read "23 september" on one
machine and "23 September" on another would be a test that passes where it was written.
Here, in the planning tier, because the tier's own phrases print a day (a wait's "until
21 Oct"), and everything above it — the CLI, the report, the views — prints the same way.
"""

from datetime import date

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
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def format_date(when: date, today: date | None = None) -> str:
    """A date as a person reads it: "23 September", or "14 Feb '27" in another year.

    A schedule is read for *when*, and an ISO date makes the reader do the month arithmetic.
    The year is the part that is usually obvious, so it appears only when it is not — and
    when it does, the month abbreviates to keep the column from doubling in width.

    ``today`` is a parameter so the rule can be tested without waiting for a year to pass;
    the default is the clock, because every caller means "now".
    """
    today = today or date.today()
    if when.year == today.year:
        return f"{when.day} {MONTHS[when.month - 1]}"
    return f"{when.day} {MONTHS[when.month - 1][:ABBREVIATION]} '{when.year % 100:02d}"


def short_date(when: date, today: date | None = None) -> str:
    """A date where a column has no room for the month spelled out: "23 Sep", with the
    year when it is not this one — :func:`format_date`'s rule, one size down. It is what
    the axis marks are labelled with, so a date printed inside a plot reads as the same
    kind of thing as the scale under it."""
    today = today or date.today()
    month = MONTHS[when.month - 1][:ABBREVIATION]
    if when.year == today.year:
        return f"{when.day} {month}"
    return f"{when.day} {month} '{when.year % 100:02d}"
