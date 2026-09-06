"""Three plots on one time axis: where the work stands, how the plan changed, and where
each milestone moved.

One chart used to carry the plan at the basis day, the plan now and what actually landed
as three lines over each other, and the reader had to untangle them. Now each question
gets a plot of its own, stacked, on **one locked x axis**: the same dates run under all
three, the gridlines at every date mark drop through every plot, the date labels are
printed once under the last one, and the edges are the earliest and latest date any of
the three has to show — so a point placed in one plot is placed in all of them.

- **Progress** — the plan now, the share landed by each date, in each stretch's shade
  (the calendar's colours, on the line); what actually landed, in ink, with a dot at
  today and beside it a short word on where it stands: *ahead 5 %*, *behind 12 %*, *on
  plan*.
- **Scope change** — the plan as it stood on the basis day (the project's start, or
  the day picked beside the chart) dashed and paler, the plan now solid, and the band
  between them washed in the plan's hue: a plan that grew shows as the area it grew by,
  a landing that moved as the gap between two marks on the 100 % line.
- **Milestones** — one row per milestone, its landing on the basis day as a hollow
  mark, its landing now filled, and an arrow from the one to the other saying which way
  it went. A milestone the plan then did not know has only the filled mark; an
  unchanged one shows the filled mark inside the ring.

**Picking a milestone highlights; it never hides.** The whole project stays on every
plot, and everything outside the picked stretch — the other segments of the lines, the
other rows — fades to a third, so the picked one stands out against the plan it is part
of. That is what the calendar does with its bands, said the same way here.

**The axis is marked at calendar boundaries.** A reader places a point by the nearest
mark, so the marks are every day, every Monday or every month's first — the finest unit
whose labels fit the width (:func:`axis_ticks`) — with a hairline up from each through
every plot and a hairline every quarter of the share, a grid a whisper of the ink; the
first mark of a new year carries the year.

**The baseline is painted over the plan, opaque.** A plan that has not changed since the
basis has a baseline that coincides with it, and a translucent dash of the same hue under
a solid line of that hue is invisible. Painted last, in the colour pulled toward the ink
and mixed opaque, the dashes ride on the solid line where the two agree and read as *two
lines in the same place*, which is the fact.

Every colour but a stretch's shade comes from the palette at paint time — the axes and
the actual line in ink, gridlines a whisper of it — and the marks keep the chart grammar
the coverage lanes and the calendar keep: 2 px lines, an 8 px end marker with a 2 px
surface ring, hairline gridlines. The height follows the data (a row per milestone) and
never the width, so nothing here can loop a scroll area. The gutters are measured from
the font, so "100 %" and the milestone names fit whatever the platform's text size.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import pairwise
from math import atan2, cos, sin

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QHelpEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from dplanner.domain.schedule import Tick, axis_ticks, format_date
from dplanner.modules.time_estimates.progress import landing_shift
from dplanner.modules.time_estimates.schedule import WHOLE_COLOR
from dplanner.modules.time_estimates.view import SECONDARY_ALPHA
from dplanner.theme.cards import over

# The two share plots are this tall; the milestone plot is a row per milestone. The gaps
# and insets are the 4-point scale.
PANEL_HEIGHT = 112
ROW_HEIGHT = 24
PANEL_GAP = 16
TITLE_GAP = 6
BOTTOM_GUTTER = 22
LABEL_GAP = 6
RIGHT_INSET = 12
# A milestone name in the left gutter is elided past this, so one long name cannot
# push every plot to the right.
GUTTER_NAME_MAX = 120
# Air between two tick labels: a unit is offered only when every label has this much.
TICK_LABEL_GAP = 16
# The dataviz mark grammar: 2 px lines, a marker of at least 8 px ringed in the surface.
LINE_WIDTH = 2.0
MARKER = 8.0
RING = 2.0
LANDING_MARK = 6.0
ARROW_HEAD = 6.0
GRID_ALPHA = 28
# The change in the plan: the plan's hue as a wash between the two curves (the dataviz
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
# The picked milestone's landing, as a line through every plot.
MARK_LINE_ALPHA = 150
# What the ahead-or-behind word sits from today's dot.
STANDING_GAP = 6
# A gap the plan leaves empty: the plan's colour pulled this far toward the surface, in
# dots. The pattern is in pen widths: a dash short enough for the round caps to make a
# dot of it, then a gap that stays a gap after the caps take a width of it — Qt's own
# DotLine under round caps reads as a solid line with a texture.
IDLE_SURFACE_ALPHA = 120
DOT_PATTERN = (0.1, 3.0)
# Everything outside the picked stretch is painted at this opacity.
FADE = 0.3
# Two shares within this are "on plan".
ON_PLAN = 0.005

Point = tuple[date, float]
Span = tuple[date, date]


@dataclass(frozen=True)
class Segment:
    """One stretch of the plan as the chart draws it: its shade, where it runs in the
    plan now and where it ran in the plan at the basis day — each a start and a landing,
    or None when that plan could not date it. Key ``""`` is the work after the last
    milestone, which colours the line but gets no row of its own."""

    key: str
    label: str
    color: QColor
    now: Span | None = None
    then: Span | None = None

    @property
    def is_milestone(self) -> bool:
        return bool(self.key)


@dataclass(frozen=True)
class ChartData:
    """The whole plan as the three plots show it: the plan now, the plan on the basis day
    (``baseline_day`` names the recorded day it came from), what actually landed, and the
    stretches the lines run through. ``emphasis`` is the milestone held in full ink while
    the rest fades — None shows every stretch alike."""

    today: date
    expected: tuple[Point, ...] = ()
    actual: tuple[Point, ...] = ()
    baseline: tuple[Point, ...] = ()
    baseline_day: date | None = None
    finish: date | None = None
    baseline_finish: date | None = None
    by_days: bool = False
    # The spans the plan leaves empty, from a landing to the day work resumes.
    idle: tuple[Span, ...] = ()
    segments: tuple[Segment, ...] = ()
    emphasis: str | None = None
    # The plan's own colour: the band, the baseline, and the line where no stretch
    # claims it.
    color: QColor = field(default_factory=lambda: QColor(WHOLE_COLOR))

    @property
    def milestones(self) -> tuple[Segment, ...]:
        return tuple(segment for segment in self.segments if segment.is_milestone)

    @property
    def emphasised(self) -> Segment | None:
        return next((s for s in self.segments if s.key == self.emphasis), None)

    def standing(self) -> float | None:
        """Actual against plan today, in share: positive ahead, negative behind — None
        when either line has nothing to say for today."""
        planned = _share_at(self.expected, self.today)
        landed = _share_at(self.actual, self.today)
        if planned is None or landed is None:
            return None
        return landed - planned


@dataclass(frozen=True)
class _Panel:
    kind: str  # "status", "scope" or "shift"
    rect: QRectF  # The plot area; the title band sits above it.


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


def standing_words(standing: float | None) -> str:
    """Ahead or behind, in one short phrase — the word beside today's dot."""
    if standing is None:
        return ""
    if abs(standing) < ON_PLAN:
        return "on plan"
    return f"{'ahead' if standing > 0 else 'behind'} {abs(standing):.0%}"


