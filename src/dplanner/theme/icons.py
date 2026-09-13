"""Tiny painted icons for segment kinds, editor modes and toolbar verbs.

Painted with QPainter instead of bundled SVGs: a handful of glyphs do not justify a
resource pipeline, and taking the colour as a parameter lets the same glyph read on the
dark binder and the light corkboard cards alike.
"""

from collections.abc import Callable

from PySide6.QtCore import QLineF, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)

from dplanner.theme.palettes import Palette

ICON_SIZE = 16
# A glyph nobody is pointing at is present without asking to be read.
IDLE_GLYPH_ALPHA = 110


def _canvas() -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(QSize(ICON_SIZE, ICON_SIZE))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    return pixmap, painter


def container_icon(color: str) -> QIcon:
    """A stack of index cards: a segment with children."""
    pixmap, painter = _canvas()
    pen = QPen(QColor(color), 1.2)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(4.5, 2.5, 9.0, 7.0), 1.5, 1.5)
    painter.drawRoundedRect(QRectF(2.5, 6.5, 9.0, 7.0), 1.5, 1.5)
    painter.end()
    return QIcon(pixmap)


def _pen(color: str | QColor, width: float) -> QPen:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def edit_icon(color: str | QColor) -> QIcon:
    """A pencil: normal editing."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(3.0, 13.0),
                QPointF(3.8, 10.2),
                QPointF(10.8, 3.2),
                QPointF(12.8, 5.2),
                QPointF(5.8, 12.2),
            ]
        )
    )
    painter.drawLine(QPointF(9.8, 4.2), QPointF(11.8, 6.2))  # The metal ferrule.
    painter.end()
    return QIcon(pixmap)


def typewriter_icon(color: str) -> QIcon:
    """Text lines with the middle one held wide: the centred typing line."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.drawLine(QPointF(4.5, 4.5), QPointF(11.5, 4.5))
    painter.setPen(_pen(color, 2.2))
    painter.drawLine(QPointF(2.5, 8.0), QPointF(13.5, 8.0))
    painter.setPen(_pen(color, 1.2))
    painter.drawLine(QPointF(4.5, 11.5), QPointF(11.5, 11.5))
    painter.end()
    return QIcon(pixmap)


def coverage_icon(color: str | QColor) -> QIcon:
    """Three dots joined by a line — a passage, a feature, what became of it."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.4))
    painter.drawLine(QPointF(3.5, 12.5), QPointF(8.0, 8.0))
    painter.drawLine(QPointF(8.0, 8.0), QPointF(12.5, 3.5))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    for centre in (QPointF(3.5, 12.5), QPointF(8.0, 8.0), QPointF(12.5, 3.5)):
        painter.drawEllipse(centre, 2.2, 2.2)
    painter.end()
    return QIcon(pixmap)


def read_icon(color: str | QColor) -> QIcon:
    """An open book: reading mode."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPolyline(
        QPolygonF(
            [
                QPointF(8.0, 4.5),
                QPointF(6.5, 3.3),
                QPointF(2.5, 3.3),
                QPointF(2.5, 12.0),
                QPointF(6.5, 12.0),
                QPointF(8.0, 13.0),
            ]
        )
    )
    painter.drawPolyline(
        QPolygonF(
            [
                QPointF(8.0, 4.5),
                QPointF(9.5, 3.3),
                QPointF(13.5, 3.3),
                QPointF(13.5, 12.0),
                QPointF(9.5, 12.0),
                QPointF(8.0, 13.0),
            ]
        )
    )
    painter.drawLine(QPointF(8.0, 4.5), QPointF(8.0, 13.0))  # The spine.
    painter.end()
    return QIcon(pixmap)


def external_icon(color: str) -> QIcon:
    """An arrow leaving a box through its open corner: open outside the application."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    # The box, open at the top-right.
    painter.drawPolyline(
        QPolygonF(
            [
                QPointF(7.0, 3.5),
                QPointF(3.0, 3.5),
                QPointF(3.0, 13.0),
                QPointF(12.5, 13.0),
                QPointF(12.5, 9.0),
            ]
        )
    )
    # The arrow out through the corner.
    painter.drawLine(QPointF(7.5, 8.5), QPointF(13.0, 3.0))
    painter.drawLine(QPointF(9.4, 3.0), QPointF(13.0, 3.0))
    painter.drawLine(QPointF(13.0, 6.6), QPointF(13.0, 3.0))
    painter.end()
    return QIcon(pixmap)


def leaf_icon(color: str) -> QIcon:
    """A single page with text lines: a segment without children."""
    pixmap, painter = _canvas()
    pen = QPen(QColor(color), 1.2)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(3.5, 2.0, 9.0, 12.0), 1.5, 1.5)
    for y in (5.5, 8.0, 10.5):
        painter.drawLine(QRectF(5.5, y, 5.0, 0.0).topLeft(), QRectF(5.5, y, 5.0, 0.0).topRight())
    painter.end()
    return QIcon(pixmap)


def project_icon(color: str) -> QIcon:
    """A card holding a tiny two-node graph: a project row in the index."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(2.5, 3.0, 11.0, 10.0), 1.5, 1.5)
    painter.drawLine(QPointF(6.6, 6.7), QPointF(9.4, 9.3))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(QPointF(5.5, 5.8), 1.5, 1.5)
    painter.drawEllipse(QPointF(10.5, 10.2), 1.5, 1.5)
    painter.end()
    return QIcon(pixmap)


