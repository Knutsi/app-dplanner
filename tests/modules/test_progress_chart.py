"""The progress plots: one axis under every plot, a page at a time, the gutters, the
fade, the volume on a scale of days, and the words."""

from datetime import date

import pytest
from PySide6.QtGui import QColor

from dplanner.domain.schedule import axis_ticks
from dplanner.modules.time_estimates.chart import (
    ALL_PAGES,
    BOTTOM_GUTTER,
    LABEL_GAP,
    MAX_PANEL_HEIGHT,
    PAGES,
    PANEL_HEIGHT,
    PROGRESS_PAGE,
    ROW_HEIGHT,
    SHIFT_PAGE,
    VOLUME_PAGE,
    ChartData,
    ProgressChart,
    Segment,
    segment_words,
)


def test_the_axis_marks_the_finest_calendar_unit_that_fits():
    """Days while they fit, else Mondays, else the firsts of months — thinned when even
    those do not — and at least one mark whatever the room."""
    days = axis_ticks(date(2026, 9, 1), date(2026, 9, 10), room=12)
    assert [label for _, label in days] == [f"{day} Sep" for day in range(1, 11)]
    weeks = axis_ticks(date(2026, 8, 31), date(2026, 10, 7), room=12)
    assert all(when.weekday() == 0 for when, _ in weeks)
    assert [label for _, label in weeks] == [
        "31 Aug",
        "7 Sep",
        "14 Sep",
        "21 Sep",
        "28 Sep",
        "5 Oct",
    ]
    months = axis_ticks(date(2026, 8, 20), date(2027, 3, 10), room=12)
    assert [label for _, label in months] == ["Sep", "Oct", "Nov", "Dec", "Jan '27", "Feb", "Mar"]
    thinned = axis_ticks(date(2026, 1, 1), date(2028, 12, 31), room=12)
    assert [when.month for when, _ in thinned] == [1, 4, 7, 10] * 3
    assert [label for _, label in thinned][3:6] == ["Oct", "Jan '27", "Apr"]
    skipping_january = axis_ticks(date(2026, 1, 4), date(2027, 11, 20), room=12)
    assert [label for _, label in skipping_january][5:7] == ["Dec", "Feb '27"]
    across = axis_ticks(date(2026, 12, 20), date(2027, 1, 20), room=12)
    assert [label for _, label in across] == ["21 Dec", "28 Dec", "4 Jan '27", "11 Jan", "18 Jan"]
    assert axis_ticks(date(2026, 9, 1), date(2026, 9, 3), room=0) == ((date(2026, 9, 1), "Sep"),)
    assert axis_ticks(date(2026, 9, 2), date(2026, 9, 4), room=0) == ((date(2026, 9, 2), "2 Sep"),)


FIRST, LAST = date(2026, 9, 1), date(2026, 10, 1)
BLUE, VIOLET, TEAL = QColor("#4a7fd6"), QColor("#8e6fd8"), QColor("#2a9d8f")


def _chart(data: ChartData, width: int = 700, page: str = PROGRESS_PAGE) -> ProgressChart:
    chart = ProgressChart(data.today, page=page)
    chart.show_data(data)
    chart.resize(width, chart.height())
    return chart


