"""Expected against actual: where the plan said it would be, where it is, and where it
said so before.

One line chart, the shape a trip planner's energy graph has — the plan's promise as a
curve in the milestone's colour, what actually landed as a solid line in ink with a dot
at today, and, faintly behind them, every earlier promise the history recorded, each a
dashed line from the day it was made to the landing it named. The x axis is time from
the plan's start to the latest landing anyone promised; the y axis is the share landed,
by steps or by estimated days — the host's toggle. Two series share the plot, so a
legend sits in its corner; the rest is tooltips, the calendar's rule: hovering answers
with the date, the plan's share and the actual one.

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
from dplanner.modules.time_estimates.progress import EarlierPlan
from dplanner.modules.time_estimates.view import SECONDARY_ALPHA

CHART_HEIGHT = 200
# The plot's insets: room for the percent labels on the left, the dates under it.
LEFT_GUTTER = 40
BOTTOM_GUTTER = 22
TOP_INSET = 12
RIGHT_INSET = 12
# The dataviz mark grammar: 2 px lines, a marker of at least 8 px ringed in the surface.
LINE_WIDTH = 2.0
EARLIER_WIDTH = 1.5
MARKER = 8.0
RING = 2.0
LANDING_MARK = 6.0
GRID_ALPHA = 28
EARLIER_ALPHA = 90
LEGEND_KEY = 18
LEGEND_GAP = 6
LEGEND_SPACING = 14
# One day of air at either end, so a line never sits on the frame.
PAD_DAYS = 1

Point = tuple[date, float]


@dataclass(frozen=True)
class ChartData:
    """What one scope's chart shows: the promise, the record, and the earlier promises."""

    label: str
    color: QColor
    today: date
    expected: tuple[Point, ...] = ()
    actual: tuple[Point, ...] = ()
    earlier: tuple[EarlierPlan, ...] = ()
    finish: date | None = None
    by_days: bool = False
    show_earlier: bool = True


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
            if data.finish is not None:
                dates.append(data.finish)
            if data.show_earlier:
                dates += [plan.day for plan in data.earlier]
                dates += [plan.finish for plan in data.earlier]
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
        planned = _share_at(data.expected, when)
        if planned is not None:
            lines.append(f"plan {planned:.0%} {unit}")
        landed = _share_at(data.actual, when)
        if landed is not None and when <= data.today:
            lines.append(f"actual {landed:.0%} {unit}")
        if data.show_earlier:
            for plan in data.earlier:
                if plan.day <= when <= plan.finish:
                    lines.append(
                        f"on {format_date(plan.day, today=data.today)} the plan said "
                        f"{format_date(plan.finish, today=data.today)}"
                    )
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

        # Earlier promises: faint dashed lines to the landings they named.
        if data.show_earlier:
            faint = QColor(data.color)
            faint.setAlpha(EARLIER_ALPHA)
            pen = QPen(faint, EARLIER_WIDTH)
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            for plan in data.earlier:
                painter.drawLine(
                    QPointF(self._x(plan.day), self._y(plan.share)),
                    QPointF(self._x(plan.finish), self._y(1.0)),
                )

        # The plan's promise, in the milestone's colour; its landing as a filled mark.
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

    def _draw_line(self, painter: QPainter, points: tuple[Point, ...], color: QColor) -> None:
        if len(points) < 2:
            return
        path = QPainterPath(QPointF(self._x(points[0][0]), self._y(points[0][1])))
        for when, share in points[1:]:
            path.lineTo(QPointF(self._x(when), self._y(share)))
        pen = QPen(color, LINE_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def _draw_legend(
        self, painter: QPainter, plot: QRectF, data: ChartData, ink: QColor, secondary: QColor
    ) -> None:
        """Two series, so a legend: short line keys and the words, in the top-left corner
        — the one the lines leave empty, since both climb from the bottom-left."""
        metrics = painter.fontMetrics()
        entries: list[tuple[str, QColor, Qt.PenStyle]] = [
            ("Plan", data.color, Qt.PenStyle.SolidLine),
            ("Actual", ink, Qt.PenStyle.SolidLine),
        ]
        if data.show_earlier and data.earlier:
            faint = QColor(data.color)
            faint.setAlpha(EARLIER_ALPHA)
            entries.append(("Earlier plans", faint, Qt.PenStyle.DashLine))
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
