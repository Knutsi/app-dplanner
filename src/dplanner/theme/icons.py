"""Tiny painted icons for segment kinds and editor modes.

Painted with QPainter instead of bundled SVGs: a handful of glyphs do not justify a
resource pipeline, and taking the colour as a parameter lets the same glyph read on the
dark binder and the light corkboard cards alike.
"""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

ICON_SIZE = 16


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


def _pen(color: str, width: float) -> QPen:
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
    """A wrench: the Utility panel's tools."""
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