def test_the_plots_share_one_axis_and_the_dates_print_once(app):
    """Every plot starts at the same left and spans the same width; the milestone plot
    is a row per milestone, one row's worth to say there are none; the widget is exactly
    as tall as the last plot plus the one gutter the dates are printed in — and the x
    range is the earliest and latest date any plot has to show."""
    plan = ((FIRST, 0.0), (LAST, 1.0))
    chart = _chart(ChartData(FIRST, expected=plan), page=ALL_PAGES)
    metrics = chart.fontMetrics()
    assert [panel.kind for panel in chart.panels()] == [
        "status",
        "scope",
        "shift",
        "volume",
        "remaining",
    ]
    status, _scope, shift, _volume, remaining = chart.panels()
    assert status.rect.left() >= metrics.horizontalAdvance("100%") + LABEL_GAP
    assert all(
        panel.rect.left() == status.rect.left() and panel.rect.width() == status.rect.width()
        for panel in chart.panels()
    )
    assert status.rect.top() >= metrics.height()
    assert shift.rect.height() == ROW_HEIGHT  # one row's worth, to say there are none
    assert chart.height() == round(remaining.rect.bottom() + BOTTOM_GUTTER)
    assert len(chart.ticks()) >= 1
    earlier = date(2026, 8, 20)
    chart.show_data(
        ChartData(
            FIRST,
            expected=plan,
            segments=(
                Segment("m1", "v1", VIOLET, now=(FIRST, date(2026, 9, 15)), then=(earlier, LAST)),
                Segment("m2", "v2", TEAL, now=(date(2026, 9, 16), LAST)),
                Segment("", "Remaining work", BLUE),
            ),
        )
    )
    shift = chart.panel("shift")
    assert shift.rect.height() == 2 * ROW_HEIGHT  # the remainder gets no row
    assert chart.span[0] < earlier < FIRST  # the then-span widened the axis
    chart.deleteLater()


def test_a_page_shows_its_own_plots_and_the_window_shows_every_page(app):
    """Milestone shifts, Progress and Volume are three pages of one widget; the page
    decides the plots and the height, the data is one record whichever page is up."""
    plan = ((FIRST, 0.0), (LAST, 1.0))
    chart = _chart(ChartData(FIRST, expected=plan), page=PAGES[1][0])
    assert chart.page == "progress"
    assert [panel.kind for panel in chart.panels()] == ["status", "scope"]
    _status, scope = chart.panels()
    assert chart.height() == round(scope.rect.bottom() + BOTTOM_GUTTER)
    chart.show_page(SHIFT_PAGE)
    assert [panel.kind for panel in chart.panels()] == ["shift"]
    assert chart.compact_height() == chart.tall_height()  # rows never grow
    chart.show_page(VOLUME_PAGE)
    assert [panel.kind for panel in chart.panels()] == ["volume", "remaining"]
    assert chart.minimumHeight() == chart.compact_height() < chart.tall_height()
    with pytest.raises(ValueError, match="no page called"):
        chart.show_page("elsewhere")
    assert [label for _page, label in PAGES] == ["Milestone shifts", "Progress", "Volume"]
    chart.deleteLater()


def test_the_volume_plots_share_one_scale_in_days(app):
    """The total and the remaining are drawn on one scale — the largest value either
    reaches, rounded up to a figure a reader can divide — labelled in days, and the
    tooltip reads them as days too. A saved snapshot's day is a hairline through every
    plot with its title beside it."""
    total = ((FIRST, 10.0), (date(2026, 9, 10), 10.0), (date(2026, 9, 10), 16.0))
    left = ((FIRST, 10.0), (date(2026, 9, 10), 8.0), (date(2026, 9, 10), 14.0))
    data = ChartData(
        date(2026, 9, 12),
        volume=total,
        remaining=left,
        marks=((date(2026, 9, 5), "Kickoff review"),),
    )
    chart = _chart(data, width=900, page=VOLUME_PAGE)
    assert data.scale == 20.0
    volume, remaining = chart.panels()
    assert volume.scale == remaining.scale == 20.0
    assert (
        chart._y(volume, 20.0) == volume.rect.top()
        and chart._y(volume, 0.0) == volume.rect.bottom()
    )
    assert chart.title(volume) == "Scope volume" and chart.title(remaining) == "Remaining work"
    assert [label for label, _ in chart.legend(remaining)] == ["Total", "Remaining"]
    words = chart.tooltip_at(date(2026, 9, 11), "remaining")  # format_days: weeks past 7d
    assert "scope: 3.2w" in words and "remaining: 2.8w · done 2d" in words
    assert "scope: 2w" in chart.tooltip_at(date(2026, 9, 9), "volume")
    assert "saved as Kickoff review" in chart.tooltip_at(date(2026, 9, 5), "volume")
    image = chart.grab().toImage()
    x = round(chart._x(date(2026, 9, 5)))
    y = round(chart._y(remaining, 5.0))
    assert image.pixelColor(x, y).name() != image.pixelColor(x + 6, y).name()  # the hairline
    chart.deleteLater()


