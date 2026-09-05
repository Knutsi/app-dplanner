"""The plan, the change in the plan, and the actual work: three lines on one chart.

The shape a trip planner's energy graph has. The **baseline** — the plan as it stood on
the basis day, the project's start unless the host picked another — is a dashed curve in
the milestone's colour; the **plan now** is the same colour, solid; the band between them
is the **change in the plan** since the basis, washed in the same hue, so a plan that
grew shows as the area it grew by and a landing that moved as the gap between two marks
on the 100 % line. What **actually** landed is a solid line in ink with a dot at today.
The x axis is time from the earlier of the two plans' starts to the later of their
landings; the y axis is the share landed, by steps or by estimated days — the host's
toggle. Three series share the plot, so a legend sits in its corner; the rest is
tooltips, the calendar's rule: hovering answers with the date and all three shares.

Every colour but the milestone's shade comes from the palette at paint time — the axes
and the actual line in ink, gridlines a whisper of it — and the marks keep the chart
grammar the coverage lanes and the calendar keep: 2 px lines, an 8 px end marker with a
2 px surface ring, hairline gridlines. A fixed height and the width it is given: no
height-for-width, so nothing here can loop a scroll area.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise

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

from dplanner.domain.schedule import format_date
from dplanner.modules.time_estimates.view import SECONDARY_ALPHA

CHART_HEIGHT = 200
# The plot's insets: room for the percent labels on the left, the dates under it.
LEFT_GUTTER = 40
BOTTOM_GUTTER = 22
TOP_INSET = 12
RIGHT_INSET = 12
# The dataviz mark grammar: 2 px lines, a marker of at least 8 px ringed in the surface.
LINE_WIDTH = 2.0
MARKER = 8.0
RING = 2.0
LANDING_MARK = 6.0
GRID_ALPHA = 28
# The change in the plan: the series hue as a wash between the two curves (the dataviz
# rule for an area — about a tenth).
BAND_ALPHA = 28
BASELINE_ALPHA = 170
LEGEND_KEY = 18
LEGEND_GAP = 6
LEGEND_SPACING = 14
# One day of air at either end, so a line never sits on the frame.
PAD_DAYS = 1

Point = tuple[date, float]


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
        landed = _share_at(data.actual, when)
        if landed is not None and when <= data.today:
            lines.append(f"actual: {landed:.0%} {unit}")
        return "\n".join(lines)

    # -- geometry --------------------------------------------------------------------------------

    def _plot(self) -> QRectF:
        return QRectF(
            LEFT_GUTTER,
            TOP_INSET,
            max(1.0, self.width() - LEFT_GUTTER - RIGHT_INSET),
            max(1.0, self.height() - TOP_INSET - BOTTOM_GUTTER),
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

        # Gridlines and the percent labels: recessive, from the left like every header.
        painter.setPen(QPen(grid, 1.0))
        for share in (0.0, 0.5, 1.0):
            y = self._y(share)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        painter.setPen(secondary)
        metrics = painter.fontMetrics()
        for share in (0.0, 0.5, 1.0):
            label = f"{share:.0%}"
            painter.drawText(
                QRectF(
                    0.0, self._y(share) - metrics.height() / 2, LEFT_GUTTER - 6, metrics.height()
                ),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
        for when, align in (
            (self._first, Qt.AlignmentFlag.AlignLeft),
            (self._last, Qt.AlignmentFlag.AlignRight),
        ):
            painter.drawText(
                QRectF(plot.left(), plot.bottom() + 4, plot.width(), metrics.height()),
                align | Qt.AlignmentFlag.AlignVCenter,
                format_date(when, today=data.today),
            )

        # Today: a hairline the reader can place everything against.
        if self._first <= data.today <= self._last:
            painter.setPen(QPen(secondary, 1.0))
            x = self._x(data.today)
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))

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

        # The baseline: the plan as it stood on the basis day, dashed, its landing hollow.
        faded = QColor(data.color)
        faded.setAlpha(BASELINE_ALPHA)
        self._draw_line(painter, data.baseline, faded, Qt.PenStyle.DashLine)
        if data.baseline_finish is not None:
            painter.setPen(QPen(faded, LINE_WIDTH))
            painter.setBrush(surface)
            painter.drawEllipse(
                QPointF(self._x(data.baseline_finish), self._y(1.0)),
                LANDING_MARK / 2,
                LANDING_MARK / 2,
            )

        # The plan now, in the milestone's colour; its landing as a filled mark.
        self._draw_line(painter, data.expected, data.color)
        if data.finish is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(data.color)
            painter.drawEllipse(
                QPointF(self._x(data.finish), self._y(1.0)), LANDING_MARK / 2, LANDING_MARK / 2
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

        self._draw_legend(painter, plot, data, ink, secondary)
        painter.end()

    def _point(self, point: Point) -> QPointF:
        return QPointF(self._x(point[0]), self._y(point[1]))

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
        pen = QPen(color, LINE_WIDTH)
        pen.setStyle(style)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def _draw_legend(
        self, painter: QPainter, plot: QRectF, data: ChartData, ink: QColor, secondary: QColor
    ) -> None:
        """Three series, so a legend: short line keys and the words, in the top-left corner
        — the one the lines leave empty, since all of them climb from the bottom-left."""
        metrics = painter.fontMetrics()
        entries: list[tuple[str, QColor, Qt.PenStyle]] = []
        if data.baseline and data.baseline_day is not None:
            faded = QColor(data.color)
            faded.setAlpha(BASELINE_ALPHA)
            when = format_date(data.baseline_day, today=data.today)
            entries.append((f"Plan at {when}", faded, Qt.PenStyle.DashLine))
        entries += [
            ("Plan now" if data.baseline else "Plan", data.color, Qt.PenStyle.SolidLine),
            ("Actual", ink, Qt.PenStyle.SolidLine),
        ]
        x = plot.left() + LEGEND_SPACING
        y = plot.top() + metrics.height() / 2
        for label, color, style in entries:
            pen = QPen(color, LINE_WIDTH)
            pen.setStyle(style)
            painter.setPen(pen)
            painter.drawLine(QPointF(x, y), QPointF(x + LEGEND_KEY, y))
            x += LEGEND_KEY + LEGEND_GAP
            painter.setPen(secondary)
            painter.drawText(
                QRectF(x, plot.top(), metrics.horizontalAdvance(label) + 2, metrics.height()),
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