def graph_icon(color: str | QColor) -> QIcon:
    """Three joined nodes: a project's step graph."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.drawLine(QPointF(4.5, 4.5), QPointF(11.5, 4.5))
    painter.drawLine(QPointF(4.5, 4.5), QPointF(8.0, 11.5))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(QPointF(4.5, 4.5), 1.8, 1.8)
    painter.drawEllipse(QPointF(11.5, 4.5), 1.8, 1.8)
    painter.drawEllipse(QPointF(8.0, 11.5), 1.8, 1.8)
    painter.end()
    return QIcon(pixmap)


def spec_icon(color: str) -> QIcon:
    """A page with a check over its lower lines: a specification with marked requirements."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(3.5, 2.0, 9.0, 12.0), 1.5, 1.5)
    painter.drawLine(QPointF(5.5, 5.0), QPointF(10.5, 5.0))
    painter.drawLine(QPointF(5.5, 7.5), QPointF(10.5, 7.5))
    painter.setPen(_pen(color, 1.5))
    painter.drawPolyline(QPolygonF([QPointF(5.5, 10.5), QPointF(7.2, 12.2), QPointF(10.5, 8.8)]))
    painter.end()
    return QIcon(pixmap)


def folder_icon(color: str) -> QIcon:
    """A folder: the workspace directory."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(2.5, 5.0, 11.0, 7.5), 1.5, 1.5)
    painter.drawPolyline(
        QPolygonF([QPointF(2.5, 5.0), QPointF(3.2, 3.5), QPointF(7.0, 3.5), QPointF(8.2, 5.0)])
    )
    painter.end()
    return QIcon(pixmap)


def branch_icon(color: str | QColor) -> QIcon:
    """A git branch: trunk with two nodes, one forked off."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(4.5, 3.5), 1.8, 1.8)
    painter.drawEllipse(QPointF(4.5, 12.5), 1.8, 1.8)
    painter.drawEllipse(QPointF(11.5, 4.5), 1.8, 1.8)
    painter.drawLine(QPointF(4.5, 5.3), QPointF(4.5, 10.7))
    fork = QPainterPath(QPointF(11.5, 6.3))
    fork.cubicTo(QPointF(11.5, 9.2), QPointF(4.5, 8.2), QPointF(4.5, 10.2))
    painter.drawPath(fork)
    painter.end()
    return QIcon(pixmap)


# -- canvas toolbar --------------------------------------------------------------------------
#
# One glyph per action id the graph editor's toolbar carries. They live here with the rest
# rather than in the module because the colour parameter is the theme's, and the theme is what
# repaints them.


def plus_icon(color: str | QColor) -> QIcon:
    """A plus: add a step, or an aspect. ``_pen`` takes either, so callers with a palette
    colour in hand need not stringify it."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.6))
    painter.drawLine(QPointF(8.0, 3.5), QPointF(8.0, 12.5))
    painter.drawLine(QPointF(3.5, 8.0), QPointF(12.5, 8.0))
    painter.end()
    return QIcon(pixmap)


def trash_icon(color: str | QColor) -> QIcon:
    """A waste basket: delete."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(QPointF(2.8, 4.5), QPointF(13.2, 4.5))
    painter.drawPolyline(
        QPolygonF(
            [
                QPointF(4.2, 4.5),
                QPointF(4.9, 13.2),
                QPointF(11.1, 13.2),
                QPointF(11.8, 4.5),
            ]
        )
    )
    painter.drawPolyline(
        QPolygonF([QPointF(6.2, 4.5), QPointF(6.5, 2.8), QPointF(9.5, 2.8), QPointF(9.8, 4.5)])
    )
    painter.end()
    return QIcon(pixmap)


def unlink_icon(color: str | QColor) -> QIcon:
    """The same two nodes with the join broken: remove a link."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(3.6, 8.0), 2.2, 2.2)
    painter.drawEllipse(QPointF(12.4, 8.0), 2.2, 2.2)
    painter.drawLine(QPointF(5.8, 8.0), QPointF(7.0, 8.0))
    painter.drawLine(QPointF(9.0, 8.0), QPointF(10.2, 8.0))
    painter.drawLine(QPointF(7.4, 10.0), QPointF(8.6, 6.0))
    painter.end()
    return QIcon(pixmap)


def lasso_icon(color: str | QColor) -> QIcon:
    """A loop with its rope trailing off: draw round the steps to pick."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.3))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    loop = QPainterPath(QPointF(8.0, 3.0))
    loop.cubicTo(QPointF(14.0, 3.0), QPointF(14.0, 10.5), QPointF(8.0, 10.5))
    loop.cubicTo(QPointF(2.0, 10.5), QPointF(2.0, 3.0), QPointF(8.0, 3.0))
    painter.drawPath(loop)
    tail = QPainterPath(QPointF(5.2, 9.8))
    tail.cubicTo(QPointF(4.2, 11.8), QPointF(6.8, 12.2), QPointF(5.6, 14.2))
    painter.drawPath(tail)
    painter.end()
    return QIcon(pixmap)


