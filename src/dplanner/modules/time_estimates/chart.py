"""The plan, the change in the plan, and the actual work: three lines on one chart.

The shape a trip planner's energy graph has. The **baseline** — the plan as it stood on
the basis day, the project's start unless the host picked another — is a dashed curve in
the milestone's colour pulled toward the ink; the **plan now** is the colour itself, solid; the
band between them is the **change in the plan** since the basis, washed in the same hue,
so a plan that grew shows as the area it grew by and a landing that moved as the gap
between two marks on the 100 % line. What **actually** landed is a solid line in ink with
a dot at today. The x axis is time from the earlier of the two plans' starts to the later
of their landings; the y axis is the share landed, by steps or by estimated days — the
host's toggle. Three series share the plot, so a legend sits in a band above it, where no
line can cross the words — wrapping onto a second row, and the plot moving down, when
the width is short; the rest is tooltips, the calendar's rule: hovering answers with the
date and all three shares.

**The baseline is painted over the plan, opaque.** A plan that has not changed since the
basis has a baseline that coincides with it, and a translucent dash of the same hue under
a solid line of that hue is invisible — the chart showed one line and the caption said
"unchanged", and a reader believed the other line had failed to draw. Painted last, in
the colour pulled toward the ink and mixed opaque — lighter on a dark theme, darker on a
light one, apart from the solid line on either — the dashes ride on the solid line where
the two agree and read as *two lines in the same place*, which is the fact.

**The axis is marked at calendar boundaries.** A reader places a point by the nearest
mark, so the marks are every day, every Monday or every month's first — the finest unit
whose labels fit the width (:func:`axis_ticks`) — with a hairline up from each and a
hairline every quarter of the share, a grid a whisper of the ink; the first mark of a new
year carries the year. Two labels at the ends of the span were not a scale.

**Milestones stand on the chart, and a gap the plan leaves empty is dotted.** Each
milestone is a hairline in its own shade where the plan now lands it, named at the top
of the plot on whichever side has room — the marks a reader was placing the curve
against in their head. Where a milestone's own start date holds its work back past the
previous landing, the plan line is flat (``progress.expected`` puts a knot where work
resumes) and drawn dotted, pulled toward the surface: no work is planned there, and a
solid slope across the gap would have said the opposite.

Every colour but the milestone's shade comes from the palette at paint time — the axes
and the actual line in ink, gridlines a whisper of it — and the marks keep the chart
grammar the coverage lanes and the calendar keep: 2 px lines, an 8 px end marker with a
2 px surface ring, hairline gridlines. A fixed height and the width it is given: no
height-for-width, so nothing here can loop a scroll area. The gutters are measured from
the font, so "100 %" fits whatever the platform's text size.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise
from math import ceil

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QHelpEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from dplanner.domain.schedule import ABBREVIATION, MONTHS, format_date
from dplanner.modules.time_estimates.view import SECONDARY_ALPHA
from dplanner.theme.cards import over

CHART_HEIGHT = 220
# The plot's insets: the left gutter is the widest percent label and a gap either side,
# the top band holds the legend, the bottom gutter the dates.
LABEL_GAP = 6
LEGEND_BAND_GAP = 8
BOTTOM_GUTTER = 22
RIGHT_INSET = 12
# Air between two tick labels: a unit is offered only when every label has this much.
TICK_LABEL_GAP = 16
# The dataviz mark grammar: 2 px lines, a marker of at least 8 px ringed in the surface.
LINE_WIDTH = 2.0
MARKER = 8.0
RING = 2.0
LANDING_MARK = 6.0
GRID_ALPHA = 28
# The change in the plan: the series hue as a wash between the two curves (the dataviz
# rule for an area — about a tenth).
BAND_ALPHA = 28
# The baseline's shade: the colour pulled this far toward the ink, mixed opaque — enough
# to tell its dashes from the solid line they may ride on, on either theme.
BASELINE_INK_ALPHA = 110
LEGEND_KEY = 18
LEGEND_GAP = 6
LEGEND_SPACING = 14
# One day of air at either end, so a line never sits on the frame.
PAD_DAYS = 1
# The horizontal grid: a hairline every quarter, a label at the ends and the middle.
GRID_SHARES = (0.0, 0.25, 0.5, 0.75, 1.0)
LABELLED_SHARES = (0.0, 0.5, 1.0)
# A milestone's line and its name: the line at this alpha, the name in the full shade.
MARK_LINE_ALPHA = 150
MARK_LABEL_GAP = 4
# A gap the plan leaves empty: the plan's colour pulled this far toward the surface.
IDLE_SURFACE_ALPHA = 120

Point = tuple[date, float]
Tick = tuple[date, str]
Mark = tuple[date, str, QColor]


@dataclass(frozen=True)
class ChartData:
    """What one scope's chart shows: the plan now, the plan on the basis day, and what
    actually landed. ``baseline_day`` names the recorded day the baseline came from."""

    label: str
    color: QColor
    today: date
    expected: tuple[Point, ...] = ()
    actual: tuple[Point, ...] = ()
    baseline: tuple[Point, ...] = ()
    baseline_day: date | None = None
    finish: date | None = None
    baseline_finish: date | None = None
    by_days: bool = False
    # Each milestone's expected landing, its label and its shade.
    marks: tuple[Mark, ...] = ()
    # The spans the plan leaves empty, from a landing to the day work resumes.
    idle: tuple[tuple[date, date], ...] = ()


def _share_at(points: tuple[Point, ...], when: date) -> float | None:
    """The line's value on ``when`` — held flat before the first point and after the last,
    interpolated between corners — or None when there is no line."""
    if not points:
        return None
    if when <= points[0][0]:
        return points[0][1] if when == points[0][0] or len(points) == 1 else None
    for (left, low), (right, high) in pairwise(points):
        if left <= when <= right:
            span = (right - left).days
            share = (when - left).days / span if span else 1.0
            return low + (high - low) * share
    return points[-1][1]


# -- the x axis ----------------------------------------------------------------------------------


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


class ProgressChart(QWidget):
    """The expected-versus-actual plot; the host hands it a :class:`ChartData`."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data: ChartData | None = None
        self._first = date.today()
        self._last = date.today()
        self.setFixedHeight(CHART_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)

    # -- the host's side of the contract -------------------------------------------------------

    def show_data(self, data: ChartData | None) -> None:
        self._data = data
        if data is not None:
            dates = [data.today, *(when for when, _ in data.expected), *(w for w, _ in data.actual)]
            dates += [when for when, _ in data.baseline]
            dates += [when for when in (data.finish, data.baseline_finish) if when is not None]
            self._first = min(dates) - timedelta(days=PAD_DAYS)
            self._last = max(dates) + timedelta(days=PAD_DAYS)
            if self._last <= self._first:
                self._last = self._first + timedelta(days=1)
        self.update()

    # -- what the tests read -------------------------------------------------------------------

    @property
    def span(self) -> tuple[date, date]:
        """The dates the x axis runs between, the padding included."""
        return (self._first, self._last)

    def ticks(self) -> tuple[Tick, ...]:
        """What the x axis marks at this width."""
        metrics = self.fontMetrics()
        widest = metrics.horizontalAdvance("30 Sep '00")
        room = int(self._plot().width() // (widest + TICK_LABEL_GAP))
        return axis_ticks(self._first, self._last, room)

    def tooltip_at(self, when: date) -> str:
        """The date, what the plan promised for it, and what actually stood — the chart's
        only words."""
        data = self._data
        if data is None:
            return ""
        lines = [format_date(when, today=data.today)]
        unit = "of days" if data.by_days else "of steps"
        was = _share_at(data.baseline, when)
        if was is not None and data.baseline_day is not None:
            lines.append(
                f"plan at {format_date(data.baseline_day, today=data.today)}: {was:.0%} {unit}"
            )
        planned = _share_at(data.expected, when)
        if planned is not None:
            lines.append(f"plan now: {planned:.0%} {unit}")
        if any(start < when < end for start, end in data.idle):
            lines.append("no work planned")
        landed = _share_at(data.actual, when)
        if landed is not None and when <= data.today:
            lines.append(f"actual: {landed:.0%} {unit}")
        return "\n".join(lines)

    # -- geometry --------------------------------------------------------------------------------

    def _left_gutter(self) -> float:
        return self.fontMetrics().horizontalAdvance("100%") + 2 * LABEL_GAP

    def _legend_entries(self) -> list[tuple[str, str]]:
        """The legend's labels and what each keys — baseline, plan, actual, idle."""
        data = self._data
        if data is None:
            return []
        entries: list[tuple[str, str]] = []
        if data.baseline and data.baseline_day is not None:
            when = format_date(data.baseline_day, today=data.today)
            entries.append((f"Plan at {when}", "baseline"))
        entries += [("Plan now" if data.baseline else "Plan", "plan"), ("Actual", "actual")]
        if data.idle:
            entries.append(("No work planned", "idle"))
        return entries

    def _legend_rows(self) -> list[list[tuple[str, str]]]:
        """The entries wrapped into rows the width holds — one, usually."""
        metrics = self.fontMetrics()
        room = self.width() - self._left_gutter() - RIGHT_INSET
        rows: list[list[tuple[str, str]]] = [[]]
        used = 0.0
        for label, kind in self._legend_entries():
            width = LEGEND_KEY + LEGEND_GAP + metrics.horizontalAdvance(label) + LEGEND_SPACING
            if rows[-1] and used + width > room:
                rows.append([])
                used = 0.0
            rows[-1].append((label, kind))
            used += width
        return rows

    def _top_inset(self) -> float:
        return len(self._legend_rows()) * self.fontMetrics().height() + LEGEND_BAND_GAP

    def _plot(self) -> QRectF:
        left, top = self._left_gutter(), self._top_inset()
        return QRectF(
            left,
            top,
            max(1.0, self.width() - left - RIGHT_INSET),
            max(1.0, self.height() - top - BOTTOM_GUTTER),
        )

    def _x(self, when: date) -> float:
        plot = self._plot()
        total = (self._last - self._first).days or 1
        return plot.left() + plot.width() * (when - self._first).days / total

    def _y(self, share: float) -> float:
        plot = self._plot()
        return plot.bottom() - plot.height() * min(max(share, 0.0), 1.0)

    def _date_at(self, x: float) -> date:
        plot = self._plot()
        share = (x - plot.left()) / plot.width() if plot.width() else 0.0
        days = round((self._last - self._first).days * min(max(share, 0.0), 1.0))
        return self._first + timedelta(days=days)

    # -- painting --------------------------------------------------------------------------------

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        data = self._data
        if data is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ink = self.palette().text().color()
        surface = self.palette().window().color()
        secondary = QColor(ink)
        secondary.setAlpha(SECONDARY_ALPHA)
        grid = QColor(ink)
        grid.setAlpha(GRID_ALPHA)
        plot = self._plot()
        self._draw_grid(painter, plot, data, grid, secondary)

        # Today: a hairline the reader can place everything against.
        if self._first <= data.today <= self._last:
            painter.setPen(QPen(secondary, 1.0))
            x = self._x(data.today)
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))

        self._draw_marks(painter, plot, data)

        # The change in the plan: the wash between the baseline and the plan now.
        if len(data.baseline) >= 2 and len(data.expected) >= 2:
            band = QPainterPath(self._point(data.expected[0]))
            for point in data.expected[1:]:
                band.lineTo(self._point(point))
            for point in reversed(data.baseline):
                band.lineTo(self._point(point))
            band.closeSubpath()
            wash = QColor(data.color)
            wash.setAlpha(BAND_ALPHA)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(wash)
            painter.drawPath(band)

        # The plan now, in the milestone's colour — dotted across a gap it leaves empty —
        # and its landing as a filled mark.
        idle_shade = self._idle_shade(data.color, surface)
        self._draw_plan(painter, data, idle_shade)
        if data.finish is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(data.color)
            painter.drawEllipse(
                QPointF(self._x(data.finish), self._y(1.0)), LANDING_MARK / 2, LANDING_MARK / 2
            )

        # The baseline over it, dashed in the paler shade, its landing hollow. Over, and
        # opaque, so a baseline the plan still agrees with shows as dashes on the line.
        faded = self._baseline_shade(data.color, ink)
        self._draw_line(painter, data.baseline, faded, Qt.PenStyle.DashLine)
        if data.baseline_finish is not None:
            painter.setPen(QPen(faded, LINE_WIDTH))
            painter.setBrush(surface)
            painter.drawEllipse(
                QPointF(self._x(data.baseline_finish), self._y(1.0)),
                LANDING_MARK / 2,
                LANDING_MARK / 2,
            )

        # What actually landed, in ink, with today's reading marked and ringed.
        self._draw_line(painter, data.actual, ink)
        if data.actual:
            when, share = data.actual[-1]
            centre = QPointF(self._x(when), self._y(share))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(surface)
            painter.drawEllipse(centre, MARKER / 2 + RING, MARKER / 2 + RING)
            painter.setBrush(ink)
            painter.drawEllipse(centre, MARKER / 2, MARKER / 2)

        self._draw_legend(painter, plot, data, ink, faded, idle_shade, secondary)
        painter.end()

    @staticmethod
    def _idle_shade(color: QColor, surface: QColor) -> QColor:
        pull = QColor(surface)
        pull.setAlpha(IDLE_SURFACE_ALPHA)
        return over(color, pull)

    @staticmethod
    def _baseline_shade(color: QColor, ink: QColor) -> QColor:
        pull = QColor(ink)
        pull.setAlpha(BASELINE_INK_ALPHA)
        return over(color, pull)

    def _draw_grid(
        self, painter: QPainter, plot: QRectF, data: ChartData, grid: QColor, secondary: QColor
    ) -> None:
        """Hairlines every quarter and at every date mark; the percent labels at the
        ends and the middle, right-aligned to the plot like every header; the dates
        centred under their marks, kept inside the widget at either end."""
        metrics = painter.fontMetrics()
        ticks = self.ticks()
        painter.setPen(QPen(grid, 1.0))
        for share in GRID_SHARES:
            y = self._y(share)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        for when, _ in ticks:
            x = self._x(when)
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
        painter.setPen(secondary)
        for share in LABELLED_SHARES:
            painter.drawText(
                QRectF(
                    0.0,
                    self._y(share) - metrics.height() / 2,
                    plot.left() - LABEL_GAP,
                    metrics.height(),
                ),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{share:.0%}",
            )
        for when, label in ticks:
            width = metrics.horizontalAdvance(label) + 2
            x = min(max(self._x(when) - width / 2, 0.0), self.width() - width)
            painter.drawText(
                QRectF(x, plot.bottom() + 4, width, metrics.height()),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                label,
            )

    def _point(self, point: Point) -> QPointF:
        return QPointF(self._x(point[0]), self._y(point[1]))

    def _draw_marks(self, painter: QPainter, plot: QRectF, data: ChartData) -> None:
        """Each milestone: a hairline in its shade where the plan lands it, named at the
        top of the plot — to the right of the line, or to the left when the right has
        no room."""
        metrics = painter.fontMetrics()
        placed: list[QRectF] = []
        for when, label, color in data.marks:
            line = QColor(color)
            line.setAlpha(MARK_LINE_ALPHA)
            painter.setPen(QPen(line, 1.0))
            x = self._x(when)
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            width = metrics.horizontalAdvance(label) + 2
            left = x + MARK_LABEL_GAP
            if left + width > plot.right():
                left = x - MARK_LABEL_GAP - width
            box = QRectF(left, plot.top() + MARK_LABEL_GAP, width, metrics.height())
            # Two milestones a few days apart: the second name steps down a line.
            while any(box.intersects(other) for other in placed):
                box.translate(0.0, metrics.height())
            placed.append(box)
            painter.setPen(color)
            painter.drawText(box, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)

    def _draw_plan(self, painter: QPainter, data: ChartData, idle_shade: QColor) -> None:
        """The plan now as two paths: solid where work is planned, dotted in the paler
        shade across a span the plan leaves empty."""
        work, gap = QPainterPath(), QPainterPath()
        current: QPainterPath | None = None
        for start, end in pairwise(data.expected):
            empty = any(since <= start[0] and end[0] <= until for since, until in data.idle)
            path = gap if empty else work
            if path is not current:
                path.moveTo(self._point(start))
                current = path
            path.lineTo(self._point(end))
        self._draw_path(painter, work, data.color)
        self._draw_path(painter, gap, idle_shade, Qt.PenStyle.DotLine)

    def _draw_line(
        self,
        painter: QPainter,
        points: tuple[Point, ...],
        color: QColor,
        style: Qt.PenStyle = Qt.PenStyle.SolidLine,
    ) -> None:
        if len(points) < 2:
            return
        path = QPainterPath(self._point(points[0]))
        for point in points[1:]:
            path.lineTo(self._point(point))
        self._draw_path(painter, path, color, style)

    @staticmethod
    def _draw_path(
        painter: QPainter,
        path: QPainterPath,
        color: QColor,
        style: Qt.PenStyle = Qt.PenStyle.SolidLine,
    ) -> None:
        if path.isEmpty():
            return
        pen = QPen(color, LINE_WIDTH)
        pen.setStyle(style)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def _draw_legend(
        self,
        painter: QPainter,
        plot: QRectF,
        data: ChartData,
        ink: QColor,
        faded: QColor,
        idle_shade: QColor,
        secondary: QColor,
    ) -> None:
        """Three series, so a legend: short line keys and the words, in the band above
        the plot, where no line can cross them — and the dotted key, when the plan
        leaves a span empty. Wrapped into rows when the width is short."""
        metrics = painter.fontMetrics()
        keys: dict[str, tuple[QColor, Qt.PenStyle]] = {
            "baseline": (faded, Qt.PenStyle.DashLine),
            "plan": (data.color, Qt.PenStyle.SolidLine),
            "actual": (ink, Qt.PenStyle.SolidLine),
            "idle": (idle_shade, Qt.PenStyle.DotLine),
        }
        for row, entries in enumerate(self._legend_rows()):
            x = plot.left()
            y = row * metrics.height() + metrics.height() / 2
            for label, kind in entries:
                color, style = keys[kind]
                pen = QPen(color, LINE_WIDTH)
                pen.setStyle(style)
                painter.setPen(pen)
                painter.drawLine(QPointF(x, y), QPointF(x + LEGEND_KEY, y))
                x += LEGEND_KEY + LEGEND_GAP
                painter.setPen(secondary)
                painter.drawText(
                    QRectF(
                        x,
                        row * metrics.height(),
                        metrics.horizontalAdvance(label) + 2,
                        metrics.height(),
                    ),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    label,
                )
                x += metrics.horizontalAdvance(label) + LEGEND_SPACING

    # -- input -----------------------------------------------------------------------------------

    def event(self, found: QEvent) -> bool:
        if found.type() == QEvent.Type.ToolTip and self._data is not None:
            assert isinstance(found, QHelpEvent)
            if self._plot().contains(QPointF(found.pos())):
                QToolTip.showText(
                    found.globalPos(), self.tooltip_at(self._date_at(found.pos().x())), self
                )
            else:
                QToolTip.hideText()
            return True
        return super().event(found)
