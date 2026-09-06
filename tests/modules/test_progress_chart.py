"""The progress chart: its axis, its gutters, and a baseline that coincides with the plan."""

from datetime import date

from PySide6.QtGui import QColor

from dplanner.domain.schedule import axis_ticks
from dplanner.modules.time_estimates.chart import CHART_HEIGHT, LABEL_GAP, ChartData, ProgressChart


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


def test_the_gutters_fit_the_labels_and_the_legend_sits_above_the_plot(app):
    """ "100%" was cut to "00%" by a gutter of fixed pixels; the legend sat inside the
    plot, where today's line crossed its words."""
    chart = ProgressChart()
    chart.resize(700, CHART_HEIGHT)
    metrics = chart.fontMetrics()
    plot = chart._plot()
    assert plot.left() >= metrics.horizontalAdvance("100%") + LABEL_GAP
    assert plot.top() >= metrics.height()
    assert len(chart.ticks()) >= 1
    chart.deleteLater()


def _colours_along_the_line(chart: ProgressChart, first: date, last: date) -> set[str]:
    image = chart.grab().toImage()
    y = round(chart._y(0.5))
    x0, x1 = round(chart._x(first)) + 12, round(chart._x(last)) - 12
    return {image.pixelColor(x, y).name() for x in range(x0, x1)}


def test_a_baseline_the_plan_still_agrees_with_shows_as_dashes_on_the_line(app):
    """Unchanged since the basis, the two plans coincide: drawn under the plan in the same
    hue the baseline vanished and the chart read as one line. Over it, opaque and paler,
    the dashes alternate with the solid line along its length."""
    first, last = date(2026, 9, 1), date(2026, 10, 1)
    plan = ((first, 0.5), (last, 0.5))
    chart = ProgressChart()
    chart.resize(700, CHART_HEIGHT)
    chart.show_data(ChartData("All work", QColor("#4a7fd6"), first, expected=plan))
    alone = _colours_along_the_line(chart, first, last)
    chart.show_data(
        ChartData(
            "All work", QColor("#4a7fd6"), first, expected=plan, baseline=plan, baseline_day=first
        )
    )
    together = _colours_along_the_line(chart, first, last)
    assert len(alone) == 1
    assert len(together) >= 2
    chart.deleteLater()


def test_milestones_are_marked_and_a_gap_the_plan_leaves_empty_is_dotted(app):
    """A hairline in the milestone's shade where the plan lands it; across a span with no
    work planned the plan line is dotted, and the tooltip says so."""
    first, landed, resume, last = (
        date(2026, 9, 1),
        date(2026, 9, 8),
        date(2026, 9, 15),
        date(2026, 10, 1),
    )
    plan = ((first, 0.0), (landed, 0.5), (resume, 0.5), (last, 1.0))
    blue, violet = QColor("#4a7fd6"), QColor("#8e6fd8")
    chart = ProgressChart()
    chart.resize(900, CHART_HEIGHT)
    chart.show_data(
        ChartData(
            "All work",
            blue,
            first,
            expected=plan,
            finish=last,
            marks=((landed, "v1", violet), (last, "v2", blue)),
            idle=((landed, resume),),
        )
    )
    image = chart.grab().toImage()
    y = round(chart._y(0.5))
    x0, x1 = round(chart._x(landed)) + 12, round(chart._x(resume)) - 12
    assert len({image.pixelColor(x, y).name() for x in range(x0, x1)}) >= 2  # Dots and ground.
    assert "no work planned" in chart.tooltip_at(date(2026, 9, 10))
    assert "no work planned" not in chart.tooltip_at(date(2026, 9, 20))
    x, between = round(chart._x(landed)), round(chart._y(0.375))  # Between two gridlines.
    assert image.pixelColor(x, between).name() != image.pixelColor(x + 6, between).name()
    chart.deleteLater()


def test_a_short_width_wraps_the_legend_and_moves_the_plot_down(app):
    """Four keys do not fit a narrow chart on one row: the legend wraps, and the plot
    starts below both rows rather than under the second."""
    first, last = date(2026, 9, 1), date(2026, 10, 1)
    plan = ((first, 0.0), (last, 1.0))
    chart = ProgressChart()
    chart.resize(900, CHART_HEIGHT)
    chart.show_data(
        ChartData(
            "All work",
            QColor("#4a7fd6"),
            first,
            expected=plan,
            baseline=plan,
            baseline_day=first,
            idle=((date(2026, 9, 10), date(2026, 9, 14)),),
        )
    )
    assert len(chart._legend_rows()) == 1
    wide = chart._plot().top()
    chart.resize(420, CHART_HEIGHT)
    assert len(chart._legend_rows()) == 2
    assert chart._plot().top() >= wide + chart.fontMetrics().height()
    chart.deleteLater()
