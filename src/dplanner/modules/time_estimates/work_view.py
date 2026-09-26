"""The Work page: two plots on one date axis and **one scale in days**, so a height in one
is the same amount of work as the same height in the other.

- **Scope** — how much work the plan held on each recorded day, against what the plan
  compared with held, the area between them warm where it holds more and cool where it
  holds less. Each day the scope changed carries one ▲ or ▼ under the line, by the day's sum.
- **Work done** — what is done, dotted across a day on which no step changed status; the
  plan's own schedule from the day shown on, dashed; and each milestone where it sits: a
  check on the done line the day it was done, or a dot on the schedule the day the plan
  lands it.

Weekends are pale bands through both plots, and each wait a hatched band, named. Hovering
reads the day under the pointer — the scope, what was done and what the schedule promised by
then — and a mark's own words where the pointer is on one. The axes hold the reach the page
was handed, so moving between days moves only the lines.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from dplanner.domain.schedule import SATURDAY, format_date, format_days
from dplanner.modules.time_estimates.plotting import (
    CHECK_RADIUS,
    COOL,
    FILL_ALPHA,
    PLAN,
    WARM,
    WEEKEND_ALPHA,
    Axis,
    Inks,
    faded,
    paint_check,
    paint_dates,
    paint_grid_dates,
    paint_triangle,
    paint_verticals,
)
from dplanner.modules.time_estimates.present import (
    Presented,
    change_words,
    milestone_words,
    step_at,
)

LEFT = 52
RIGHT = 90
TOP = 30
PLOT_HEIGHT = 150
GAP = 46
BOTTOM = 26
MARK = 8.0
MILESTONE_DOT = 5.0
DONE_ALPHA = 26
WAIT_ALPHA = 70  # A wait's hatching: seen through, over the weekend bands.
SCOPE_WIDTH = 2.5
HIT = 8.0  # How near a mark the pointer must be to read the mark's words.
KEY_SAMPLE = 18
KEY_GAP = 12
_ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class _Hit:
    """A mark the pointer can land on, and its words."""

    centre: QPointF
    words: str


class WorkView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._shown: Presented | None = None
        self._day_word = "today"
        self._hover: float | None = None
        self._hits: list[_Hit] = []
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(TOP + 2 * PLOT_HEIGHT + GAP + BOTTOM)

    def show_presented(self, shown: Presented, day_word: str) -> None:
        self._shown, self._day_word = shown, day_word
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(LEFT + RIGHT + 480, self.height())

    # -- the geometry, which the tests read ----------------------------------------------------

    @property
    def scope_top(self) -> float:
        return TOP

    @property
    def work_top(self) -> float:
        return TOP + PLOT_HEIGHT + GAP

    def axis(self) -> Axis:
        shown = self._shown
        assert shown is not None
        data = shown.burnup
        days = [shown.day, shown.reach.first, shown.reach.last]
        days += [day for day, _value in (*data.scope, *shown.schedule)]
        days += [scope.end for scope in shown.marked if scope.end is not None]
        return Axis(
            min(days) - _ONE_DAY,
            max(days) + 2 * _ONE_DAY,
            LEFT,
            max(LEFT + 1, self.width() - RIGHT),
        )

    def _y(self, top: float, value: float) -> float:
        assert self._shown is not None
        return top + (1 - value / self._shown.scale) * PLOT_HEIGHT

    # -- painting ------------------------------------------------------------------------------

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        shown = self._shown
        if shown is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inks = Inks.of(self.palette().text().color(), self.palette().base().color())
        axis = self.axis()
        self._hits = []
        bottom = self.work_top + PLOT_HEIGHT
        for top in (self.scope_top, self.work_top):
            self._paint_scale(painter, axis, inks, top)
        self._paint_weekends(painter, axis, inks)
        self._paint_waits(painter, axis, inks)
        paint_grid_dates(painter, axis, self.scope_top, bottom, inks)
        self._paint_scope(painter, axis, inks)
        self._paint_work(painter, axis, inks)
        paint_verticals(
            painter, axis, self.scope_top, bottom, inks, day=shown.day, saved=shown.saved
        )
        paint_dates(painter, axis, bottom + 6, inks, day=shown.day, day_word=self._day_word)
        if self._hover is not None and axis.left <= self._hover <= axis.right:
            painter.setPen(QPen(faded(inks.ink, 128), 1.0))
            painter.drawLine(QPointF(self._hover, self.scope_top), QPointF(self._hover, bottom))
        painter.end()

    def _paint_scale(self, painter: QPainter, axis: Axis, inks: Inks, top: float) -> None:
        assert self._shown is not None
        scale = self._shown.scale
        for share in (0.0, 0.5, 1.0):
            at = self._y(top, scale * share)
            painter.setPen(QPen(faded(inks.ink, 64 if not share else 26), 1.0))
            painter.drawLine(QPointF(LEFT, at), QPointF(axis.right, at))
            painter.setPen(inks.secondary)
            painter.drawText(
                QRectF(0, at - 8, LEFT - 8, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                format_days(scale * share) or "0d",
            )

    def _paint_weekends(self, painter: QPainter, axis: Axis, inks: Inks) -> None:
        """A pale band over each day off, in both plots: a day runs from the point before
        to its own."""
        band = faded(inks.ink, WEEKEND_ALPHA)
        day = axis.first + _ONE_DAY
        while day <= axis.last:
            if day.weekday() >= SATURDAY:
                left, right = max(LEFT, axis.x(day - _ONE_DAY)), min(axis.right, axis.x(day))
                for top in (self.scope_top, self.work_top):
                    painter.fillRect(QRectF(left, top, right - left, PLOT_HEIGHT), band)
            day += _ONE_DAY

    def _paint_waits(self, painter: QPainter, axis: Axis, inks: Inks) -> None:
        """A hatched band over each wait's days, through both plots, named at the top — the
        plan's waits as it dates them now; a record looked back at has none."""
        assert self._shown is not None
        hatch = QBrush(faded(inks.ink, WAIT_ALPHA), Qt.BrushStyle.BDiagPattern)
        small = QFont(self.font())
        small.setPointSizeF(max(6.0, small.pointSizeF() - 1))
        for wait in self._shown.now.waits:
            left = max(LEFT, axis.x(wait.start - _ONE_DAY))
            right = min(axis.right, axis.x(wait.end))
            if right <= left:
                continue
            for top in (self.scope_top, self.work_top):
                painter.fillRect(QRectF(left, top, right - left, PLOT_HEIGHT), hatch)
            painter.setFont(small)
            painter.setPen(inks.secondary)
            painter.drawText(
                QRectF(left + 2, self.scope_top + 2, max(0.0, right - left - 4), 14),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                QFontMetricsF(small).elidedText(
                    wait.title, Qt.TextElideMode.ElideRight, max(0.0, right - left - 4)
                ),
            )
            painter.setFont(self.font())

    def _title(
        self, painter: QPainter, inks: Inks, top: float, name: str, keys: list[tuple[str, str]]
    ) -> None:
        """A plot's name at the left of the band over it, and a key per thing it draws at
        the right — a small sample, then its words."""
        y = top - 14
        bold = QFont(self.font())
        bold.setBold(True)
        painter.setFont(bold)
        painter.setPen(inks.ink)
        painter.drawText(QRectF(LEFT, y - 8, 200, 16), Qt.AlignmentFlag.AlignVCenter, name)
        painter.setFont(self.font())
        metrics = QFontMetricsF(self.font())
        cursor = float(self.width() - RIGHT)
        for sample, words in reversed(keys):
            width = metrics.horizontalAdvance(words)
            cursor -= width
            painter.setPen(inks.secondary)
            painter.drawText(
                QRectF(cursor, y - 8, width + 2, 16), Qt.AlignmentFlag.AlignVCenter, words
            )
            cursor -= KEY_SAMPLE + 6
            self._paint_sample(painter, inks, sample, QRectF(cursor, y - 6, KEY_SAMPLE, 12))
            cursor -= KEY_GAP

    def _paint_sample(self, painter: QPainter, inks: Inks, sample: str, box: QRectF) -> None:
        middle = box.center().y()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if sample == "scope":
            painter.setPen(QPen(PLAN, SCOPE_WIDTH))
        elif sample == "then":
            painter.setPen(QPen(inks.secondary, 1.0, Qt.PenStyle.DashLine))
        elif sample == "schedule":
            painter.setPen(QPen(inks.secondary, 1.5, Qt.PenStyle.DashLine))
        elif sample == "idle":
            painter.setPen(QPen(inks.ink, 2.0, Qt.PenStyle.DotLine))
        elif sample == "done":
            painter.fillRect(box, faded(inks.ink, DONE_ALPHA))
            painter.setPen(QPen(inks.ink, 2.0))
            painter.drawLine(box.topLeft(), box.topRight())
            return
        else:  # "added" or "removed": the fill, and its ▲ or ▼.
            up = sample == "added"
            painter.fillRect(box, faded(WARM if up else COOL, FILL_ALPHA))
            paint_triangle(painter, box.center(), MARK, up, WARM if up else COOL)
            return
        painter.drawLine(QPointF(box.left(), middle), QPointF(box.right(), middle))

    def _paint_scope(self, painter: QPainter, axis: Axis, inks: Inks) -> None:
        shown = self._shown
        assert shown is not None
        data = shown.burnup
        top = self.scope_top
        compared = shown.compared and data.baseline is not None and shown.then is not None
        keys = [("scope", "scope"), *([("then", "then")] if compared else [])]
        self._title(
            painter, inks, top, "Scope", [*keys, ("added", "added"), ("removed", "removed")]
        )
        now = data.scope[-1][1] if data.scope else 0.0
        if compared and data.baseline is not None and shown.then is not None:
            self._paint_scope_fills(
                painter, axis, data.scope, data.baseline, shown.then.day, shown.day
            )
            at = self._y(top, data.baseline)
            painter.setPen(QPen(inks.secondary, 1.0, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(axis.x(shown.then.day), at), QPointF(axis.right, at))
            clash = abs(at - self._y(top, now)) < 13
            painter.drawText(
                QRectF(axis.right + 6, at - 8 + (7 if clash else 0), RIGHT - 6, 16),
                Qt.AlignmentFlag.AlignVCenter,
                f"{format_days(data.baseline) or '0d'} then",
            )
        if data.scope:
            self._paint_line(
                painter, self._step_path(data.scope, axis, top, shown.day), QPen(PLAN, SCOPE_WIDTH)
            )
            clash = (
                data.baseline is not None
                and compared
                and abs(self._y(top, data.baseline) - self._y(top, now)) < 13
            )
            bold = QFont(self.font())
            bold.setBold(True)
            painter.setFont(bold)
            painter.setPen(PLAN)
            at = self._y(top, now) - (7 if clash else 0)
            painter.drawText(
                QRectF(axis.right + 6, at - 8, RIGHT - 6, 16),
                Qt.AlignmentFlag.AlignVCenter,
                f"{format_days(now) or '0d'} now",
            )
            painter.setFont(self.font())
        for mark in data.marks:
            level = step_at(data.scope, mark.day) or 0.0
            centre = QPointF(axis.x(mark.day) + 6, self._y(top, level) + MARK)
            paint_triangle(painter, centre, MARK, mark.up, WARM if mark.up else COOL)
            self._hits.append(_Hit(centre, change_words(mark, shown.day)))

    def _paint_scope_fills(
        self,
        painter: QPainter,
        axis: Axis,
        points: tuple[tuple[date, float], ...],
        baseline: float,
        since: date,
        until: date,
    ) -> None:
        """The area between the scope and the baseline from the day compared with: warm
        where the plan holds more than it did, cool where less. One band per level."""
        top = self.scope_top
        for index, (day, value) in enumerate(points):
            start = max(day, since)
            end = points[index + 1][0] if index + 1 < len(points) else until
            if end <= start or abs(value - baseline) < 1e-9:
                continue
            upper, lower = self._y(top, max(value, baseline)), self._y(top, min(value, baseline))
            shade = faded(WARM if value > baseline else COOL, FILL_ALPHA)
            painter.fillRect(
                QRectF(axis.x(start), upper, axis.x(end) - axis.x(start), lower - upper), shade
            )

    def _paint_work(self, painter: QPainter, axis: Axis, inks: Inks) -> None:
        shown = self._shown
        assert shown is not None
        data = shown.burnup
        top = self.work_top
        self._title(
            painter,
            inks,
            top,
            "Work done",
            [("done", "done"), ("idle", "no status change"), ("schedule", "the plan's schedule")],
        )
        now = data.scope[-1][1] if data.scope else 0.0
        painter.setPen(QPen(faded(PLAN, 90), 1.0, Qt.PenStyle.DotLine))
        painter.drawLine(QPointF(LEFT, self._y(top, now)), QPointF(axis.right, self._y(top, now)))
        schedule = shown.schedule
        if len(schedule) > 1:
            painter.setPen(QPen(inks.secondary, 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(self._step_path(schedule, axis, top, schedule[-1][0]))
        if data.done:
            area = self._step_path(data.done, axis, top, shown.day)
            area.lineTo(axis.x(shown.day), self._y(top, 0))
            area.lineTo(axis.x(data.done[0][0]), self._y(top, 0))
            area.closeSubpath()
            painter.fillPath(area, faded(inks.ink, DONE_ALPHA))
            if data.done[0][0] >= shown.day:
                self._paint_line(painter, area, QPen(inks.ink, 2.0))
            else:
                self._paint_done_line(painter, axis, inks, data.done, set(data.active), shown.day)
        self._paint_milestone_marks(painter, axis, inks)

    def _paint_done_line(
        self,
        painter: QPainter,
        axis: Axis,
        inks: Inks,
        done: tuple[tuple[date, float], ...],
        active: set[date],
        day_shown: date,
    ) -> None:
        """Solid across a day some step changed status, dotted across one none did."""
        top = self.work_top
        solid, dotted = QPainterPath(), QPainterPath()
        level = done[0][1]
        day = done[0][0] + _ONE_DAY
        while day <= day_shown:
            y = self._y(top, level)
            path = solid if day in active else dotted
            path.moveTo(axis.x(day - _ONE_DAY), y)
            path.lineTo(axis.x(day), y)
            after = step_at(done, day)
            following = level if after is None else after
            if following != level:
                solid.moveTo(axis.x(day), y)
                solid.lineTo(axis.x(day), self._y(top, following))
            level = following
            day += _ONE_DAY
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(inks.ink, 2.0))
        painter.drawPath(solid)
        painter.setPen(QPen(inks.ink, 2.0, Qt.PenStyle.DotLine))
        painter.drawPath(dotted)

    def _paint_milestone_marks(self, painter: QPainter, axis: Axis, inks: Inks) -> None:
        shown = self._shown
        assert shown is not None
        top = self.work_top
        data = shown.burnup
        labelled: list[QPointF] = []
        bold = QFont(self.font())
        bold.setBold(True)
        metrics = QFontMetricsF(bold)
        for scope in shown.marked:
            done = scope.landed_by
            day = scope.end
            if day is None:
                continue
            value = step_at(data.done, day) if done is not None else step_at(data.promised, day)
            centre = QPointF(axis.x(day), self._y(top, value or 0.0))
            color = QColor(scope.named.color)
            if done is not None:
                paint_check(painter, centre, color)
            else:
                painter.setPen(QPen(inks.surface, 1.5))
                painter.setBrush(color)
                painter.drawEllipse(centre, MILESTONE_DOT, MILESTONE_DOT)
            named = scope.named
            self._hits.append(_Hit(centre, milestone_words(scope, shown.day)))
            # A name goes over its mark, or beside it where that would leave the plot for the
            # key above; one that would sit on another's is left to the tooltip.
            radius = CHECK_RADIUS if done is not None else MILESTONE_DOT
            width = metrics.horizontalAdvance(named.label)
            spot = QPointF(centre.x(), centre.y() - radius - 8)
            if spot.y() - 8 < top:
                spot = QPointF(centre.x() - radius - 4 - width / 2, centre.y())
            if any(abs(spot.x() - x.x()) < 28 and abs(spot.y() - x.y()) < 14 for x in labelled):
                continue
            labelled.append(spot)
            painter.setFont(bold)
            painter.setPen(inks.ink)
            painter.drawText(
                QRectF(spot.x() - width / 2 - 2, spot.y() - 8, width + 4, 16),
                Qt.AlignmentFlag.AlignCenter,
                named.label,
            )
            painter.setFont(self.font())

    @staticmethod
    def _paint_line(painter: QPainter, path: QPainterPath, pen: QPen) -> None:
        """A line, or — for a series one day long, as a plan's first day is — a dot where it
        starts, so a plan with no past still shows where it stands."""
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if path.boundingRect().width() >= 1:
            painter.setPen(pen)
            painter.drawPath(path)
            return
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(pen.color())
        start = path.pointAtPercent(0) if path.elementCount() else QPointF()
        painter.drawEllipse(start, pen.widthF() + 1.5, pen.widthF() + 1.5)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _step_path(
        self, points: tuple[tuple[date, float], ...], axis: Axis, top: float, end: date
    ) -> QPainterPath:
        path = QPainterPath(QPointF(axis.x(points[0][0]), self._y(top, points[0][1])))
        for index, _point in enumerate(points):
            following = points[index + 1] if index + 1 < len(points) else None
            path.lineTo(axis.x(following[0] if following else end), path.currentPosition().y())
            if following is not None:
                path.lineTo(path.currentPosition().x(), self._y(top, following[1]))
        return path

    # -- reading it ----------------------------------------------------------------------------

    def reading(self, x: float, y: float) -> str:
        """What the page says at a point: a mark's words where the pointer is on one, else
        the day under it and what each line said by then."""
        shown = self._shown
        if shown is None:
            return ""
        near = next(
            (
                hit
                for hit in self._hits
                if abs(hit.centre.x() - x) <= HIT and abs(hit.centre.y() - y) <= HIT
            ),
            None,
        )
        if near is not None:
            return near.words
        axis = self.axis()
        if not axis.left <= x <= axis.right:
            return ""
        day = axis.day_at(x)
        data = shown.burnup
        lines = [format_date(day, today=shown.day)]
        lines += [
            f"waits: {wait.title}" for wait in shown.now.waits if wait.start <= day <= wait.end
        ]
        readings = []
        if day <= shown.day:
            readings += [("scope", step_at(data.scope, day)), ("done", step_at(data.done, day))]
        readings.append(("the plan's schedule", step_at(shown.schedule, day)))
        lines += [
            f"{name}: {format_days(round(value * 4) / 4) or '0d'}"
            for name, value in readings
            if value is not None
        ]
        return "\n".join(lines)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        position = event.position()
        self._hover = position.x()
        said = self.reading(position.x(), position.y())
        if said:
            QToolTip.showText(event.globalPosition().toPoint(), said, self)
        else:
            QToolTip.hideText()
        self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        self._hover = None
        QToolTip.hideText()
        self.update()
        super().leaveEvent(event)
