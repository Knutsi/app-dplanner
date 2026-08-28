"""Tiny painted icons for segment kinds, editor modes and toolbar verbs.

Painted with QPainter instead of bundled SVGs: a handful of glyphs do not justify a
resource pipeline, and taking the colour as a parameter lets the same glyph read on the
dark binder and the light corkboard cards alike.
"""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

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


def edit_icon(color: str) -> QIcon:
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


def read_icon(color: str) -> QIcon:
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


def exit_icon(color: str) -> QIcon:
    """An arrow stepping out of a door frame: leave."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    # The frame, open on the right.
    painter.drawPolyline(
        QPolygonF(
            [
                QPointF(8.5, 2.5),
                QPointF(3.0, 2.5),
                QPointF(3.0, 13.5),
                QPointF(8.5, 13.5),
            ]
        )
    )
    # The arrow out.
    painter.drawLine(QPointF(6.5, 8.0), QPointF(13.5, 8.0))
    painter.drawLine(QPointF(10.8, 5.4), QPointF(13.5, 8.0))
    painter.drawLine(QPointF(10.8, 10.6), QPointF(13.5, 8.0))
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


def graph_icon(color: str) -> QIcon:
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


def dot_icon(color: str) -> QIcon:
    """A filled dot: the active item in a list."""
    pixmap, painter = _canvas()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(QPointF(8.0, 8.0), 3.0, 3.0)
    painter.end()
    return QIcon(pixmap)


def check_icon(color: str) -> QIcon:
    """A check mark: done / read."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.8))
    painter.drawPolyline(QPolygonF([QPointF(3.5, 8.5), QPointF(6.8, 11.8), QPointF(12.5, 4.5)]))
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


def branch_icon(color: str) -> QIcon:
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


def wrench_icon(color: str) -> QIcon:
    """A wrench: tools and maintenance."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 2.0))
    painter.drawLine(QPointF(3.5, 12.5), QPointF(8.6, 7.4))
    painter.setPen(_pen(color, 1.4))
    # An open-ended head: an arc whose gap faces the handle's far end.
    painter.drawArc(QRectF(8.2, 2.2, 5.6, 5.6), -45 * 16, 270 * 16)
    painter.end()
    return QIcon(pixmap)


def sliders_icon(color: str) -> QIcon:
    """Three sliders: properties and settings."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.2))
    for y in (4.0, 8.0, 12.0):
        painter.drawLine(QPointF(3.0, y), QPointF(13.0, y))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    for y, knob_x in ((4.0, 10.0), (8.0, 5.5), (12.0, 8.5)):
        painter.drawEllipse(QPointF(knob_x, y), 1.8, 1.8)
    painter.end()
    return QIcon(pixmap)


# -- canvas toolbar --------------------------------------------------------------------------
#
# One glyph per action id the graph editor's toolbar carries. They live here with the rest
# rather than in the module because the colour parameter is the theme's, and the theme is what
# repaints them.


def plus_icon(color: str) -> QIcon:
    """A plus: add a step."""
    pixmap, painter = _canvas()
    painter.setPen(_pen(color, 1.6))
    painter.drawLine(QPointF(8.0, 3.5), QPointF(8.0, 12.5))
    painter.drawLine(QPointF(3.5, 8.0), QPointF(12.5, 8.0))
    painter.end()
    return QIcon(pixmap)


def trash_icon(color: str) -> QIcon:
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


def unlink_icon(color: str) -> QIcon:
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


def undo_icon(color: str) -> QIcon:
    """An arrow curving back on itself, anticlockwise."""
    return _turn_icon(color, mirrored=False)


def redo_icon(color: str) -> QIcon:
    """The same arrow the other way round."""
    return _turn_icon(color, mirrored=True)


def _turn_icon(color: str, mirrored: bool) -> QIcon:
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


def frame_icon(color: str) -> QIcon:
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


def gauge_icon(color: str) -> QIcon:
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


def list_icon(color: str) -> QIcon:
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
