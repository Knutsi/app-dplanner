"""Three plots on one time axis: where the work stands, how the plan changed, and where
each milestone moved.

One chart used to carry the plan at the basis day, the plan now and what actually landed
as three lines over each other, and the reader had to untangle them. Now each question
gets a plot of its own, stacked, on **one locked x axis**: the same dates run under all
three, the gridlines at every date mark drop through every plot, the date labels are
printed once under the last one, and the edges are the earliest and latest date any of
the three has to show — so a point placed in one plot is placed in all of them.

- **Progress** — the plan now, the share landed by each date, in each stretch's shade
  (the calendar's colours, on the line), with every milestone's landing marked and
  named; what actually landed, in ink, with a dot at today and beside it a short word on
  where it stands: *ahead 5 %*, *behind 12 %*, *on plan*.
- **Scope change** — the plan as it stood on the basis day (the project's start, or the
  day picked beside the chart) dashed and paler, the plan now solid, and **the area
  between them filled by which way it went**: the plan now above the baseline is work
  pulled in — the same amount promised sooner — and wears the attention amber; below it
  is work that slipped, and wears the bad red; where the two agree there is no area to
  fill, so the run is a line in the good green. The overlap is the point, so the fill
  says the direction and the legend does not have to.
- **Milestones** — one row per milestone, its landing on the basis day as a hollow
  mark, its landing now filled, and an arrow from the one to the other saying which way
  it went. A milestone the plan then did not know has only the filled mark; an
  unchanged one shows the filled mark inside the ring.

**Picking a milestone highlights; it never hides.** The whole project stays on every
plot, and everything outside the picked stretch — the other segments of the lines, the
other rows — fades to a third, so the picked one stands out against the plan it is part
of. That is what the calendar does with its bands, said the same way here.

**The chart names the day it is measured against, and only that one.** The scope plot is
headed *Scope change — versus plan at 1 June*: the **basis** the reader asked for, which
is the day the control beside the plots holds. Which daily record stood in for it is
bookkeeping and is reported by ``dplanner progress show``; a heading naming that record
while the control named another read as a contradiction. With nothing recorded that early
the heading says so rather than comparing the plan with itself (``progress.baseline``).

**A plot is given the room the window has, up to a ceiling.** The two share plots take
whatever height the host gives the widget over its minimum, in equal parts, and stop at
``MAX_PANEL_HEIGHT``; the milestone rows never grow. The bounds are set from the data,
never from a resize — see ``months.py`` for what a widget that resizes itself inside its
own resize event does to a scroll area. :class:`ChartDialog` is the same widget with the
same data in a window of its own, for a reader who wants more than the panel.

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
the room the host gives it, never the width, so nothing here can loop a scroll area. The
gutters are measured from the font, so "100 %" and the milestone names fit whatever the
platform's text size, and a plot's name is set bold with air above it so the three read
as headings.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import pairwise
from math import atan2, cos, sin

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QHelpEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.schedule import (
    Tick,
    axis_ticks,
    change_runs,
    format_date,
    share_at,
    short_date,
)
from dplanner.modules.time_estimates.progress import scope_words, shift_words, standing_words
from dplanner.modules.time_estimates.schedule import WHOLE_COLOR
from dplanner.modules.time_estimates.view import SECONDARY_ALPHA
from dplanner.theme.cards import over

# The two share plots are at least this tall and at most that; a tall window grows them
# in equal parts (:meth:`ProgressChart.panels`) and the milestone plot stays a row per
# milestone. The gaps and insets are the 4-point scale.
PANEL_HEIGHT = 112
MAX_PANEL_HEIGHT = 224
ROW_HEIGHT = 24
PANEL_GAP = 16
TITLE_GAP = 6
# Air over a plot's heading, so the bold names read as headings rather than as a caption
# stuck under the plot above.
TITLE_TOP = 12
BOTTOM_GUTTER = 22
LABEL_GAP = 6
RIGHT_INSET = 12
# A milestone name in the left gutter is elided past this, so one long name cannot
# push every plot to the right.
GUTTER_NAME_MAX = 120
# A milestone's name beside its landing on the progress line: elided past this, and set
# this far from the mark. A name with no room left by the one before it is dropped
# rather than drawn over it — the milestone plot below names every one of them.
LANDING_NAME_MAX = 90
LANDING_NAME_GAP = 6
# A milestone row's dates sit this far from the mark they belong to, and the line that
# drops from its landing to the axis wears its shade at this alpha.
DATE_GAP = 6
DROP_ALPHA = 90
# Air between two tick labels: a unit is offered only when every label has this much.
TICK_LABEL_GAP = 16
# The dataviz mark grammar: 2 px lines, a marker of at least 8 px ringed in the surface.
LINE_WIDTH = 2.0
MARKER = 8.0
RING = 2.0
LANDING_MARK = 6.0
ARROW_HEAD = 6.0
GRID_ALPHA = 28
# The change in the plan, by direction: work pulled in wears the attention amber, work
# that slipped the bad red, and a stretch the two plans agree on the good green — the
# window's tones (``theme/tones.py``), as a low-alpha region tint (DESIGN.md's deliberate
# exception #2) so the two curves stay what a reader measures against.
PULLED_TONE = QColor(220, 170, 90)
SLIPPED_TONE = QColor(220, 110, 110)
GOOD_TONE = QColor(120, 200, 140)
BAND_ALPHA = 56
# The baseline's shade: the colour pulled this far toward the ink, mixed opaque — enough
# to tell its dashes from the solid line they may ride on, on either theme.
BASELINE_INK_ALPHA = 110
LEGEND_KEY = 18
LEGEND_PATCH = 9  # A fill's key is a patch of it, not a line.
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
    """The whole plan as the three plots show it: the plan now, the plan on the basis day,
    what actually landed, and the stretches the lines run through. ``emphasis`` is the
    milestone held in full ink while the rest fades — None shows every stretch alike.

    ``basis_day`` is the day the plan is compared against — the project's start unless
    the reader picked another — and the one day the chart names. The baseline drawn for
    it is the nearest plan anybody recorded (``progress.baseline``); which record that
    was is bookkeeping, and ``dplanner progress show`` is where it is reported."""

    today: date
    expected: tuple[Point, ...] = ()
    actual: tuple[Point, ...] = ()
    baseline: tuple[Point, ...] = ()
    basis_day: date | None = None
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
    def compared(self) -> bool:
        """Whether a plan was recorded for the basis day to compare this one against."""
        return bool(self.baseline) or any(segment.then is not None for segment in self.segments)

    @property
    def emphasised(self) -> Segment | None:
        return next((s for s in self.segments if s.key == self.emphasis), None)

    def standing(self) -> float | None:
        """Actual against plan today, in share: positive ahead, negative behind — None
        when either line has nothing to say for today."""
        planned = share_at(self.expected, self.today)
        landed = share_at(self.actual, self.today)
        if planned is None or landed is None:
            return None
        return landed - planned


@dataclass(frozen=True)
class _Panel:
    kind: str  # "status", "scope" or "shift"
    rect: QRectF  # The plot area; the title band sits above it.


def segment_words(segment: Segment, basis_day: date | None, today: date) -> str:
    """A milestone row's sentence for a :class:`Segment` — ``progress.shift_words`` with
    the segment's own fields, so the window and the report word one move one way."""
    return shift_words(
        segment.label,
        segment.then[1] if segment.then else None,
        segment.now[1] if segment.now else None,
        basis_day,
        today,
    )