def isolate_icon(color: str | QColor) -> QIcon:
    """One node with the joins on both sides cut: cut a selection loose."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(5.0, 5.0, 6.0, 6.0), 1.5, 1.5)
    for x in (1.0, 12.0):
        painter.drawLine(QPointF(x, 8.0), QPointF(x + 1.6, 8.0))
        painter.drawLine(QPointF(x + 1.4, 10.4), QPointF(x + 2.6, 5.6))
    painter.end()
    return QIcon(pixmap)


def _arrow(painter: QPainter, start: QPointF, end: QPointF, head: float = 3.4) -> None:
    """A line with a chevron at ``end``: what every "goes there" glyph is made of."""
    painter.drawLine(start, end)
    back = QLineF(end, start)
    for turn in (-26.0, 26.0):
        wing = QLineF(back)
        wing.setAngle(back.angle() + turn)
        wing.setLength(head)
        painter.drawLine(wing.p1(), wing.p2())


def link_icon(color: str | QColor) -> QIcon:
    """Two nodes joined: ``unlink_icon`` without the cut."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(3.6, 8.0), 2.2, 2.2)
    painter.drawEllipse(QPointF(12.4, 8.0), 2.2, 2.2)
    painter.drawLine(QPointF(5.8, 8.0), QPointF(10.2, 8.0))
    painter.end()
    return QIcon(pixmap)


def connect_icon(color: str | QColor) -> QIcon:
    """An arrow being drawn from one node to another: the linking mode."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(3.4, 8.0), 2.2, 2.2)
    painter.drawEllipse(QPointF(12.6, 8.0), 2.2, 2.2)
    _arrow(painter, QPointF(6.0, 8.0), QPointF(10.0, 8.0))
    painter.end()
    return QIcon(pixmap)


def redirect_to_icon(color: str | QColor) -> QIcon:
    """Arrows converging on one node: the picked links come to point here."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(12.6, 8.0), 2.2, 2.2)
    _arrow(painter, QPointF(1.8, 3.0), QPointF(9.6, 6.6))
    _arrow(painter, QPointF(1.8, 13.0), QPointF(9.6, 9.4))
    painter.end()
    return QIcon(pixmap)


def redirect_from_icon(color: str | QColor) -> QIcon:
    """The same arrows fanning out of one node: the picked links come to start here."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(3.4, 8.0), 2.2, 2.2)
    _arrow(painter, QPointF(6.4, 6.6), QPointF(14.2, 3.0))
    _arrow(painter, QPointF(6.4, 9.4), QPointF(14.2, 13.0))
    painter.end()
    return QIcon(pixmap)


def _divide_icon(color: str | QColor, upright: bool) -> QIcon:
    pixmap, painter = _canvas()
    if not upright:
        painter.translate(ICON_SIZE, 0.0)
        painter.rotate(90.0)
    dashes = _pen(color, 1.1)
    dashes.setStyle(Qt.PenStyle.DashLine)
    painter.setPen(dashes)
    painter.drawLine(QPointF(8.0, 1.4), QPointF(8.0, 14.6))
    painter.setPen(_pen(color, 1.2))
    _arrow(painter, QPointF(6.2, 8.0), QPointF(2.2, 8.0))
    _arrow(painter, QPointF(9.8, 8.0), QPointF(13.8, 8.0))
    painter.end()
    return QIcon(pixmap)


def divide_vertical_icon(color: str | QColor) -> QIcon:
    """An upright cut with the two sides pushed apart: make room left or right."""
    return _divide_icon(color, upright=True)


def divide_horizontal_icon(color: str | QColor) -> QIcon:
    """The same cut on its side: make room above or below."""
    return _divide_icon(color, upright=False)


def sort_icon(color: str | QColor) -> QIcon:
    """Two feeders and what they lead to: laying the graph out by dependency."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(1.5, 2.0, 4.6, 3.6), 1.0, 1.0)
    painter.drawRoundedRect(QRectF(1.5, 10.4, 4.6, 3.6), 1.0, 1.0)
    painter.drawRoundedRect(QRectF(9.9, 6.2, 4.6, 3.6), 1.0, 1.0)
    painter.drawLine(QPointF(6.1, 3.8), QPointF(9.9, 7.2))
    painter.drawLine(QPointF(6.1, 12.2), QPointF(9.9, 8.8))
    painter.end()
    return QIcon(pixmap)