def test_the_share_plots_take_the_height_they_are_given_up_to_a_ceiling(app):
    """A tall host grows the page's two plots in equal parts; a short one gets the floor;
    past the ceiling neither grows again, and the milestone rows never do."""
    plan = ((FIRST, 0.0), (LAST, 1.0))
    chart = _chart(
        ChartData(
            FIRST,
            expected=plan,
            segments=(Segment("m1", "v1", VIOLET, now=(FIRST, LAST)),),
        )
    )
    chart.resize(700, chart.compact_height())
    status, scope = chart.panels()
    assert status.rect.height() == scope.rect.height() == PANEL_HEIGHT
    assert chart.minimumHeight() == chart.compact_height()
    chart.resize(700, chart.compact_height() + 200)
    status, scope = chart.panels()
    assert status.rect.height() == scope.rect.height() == PANEL_HEIGHT + 100
    chart.resize(700, chart.tall_height() + 400)
    status, scope = chart.panels()
    assert status.rect.height() == scope.rect.height() == MAX_PANEL_HEIGHT
    assert chart.maximumHeight() == chart.tall_height()
    chart.show_page(SHIFT_PAGE)
    chart.resize(700, chart.compact_height() + 200)
    (shift,) = chart.panels()
    assert shift.rect.height() == ROW_HEIGHT  # a row is a row
    chart.deleteLater()


def test_the_scope_heading_names_the_basis_and_every_landing_carries_its_milestone(app):
    """The heading names the plan the reader picked, with the record that stood in for
    it; the keys carry no second name; and each milestone's landing on the progress line
    sits on the plan at its own share, named."""
    plan = ((FIRST, 0.0), (date(2026, 9, 16), 0.5), (LAST, 1.0))
    segments = (
        Segment("m1", "v1", VIOLET, now=(FIRST, date(2026, 9, 16))),
        Segment("m2", "v2", TEAL, now=(date(2026, 9, 17), LAST)),
    )
    chart = _chart(ChartData(FIRST, expected=plan, segments=segments), width=900)
    assert chart.title(chart.panel("scope")) == "Scope change — nothing to compare with"
    assert chart.title(chart.panel("status")) == "Progress"
    status = chart.panel("status")
    marks = chart.landing_marks(status)
    assert [(segment.key, name) for segment, name, _ in marks] == [("m1", "v1"), ("m2", "v2")]
    assert [round(at.x()) for _s, _n, at in marks] == [
        round(chart._x(date(2026, 9, 16))),
        round(chart._x(LAST)),
    ]
    assert marks[0][2].y() == chart._y(status, 0.5) and marks[1][2].y() == chart._y(status, 1.0)
    image = chart.grab().toImage()
    for segment, _name, at in marks:
        assert image.pixelColor(round(at.x()), round(at.y())).name() == segment.color.name()
    basis = "the plan at start, recorded 1 September"
    chart.show_data(ChartData(FIRST, expected=plan, baseline=plan, basis=basis, segments=segments))
    assert chart.title(chart.panel("scope")) == f"Scope change — versus {basis}"
    keys = [label for label, _ in chart.legend(chart.panel("scope"))]
    assert keys[:2] == ["Plan then", "Plan now"]  # the heading holds the only name
    chart.show_data(ChartData(FIRST, expected=plan, as_of="Review 2 (20 September)"))
    assert chart.title(chart.panel("status")) == "Progress — as of Review 2 (20 September)"
    chart.show_page(VOLUME_PAGE)
    assert chart.title(chart.panel("volume")) == "Scope volume — as of Review 2 (20 September)"
    chart.deleteLater()