class ProgressChart(QWidget):
    """The three plots; the host hands it a :class:`ChartData`."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data: ChartData | None = None
        self._first = date.today()
        self._last = date.today()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self._bound_height()

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
        self._bound_height()
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
        """The plots top to bottom, each with its area — the third only with milestones.

        The two share plots take whatever height the host gave the widget over its
        minimum, in equal parts, and stop at ``MAX_PANEL_HEIGHT``: a taller window buys
        a line more room to say something, and past a point it only stretches two lines
        into a wall. The milestone plot is a row per milestone whatever the room.
        """
        left = self._left_gutter()
        width = self._plot_width()
        band = self._band_height()
        share = self._share_height()
        heights = [("status", share), ("scope", share)]
        rows = self._rows()
        if rows:
            heights.append(("shift", float(rows * ROW_HEIGHT)))
        found = []
        top = 0.0
        for kind, height in heights:
            found.append(_Panel(kind, QRectF(left, top + TITLE_TOP + band, width, height)))
            top += TITLE_TOP + band + height + PANEL_GAP
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
            was = share_at(data.baseline, when)
            if was is not None and data.basis_day is not None:
                lines.append(
                    f"plan at {format_date(data.basis_day, today=data.today)}: {was:.0%} {unit}"
                )
        planned = share_at(data.expected, when)
        if planned is not None:
            lines.append(f"plan now: {planned:.0%} {unit}")
        if any(start < when < end for start, end in data.idle):
            lines.append("no work planned")
        if kind == "status":
            landed = share_at(data.actual, when)
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

    def _rows(self) -> int:
        return len(self._data.milestones) if self._data is not None else 0

    def _title_font(self) -> QFont:
        """A plot's name is a heading, so it is set bold — measured with its own metrics,
        because a bold band is not always as tall as a plain one."""
        font = QFont(self.font())
        font.setBold(True)
        return font

    def _band_height(self) -> float:
        return QFontMetricsF(self._title_font()).height() + TITLE_GAP

    def _fixed_height(self) -> float:
        """Everything but the two share plots: the heading bands, the gaps between the
        plots, the milestone rows and the gutter the dates print in."""
        rows = self._rows()
        plots = 3 if rows else 2
        return (
            plots * (TITLE_TOP + self._band_height())
            + (plots - 1) * PANEL_GAP
            + rows * ROW_HEIGHT
            + BOTTOM_GUTTER
        )

    def compact_height(self) -> int:
        """The least the chart is legible in: both share plots on their floor."""
        return round(self._fixed_height() + 2 * PANEL_HEIGHT)

    def tall_height(self) -> int:
        """The most it takes: both share plots at their ceiling."""
        return round(self._fixed_height() + 2 * MAX_PANEL_HEIGHT)

    def _share_height(self) -> float:
        spare = max(0.0, float(self.height() - self.compact_height()))
        return min(float(MAX_PANEL_HEIGHT), PANEL_HEIGHT + spare / 2)

    def _bound_height(self) -> None:
        """What the host may give it, floor and ceiling — set from the data, never from a
        resize: a widget that resizes itself inside its own resize event loops a scroll
        area (see ``months.py``)."""
        self.setMinimumHeight(self.compact_height())
        self.setMaximumHeight(self.tall_height())

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
    def _tone(tone: QColor) -> QColor:
        """A fresh copy of a constant tone — a painter must never mutate the module's."""
        return QColor(tone)

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
        """The plan now in each stretch's shade with every landing marked and named, and
        what actually landed in ink — today's reading ringed, and worded beside it."""
        self._draw_plan(painter, panel, data, surface)
        self._draw_landings(painter, panel, data, ink)
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

    def landing_marks(self, panel: _Panel) -> tuple[tuple[Segment, str, QPointF], ...]:
        """Where each milestone lands on the plan line, and the name to print beside it.

        The line already changes shade at every landing; what it cannot say is *which*
        milestone that was, and a reader should not have to count rows in the plot below
        to find out. The name is elided past ``LANDING_NAME_MAX`` and comes back **empty**
        for a landing the name before it already reaches — two names squeezed together
        say less than one, and the milestone plot names every one of them anyway.
        """
        data = self._data
        if data is None:
            return ()
        metrics = self.fontMetrics()
        found: list[tuple[Segment, str, QPointF]] = []
        reached = panel.rect.left()
        for segment in data.milestones:
            if segment.now is None:
                continue
            when = segment.now[1]
            share = share_at(data.expected, when)
            if share is None:
                continue
            centre = QPointF(self._x(when), self._y(panel, share))
            name = metrics.elidedText(segment.label, Qt.TextElideMode.ElideRight, LANDING_NAME_MAX)
            left = centre.x() - metrics.horizontalAdvance(name) - LANDING_NAME_GAP
            if not name or left < reached:
                name = ""
            else:
                reached = centre.x() - LANDING_NAME_GAP
            found.append((segment, name, centre))
        return tuple(found)

    def _draw_landings(
        self, painter: QPainter, panel: _Panel, data: ChartData, ink: QColor
    ) -> None:
        """Each milestone's landing: a mark in its stretch's shade, with its name in
        secondary ink ending a gap short of the mark so the two read as one thing."""
        metrics = self.fontMetrics()  # the font :meth:`landing_marks` measured with
        secondary = QColor(ink)
        secondary.setAlpha(SECONDARY_ALPHA)
        for segment, name, centre in self.landing_marks(panel):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(segment.color)
            painter.drawEllipse(centre, LANDING_MARK / 2, LANDING_MARK / 2)
            if not name:
                continue
            width = metrics.horizontalAdvance(name) + 2
            # Above the mark, where a rising line leaves the room — and inside the plot
            # for a milestone that lands the whole thing at the top of it.
            top = max(panel.rect.top(), centre.y() - metrics.height() - LANDING_NAME_GAP)
            painter.setPen(secondary)
            painter.drawText(
                QRectF(centre.x() - width - LANDING_NAME_GAP, top, width, metrics.height()),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                name,
            )

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
        for sign, run in change_runs(data.expected, data.baseline):
            if sign == 0:
                same = QPainterPath(QPointF(self._x(run[0][0]), self._y(panel, run[0][1])))
                for when, high, _low in run[1:]:
                    same.lineTo(QPointF(self._x(when), self._y(panel, high)))
                self._draw_path(painter, same, self._tone(GOOD_TONE))
                continue
            band = QPainterPath(QPointF(self._x(run[0][0]), self._y(panel, run[0][1])))
            for when, high, _low in run[1:]:
                band.lineTo(QPointF(self._x(when), self._y(panel, high)))
            for when, _high, low in reversed(run):
                band.lineTo(QPointF(self._x(when), self._y(panel, low)))
            band.closeSubpath()
            wash = self._tone(PULLED_TONE if sign > 0 else SLIPPED_TONE)
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

    def row_dates(self, panel: _Panel) -> tuple[tuple[Segment, str, QRectF], ...]:
        """Every date the milestone plot prints, row by row: where the plan now lands the
        milestone, and — when it moved — where the plan at the basis day landed it.

        The axis under the plot places a mark to the nearest week or month; the shift a
        row draws is often a few days, and that is the size a reader wants in figures.
        A date is set beside its own mark, outside the pair when there is room and inside
        it otherwise, and is **left out rather than squeezed**: it needs to fall inside
        the plot and clear of the row's other mark. Nothing is lost when it goes — the
        row's tooltip says the move in words.
        """
        data = self._data
        if data is None:
            return ()
        metrics = self.fontMetrics()
        height = metrics.height()
        found: list[tuple[Segment, str, QRectF]] = []
        for index, segment in enumerate(data.milestones):
            y = self._row_y(panel, index)
            then = segment.then[1] if segment.then else None
            now = segment.now[1] if segment.now else None
            spots = [(now, then)] if now is not None else []
            if then is not None and then != now:
                spots.append((then, now))
            for when, other in spots:
                text = short_date(when, today=data.today)
                width = metrics.horizontalAdvance(text) + 2
                place = self._date_spot(panel, when, other, width)
                if place is not None:
                    found.append((segment, text, QRectF(place, y - height / 2, width, height)))
        return tuple(found)

    def _date_spot(
        self, panel: _Panel, when: date, other: date | None, width: float
    ) -> float | None:
        """Where a row's date starts: away from the row's other mark if there is room on
        that side, else on the near side, else nowhere. The clearance a mark keeps is its
        own radius and the gap every label here keeps."""
        mark = self._x(when)
        away = -1.0 if other is not None and self._x(other) > mark else 1.0
        for way in (away, -away):
            left = mark + MARKER / 2 + DATE_GAP if way > 0 else mark - MARKER / 2 - DATE_GAP - width
            if left < panel.rect.left() or left + width > panel.rect.right():
                continue
            if other is not None:
                keep = self._x(other)
                if (
                    left < keep + MARKER / 2 + DATE_GAP
                    and keep - MARKER / 2 - DATE_GAP < left + width
                ):
                    continue
            return left
        return None

    def _draw_shift(
        self, painter: QPainter, panel: _Panel, data: ChartData, ink: QColor, surface: QColor
    ) -> None:
        """A row per milestone: its name in the gutter (in secondary ink — a palette's
        darkest shade is not a text colour), a line dropping from where it lands to the
        axis, a hollow mark where the plan then landed it, a filled one where the plan
        now does, an arrow between them and the two dates beside them. Rows other than
        the picked one fade."""
        metrics = painter.fontMetrics()
        secondary = QColor(ink)
        secondary.setAlpha(SECONDARY_ALPHA)
        # The drops first, so every mark and every date is painted over them.
        for index, segment in enumerate(data.milestones):
            if segment.now is None:
                continue
            painter.setOpacity(self._row_opacity(data, segment))
            drop = QColor(segment.color)
            drop.setAlpha(DROP_ALPHA)
            painter.setPen(QPen(drop, 1.0))
            x = self._x(segment.now[1])
            painter.drawLine(QPointF(x, self._row_y(panel, index)), QPointF(x, panel.rect.bottom()))
        for index, segment in enumerate(data.milestones):
            y = self._row_y(panel, index)
            painter.setOpacity(self._row_opacity(data, segment))
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
        for segment, text, place in self.row_dates(panel):
            painter.setOpacity(self._row_opacity(data, segment))
            painter.setPen(secondary)
            painter.drawText(
                place, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text
            )
        painter.setOpacity(1.0)

    @staticmethod
    def _row_opacity(data: ChartData, segment: Segment) -> float:
        """Everything a row draws fades together when another milestone is picked."""
        return FADE if data.emphasis is not None and segment.key != data.emphasis else 1.0

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
        if data is None or data.basis_day is None:
            return "Scope change"
        return scope_words(data.basis_day, data.today, compared=data.compared)

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
            # The heading already names the day; a second date in the key would only
            # repeat it, and there is one plan then whatever record stood in for it.
            found = [("Plan then", "baseline")] if data.baseline else []
            return [*found, ("Plan now", "plan"), ("Pulled in", "pulled"), ("Slipped", "slipped")]
        return [("Then", "hollow"), ("Now", "filled")] if data.compared else []

    def _draw_title(
        self,
        painter: QPainter,
        panel: _Panel,
        data: ChartData,
        ink: QColor,
        surface: QColor,
        secondary: QColor,
    ) -> None:
        """The plot's name at the left of its band, in bold, and its keys at the right in
        the ordinary weight — the keys left out when the two would meet, and the tooltips
        still answer."""
        metrics = painter.fontMetrics()
        heading = QFontMetricsF(self._title_font())
        band = QRectF(
            panel.rect.left(),
            panel.rect.top() - TITLE_GAP - heading.height(),
            panel.rect.width(),
            heading.height(),
        )
        title = self.title(panel)
        painter.save()
        painter.setFont(self._title_font())
        painter.setPen(secondary)
        painter.drawText(band, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        painter.restore()
        entries = self.legend(panel)
        needed = sum(
            LEGEND_KEY + LEGEND_GAP + metrics.horizontalAdvance(label) + LEGEND_SPACING
            for label, _ in entries
        )
        if not entries or heading.horizontalAdvance(title) + LEGEND_SPACING + needed > band.width():
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
            if kind in ("pulled", "slipped"):
                # A fill is keyed by a patch of that fill, never a line of it.
                wash = self._tone(PULLED_TONE if kind == "pulled" else SLIPPED_TONE)
                wash.setAlpha(BAND_ALPHA)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(wash)
                painter.drawRect(QRectF(x, y - LEGEND_PATCH / 2, LEGEND_KEY, LEGEND_PATCH))
            elif kind in keys:
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
                    return segment_words(data.milestones[index], data.basis_day, data.today)
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


# DESIGN.md: dialogs get 20 px outer margins and 12 px between sections, and a big one
# claims the same slice of the screen the image preview and the text dialog claim.
DIALOG_MARGIN = 20
DIALOG_GAP = 12
SCREEN_SHARE = 0.8


class ChartDialog(QDialog):
    """The three plots, briefly in a window of their own.

    The same widget with the same data and more room — never a second rendering, so
    there is nothing that can drift: the host feeds it whatever it feeds the inline
    chart, and a plan that changes while the window is open redraws in both. It holds no
    state, so closing it loses nothing and there is nothing to confirm.
    """

    def __init__(self, data: ChartData | None, *, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.chart = ProgressChart(self)
        # The plots stop growing at their ceiling; with many milestones the rows can
        # still outrun a short screen, and then this scrolls rather than squeezing them.
        scroller = QScrollArea(self)
        scroller.setWidget(self.chart)
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        column = QVBoxLayout(self)
        column.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN)
        column.setSpacing(DIALOG_GAP)
        column.addWidget(scroller, 1)
        column.addWidget(buttons)
        self.show_data(data)
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.resize(
                round(available.width() * SCREEN_SHARE),
                round(available.height() * SCREEN_SHARE),
            )

    def show_data(self, data: ChartData | None) -> None:
        self.chart.show_data(data)