def region_icon(color: str | QColor) -> QIcon:
    """A titled area drawn behind the graph."""
    pixmap, painter = _canvas()
    dashes = _pen(color, 1.2)
    dashes.setStyle(Qt.PenStyle.DashLine)
    painter.setPen(dashes)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(2.0, 4.0, 12.0, 9.5), 1.5, 1.5)
    painter.setPen(_pen(color, 1.4))
    painter.drawLine(QPointF(2.4, 2.4), QPointF(7.6, 2.4))
    painter.end()
    return QIcon(pixmap)


def grid_icon(color: str | QColor) -> QIcon:
    """Ruled lines: what a drag, a resize and a placed card land on."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.1))
    for at in (5.5, 10.5):
        painter.drawLine(QPointF(at, 2.0), QPointF(at, 14.0))
        painter.drawLine(QPointF(2.0, at), QPointF(14.0, at))
    painter.end()
    return QIcon(pixmap)


def undo_icon(color: str | QColor) -> QIcon:
    """An arrow curving back on itself, anticlockwise."""
    return _turn_icon(color, mirrored=False)


def redo_icon(color: str | QColor) -> QIcon:
    """The same arrow the other way round."""
    return _turn_icon(color, mirrored=True)


def _turn_icon(color: str | QColor, mirrored: bool) -> QIcon:
    pixmap, painter = _canvas()
    if mirrored:
        painter.translate(ICON_SIZE, 0.0)
        painter.scale(-1.0, 1.0)
    painter.setPen(_pen(color, 1.4))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRectF(3.0, 4.5, 10.0, 8.0), 20 * 16, 160 * 16)
    painter.drawPolyline(QPolygonF([QPointF(2.4, 3.2), QPointF(3.0, 7.0), QPointF(6.8, 6.4)]))
    painter.end()
    return QIcon(pixmap)


def frame_icon(color: str | QColor) -> QIcon:
    """Four corners: fit the whole graph in the window."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.4))
    for x_from, x_to, y_from, y_to in (
        (3.0, 6.0, 3.0, 6.0),
        (13.0, 10.0, 3.0, 6.0),
        (3.0, 6.0, 13.0, 10.0),
        (13.0, 10.0, 13.0, 10.0),
    ):
        painter.drawLine(QPointF(x_from, y_from), QPointF(x_to, y_from))
        painter.drawLine(QPointF(x_from, y_from), QPointF(x_from, y_to))
    painter.end()
    return QIcon(pixmap)


def refresh_icon(color: str | QColor) -> QIcon:
    """A circular arrow: run the rebuild again, now."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.6))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRectF(3.0, 3.0, 10.0, 10.0), 40 * 16, 280 * 16)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawPolygon([QPointF(13.5, 3.0), QPointF(13.5, 8.0), QPointF(9.5, 5.0)])
    painter.end()
    return QIcon(pixmap)


def jump_icon(color: str | QColor) -> QIcon:
    """A crosshair: name a step and put the viewport on it."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.3))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(8.0, 8.0), 4.0, 4.0)
    for start, end in (
        (QPointF(8.0, 1.6), QPointF(8.0, 3.4)),
        (QPointF(8.0, 12.6), QPointF(8.0, 14.4)),
        (QPointF(1.6, 8.0), QPointF(3.4, 8.0)),
        (QPointF(12.6, 8.0), QPointF(14.4, 8.0)),
    ):
        painter.drawLine(start, end)
    painter.end()
    return QIcon(pixmap)


def options_icon(color: str | QColor) -> QIcon:
    """Two sliders: how the graph is drawn, rather than what is drawn."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.3))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for rail, knob in ((5.0, 10.0), (11.0, 6.0)):
        painter.drawLine(QPointF(2.0, rail), QPointF(14.0, rail))
        painter.drawEllipse(QPointF(knob, rail), 1.9, 1.9)
    painter.end()
    return QIcon(pixmap)


def mark_starts_icon(color: str | QColor) -> QIcon:
    """A bar with the flow leaving it: a step nothing comes before."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.4))
    painter.drawLine(QPointF(2.6, 3.0), QPointF(2.6, 13.0))
    painter.setPen(_pen(color, 1.2))
    _arrow(painter, QPointF(5.0, 8.0), QPointF(13.4, 8.0))
    painter.end()
    return QIcon(pixmap)


def mark_ends_icon(color: str | QColor) -> QIcon:
    """The flow arriving at a bar: a step nothing comes after."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    _arrow(painter, QPointF(2.6, 8.0), QPointF(11.0, 8.0))
    painter.setPen(_pen(color, 1.4))
    painter.drawLine(QPointF(13.4, 3.0), QPointF(13.4, 13.0))
    painter.end()
    return QIcon(pixmap)


def mark_orphans_icon(color: str | QColor) -> QIcon:
    """A node ringed and joined to nothing: the one thing a graph can be wrong about."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(5.4, 5.4, 5.2, 5.2), 1.2, 1.2)
    ring = _pen(color, 1.2)
    ring.setStyle(Qt.PenStyle.DotLine)
    painter.setPen(ring)
    painter.drawEllipse(QPointF(8.0, 8.0), 6.3, 6.3)
    painter.end()
    return QIcon(pixmap)