def test_a_milestone_name_with_no_room_beside_it_is_dropped_not_squeezed(app):
    """Two long names a day apart cannot both be printed: the second comes back empty,
    and its mark is drawn all the same."""
    close = (date(2026, 9, 20), date(2026, 9, 21))
    plan = ((FIRST, 0.0), (close[0], 0.5), (close[1], 0.75), (LAST, 1.0))
    crowded = (
        Segment("m1", "a milestone with a long name", VIOLET, now=(FIRST, close[0])),
        Segment("m2", "another long milestone name", TEAL, now=(close[0], close[1])),
    )
    chart = _chart(ChartData(FIRST, expected=plan, segments=crowded), width=700)
    named = [bool(name) for _s, name, _at in chart.landing_marks(chart.panel("status"))]
    assert named == [True, False]
    apart = (crowded[0], Segment("m2", crowded[1].label, TEAL, now=(close[0], LAST)))
    chart.show_data(ChartData(FIRST, expected=plan, segments=apart))
    assert [bool(name) for _s, name, _at in chart.landing_marks(chart.panel("status"))] == [
        True,
        True,
    ]
    chart.deleteLater()


def test_a_milestone_row_dates_both_its_marks_and_drops_a_line_to_the_axis(app):
    """The axis marks weeks; the shift a row draws is days, so each mark is dated beside
    itself — the landing now on the far side of the pair, the plan then's on its own —
    and a line falls from the landing to the axis so the day can be read off the scale."""
    plan = ((FIRST, 0.0), (LAST, 1.0))
    moved = Segment(
        "m1", "v1", VIOLET, now=(FIRST, date(2026, 9, 18)), then=(FIRST, date(2026, 9, 11))
    )
    still = Segment("m2", "v2", TEAL, now=(FIRST, LAST), then=(FIRST, LAST))
    chart = _chart(
        ChartData(FIRST, expected=plan, segments=(moved, still)), width=900, page=SHIFT_PAGE
    )
    shift = chart.panel("shift")
    dates = chart.row_dates(shift)
    assert [text for _s, text, _r in dates] == ["18 Sep", "11 Sep", "1 Oct"]
    # The pair is dated on the outside: the earlier landing to the left of its mark, the
    # later one to the right of its own, so neither sits on the arrow between them.
    _s, _text, then_at = dates[1]
    _s, _text, now_at = dates[0]
    assert then_at.right() < chart._x(date(2026, 9, 11))
    assert now_at.left() > chart._x(date(2026, 9, 18))
    # A row that did not move is dated once, not twice with the same day.
    assert [text for segment, text, _r in dates if segment is still] == ["1 Oct"]
    image = chart.grab().toImage()
    x = round(chart._x(date(2026, 9, 18)))
    below = round(chart._row_y(shift, 0) + ROW_HEIGHT * 0.75)
    assert image.pixelColor(x, below) != image.pixelColor(x - 6, below)
    chart.deleteLater()


def _colours_along_the_line(chart: ProgressChart, kind: str, first: date, last: date) -> set[str]:
    image = chart.grab().toImage()
    panel = chart.panel(kind)
    y = round(chart._y(panel, 0.5))
    x0, x1 = round(chart._x(first)) + 12, round(chart._x(last)) - 12
    return {image.pixelColor(x, y).name() for x in range(x0, x1)}


def test_a_baseline_the_plan_still_agrees_with_shows_as_dashes_on_the_line(app):
    """Unchanged since the basis, the two plans coincide: drawn under the plan in the same
    hue the baseline vanished and the scope plot read as one line. Over it, opaque and
    paler, the dashes alternate with the solid line along its length."""
    plan = ((FIRST, 0.5), (LAST, 0.5))
    chart = _chart(ChartData(FIRST, expected=plan))
    alone = _colours_along_the_line(chart, "scope", FIRST, LAST)
    chart.show_data(ChartData(FIRST, expected=plan, baseline=plan, basis="the plan at start"))
    together = _colours_along_the_line(chart, "scope", FIRST, LAST)
    assert len(alone) == 1
    assert len(together) >= 2
    chart.deleteLater()