def shift_words(segment: Segment, baseline_day: date | None, today: date) -> str:
    """A milestone's row in words: where it lands, where it landed then, and the move."""
    now = segment.now[1] if segment.now else None
    then = segment.then[1] if segment.then else None
    if now is None:
        return f"{segment.label} — nothing estimated, so no date"
    said = f"{segment.label} lands {format_date(now, today=today)}"
    if baseline_day is None:
        return said
    if then is None:
        return f"{said} — not in the plan at {format_date(baseline_day, today=today)}"
    moved = landing_shift(then, now)
    if moved == 0:
        return f"{said} — unchanged since {format_date(baseline_day, today=today)}"
    direction = "later" if moved > 0 else "earlier"
    return (
        f"{said} — {abs(moved)} working day{'' if abs(moved) == 1 else 's'} {direction} "
        f"than planned on {format_date(baseline_day, today=today)} "
        f"({format_date(then, today=today)})"
    )


class ProgressChart(QWidget):
    """The three plots; the host hands it a :class:`ChartData`."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data: ChartData | None = None
        self._first = date.today()
        self._last = date.today()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setFixedHeight(self._height())

    # -- the host's side of the contract -------------------------------------------------------

    def show_data(self, data: ChartData | None) -> None:
        self._data = data
        if data is not None:
            dates = [data.today, *(when for when, _ in data.expected), *(w for w, _ in data.actual)]
            dates += [when for when, _ in data.baseline]
            dates += [when for when in (data.finish, data.baseline_finish) if when is not None]
            for segment in data.segments:
                for span in (segment.now, segment.then):
                    if span is not None:
                        dates += [span[0], span[1]]
            self._first = min(dates) - timedelta(days=PAD_DAYS)
            self._last = max(dates) + timedelta(days=PAD_DAYS)
            if self._last <= self._first:
                self._last = self._first + timedelta(days=1)
        self.setFixedHeight(self._height())
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
        room = int(self._plot_width() // (widest + TICK_LABEL_GAP))
        return axis_ticks(self._first, self._last, room)

    def panels(self) -> tuple[_Panel, ...]:
        """The plots top to bottom, each with its area — the third only with milestones."""
        left = self._left_gutter()
        width = self._plot_width()
        band = self.fontMetrics().height() + TITLE_GAP
        heights = [("status", float(PANEL_HEIGHT)), ("scope", float(PANEL_HEIGHT))]
        rows = len(self._data.milestones) if self._data is not None else 0
        if rows:
            heights.append(("shift", float(rows * ROW_HEIGHT)))
        found = []
        top = 0.0
        for kind, height in heights:
            found.append(_Panel(kind, QRectF(left, top + band, width, height)))
            top += band + height + PANEL_GAP
        return tuple(found)

    def panel(self, kind: str) -> _Panel:
        return next(panel for panel in self.panels() if panel.kind == kind)

    def tooltip_at(self, when: date, kind: str = "status") -> str:
        """The date and what the plot under the cursor says for it — the chart's only
        words, with the standing word and the milestone rows."""
        data = self._data
        if data is None:
            return ""
        lines = [format_date(when, today=data.today)]
        unit = "of days" if data.by_days else "of steps"
        if kind == "scope":
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
        if kind == "status":
            landed = _share_at(data.actual, when)
            if landed is not None and when <= data.today:
                lines.append(f"actual: {landed:.0%} {unit}")
        return "\n".join(lines)

    # -- geometry --------------------------------------------------------------------------------

    def _left_gutter(self) -> float:
        metrics = self.fontMetrics()
        widest = float(metrics.horizontalAdvance("100%"))
        if self._data is not None:
            for segment in self._data.milestones:
                widest = max(widest, min(GUTTER_NAME_MAX, metrics.horizontalAdvance(segment.label)))
        return widest + 2 * LABEL_GAP

    def _plot_width(self) -> float:
        return max(1.0, self.width() - self._left_gutter() - RIGHT_INSET)

    def _height(self) -> int:
        panels = self.panels()
        return round(panels[-1].rect.bottom() + BOTTOM_GUTTER)

    def _x(self, when: date) -> float:
        total = (self._last - self._first).days or 1
        return self._left_gutter() + self._plot_width() * (when - self._first).days / total

    @staticmethod
    def _y(panel: _Panel, share: float) -> float:
        return panel.rect.bottom() - panel.rect.height() * min(max(share, 0.0), 1.0)

    @staticmethod
    def _row_y(panel: _Panel, index: int) -> float:
        return panel.rect.top() + (index + 0.5) * ROW_HEIGHT

    def _date_at(self, x: float) -> date:
        width = self._plot_width()
        share = (x - self._left_gutter()) / width if width else 0.0
        days = round((self._last - self._first).days * min(max(share, 0.0), 1.0))
        return self._first + timedelta(days=days)

    def _point(self, panel: _Panel, point: Point) -> QPointF:
        return QPointF(self._x(point[0]), self._y(panel, point[1]))

    def _span_rect(self, panel: _Panel, span: Span) -> QRectF:
        left, right = self._x(span[0]), self._x(span[1])
        return QRectF(left, panel.rect.top(), max(1.0, right - left), panel.rect.height())

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
        panels = self.panels()
        for panel in panels:
            self._draw_grid(painter, panel, data, grid, secondary, last=panel is panels[-1])
            self._draw_title(painter, panel, data, ink, surface, secondary)

        # Today, and the picked milestone's landing: hairlines through every plot.
        top, bottom = panels[0].rect.top(), panels[-1].rect.bottom()
        if self._first <= data.today <= self._last:
            painter.setPen(QPen(secondary, 1.0))
            x = self._x(data.today)
            painter.drawLine(QPointF(x, top), QPointF(x, bottom))
        picked = data.emphasised
        if picked is not None and picked.now is not None:
            line = QColor(picked.color)
            line.setAlpha(MARK_LINE_ALPHA)
            painter.setPen(QPen(line, 1.0))
            x = self._x(picked.now[1])
            painter.drawLine(QPointF(x, top), QPointF(x, bottom))

        for panel in panels:
            if panel.kind == "shift":
                self._draw_shift(painter, panel, data, ink, surface)
                continue
            draw = self._draw_status if panel.kind == "status" else self._draw_scope
            # Everything faded, then the picked stretch over it in full — clipped to
            # where that stretch runs, so the same lines are drawn twice and read once.
            span = self._emphasis_span(panel, data)
            painter.save()
            painter.setClipRect(panel.rect.adjusted(-MARKER, -MARKER, MARKER, MARKER))
            painter.setOpacity(FADE if span is not None else 1.0)
            draw(painter, panel, data, ink, surface)
            if span is not None:
                painter.setOpacity(1.0)
                painter.setClipRect(self._span_rect(panel, span).adjusted(0, -MARKER, 0, MARKER))
                draw(painter, panel, data, ink, surface)
            painter.restore()
            if panel.kind == "status":
                self._draw_standing(painter, panel, data, ink)
        painter.end()

    @staticmethod
    def _emphasis_span(panel: _Panel, data: ChartData) -> Span | None:
        """Where the picked stretch runs in this plot: in the plan now, and — for the
        scope plot, which draws both plans — in the plan then as well."""
        picked = data.emphasised
        if picked is None:
            return None
        spans = [picked.now] if panel.kind == "status" else [picked.now, picked.then]
        found = [span for span in spans if span is not None]
        if not found:
            return None
        return (min(span[0] for span in found), max(span[1] for span in found))

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
        self,
        painter: QPainter,
        panel: _Panel,
        data: ChartData,
        grid: QColor,
        secondary: QColor,
        *,
        last: bool,
    ) -> None:
        """Hairlines at every date mark through the plot and — on a share plot — every
        quarter, with the percent labels at the ends and the middle, right-aligned to the
        plot like every header; on the milestone plot a guide per row. The dates are
        printed under the last plot only, centred under their marks and kept inside the
        widget at either end."""
        metrics = painter.fontMetrics()
        plot = panel.rect
        painter.setPen(QPen(grid, 1.0))
        if panel.kind == "shift":
            for index in range(len(data.milestones)):
                y = self._row_y(panel, index)
                painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        else:
            for share in GRID_SHARES:
                y = self._y(panel, share)
                painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        ticks = self.ticks()
        for when, _ in ticks:
            x = self._x(when)
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
        painter.setPen(secondary)
        if panel.kind != "shift":
            for share in LABELLED_SHARES:
                painter.drawText(
                    QRectF(
                        0.0,
                        self._y(panel, share) - metrics.height() / 2,
                        plot.left() - LABEL_GAP,
                        metrics.height(),
                    ),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    f"{share:.0%}",
                )
        if not last:
            return
        for when, label in ticks:
            width = metrics.horizontalAdvance(label) + 2
            x = min(max(self._x(when) - width / 2, 0.0), self.width() - width)
            painter.drawText(
                QRectF(x, plot.bottom() + 4, width, metrics.height()),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                label,
            )

    # -- the plots -------------------------------------------------------------------------------

    def _draw_status(
        self, painter: QPainter, panel: _Panel, data: ChartData, ink: QColor, surface: QColor
    ) -> None:
        """The plan now in each stretch's shade with its landing marked, and what actually
        landed in ink — today's reading ringed, and worded beside it."""
        self._draw_plan(painter, panel, data, surface)
        if data.finish is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._shade_at(data, data.finish))
            painter.drawEllipse(
                QPointF(self._x(data.finish), self._y(panel, 1.0)),
                LANDING_MARK / 2,
                LANDING_MARK / 2,
            )
        self._draw_line(painter, panel, data.actual, ink)
        if not data.actual:
            return
        when, share = data.actual[-1]
        centre = QPointF(self._x(when), self._y(panel, share))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(surface)
        painter.drawEllipse(centre, MARKER / 2 + RING, MARKER / 2 + RING)
        painter.setBrush(ink)
        painter.drawEllipse(centre, MARKER / 2, MARKER / 2)

    def _draw_standing(
        self, painter: QPainter, panel: _Panel, data: ChartData, ink: QColor
    ) -> None:
        """Ahead or behind, beside today's dot — after the faded and the clipped pass,
        so the word is whole and in full ink whatever is picked."""
        words = standing_words(data.standing())
        if not words or not data.actual:
            return
        when, share = data.actual[-1]
        centre = QPointF(self._x(when), self._y(panel, share))
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(words) + 2
        left = centre.x() + MARKER / 2 + STANDING_GAP
        if left + width > panel.rect.right():
            left = centre.x() - MARKER / 2 - STANDING_GAP - width
        painter.setPen(ink)
        painter.drawText(
            QRectF(left, centre.y() - metrics.height() / 2, width, metrics.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            words,
        )

    def _draw_scope(
        self, painter: QPainter, panel: _Panel, data: ChartData, ink: QColor, surface: QColor
    ) -> None:
        """The band between the two plans, the plan now over it, and the baseline over
        both — opaque and paler, so dashes on the line say the plans agree."""
        if len(data.baseline) >= 2 and len(data.expected) >= 2:
            band = QPainterPath(self._point(panel, data.expected[0]))
            for point in data.expected[1:]:
                band.lineTo(self._point(panel, point))
            for point in reversed(data.baseline):
                band.lineTo(self._point(panel, point))
            band.closeSubpath()
            wash = QColor(data.color)
            wash.setAlpha(BAND_ALPHA)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(wash)
            painter.drawPath(band)
        self._draw_plan(painter, panel, data, surface)
        if data.finish is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._shade_at(data, data.finish))
            painter.drawEllipse(
                QPointF(self._x(data.finish), self._y(panel, 1.0)),
                LANDING_MARK / 2,
                LANDING_MARK / 2,
            )
        faded = self._baseline_shade(data.color, ink)
        self._draw_line(painter, panel, data.baseline, faded, Qt.PenStyle.DashLine)
        if data.baseline_finish is not None:
            painter.setPen(QPen(faded, LINE_WIDTH))
            painter.setBrush(surface)
            painter.drawEllipse(
                QPointF(self._x(data.baseline_finish), self._y(panel, 1.0)),
                LANDING_MARK / 2,
                LANDING_MARK / 2,
            )

    def _draw_shift(
        self, painter: QPainter, panel: _Panel, data: ChartData, ink: QColor, surface: QColor
    ) -> None:
        """A row per milestone: its name in the gutter (in secondary ink — a palette's
        darkest shade is not a text colour), a hollow mark where the plan then landed it,
        a filled one where the plan now does, and an arrow between them. Rows other than
        the picked one fade."""
        metrics = painter.fontMetrics()
        secondary = QColor(ink)
        secondary.setAlpha(SECONDARY_ALPHA)
        for index, segment in enumerate(data.milestones):
            y = self._row_y(panel, index)
            faded = data.emphasis is not None and segment.key != data.emphasis
            painter.setOpacity(FADE if faded else 1.0)
            name = metrics.elidedText(segment.label, Qt.TextElideMode.ElideRight, GUTTER_NAME_MAX)
            painter.setPen(secondary)
            painter.drawText(
                QRectF(
                    0.0, y - metrics.height() / 2, panel.rect.left() - LABEL_GAP, metrics.height()
                ),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                name,
            )
            then = segment.then[1] if segment.then else None
            now = segment.now[1] if segment.now else None
            if then is not None and now is not None and then != now:
                self._draw_arrow(
                    painter, QPointF(self._x(then), y), QPointF(self._x(now), y), segment.color
                )
            if then is not None:
                painter.setPen(QPen(segment.color, LINE_WIDTH))
                painter.setBrush(surface)
                radius = MARKER / 2 + (RING if then == now else 0.0)
                painter.drawEllipse(QPointF(self._x(then), y), radius, radius)
            if now is not None:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(segment.color)
                painter.drawEllipse(QPointF(self._x(now), y), LANDING_MARK / 2, LANDING_MARK / 2)
        painter.setOpacity(1.0)

    def _draw_arrow(self, painter: QPainter, start: QPointF, end: QPointF, color: QColor) -> None:
        """A shaft from ``start`` stopping short of the mark at ``end``, with a head
        pointing the way the landing moved."""
        angle = atan2(end.y() - start.y(), end.x() - start.x())
        tip = QPointF(end.x() - cos(angle) * LANDING_MARK, end.y() - sin(angle) * LANDING_MARK)
        painter.setPen(self._pen(color))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(start, tip)
        spread = 0.5
        head = QPolygonF(
            [
                tip,
                QPointF(
                    tip.x() - cos(angle - spread) * ARROW_HEAD,
                    tip.y() - sin(angle - spread) * ARROW_HEAD,
                ),
                QPointF(
                    tip.x() - cos(angle + spread) * ARROW_HEAD,
                    tip.y() - sin(angle + spread) * ARROW_HEAD,
                ),
            ]
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(head)

    def _shade_at(self, data: ChartData, when: date) -> QColor:
        """The colour of the stretch the plan now runs on ``when`` — the plan's own
        colour where no stretch claims the day."""
        for segment in data.segments:
            if segment.now is not None and segment.now[0] <= when <= segment.now[1]:
                return segment.color
        return data.color

    def _draw_plan(
        self, painter: QPainter, panel: _Panel, data: ChartData, surface: QColor
    ) -> None:
        """The plan now as two paths — solid where work is planned, dotted in the paler
        shade across a span the plan leaves empty — the solid one painted once per
        stretch, clipped to where that stretch runs, in its shade. A stretch's clip
        reaches back to the previous landing, so the weekend between two stretches is
        nobody's gap."""
        work, gap = QPainterPath(), QPainterPath()
        current: QPainterPath | None = None
        for start, end in pairwise(data.expected):
            empty = any(since <= start[0] and end[0] <= until for since, until in data.idle)
            path = gap if empty else work
            if path is not current:
                path.moveTo(self._point(panel, start))
                current = path
            path.lineTo(self._point(panel, end))
        spans = [(segment.now, segment.color) for segment in data.segments if segment.now]
        if not spans:
            self._draw_path(painter, work, data.color)
        previous: date | None = None
        for (begins, lands), color in spans:
            painter.save()
            painter.setClipRect(
                self._span_rect(panel, (previous or begins, lands)).adjusted(0, -MARKER, 0, MARKER),
                Qt.ClipOperation.IntersectClip,
            )
            self._draw_path(painter, work, color)
            painter.restore()
            previous = lands
        self._draw_path(painter, gap, self._idle_shade(data.color, surface), Qt.PenStyle.DotLine)

    def _draw_line(
        self,
        painter: QPainter,
        panel: _Panel,
        points: tuple[Point, ...],
        color: QColor,
        style: Qt.PenStyle = Qt.PenStyle.SolidLine,
    ) -> None:
        if len(points) < 2:
            return
        path = QPainterPath(self._point(panel, points[0]))
        for point in points[1:]:
            path.lineTo(self._point(panel, point))
        self._draw_path(painter, path, color, style)

    @staticmethod
    def _pen(color: QColor, style: Qt.PenStyle = Qt.PenStyle.SolidLine) -> QPen:
        """A series line: 2 px, round-capped, dashed or dotted as the style says."""
        pen = QPen(color, LINE_WIDTH)
        pen.setStyle(style)
        if style == Qt.PenStyle.DotLine:
            pen.setDashPattern(list(DOT_PATTERN))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    @staticmethod
    def _draw_path(
        painter: QPainter,
        path: QPainterPath,
        color: QColor,
        style: Qt.PenStyle = Qt.PenStyle.SolidLine,
    ) -> None:
        if path.isEmpty():
            return
        painter.setPen(ProgressChart._pen(color, style))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    # -- the title bands -------------------------------------------------------------------------

    def title(self, panel: _Panel) -> str:
        data = self._data
        if panel.kind == "status":
            return "Progress"
        if panel.kind == "shift":
            return "Milestones"
        if data is None or data.baseline_day is None:
            return "Scope change — no earlier plan recorded"
        return f"Scope change since {format_date(data.baseline_day, today=data.today)}"

    def legend(self, panel: _Panel) -> list[tuple[str, str]]:
        """The plot's keys: a label and what draws it."""
        data = self._data
        if data is None:
            return []
        if panel.kind == "status":
            found = [("Plan", "plan"), ("Actual", "actual")]
            if data.idle:
                found.append(("No work planned", "idle"))
            return found
        if panel.kind == "scope":
            found = []
            if data.baseline and data.baseline_day is not None:
                found.append(
                    (f"Plan at {format_date(data.baseline_day, today=data.today)}", "baseline")
                )
            return [*found, ("Plan now", "plan")]
        return [("Then", "hollow"), ("Now", "filled")] if data.baseline_day is not None else []

    def _draw_title(
        self,
        painter: QPainter,
        panel: _Panel,
        data: ChartData,
        ink: QColor,
        surface: QColor,
        secondary: QColor,
    ) -> None:
        """The plot's name at the left of its band and its keys at the right — the keys
        left out when the two would meet, and the tooltips still answer."""
        metrics = painter.fontMetrics()
        band = QRectF(
            panel.rect.left(),
            panel.rect.top() - TITLE_GAP - metrics.height(),
            panel.rect.width(),
            metrics.height(),
        )
        painter.setPen(secondary)
        title = self.title(panel)
        painter.drawText(band, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        entries = self.legend(panel)
        needed = sum(
            LEGEND_KEY + LEGEND_GAP + metrics.horizontalAdvance(label) + LEGEND_SPACING
            for label, _ in entries
        )
        if not entries or metrics.horizontalAdvance(title) + LEGEND_SPACING + needed > band.width():
            return
        keys: dict[str, tuple[QColor, Qt.PenStyle]] = {
            "baseline": (self._baseline_shade(data.color, ink), Qt.PenStyle.DashLine),
            "plan": (data.color, Qt.PenStyle.SolidLine),
            "actual": (ink, Qt.PenStyle.SolidLine),
            "idle": (self._idle_shade(data.color, surface), Qt.PenStyle.DotLine),
        }
        x = band.right() - needed + LEGEND_SPACING
        y = band.center().y()
        for label, kind in entries:
            if kind in keys:
                color, style = keys[kind]
                painter.setPen(self._pen(color, style))
                painter.drawLine(QPointF(x, y), QPointF(x + LEGEND_KEY, y))
            else:
                centre = QPointF(x + LEGEND_KEY / 2, y)
                if kind == "hollow":
                    painter.setPen(QPen(secondary, LINE_WIDTH))
                    painter.setBrush(surface)
                    painter.drawEllipse(centre, MARKER / 2, MARKER / 2)
                else:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(secondary)
                    painter.drawEllipse(centre, LANDING_MARK / 2, LANDING_MARK / 2)
            x += LEGEND_KEY + LEGEND_GAP
            painter.setPen(secondary)
            width = metrics.horizontalAdvance(label) + 2
            painter.drawText(
                QRectF(x, band.top(), width, band.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            x += metrics.horizontalAdvance(label) + LEGEND_SPACING

    # -- input -----------------------------------------------------------------------------------

    def _words_at(self, position: QPointF) -> str:
        data = self._data
        if data is None:
            return ""
        for panel in self.panels():
            if not panel.rect.adjusted(-self._left_gutter(), 0, 0, 0).contains(position):
                continue
            if panel.kind == "shift":
                index = int((position.y() - panel.rect.top()) // ROW_HEIGHT)
                if 0 <= index < len(data.milestones):
                    return shift_words(data.milestones[index], data.baseline_day, data.today)
                return ""
            return self.tooltip_at(self._date_at(position.x()), panel.kind)
        return ""

    def event(self, found: QEvent) -> bool:
        if found.type() == QEvent.Type.ToolTip and self._data is not None:
            assert isinstance(found, QHelpEvent)
            words = self._words_at(QPointF(found.pos()))
            if words:
                QToolTip.showText(found.globalPos(), words, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(found)