def blank_icon(_color: str | QColor) -> QIcon:
    """No glyph, but the slot: a verb whose spec carries no painter must not jump the row."""
    return QIcon()


# A step's key as a badge — the width a three-character key needs at a glyph's height.
KEY_BADGE_W = 28
KEY_BADGE_ALPHA = 44  # The tone washed under the letters; the border and the ink at full.
KEY_BADGE_POINTS = 7.5


def key_badge_icon(text: str, color: str | QColor) -> QIcon:
    """``F1``, ``M2`` as a rounded chip in a tone: a glyph that names the step.

    Where a row is a milestone the badge stands where the glyph would — the key is what a
    milestone is known by across the graph, and a tag glyph beside a key on the second
    line said the same thing twice.
    """
    pixmap = QPixmap(KEY_BADGE_W, ICON_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    tone = QColor(color)
    wash = QColor(tone)
    wash.setAlpha(KEY_BADGE_ALPHA)
    painter.setPen(_pen(tone, 1.0))
    painter.setBrush(wash)
    painter.drawRoundedRect(QRectF(0.5, 0.5, KEY_BADGE_W - 1.0, ICON_SIZE - 1.0), 4.0, 4.0)
    font = painter.font()
    font.setPointSizeF(KEY_BADGE_POINTS)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(tone)
    painter.drawText(QRectF(0.0, 0.0, KEY_BADGE_W, ICON_SIZE), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return QIcon(pixmap)


# A colour map as a strip: wide enough to read the ramp, short enough to sit in a menu row.
PALETTE_STRIP = QSize(56, 12)
PALETTE_STRIP_RADIUS = 3


def palette_strip_icon(found: Palette, size: QSize = PALETTE_STRIP) -> QIcon:
    """A milestone colour map as a strip, dark to light — the map before it is dealt.

    The Time tab's picker and the command palette both show it, which is why it lives here
    rather than beside either of them: one painter, so the two surfaces cannot draw the same
    map differently. ``size`` is the caller's because the two want different shapes — a wide
    strip in a combo row, a square at :data:`ICON_SIZE` in a list of glyphs — and a wide
    pixmap scaled into a square slot renders as a sliver.
    """
    pixmap = QPixmap(size)
    pixmap.fill(Qt.GlobalColor.transparent)
    gradient = QLinearGradient(QPointF(0, 0), QPointF(size.width(), 0))
    last = len(found.stops) - 1
    for index, stop in enumerate(found.stops):
        gradient.setColorAt(index / last, QColor(stop))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(
        QRectF(0, 0, size.width(), size.height()),
        PALETTE_STRIP_RADIUS,
        PALETTE_STRIP_RADIUS,
    )
    painter.end()
    return QIcon(pixmap)


SPINNER_FRAMES = 12  # One turn: a frame every 30°, so the arc reads as turning, not jumping.


def spinner_frames(color: str | QColor, count: int = SPINNER_FRAMES) -> list[QIcon]:
    """A three-quarter arc at ``count`` rotations: the glyph of a button whose work is
    running. Painted once per ink and stepped by ``framework/signalling.py``'s Spinner."""
    frames = []
    for step in range(count):
        pixmap, painter = _canvas()
        painter.setPen(_pen(color, 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        start = (90 - step * 360 // count) * 16
        painter.drawArc(QRectF(2.5, 2.5, 11.0, 11.0), start, -270 * 16)
        painter.end()
        frames.append(QIcon(pixmap))
    return frames


FILTER_ICON_W = 24  # A dot's slot at the left, then the funnel: one width, on or off.


def filter_icon(color: str | QColor, *, active: bool = False) -> QIcon:
    """A funnel with a slot for the indicator before it: outline while no filter is on,
    filled with a dot in the slot while one is — so the face never changes size."""
    pixmap = QPixmap(QSize(FILTER_ICON_W, ICON_SIZE))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    left = FILTER_ICON_W - ICON_SIZE
    funnel = [
        QPointF(left + 2.5, 3.5),
        QPointF(left + 13.5, 3.5),
        QPointF(left + 9.5, 8.5),
        QPointF(left + 9.5, 13.0),
        QPointF(left + 6.5, 11.5),
        QPointF(left + 6.5, 8.5),
    ]
    painter.setPen(_pen(color, 1.5))
    painter.setBrush(QColor(color) if active else Qt.BrushStyle.NoBrush)
    painter.drawPolygon(funnel)
    if active:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(QRectF(1.0, 5.5, 5.0, 5.0))
    painter.end()
    return QIcon(pixmap)


def close_icon(color: str) -> QIcon:
    """A cross: the close button on a tab.

    Two pixmaps rather than one because Qt asks for the ``Disabled`` variant whenever the
    button is neither hovered nor on the current tab, and the variant it generates for
    itself is greyscale — the one colour a theme cannot reach.
    """
    icon = QIcon()
    icon.addPixmap(_cross(color, 255), QIcon.Mode.Normal)
    icon.addPixmap(_cross(color, IDLE_GLYPH_ALPHA), QIcon.Mode.Disabled)
    return icon


def _cross(color: str, alpha: int) -> QPixmap:
    tint = QColor(color)
    tint.setAlpha(alpha)
    pixmap, painter = _canvas()
    painter.setPen(_pen(tint, 1.4))
    painter.drawLine(QPointF(4.6, 4.6), QPointF(11.4, 11.4))
    painter.drawLine(QPointF(11.4, 4.6), QPointF(4.6, 11.4))
    painter.end()
    return pixmap


def gauge_icon(color: str | QColor) -> QIcon:
    """A dial with its needle past halfway: the progression board."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.4))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    # The dial: an arc open at the bottom.
    painter.drawArc(QRectF(2.5, 3.0, 11.0, 11.0), -30 * 16, 240 * 16)
    # The needle, pointing up-right.
    painter.drawLine(QPointF(8.0, 8.5), QPointF(11.2, 5.3))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(QPointF(8.0, 8.5), 1.3, 1.3)
    painter.end()
    return QIcon(pixmap)


def clock_icon(color: str) -> QIcon:
    """A clock face reading shortly before ten past ten: the time estimates."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.4))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QRectF(2.5, 2.5, 11.0, 11.0))
    painter.drawLine(QPointF(8.0, 8.0), QPointF(8.0, 4.5))
    painter.drawLine(QPointF(8.0, 8.0), QPointF(10.8, 9.6))
    painter.end()
    return QIcon(pixmap)


def image_icon(color: str) -> QIcon:
    """A framed picture — sun over a hillside: the project's assets."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.4))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(2.5, 3.0, 11.0, 10.0), 1.5, 1.5)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(QPointF(6.0, 6.3), 1.2, 1.2)
    painter.setPen(_pen(color, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    hills = QPainterPath(QPointF(3.4, 11.6))
    hills.lineTo(QPointF(6.8, 8.2))
    hills.lineTo(QPointF(9.0, 10.2))
    hills.lineTo(QPointF(10.8, 8.6))
    hills.lineTo(QPointF(12.6, 10.4))
    painter.drawPath(hills)
    painter.end()
    return QIcon(pixmap)


def list_icon(color: str | QColor) -> QIcon:
    """A numbered list: the order table."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    for y in (4.0, 8.0, 12.0):
        painter.drawLine(QPointF(6.5, y), QPointF(13.0, y))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    for y in (4.0, 8.0, 12.0):
        painter.drawEllipse(QPointF(3.5, y), 1.3, 1.3)
    painter.end()
    return QIcon(pixmap)


# -- the step-kind glyphs ----------------------------------------------------------------------
# Shared by the canvas's medallions (modules/project_editor/renderers.py) and the order
# table's title column, so a step reads as the same kind everywhere it appears. The painters
# take an explicit rect for the canvas; the icon wrappers dress them for item views.


def paint_tag_glyph(painter: QPainter, rect: QRectF, colour: QColor) -> None:
    """A tiny release tag: a square hanging point-first — a marker on the timeline."""
    path = QPainterPath(QPointF(rect.center().x(), rect.bottom()))
    path.lineTo(QPointF(rect.left(), rect.center().y() - rect.height() * 0.1))
    path.lineTo(QPointF(rect.left(), rect.top()))
    path.lineTo(QPointF(rect.right(), rect.top()))
    path.lineTo(QPointF(rect.right(), rect.center().y() - rect.height() * 0.1))
    path.closeSubpath()
    painter.setBrush(colour)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawPath(path)


def paint_spark_glyph(painter: QPainter, rect: QRectF, colour: QColor) -> None:
    """A four-pointed spark: there is machine guidance — an agent instruction — here."""
    cx, cy = rect.center().x(), rect.center().y()
    pull = rect.width() * 0.14
    path = QPainterPath(QPointF(cx, rect.top()))
    path.quadTo(QPointF(cx + pull, cy - pull), QPointF(rect.right(), cy))
    path.quadTo(QPointF(cx + pull, cy + pull), QPointF(cx, rect.bottom()))
    path.quadTo(QPointF(cx - pull, cy + pull), QPointF(rect.left(), cy))
    path.quadTo(QPointF(cx - pull, cy - pull), QPointF(cx, rect.top()))
    painter.setBrush(colour)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawPath(path)


def tag_icon(color: str | QColor) -> QIcon:
    """The release tag as a row icon: this step is a milestone the graph aims at."""
    pixmap, painter = _canvas()
    paint_tag_glyph(painter, QRectF(4.0, 3.5, 8.0, 9.5), QColor(color))
    painter.end()
    return QIcon(pixmap)


def spark_icon(color: str | QColor) -> QIcon:
    """The agent-instruction spark as a row icon: machine guidance travels with this step."""
    pixmap, painter = _canvas()
    paint_spark_glyph(painter, QRectF(3.0, 3.0, 10.0, 10.0), QColor(color))
    painter.end()
    return QIcon(pixmap)


def paint_beaker_glyph(painter: QPainter, rect: QRectF, colour: QColor) -> None:
    """A beaker: this step carries tests — things that must keep being true."""
    neck = rect.width() * 0.22
    top = rect.top() + rect.height() * 0.06
    path = QPainterPath(QPointF(rect.center().x() - neck, top))
    path.lineTo(QPointF(rect.center().x() - neck, rect.center().y() - rect.height() * 0.1))
    path.lineTo(QPointF(rect.left(), rect.bottom()))
    path.lineTo(QPointF(rect.right(), rect.bottom()))
    path.lineTo(QPointF(rect.center().x() + neck, rect.center().y() - rect.height() * 0.1))
    path.lineTo(QPointF(rect.center().x() + neck, top))
    painter.setPen(_pen(colour, 1.3))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)
    # The lip, so the shape reads as a vessel rather than an arrow at 16 px.
    painter.drawLine(
        QPointF(rect.center().x() - neck * 1.7, top), QPointF(rect.center().x() + neck * 1.7, top)
    )


def paint_shield_glyph(painter: QPainter, rect: QRectF, colour: QColor) -> None:
    """A shield with a tick: a check — everything behind this point has been verified."""
    path = QPainterPath(QPointF(rect.center().x(), rect.top()))
    path.lineTo(QPointF(rect.right(), rect.top() + rect.height() * 0.22))
    path.quadTo(
        QPointF(rect.right(), rect.center().y() + rect.height() * 0.2),
        QPointF(rect.center().x(), rect.bottom()),
    )
    path.quadTo(
        QPointF(rect.left(), rect.center().y() + rect.height() * 0.2),
        QPointF(rect.left(), rect.top() + rect.height() * 0.22),
    )
    path.closeSubpath()
    painter.setPen(_pen(colour, 1.3))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)
    tick = QPainterPath(QPointF(rect.left() + rect.width() * 0.3, rect.center().y()))
    tick.lineTo(
        QPointF(rect.center().x() - rect.width() * 0.02, rect.center().y() + rect.height() * 0.18)
    )
    tick.lineTo(
        QPointF(rect.right() - rect.width() * 0.26, rect.center().y() - rect.height() * 0.16)
    )
    painter.drawPath(tick)


def beaker_icon(color: str | QColor) -> QIcon:
    """The beaker as a row icon: this step keeps tests."""
    pixmap, painter = _canvas()
    paint_beaker_glyph(painter, QRectF(3.0, 2.5, 10.0, 11.0), QColor(color))
    painter.end()
    return QIcon(pixmap)


def shield_icon(color: str | QColor) -> QIcon:
    """The check shield as a row icon: this step stands for what it waits on passing."""
    pixmap, painter = _canvas()
    paint_shield_glyph(painter, QRectF(3.0, 2.5, 10.0, 11.0), QColor(color))
    painter.end()
    return QIcon(pixmap)


def paint_layers_glyph(painter: QPainter, rect: QRectF, colour: QColor) -> None:
    """Three stacked plates: a feature — a gathered set of work, read as one thing."""
    painter.setPen(_pen(colour, 1.3))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    # The top plate is drawn whole; the two beneath show only their leading edges, which is
    # what makes a stack read as depth rather than as three separate bars at 16 px.
    top = QPainterPath(QPointF(rect.center().x(), rect.top()))
    top.lineTo(QPointF(rect.right(), rect.top() + rect.height() * 0.22))
    top.lineTo(QPointF(rect.center().x(), rect.top() + rect.height() * 0.44))
    top.lineTo(QPointF(rect.left(), rect.top() + rect.height() * 0.22))
    top.closeSubpath()
    painter.drawPath(top)
    for offset in (0.62, 0.84):
        edge = rect.top() + rect.height() * offset
        painter.drawPolyline(
            QPolygonF(
                [
                    QPointF(rect.left(), edge - rect.height() * 0.11),
                    QPointF(rect.center().x(), edge),
                    QPointF(rect.right(), edge - rect.height() * 0.11),
                ]
            )
        )


def layers_icon(color: str | QColor) -> QIcon:
    """The layer stack as a row icon: this step collects the work behind it."""
    pixmap, painter = _canvas()
    paint_layers_glyph(painter, QRectF(2.5, 2.5, 11.0, 11.0), QColor(color))
    painter.end()
    return QIcon(pixmap)


def paint_step_glyph(painter: QPainter, rect: QRectF, colour: QColor) -> None:
    """A small rounded card: one piece of work — the node the graph is made of."""
    painter.setPen(_pen(colour, 1.3))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect, 2.0, 2.0)


def step_icon(color: str | QColor) -> QIcon:
    """The card as a row icon: a plain work step, beside the tag and the layers a list
    of mixed kinds wears — the canvas paints no medallion for it, because there every
    node is one."""
    pixmap, painter = _canvas()
    paint_step_glyph(painter, QRectF(3.0, 4.5, 10.0, 7.5), QColor(color))
    painter.end()
    return QIcon(pixmap)


def info_icon(color: str | QColor) -> QIcon:
    """A circled *i*: the tooltip beside a caption that carries a standing convention.

    ``DESIGN.md``'s *Words* rule — a definition belongs behind this glyph, never on a line
    of its own under a field where it is re-read on every visit.
    """
    pixmap, painter = _canvas()
    circle = QColor(color)
    painter.setPen(_pen(circle, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QRectF(2.5, 2.5, 11.0, 11.0))
    painter.setPen(_pen(circle, 1.4))
    painter.drawPoint(QPointF(8.0, 5.6))
    painter.drawLine(QPointF(8.0, 7.6), QPointF(8.0, 11.0))
    painter.end()
    return QIcon(pixmap)


def ticket_icon(color: str | QColor) -> QIcon:
    """A ticket stub: this step is tracked somewhere else."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    stub = QPainterPath(QPointF(2.5, 4.5))
    stub.lineTo(QPointF(13.5, 4.5))
    stub.lineTo(QPointF(13.5, 7.0))
    stub.arcTo(QRectF(12.2, 7.0, 2.6, 2.0), 90, -180)
    stub.lineTo(QPointF(13.5, 11.5))
    stub.lineTo(QPointF(2.5, 11.5))
    stub.lineTo(QPointF(2.5, 9.0))
    stub.arcTo(QRectF(1.2, 7.0, 2.6, 2.0), 270, -180)
    stub.closeSubpath()
    painter.drawPath(stub)
    painter.drawLine(QPointF(9.5, 5.5), QPointF(9.5, 10.5))
    painter.end()
    return QIcon(pixmap)


# The medallion vocabulary the canvas painted first, as row and menu icons: one painter per
# kind name a step can wear ("tag" a milestone, "layers" a feature, "spark" an agent step,
# "beaker" one carrying tests, "shield" a check). It lives here, beside the glyphs, so a
# surface that shows what kind a step is looks it up rather than keeping its own table.
GLYPH_ICONS: dict[str, Callable[[str | QColor], QIcon]] = {
    "step": step_icon,
    "tag": tag_icon,
    "layers": layers_icon,
    "spark": spark_icon,
    "beaker": beaker_icon,
    "shield": shield_icon,
    "ticket": ticket_icon,
}


def glyph_painter(kind: str) -> Callable[[QColor], QIcon] | None:
    """The painter for one kind name, or None for a name this build has no glyph for."""
    return GLYPH_ICONS.get(kind)


# -- repositories ------------------------------------------------------------------------------
#
# The Project dialog's and the Repositories card's vocabulary: the code repository, a pull
# request, a clone arriving, a plan moving out.


def code_icon(color: str | QColor) -> QIcon:
    """Two angle brackets: the code repository."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.3))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPolyline(QPolygonF([QPointF(6.0, 4.5), QPointF(2.5, 8.0), QPointF(6.0, 11.5)]))
    painter.drawPolyline(QPolygonF([QPointF(10.0, 4.5), QPointF(13.5, 8.0), QPointF(10.0, 11.5)]))
    painter.end()
    return QIcon(pixmap)


def pull_request_icon(color: str | QColor) -> QIcon:
    """A pull request: a branch's node arriving on the trunk — GitHub's own shape."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(4.5, 3.5), 1.8, 1.8)
    painter.drawEllipse(QPointF(4.5, 12.5), 1.8, 1.8)
    painter.drawEllipse(QPointF(11.5, 12.5), 1.8, 1.8)
    painter.drawLine(QPointF(4.5, 5.3), QPointF(4.5, 10.7))
    arm = QPainterPath(QPointF(8.0, 3.5))
    arm.lineTo(QPointF(9.5, 3.5))
    arm.quadTo(QPointF(11.5, 3.5), QPointF(11.5, 5.5))
    arm.lineTo(QPointF(11.5, 10.7))
    painter.drawPath(arm)
    painter.drawLine(QPointF(8.0, 3.5), QPointF(9.6, 1.9))
    painter.drawLine(QPointF(8.0, 3.5), QPointF(9.6, 5.1))
    painter.end()
    return QIcon(pixmap)


def clone_icon(color: str | QColor) -> QIcon:
    """An arrow coming down into a tray: bring a repository onto this machine."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.3))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(QPointF(8.0, 2.5), QPointF(8.0, 9.5))
    painter.drawPolyline(QPolygonF([QPointF(5.0, 6.8), QPointF(8.0, 9.8), QPointF(11.0, 6.8)]))
    painter.drawPolyline(
        QPolygonF(
            [QPointF(3.0, 10.0), QPointF(3.0, 13.0), QPointF(13.0, 13.0), QPointF(13.0, 10.0)]
        )
    )
    painter.end()
    return QIcon(pixmap)


def move_icon(color: str | QColor) -> QIcon:
    """A box with an arrow leaving it: move the plan into a repository of its own."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(2.5, 4.5, 5.5, 7.0), 1.0, 1.0)
    painter.drawLine(QPointF(9.0, 8.0), QPointF(13.5, 8.0))
    painter.drawLine(QPointF(11.3, 5.8), QPointF(13.5, 8.0))
    painter.drawLine(QPointF(11.3, 10.2), QPointF(13.5, 8.0))
    painter.end()
    return QIcon(pixmap)
