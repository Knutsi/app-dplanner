"""The Milestones page: where each milestone lands against the plan it is compared with.

One row per milestone: where the plan compared with landed it (a hollow ring), where the
plan now lands it (a dot), an arrow between, the dates beside them and a line dropped to the
axis. A milestone that is done ends in a circle with a check on the day it was first
recorded done. A click picks a milestone — the other rows fade, as the calendar's bands do —
a second click hands it back, and a double-click opens the milestone's step, the one gesture
every surface answers. The words live in each row's tooltip.

The axis holds the reach :class:`~dplanner.modules.time_estimates.present.Presented`
carries, so moving between days moves the rows and never the dates under them.
"""

from datetime import timedelta

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QHelpEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from dplanner.domain.schedule import short_date
from dplanner.modules.time_estimates.plotting import (
    CHECK_RADIUS,
    Axis,
    Inks,
    faded,
    paint_check,
    paint_dates,
    paint_grid_dates,
    paint_verticals,
)
from dplanner.modules.time_estimates.present import Presented, Scope, milestone_words
from dplanner.theme.icons import ICON_SIZE, KEY_BADGE_W, key_badge_icon

ROW_HEIGHT = 34
LEFT = 230  # The names.
RIGHT = 80
TOP = 28
BOTTOM = 26
DOT = 4.5
ARROW_HEAD = 6.0
DROP_ALPHA = 76
FADE = 0.35
PICKED_ALPHA = 26
# Days of air either side of the dates the rows reach.
BEFORE = timedelta(days=2)
AFTER = timedelta(days=3)
NO_MILESTONES = "No milestones yet · Step ▸ Type ▸ Milestone"


