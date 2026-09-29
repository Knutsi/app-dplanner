"""The ruler over Wave view: what each column is, and when its work runs.

Wave view stands every card in the column of its dependency depth
(``sorts.arranged_in_waves``). This band across the top of the canvas names each column —
START, then WAVE 2, WAVE 3…, numbered as the Order tab numbers waves — and says when its work
runs, from its earliest start to its latest finish, and, once any of it is, how much is done.

**Chrome, pinned to the view like the minimap** (``DESIGN.md``'s *Overlays on a canvas*): a
child of the view, never of the viewport, so a pan cannot carry it off. It follows the plane
across — a heading stands over its column at every scroll and zoom — and never down.

**The canvas pushes; the ruler never pulls.** It is handed headings and holds no scene, so a
test drives it with a list, and it cannot outlive what it describes.
"""

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QGraphicsView, QWidget

from dplanner.modules.project_editor.sorts import Wave
from dplanner.theme.cards import detail_font
from dplanner.theme.fonts import mono_font
from dplanner.theme.tokens import SECONDARY_ALPHA
from dplanner.theme.tones import STATUS_TONES

RULER_H = 36
# $BG_BASE at about 72 % over the ground: cards pass under the ruler and are still seen.
GROUND_ALPHA = 184
# Between one part of a heading and the next, and before the next column's heading.
PART_GAP = 8.0


@dataclass(frozen=True)
class Heading:
    """One column's heading: where the column stands on the plane, and what it says."""

    left: float
    right: float
    label: str
    span: str
    done: str  # "4 of 5 done" — empty while none of it is.


def heading(wave: Wave, done: int) -> Heading:
    """A wave's heading, given how many of its steps are done."""
    words = f"{done} of {len(wave.steps)} done" if done else ""
    return Heading(wave.left, wave.right, wave.label, wave.span, words)


class WaveRuler(QWidget):
    """The band of column headings across the top of the canvas, in Wave view alone."""

    def __init__(self, view: QGraphicsView) -> None:
        # Parented to the view and raised over its viewport, for the minimap's reason: a
        # child of the viewport is moved by every pan.
        super().__init__(view)
        self.setObjectName("WaveRuler")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedHeight(RULER_H)
        self.raise_()
        self._view = view
        self._headings: tuple[Heading, ...] = ()
        self.hide()

    def show_headings(self, headings: Sequence[Heading]) -> None:
        """Say these; none takes the ruler off screen."""
        self._headings = tuple(headings)
        self.setVisible(bool(self._headings))
        self.update()

    def headings(self) -> tuple[Heading, ...]:
        """What the ruler is saying — how a test reads it."""
        return self._headings

    def place(self) -> None:
        """Span the top of the canvas. Called when the view is resized."""
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(0, 0, parent.width(), RULER_H)

    # -- painting ------------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = self.palette()
        ground = QColor(palette.window().color())
        ground.setAlpha(GROUND_ALPHA)
        painter.fillRect(self.rect(), ground)
        painter.setPen(QPen(palette.mid().color(), 1.0))  # $BORDER, the seam under it.
        painter.drawLine(QPointF(0.0, RULER_H - 0.5), QPointF(self.width(), RULER_H - 0.5))

        label_font = detail_font(self.font())
        label_font.setBold(True)
        span_font = mono_font(label_font.pointSizeF() if label_font.pointSizeF() > 0 else 10.0)
        ink = QColor(palette.text().color())
        quiet = QColor(ink)
        quiet.setAlpha(SECONDARY_ALPHA)
        parts = (
            (label_font, ink),
            (span_font, quiet),
            (detail_font(self.font()), STATUS_TONES["good"]),
        )

        # Only the headings over the plane in view: a long chain is hundreds of waves.
        start, stop = self._in_view()
        for index in range(start, stop):
            found = self._headings[index]
            left = self._across(found.left)
            following = index + 1 < len(self._headings)
            limit = (
                self._across(self._headings[index + 1].left) - PART_GAP
                if following
                else self.width()
            )
            x = left
            said = (found.label, found.span, found.done)
            for text, (font, colour) in zip(said, parts, strict=True):
                if not text:
                    continue
                width = QFontMetricsF(font).horizontalAdvance(text)
                if x + width > limit:
                    break  # What does not fit is dropped from the end: done, then the span.
                self._draw(painter, text, font, colour, x, width)
                x += width + PART_GAP

    def _in_view(self) -> tuple[int, int]:
        """The headings whose columns the view shows some of, as a range — they are in
        order across, so two bisections find it."""
        left = self._view.mapToScene(QPoint(0, 0)).x()
        right = self._view.mapToScene(QPoint(self.width(), 0)).x()
        rights = [h.right for h in self._headings]
        lefts = [h.left for h in self._headings]
        return bisect_left(rights, left), bisect_right(lefts, right)

    def _across(self, plane_x: float) -> float:
        """Where a point of the plane is, across the ruler — the view's own mapping."""
        return float(self._view.mapFromScene(QPointF(plane_x, 0.0)).x())

    def _draw(
        self, painter: QPainter, text: str, font: QFont, colour: QColor, x: float, width: float
    ) -> None:
        painter.setFont(font)
        painter.setPen(colour)
        box = QRectF(x, 0.0, width, RULER_H)
        painter.drawText(box, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