def test_a_gap_the_plan_leaves_empty_is_dotted_and_the_gridlines_drop_through(app):
    """Across a span with no work planned the plan line is dotted, and the tooltip says
    so; a date mark is a hairline down every plot."""
    landed, resume = date(2026, 9, 8), date(2026, 9, 15)
    plan = ((FIRST, 0.0), (landed, 0.5), (resume, 0.5), (LAST, 1.0))
    chart = _chart(
        ChartData(FIRST, expected=plan, finish=LAST, idle=((landed, resume),)), width=900
    )
    image = chart.grab().toImage()
    status = chart.panel("status")
    y = round(chart._y(status, 0.5))
    x0, x1 = round(chart._x(landed)) + 12, round(chart._x(resume)) - 12
    assert len({image.pixelColor(x, y).name() for x in range(x0, x1)}) >= 2  # Dots and ground.
    assert "no work planned" in chart.tooltip_at(date(2026, 9, 10))
    assert "no work planned" not in chart.tooltip_at(date(2026, 9, 20))
    (mark, _), *_ = [tick for tick in chart.ticks() if FIRST < tick[0] < landed]
    x = round(chart._x(mark))
    for panel in chart.panels():
        between = round(chart._y(panel, 0.375))  # Between two horizontal gridlines.
        assert image.pixelColor(x, between).name() != image.pixelColor(x + 6, between).name()
    chart.deleteLater()


def test_picking_a_milestone_fades_the_line_outside_its_stretch(app):
    """The plan line runs in each stretch's shade; with one picked, the other stretch's
    part is painted at a fraction of its ink, and the picked one whole."""
    middle = date(2026, 9, 16)
    plan = ((FIRST, 0.5), (LAST, 0.5))
    segments = (
        Segment("m1", "v1", VIOLET, now=(FIRST, date(2026, 9, 15))),
        Segment("m2", "v2", TEAL, now=(middle, LAST)),
    )
    chart = _chart(ChartData(FIRST, expected=plan, segments=segments), width=900)
    status = chart.panel("status")
    y = round(chart._y(status, 0.5))
    first_x = round(chart._x(date(2026, 9, 8)))
    second_x = round(chart._x(date(2026, 9, 24)))
    plain = chart.grab().toImage()
    assert plain.pixelColor(first_x, y).name() == VIOLET.name()
    assert plain.pixelColor(second_x, y).name() == TEAL.name()
    chart.show_data(ChartData(FIRST, expected=plan, segments=segments, emphasis="m2"))
    picked = chart.grab().toImage()
    assert picked.pixelColor(second_x, y).name() == TEAL.name()  # held in full ink
    assert picked.pixelColor(first_x, y).name() != VIOLET.name()  # faded
    chart.deleteLater()


def test_the_words_on_a_milestone_row():
    """A milestone's row says which way its landing went, in working days, against the
    plan on the basis day."""
    today = date(2026, 9, 10)
    basis = "the plan at start"
    later = Segment(
        "m", "v1", TEAL, now=(FIRST, date(2026, 9, 23)), then=(FIRST, date(2026, 9, 18))
    )
    assert segment_words(later, basis, today) == (
        "v1 lands 23 September — 3 working days later than the plan at start said (18 September)"
    )
    earlier = Segment(
        "m", "v1", TEAL, now=(FIRST, date(2026, 9, 17)), then=(FIRST, date(2026, 9, 18))
    )
    assert segment_words(earlier, basis, today).endswith(
        "1 working day earlier than the plan at start said (18 September)"
    )
    same = Segment("m", "v1", TEAL, now=(FIRST, date(2026, 9, 18)), then=(FIRST, date(2026, 9, 18)))
    assert segment_words(same, basis, today) == (
        "v1 lands 18 September — unchanged since the plan at start"
    )
    new = Segment("m", "v1", TEAL, now=(FIRST, date(2026, 9, 18)))
    assert segment_words(new, basis, today) == "v1 lands 18 September — not in the plan at start"
    undated = Segment("m", "v1", TEAL)
    assert segment_words(undated, basis, today) == "v1 — nothing estimated, so no date"
