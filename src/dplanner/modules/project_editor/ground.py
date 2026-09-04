"""The ground under the graph: the background the user chose, painted by name.

Which background — and whether a gesture snaps to the grid it shows — is the user's
:class:`~dplanner.modules.project_editor.look.Look`; this file is the painter. Nothing the
CLI writes is snapped, because a verb has no gesture to snap.

**What is drawn is a coarsening of what snaps.** A gesture lands on ``positions.GRID``;
the ground shows every ``pitch_for(zoom)``-th line of it — the smallest power-of-two
multiple that keeps the dots a readable distance apart on screen — so a card's corner is
always on a line the ground *could* show, and zooming in reveals the finer ones rather
than a grid that drifts against the cards.
"""

from math import floor

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QPolygonF

from dplanner.modules.project_editor.positions import GRID

# How close two grid marks may come on screen before the ground steps up to the next
# coarser pitch: at 24 device pixels a dot grid still reads as a grid, not as a texture.
MIN_SCREEN_PITCH = 24.0
# Every this-many lines of the line grid is drawn a shade stronger — graph paper's rule.
MAJOR_EVERY = 4

# Ink on the canvas at low alpha: theme-independent by construction (DESIGN.md exception
# #1), and quiet enough that a card's shadow is still the darkest thing on the ground.
DOT_ALPHA = 52
LINE_ALPHA = 18
MAJOR_LINE_ALPHA = 32
CROSS_ALPHA = 46
# Device pixels: a dot's diameter, a line's width and a cross's arm, the same at any zoom.
DOT_SIZE = 2.0
LINE_WIDTH = 1.0
CROSS_ARM = 3.0


def pitch_for(zoom: float) -> float:
    """The grid pitch to draw at this zoom, in scene units.

    The smallest power-of-two multiple of :data:`GRID` that lands its marks at least
    :data:`MIN_SCREEN_PITCH` device pixels apart — so the ground never turns into noise
    zoomed out, and zooming in shows the finer grid the gestures were snapping to all along.
    """
    pitch = GRID
    while pitch * max(zoom, 1e-6) < MIN_SCREEN_PITCH:
        pitch *= 2
    return pitch


def paint_ground(
    painter: QPainter, rect: QRectF, palette: QPalette, background: str, zoom: float
) -> None:
    """Draw ``background`` (a ``look.BACKGROUNDS`` name) over ``rect`` — the part of the
    plane a view is showing.

    Cosmetic pens throughout: a dot is two device pixels and a line one whatever the zoom,
    which is what keeps the ground a texture rather than a drawing that scales with the
    graph. The lines are drawn without antialiasing so a hairline lands on one pixel
    column instead of two grey ones; dots and crosses keep it, since a round dot wants it.
    """
    if background == "none":
        return
    pitch = pitch_for(zoom)
    ink = QColor(palette.text().color())
    first_x = floor(rect.left() / pitch) * pitch
    first_y = floor(rect.top() / pitch) * pitch
    xs = [first_x + step * pitch for step in range(int((rect.right() - first_x) / pitch) + 2)]
    ys = [first_y + step * pitch for step in range(int((rect.bottom() - first_y) / pitch) + 2)]

    painter.save()
    if background == "dots":
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(_pen(ink, DOT_ALPHA, DOT_SIZE, round_cap=True))
        painter.drawPoints(QPolygonF([QPointF(x, y) for x in xs for y in ys]))
    elif background == "lines":
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        major = pitch * MAJOR_EVERY
        for alpha, wanted in ((LINE_ALPHA, False), (MAJOR_LINE_ALPHA, True)):
            painter.setPen(_pen(ink, alpha, LINE_WIDTH))
            painter.drawLines(
                [QLineF(x, rect.top(), x, rect.bottom()) for x in xs if (x % major == 0) == wanted]
                + [
                    QLineF(rect.left(), y, rect.right(), y)
                    for y in ys
                    if (y % major == 0) == wanted
                ]
            )
    elif background == "crosses":
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        arm = CROSS_ARM / max(zoom, 1e-6)
        painter.setPen(_pen(ink, CROSS_ALPHA, LINE_WIDTH))
        painter.drawLines(
            [QLineF(x - arm, y, x + arm, y) for x in xs for y in ys]
            + [QLineF(x, y - arm, x, y + arm) for x in xs for y in ys]
        )
    painter.restore()


def _pen(ink: QColor, alpha: int, width: float, round_cap: bool = False) -> QPen:
    colour = QColor(ink)
    colour.setAlpha(alpha)
    pen = QPen(colour, width)
    pen.setCosmetic(True)
    if round_cap:
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    return pen
