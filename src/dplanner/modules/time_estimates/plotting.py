"""What the Time tab's plots share: one date axis, today, the saved snapshots and the ✓.

**A day's point on the axis is its end**, so the day itself runs from the point before to its
own: a weekend is the band between the two, and so is a quiet day on the done line. Every
plot on a page is drawn against the same :class:`Axis`, which is what lets the eye run down
from a milestone's mark to the date under it.

Every colour but a milestone's shade comes from the palette at paint time, the way the
calendar's painter takes it (``months.py``): ink, a secondary tone of it, and a whisper of it
for the grid.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QPolygonF

from dplanner.domain.schedule import Tick, axis_ticks
from dplanner.theme.tokens import SECONDARY_ALPHA

# How far apart the date labels under an axis sit at the least.
TICK_ROOM = 70
# The least air between a label under the axis and the day shown's own word, which it
# gives way to — "today", or a date while History looks back.
TODAY_GAP = 8
GRID_ALPHA = 20
SAVED_ALPHA = 100
TODAY_ALPHA = 140
CHECK_RADIUS = 8.0
# The plan's own blue: the scope line and the schedule — the report's plan colour.
PLAN = QColor("#5f87d7")
# The scope grew (amber) or shrank (teal): the area between the lines, and the ▲ or ▼.
WARM = QColor(232, 150, 70)
COOL = QColor(47, 160, 170)
FILL_ALPHA = 48
WEEKEND_ALPHA = 12


@dataclass(frozen=True)
class Axis:
    """The dates from ``first`` to ``last`` laid from ``left`` to ``right``."""

    first: date
    last: date
    left: float
    right: float

    def x(self, day: date) -> float:
        span = max(1, (self.last - self.first).days)
        return self.left + (day - self.first).days / span * (self.right - self.left)

    def day_at(self, x: float) -> date:
        span = max(1, (self.last - self.first).days)
        share = (x - self.left) / max(1.0, self.right - self.left)
        return self.first + timedelta(days=round(share * span))

    def ticks(self) -> tuple[Tick, ...]:
        return axis_ticks(self.first, self.last, max(1, int((self.right - self.left) // TICK_ROOM)))

    def holds(self, day: date) -> bool:
        return self.first <= day <= self.last


@dataclass(frozen=True)
class Inks:
    """The palette's colours a plot paints with, read at paint time."""

    ink: QColor
    secondary: QColor
    grid: QColor
    surface: QColor

    @staticmethod
    def of(ink: QColor, surface: QColor) -> "Inks":
        secondary = QColor(ink)
        secondary.setAlpha(SECONDARY_ALPHA)
        grid = QColor(ink)
        grid.setAlpha(GRID_ALPHA)
        return Inks(QColor(ink), secondary, grid, QColor(surface))


def faded(color: QColor, alpha: int) -> QColor:
    found = QColor(color)
    found.setAlpha(alpha)
    return found


def paint_check(painter: QPainter, centre: QPointF, color: QColor) -> None:
    """A circle with a check, in the milestone's colour: this milestone is done."""
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(centre, CHECK_RADIUS, CHECK_RADIUS)
    tick = QPainterPath(QPointF(centre.x() - 3.8, centre.y() + 0.2))
    tick.lineTo(centre.x() - 1.0, centre.y() + 3.0)
    tick.lineTo(centre.x() + 4.0, centre.y() - 3.0)
    pen = QPen(QColor("#ffffff"), 2.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(tick)


def paint_triangle(
    painter: QPainter, centre: QPointF, size: float, up: bool, color: QColor
) -> None:
    """A ▲ or ▼ ``size`` across, filled."""
    half = size / 2
    tip = -half if up else half
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(centre.x(), centre.y() + tip),
                QPointF(centre.x() - half, centre.y() - tip),
                QPointF(centre.x() + half, centre.y() - tip),
            ]
        )
    )


def paint_verticals(
    painter: QPainter,
    axis: Axis,
    top: float,
    bottom: float,
    inks: Inks,
    *,
    day: date,
    saved: tuple[tuple[date, str], ...],
) -> None:
    """Through every plot on the page: each saved snapshot's day dashed, the day shown
    dotted."""
    for when, _title in saved:
        if axis.holds(when):
            pen = QPen(faded(inks.ink, SAVED_ALPHA), 1.0, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(axis.x(when), top), QPointF(axis.x(when), bottom))
    if axis.holds(day):
        pen = QPen(faded(inks.ink, TODAY_ALPHA), 1.0, Qt.PenStyle.DotLine)
        painter.setPen(pen)
        painter.drawLine(QPointF(axis.x(day), top), QPointF(axis.x(day), bottom))


def paint_dates(
    painter: QPainter, axis: Axis, baseline: float, inks: Inks, *, day: date, day_word: str
) -> None:
    """The dates under the axis, and the day shown's own word under its line — a date that
    would touch the word gives way to it."""
    bold = QFont(painter.font())
    bold.setBold(True)
    plain = QFontMetricsF(painter.font())
    half_word = QFontMetricsF(bold).horizontalAdvance(day_word) / 2
    painter.setPen(inks.secondary)
    for when, label in axis.ticks():
        at = axis.x(when)
        reach = half_word + plain.horizontalAdvance(label) / 2 + TODAY_GAP
        if axis.holds(day) and abs(at - axis.x(day)) < reach:
            continue
        painter.drawText(QRectF(at - 40, baseline, 80, 16), Qt.AlignmentFlag.AlignHCenter, label)
    if axis.holds(day):
        painter.save()
        painter.setFont(bold)
        painter.setPen(inks.ink)
        at = axis.x(day)
        painter.drawText(
            QRectF(at - 50, baseline, 100, 16), Qt.AlignmentFlag.AlignHCenter, day_word
        )
        painter.restore()


def paint_grid_dates(painter: QPainter, axis: Axis, top: float, bottom: float, inks: Inks) -> None:
    """A hairline up from each date mark."""
    painter.setPen(QPen(inks.grid, 1.0))
    for when, _label in axis.ticks():
        painter.drawLine(QPointF(axis.x(when), top), QPointF(axis.x(when), bottom))