class ShiftView(QWidget):
    """The rows. ``picked`` says which milestone a click picked (None to hand it back);
    ``activated`` names the milestone's step a double-click opens."""

    picked = Signal(object)
    activated = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._shown: Presented | None = None
        self._picked: str | None = None
        self._day_word = "today"
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(self._height())

    def show_presented(self, shown: Presented, picked: str | None, day_word: str) -> None:
        self._shown, self._picked, self._day_word = shown, picked, day_word
        self.setFixedHeight(self._height())
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(LEFT + RIGHT + 480, self._height())

    # -- what the tests read -------------------------------------------------------------------

    @property
    def rows(self) -> tuple[Scope, ...]:
        return self._shown.milestones if self._shown is not None else ()

    def axis(self) -> Axis:
        shown = self._shown
        assert shown is not None
        days = [shown.day, shown.reach.first, shown.reach.last]
        for scope in shown.milestones:
            days += [day for day in (scope.then, scope.planned, scope.landed_by) if day]
        days += [day for day, _title in shown.saved]
        return Axis(
            min(days) - BEFORE, max(days) + AFTER, LEFT, max(LEFT + 1, self.width() - RIGHT)
        )

    def row_at(self, y: float) -> Scope | None:
        index = int((y - TOP) // ROW_HEIGHT)
        rows = self.rows
        return rows[index] if y >= TOP and 0 <= index < len(rows) else None

    def words(self, scope: Scope) -> str:
        """A row's tooltip: the milestone, then where it landed, where it lands."""
        assert self._shown is not None
        return milestone_words(scope, self._shown.day)

    # -- painting ------------------------------------------------------------------------------

    def _height(self) -> int:
        return TOP + max(1, len(self.rows)) * ROW_HEIGHT + BOTTOM

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        shown = self._shown
        if shown is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inks = Inks.of(self.palette().text().color(), self.palette().base().color())
        axis = self.axis()
        bottom = self.height() - BOTTOM
        paint_grid_dates(painter, axis, TOP, bottom, inks)
        if not self.rows:
            painter.setPen(inks.secondary)
            painter.drawText(
                QRectF(LEFT, TOP, axis.right - LEFT, ROW_HEIGHT),
                Qt.AlignmentFlag.AlignVCenter,
                NO_MILESTONES,
            )
        for index, scope in enumerate(self.rows):
            painter.save()
            if self._picked is not None and scope.key != self._picked:
                painter.setOpacity(FADE)
            self._paint_row(painter, axis, inks, scope, TOP + (index + 0.5) * ROW_HEIGHT, bottom)
            painter.restore()
        paint_verticals(painter, axis, TOP - 4, bottom, inks, day=shown.day, saved=shown.saved)
        self._paint_saved_names(painter, axis, inks)
        paint_dates(painter, axis, bottom + 6, inks, day=shown.day, day_word=self._day_word)
        painter.end()

    def _paint_row(
        self, painter: QPainter, axis: Axis, inks: Inks, scope: Scope, y: float, bottom: float
    ) -> None:
        color = QColor(scope.named.color)
        if self._picked == scope.key:
            painter.fillRect(
                QRectF(0, y - ROW_HEIGHT / 2, self.width(), ROW_HEIGHT),
                faded(self.palette().highlight().color(), PICKED_ALPHA),
            )
        painter.setPen(QPen(inks.grid, 1.0))
        painter.drawLine(QPointF(LEFT, y), QPointF(axis.right, y))
        self._paint_name(painter, inks, scope, y)
        then, end = scope.then, scope.end
        if end is not None:
            painter.setPen(QPen(faded(color, DROP_ALPHA), 1.0))
            painter.drawLine(QPointF(axis.x(end), y), QPointF(axis.x(end), bottom))
        if then is not None and end is not None and then != end:
            self._paint_arrow(painter, axis.x(then), axis.x(end), y, color)
        if then is not None:
            painter.setPen(QPen(color, 1.6))
            painter.setBrush(inks.surface)
            radius = DOT + (2 if then == end else 0)
            painter.drawEllipse(QPointF(axis.x(then), y), radius, radius)
        if scope.landed_by is not None:
            paint_check(painter, QPointF(axis.x(scope.landed_by), y), color)
        elif end is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(axis.x(end), y), DOT, DOT)
        self._paint_row_dates(painter, axis, inks, scope, y)

    def _paint_name(self, painter: QPainter, inks: Inks, scope: Scope, y: float) -> None:
        named = scope.named
        badge = key_badge_icon(named.badge, named.color) if named.badge else None
        cursor = 8.0
        if badge is not None:
            badge.paint(painter, int(cursor), int(y - ICON_SIZE / 2), KEY_BADGE_W, ICON_SIZE)
            cursor += KEY_BADGE_W + 8
        bold = QFont(self.font())
        bold.setBold(True)
        painter.setFont(bold)
        painter.setPen(inks.ink)
        room = LEFT - cursor - 12
        label = QFontMetricsF(bold).elidedText(named.label, Qt.TextElideMode.ElideRight, room)
        painter.drawText(QRectF(cursor, y - 10, room, 20), Qt.AlignmentFlag.AlignVCenter, label)
        cursor += QFontMetricsF(bold).horizontalAdvance(label) + 8
        painter.setFont(self.font())
        if named.title and LEFT - cursor - 12 > 30:
            room = LEFT - cursor - 12
            title = QFontMetricsF(self.font()).elidedText(
                named.title, Qt.TextElideMode.ElideRight, room
            )
            painter.setPen(inks.secondary)
            painter.drawText(QRectF(cursor, y - 10, room, 20), Qt.AlignmentFlag.AlignVCenter, title)

    def _paint_arrow(
        self, painter: QPainter, start: float, end: float, y: float, color: QColor
    ) -> None:
        way = 1 if end >= start else -1
        tip = end - way * (DOT + 2)
        if abs(tip - start) < 6:
            return
        shade = faded(color, 216)
        painter.setPen(QPen(shade, 1.5))
        painter.drawLine(QPointF(start + way * (DOT + 1), y), QPointF(tip, y))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shade)
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(tip, y),
                    QPointF(tip - way * ARROW_HEAD, y - 3.5),
                    QPointF(tip - way * ARROW_HEAD, y + 3.5),
                ]
            )
        )

    def _paint_row_dates(
        self, painter: QPainter, axis: Axis, inks: Inks, scope: Scope, y: float
    ) -> None:
        """The outer end of each mark carries its date — left out rather than squeezed."""
        assert self._shown is not None
        day = self._shown.day
        metrics = QFontMetricsF(self.font())
        then, end = scope.then, scope.end
        labels: list[tuple[str, float, bool, QColor]] = []  # text, x, rightward, ink
        if end is not None:
            rightward = then is None or then <= end
            offset = (CHECK_RADIUS if scope.landed_by is not None else DOT) + 6
            at = axis.x(end) + offset if rightward else axis.x(end) - offset
            labels.append((short_date(end, day), at, rightward, inks.ink))
        if then is not None and then != end:
            leftward = end is None or then <= end
            at = axis.x(then) - DOT - 6 if leftward else axis.x(then) + DOT + 6
            labels.append((short_date(then, day), at, not leftward, inks.secondary))
        spans = [
            (at, at + metrics.horizontalAdvance(text))
            if rightward
            else (at - metrics.horizontalAdvance(text), at)
            for text, at, rightward, _ink in labels
        ]
        for position, (text, _at, _rightward, ink) in enumerate(labels):
            left, right = spans[position]
            clash = position == 1 and left < spans[0][1] and spans[0][0] < right
            if clash or left < LEFT - 4 or right > self.width() - 2:
                continue
            painter.setPen(ink)
            painter.drawText(
                QRectF(left, y - 10, right - left + 2, 20), Qt.AlignmentFlag.AlignVCenter, text
            )

    def _paint_saved_names(self, painter: QPainter, axis: Axis, inks: Inks) -> None:
        assert self._shown is not None
        metrics = QFontMetricsF(self.font())
        painter.setPen(inks.secondary)
        for when, title in self._shown.saved:
            if axis.holds(when):
                name = metrics.elidedText(title, Qt.TextElideMode.ElideRight, 140)
                painter.drawText(
                    QRectF(axis.x(when) + 4, 2, 150, TOP - 8), Qt.AlignmentFlag.AlignVCenter, name
                )

    # -- input ---------------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            row = self.row_at(event.position().y())
            key = row.key if row is not None and row.key != self._picked else None
            self.picked.emit(key)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        row = self.row_at(event.position().y())
        if row is not None and row.key:
            self.activated.emit(row.key)
        super().mouseDoubleClickEvent(event)

    def event(self, found: QEvent) -> bool:
        if found.type() == QEvent.Type.ToolTip and self._shown is not None:
            assert isinstance(found, QHelpEvent)
            row = self.row_at(found.pos().y())
            if row is not None:
                QToolTip.showText(found.globalPos(), self.words(row), self)
            else:
                QToolTip.hideText()
            return True
        return super().event(found)
