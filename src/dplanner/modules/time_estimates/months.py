"""A compact run of months with the work period lit — when, on a real calendar.

The headline says "Lands 24 September"; this shows it: the span from the start date to
the selected team's landing date, filled with the report's one tint, fainter over the
weekends the schedule skips. The strip runs from the month before the work starts and
always covers at least six months, growing to keep the landing in view (capped — a
multi-year plan keeps its date in the headline rather than a wall of months).

Every colour but the tint comes from the palette at paint time; the tint is the same
constant low-alpha blue the matrix uses, so the two surfaces read as one report. Hovering
a day answers precisely — which working day of how many, a weekend, the landing — so the
strip itself stays wordless.
"""

from datetime import date, timedelta

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QHelpEvent, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from dplanner.domain.schedule import SATURDAY, format_date
from dplanner.modules.time_estimates.view import SECONDARY_ALPHA, TINT

MONTHS_SHOWN_AT_LEAST = 6
MONTHS_SHOWN_AT_MOST = 12
MONTHS_PER_ROW = 3

CELL = 18
CELL_GAP = 2
MONTH_GAP = 12
TITLE_HEIGHT = 20
DAY_RADIUS = 3

# How loudly a day carries the tint: a worked day, a weekend inside the span (kept faint —
# the schedule skips it, but the band should read as one period), and the endpoints.
SPAN_ALPHA = 64
SPAN_WEEKEND_ALPHA = 24
ENDPOINT_ALPHA = 130

# Day numbers: quiet by default, quieter on weekends, full ink inside the span.
DAY_ALPHA = 190
WEEKEND_ALPHA = 90

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

_ONE_DAY = timedelta(days=1)


def _first_of(when: date) -> date:
    return when.replace(day=1)


