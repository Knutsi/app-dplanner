"""A run of months with the plan lit on it — each milestone's stretch in its own colour.

The landing list under it says "v1 · 24 September"; this shows it: from the start date
to the last landing, every stretch of work filled with its milestone's hue, fainter over
the weekends the schedule skips, and the day a milestone lands drawn as a filled mark. One
stretch can be *emphasised* (the host says which, from either list beside the calendar),
and the others fade so the work leading up to that milestone stands alone.

**The calendar fills the width it is given.** It is the one surface on the page that is
not a fixed-size drawing: the number of months across follows the width and the day cells
grow with it, so a wide window shows a wide calendar rather than a small one in a corner.
The height follows from the rows, which is why it is `Expanding` by `Fixed` and sets its own
height. The window of months runs from the month before the work starts, covers at least
six, grows to keep the last landing in view (capped — a multi-year plan keeps its dates in
the list rather than a wall of months), and rounds up to fill its last row.

Every colour but the milestone hues comes from the palette at paint time; the hues are the
same constants the lists beside it use (``schedule.py``'s ``PALETTE``), so the calendar and
the lists read as one report. Hovering a day answers precisely — which stretch, which
working day of how many, a weekend, a landing — so the calendar itself stays wordless.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QHelpEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
)
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from dplanner.domain.schedule import SATURDAY, format_date, working_days_between
from dplanner.modules.time_estimates.view import SECONDARY_ALPHA

MONTHS_SHOWN_AT_LEAST = 6
MONTHS_SHOWN_AT_MOST = 12
MONTHS_ACROSS_AT_MOST = 4

# Day cells grow with the width between these, on the 4-point scale's neighbours.
CELL_MIN = 18
CELL_MAX = 28
CELL_GAP = 2
MONTH_GAP = 16
TITLE_HEIGHT = 20
DAY_RADIUS = 3

# How loudly a day carries its stretch's hue: a worked day, a weekend inside the stretch
# (kept faint — the schedule skips it, but the band should read as one period), the
# plan's first day, and the day a milestone lands (filled: the mark the list points at).
SPAN_ALPHA = 64
SPAN_WEEKEND_ALPHA = 24
START_ALPHA = 130
LANDING_ALPHA = 220
# A stretch that is not the emphasised one keeps this much of its ink.
FADE = 0.4

# Day numbers: quiet by default, quieter on weekends, full ink inside a stretch — and
# reversed on a landing, which is filled.
DAY_ALPHA = 190
WEEKEND_ALPHA = 90

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

_ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class Band:
    """One stretch of the plan as the calendar paints it.

    ``key`` is what the host emphasises by — the milestone's step id, or "" for the work
    after the last milestone. ``lands`` says ``finish`` is a milestone's landing and gets
    the filled mark; the remainder's last day is just its last day.
    """

    key: str
    label: str
    start: date
    finish: date
    color: QColor
    lands: bool


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
    """The months around the plan, each stretch of work filled in its colour.

    The calendar is also the start-date control: clicking a day reports it through
    ``day_picked``, and the host turns that into the one undoable write. The widget
    itself never writes — the same contract as every input here.
    """

    day_picked = Signal(object)  # a datetime.date

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._start: date | None = None
        self._bands: tuple[Band, ...] = ()
        self._emphasised: str | None = None
        self._today = date.today()
        self._begin = date.today().replace(day=1)
        self._wanted = 0  # Months the plan asks for; the grid rounds up to fill its rows.
        self._count = 0
        self._columns = 1
        self._cell = CELL_MIN
        self._offset = 0  # months the user has paged away from the plan's own window
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(self._month_width(CELL_MIN))

    # -- the host's side of the contract -------------------------------------------------------

    def show_bands(self, start: date, bands: tuple[Band, ...], today: date | None = None) -> None:
        self._start = start
        self._bands = bands
        self._today = today or date.today()
        finish = max((band.finish for band in bands), default=None)
        self._begin, self._wanted = _month_span(start, finish)
        self._begin = _add_months(self._begin, self._offset)
        self._relayout()

    def emphasise(self, key: str | None) -> None:
        """Fade every stretch but this one; None shows them all alike."""
        if key != self._emphasised:
            self._emphasised = key
            self.update()

    def page(self, months: int) -> None:
        """Move the window through time; the plan's own window is offset zero."""
        self._offset += months
        self._begin = _add_months(self._begin, months)
        self.update()

    @property
    def span(self) -> tuple[date | None, date | None]:
        finish = max((band.finish for band in self._bands), default=None)
        return (self._start, finish)

    @property
    def emphasised(self) -> str | None:
        return self._emphasised

    @property
    def month_count(self) -> int:
        return self._count

    @property
    def columns(self) -> int:
        return self._columns

    @property
    def cell_size(self) -> int:
        return self._cell

    @property
    def first_month(self) -> date:
        return self._begin

    def band_at(self, when: date) -> Band | None:
        return next((band for band in self._bands if band.start <= when <= band.finish), None)

    def day_tooltip(self, when: date) -> str:
        """One precise sentence per day — the calendar's only words."""
        said = f"{WEEKDAYS[when.weekday()]} {format_date(when, today=self._today)}"
        band = self.band_at(when)
        if band is None:
            said += " — click to start the work here"
        elif when == band.finish and band.lands:
            said += f" — {band.label} lands"
        elif when.weekday() >= SATURDAY:
            said += " — weekend, not counted"
        else:
            worked = working_days_between(band.start, when)
            total = working_days_between(band.start, band.finish)
            starts = " starts," if when == band.start else ","
            said += f" — {band.label}{starts} working day {worked} of {total}"
        if when == self._today:
            said += " · today"
        return said

    # -- geometry ------------------------------------------------------------------------------

    @staticmethod
    def _month_width(cell: int) -> int:
        return 7 * (cell + CELL_GAP) - CELL_GAP

    @staticmethod
    def _month_height(cell: int) -> int:
        return TITLE_HEIGHT + 6 * (cell + CELL_GAP) - CELL_GAP

    def _relayout(self) -> None:
        """Fit the months to the width: as many across as fit at the smallest cell, then
        the cells grow to use what is left, and the rows fill out."""
        width = self.width()
        narrowest = self._month_width(CELL_MIN)
        columns = (width + MONTH_GAP) // (narrowest + MONTH_GAP)
        self._columns = max(1, min(MONTHS_ACROSS_AT_MOST, columns))
        room = width - (self._columns - 1) * MONTH_GAP - self._columns * 6 * CELL_GAP
        self._cell = max(CELL_MIN, min(CELL_MAX, room // (7 * self._columns)))
        rows = ceil(self._wanted / self._columns) if self._wanted else 0
        self._count = rows * self._columns
        self.setFixedHeight(rows * self._month_height(self._cell) + max(0, rows - 1) * MONTH_GAP)
        self.update()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self._relayout()

    def _month_origin(self, index: int) -> tuple[float, float]:
        row, column = divmod(index, self._columns)
        return (
            column * (self._month_width(self._cell) + MONTH_GAP),
            row * (self._month_height(self._cell) + MONTH_GAP),
        )

    def _day_rect(self, index: int, when: date) -> QRectF:
        left, top = self._month_origin(index)
        first = _add_months(self._begin, index)
        seat = when.day - 1 + first.weekday()
        row, column = divmod(seat, 7)
        return QRectF(
            left + column * (self._cell + CELL_GAP),
            top + TITLE_HEIGHT + row * (self._cell + CELL_GAP),
            self._cell,
            self._cell,
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

    # -- painting ------------------------------------------------------------------------------

    def _ink(self, band: Band, alpha: int) -> QColor:
        tint = QColor(band.color)
        faded = self._emphasised is not None and band.key != self._emphasised
        tint.setAlpha(round(alpha * FADE) if faded else alpha)
        return tint

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ink = self.palette().text().color()
        secondary = QColor(ink)
        secondary.setAlpha(SECONDARY_ALPHA)
        small = QFont(self.font())
        small.setPointSizeF(small.pointSizeF() - 1.5)
        for index in range(self._count):
            first = _add_months(self._begin, index)
            left, top = self._month_origin(index)
            painter.setFont(self.font())
            painter.setPen(secondary)
            title = format_date(first, today=self._today).split(" ", 1)[1]
            painter.drawText(
                QRectF(left, top, self._month_width(self._cell), TITLE_HEIGHT - 4),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                title,
            )
            painter.setFont(small)
            until = _add_months(first, 1)
            when = first
            while when < until:
                self._paint_day(painter, self._day_rect(index, when), when, ink, secondary)
                when += _ONE_DAY
        painter.end()

    def _paint_day(
        self, painter: QPainter, rect: QRectF, when: date, ink: QColor, secondary: QColor
    ) -> None:
        weekend = when.weekday() >= SATURDAY
        band = self.band_at(when)
        landing = band is not None and band.lands and when == band.finish
        if band is not None:
            if landing:
                alpha = LANDING_ALPHA
            elif when == self._start:
                alpha = START_ALPHA
            else:
                alpha = SPAN_WEEKEND_ALPHA if weekend else SPAN_ALPHA
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._ink(band, alpha))
            painter.drawRoundedRect(rect, DAY_RADIUS, DAY_RADIUS)
        if when == self._today:
            painter.setPen(QPen(secondary, 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), DAY_RADIUS, DAY_RADIUS)
        number = QColor(ink)
        if landing:
            # A filled mark takes the ground's colour for its number, so it reads on the hue.
            number = QColor(self.palette().base().color())
            if self._emphasised is not None and band is not None and band.key != self._emphasised:
                number = QColor(ink)
        elif band is None:
            number.setAlpha(WEEKEND_ALPHA if weekend else DAY_ALPHA)
        painter.setPen(number)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(when.day))

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
