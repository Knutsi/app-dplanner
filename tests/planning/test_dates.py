"""How a date reads, wherever DPlanner prints one."""

from datetime import date

from dplanner.planning.dates import format_date


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