def _add_months(first: date, count: int) -> date:
    total = first.year * 12 + (first.month - 1) + count
    return date(total // 12, total % 12 + 1, 1)


def _month_span(start: date, finish: date | None) -> tuple[date, int]:
    """The first month shown and how many: one before the start, six at least, the
    landing kept in view, capped."""
    begin = _add_months(_first_of(start), -1)
    last = _add_months(_first_of(finish or start), 1)
    count = (last.year - begin.year) * 12 + (last.month - begin.month) + 1
    return begin, max(MONTHS_SHOWN_AT_LEAST, min(MONTHS_SHOWN_AT_MOST, count))


class MonthsView(QWidget):
    """The months around the plan, the work period filled in.

    The calendar is also the start-date control: clicking a day reports it through
    ``day_picked``, and the host turns that into the one undoable write. The widget
    itself never writes — the same contract as every input here.
    """

    day_picked = Signal(object)  # a datetime.date

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._start: date | None = None
        self._finish: date | None = None
        self._today = date.today()
        self._begin = date.today().replace(day=1)
        self._count = 0
        self._offset = 0  # months the user has paged away from the plan's own window
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # -- the host's side of the contract -------------------------------------------------------

    def show_span(self, start: date, finish: date | None, today: date | None = None) -> None:
        self._start = start
        self._finish = finish
        self._today = today or date.today()
        self._begin, self._count = _month_span(start, finish)
        self._begin = _add_months(self._begin, self._offset)
        rows = (self._count + MONTHS_PER_ROW - 1) // MONTHS_PER_ROW
        columns = min(self._count, MONTHS_PER_ROW)
        month_width = 7 * (CELL + CELL_GAP) - CELL_GAP
        month_height = TITLE_HEIGHT + 6 * (CELL + CELL_GAP) - CELL_GAP
        self.setFixedSize(
            columns * month_width + (columns - 1) * MONTH_GAP,
            rows * month_height + (rows - 1) * MONTH_GAP,
        )
        self.update()

    def page(self, months: int) -> None:
        """Move the window through time; the plan's own window is offset zero."""
        self._offset += months
        self._begin = _add_months(self._begin, months)
        self.update()

    @property
    def span(self) -> tuple[date | None, date | None]:
        return (self._start, self._finish)

    @property
    def month_count(self) -> int:
        return self._count

    @property
    def first_month(self) -> date:
        return self._begin

    def day_tooltip(self, when: date) -> str:
        """One precise sentence per day — the strip's only words."""
        said = f"{WEEKDAYS[when.weekday()]} {format_date(when, today=self._today)}"
        start, finish = self._start, self._finish
        if start is not None and finish is not None and start <= when <= finish:
            if when == finish:
                said += " — the work lands"
            elif when.weekday() >= SATURDAY:
                said += " — weekend, not counted"
            else:
                worked = sum(
                    1
                    for offset in range((when - start).days + 1)
                    if (start + offset * _ONE_DAY).weekday() < SATURDAY
                )
                total = sum(
                    1
                    for offset in range((finish - start).days + 1)
                    if (start + offset * _ONE_DAY).weekday() < SATURDAY
                )
                start_note = " — the work starts, " if when == start else " — "
                said += f"{start_note}working day {worked} of {total}"
        else:
            said += " — click to start the work here"
        if when == self._today:
            said += " · today"
        return said

    # -- painting ------------------------------------------------------------------------------

    def _month_origin(self, index: int) -> tuple[float, float]:
        month_width = 7 * (CELL + CELL_GAP) - CELL_GAP
        month_height = TITLE_HEIGHT + 6 * (CELL + CELL_GAP) - CELL_GAP
        row, column = divmod(index, MONTHS_PER_ROW)
        return (
            column * (month_width + MONTH_GAP),
            row * (month_height + MONTH_GAP),
        )

    def _day_rect(self, index: int, when: date) -> QRectF:
        left, top = self._month_origin(index)
        first = _add_months(self._begin, index)
        seat = when.day - 1 + first.weekday()
        row, column = divmod(seat, 7)
        return QRectF(
            left + column * (CELL + CELL_GAP),
            top + TITLE_HEIGHT + row * (CELL + CELL_GAP),
            CELL,
            CELL,
        )

    def _day_at(self, position: QPointF) -> date | None:
        for index in range(self._count):
            first = _add_months(self._begin, index)
            until = _add_months(first, 1)
            when = first
            while when < until:
                if self._day_rect(index, when).contains(position):
                    return when
                when += _ONE_DAY
        return None

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ink = self.palette().text().color()
        secondary = QColor(ink)
        secondary.setAlpha(SECONDARY_ALPHA)
        small = QFont(self.font())
        small.setPointSizeF(small.pointSizeF() - 1.5)
        start, finish = self._start, self._finish
        for index in range(self._count):
            first = _add_months(self._begin, index)
            left, top = self._month_origin(index)
            painter.setFont(self.font())
            painter.setPen(secondary)
            title = format_date(first, today=self._today).split(" ", 1)[1]
            painter.drawText(
                QRectF(left, top, 7 * (CELL + CELL_GAP) - CELL_GAP, TITLE_HEIGHT - 4),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                title,
            )
            painter.setFont(small)
            until = _add_months(first, 1)
            when = first
            while when < until:
                rect = self._day_rect(index, when)
                weekend = when.weekday() >= SATURDAY
                in_span = (
                    start is not None and finish is not None and start <= when <= finish
                )
                if in_span:
                    tint = QColor(TINT)
                    if when in (start, finish):
                        tint.setAlpha(ENDPOINT_ALPHA)
                    else:
                        tint.setAlpha(SPAN_WEEKEND_ALPHA if weekend else SPAN_ALPHA)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(tint)
                    painter.drawRoundedRect(rect, DAY_RADIUS, DAY_RADIUS)
                if when == finish:
                    ring = QPen(self.palette().highlight().color(), 1.5)
                    painter.setPen(ring)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRoundedRect(
                        rect.adjusted(0.75, 0.75, -0.75, -0.75), DAY_RADIUS, DAY_RADIUS
                    )
                elif when == self._today:
                    painter.setPen(QPen(secondary, 1.0))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRoundedRect(
                        rect.adjusted(0.5, 0.5, -0.5, -0.5), DAY_RADIUS, DAY_RADIUS
                    )
                number = QColor(ink)
                if in_span:
                    number.setAlpha(255)
                else:
                    number.setAlpha(WEEKEND_ALPHA if weekend else DAY_ALPHA)
                painter.setPen(number)
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(when.day))
                when += _ONE_DAY
        painter.end()

    # -- input ---------------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        when = self._day_at(event.position())
        if when is not None:
            self.day_picked.emit(when)
        super().mousePressEvent(event)

    def event(self, found: QEvent) -> bool:
        if found.type() == QEvent.Type.ToolTip:
            assert isinstance(found, QHelpEvent)
            when = self._day_at(QPointF(found.pos()))
            if when is not None:
                QToolTip.showText(found.globalPos(), self.day_tooltip(when), self)
            else:
                QToolTip.hideText()
            return True
        return super().event(found)
