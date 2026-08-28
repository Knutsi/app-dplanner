"""Region frames on the canvas: annotation drawn behind the graph, never structure.

Split from ``items.py`` the way ``regions.py``/``region_verbs.py`` already split the
Qt-free half: regions are a feature layered *on* the graph, and the node/edge items share
nothing with them but ``live_palette``.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QStyleOptionGraphicsItem, QWidget

from dplanner.modules.project_editor.items import live_palette
from dplanner.modules.project_editor.positions import GRID
from dplanner.modules.project_editor.regions import TITLE_STRIP_H
from dplanner.modules.project_editor.renderers import PADDING, SECONDARY_ALPHA

# A region's grabbable edges: how far the clickable ring reaches either side of the border,
# and the square at the bottom-right corner that resizes.
REGION_BORDER_GRAB = 6.0
REGION_GRIP = 16.0
REGION_FILL_ALPHA = 10
REGION_STRIP_ALPHA = 16
REGION_BORDER_ALPHA = 60
REGION_RADIUS = 8.0


class RegionItem(QGraphicsItem):
    """A titled rectangle painted behind the graph — annotation, not structure.

    It sits below the edges, so nothing it does can obscure the plan. Qt's hit-testing sees
    only the title strip and the border ring (see :meth:`shape`): grabbing either moves the
    frame alone, and a rubber band swept over the *body* selects the steps, not the region.
    The body is still grabbable — ``RegionDragMode`` claims those presses before Qt and
    carries the steps whose centres lie inside.
    """

    def __init__(self, region_id: str) -> None:
        super().__init__()
        self.region_id = region_id
        self._title = ""
        self._w = 0.0
        self._h = 0.0
        self._hovered = False
        self.setZValue(-2)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)

    def set_title(self, title: str) -> None:
        if title != self._title:
            self._title = title
            self.update()

    def set_rect(self, w: float, h: float) -> None:
        if (w, h) != (self._w, self._h):
            self.prepareGeometryChange()
            self._w, self._h = w, h
            self.update()

    def size(self) -> tuple[float, float]:
        return self._w, self._h

    # -- where a press means what ----------------------------------------------------------------

    def contains_point(self, scene_pos: QPointF) -> bool:
        return QRectF(0, 0, self._w, self._h).contains(self.mapFromScene(scene_pos))

    def is_over_title(self, scene_pos: QPointF) -> bool:
        local = self.mapFromScene(scene_pos)
        return QRectF(0, 0, self._w, TITLE_STRIP_H).contains(local)

    def is_over_grip(self, scene_pos: QPointF) -> bool:
        local = self.mapFromScene(scene_pos)
        grip = QRectF(self._w - REGION_GRIP, self._h - REGION_GRIP, REGION_GRIP, REGION_GRIP)
        return grip.contains(local)

    def is_over_body(self, scene_pos: QPointF) -> bool:
        """Inside, but not on any part that moves the frame alone or resizes it."""
        if not self.contains_point(scene_pos) or self.is_over_grip(scene_pos):
            return False
        local = self.mapFromScene(scene_pos)
        inner = QRectF(
            REGION_BORDER_GRAB,
            TITLE_STRIP_H,
            self._w - 2 * REGION_BORDER_GRAB,
            self._h - TITLE_STRIP_H - REGION_BORDER_GRAB,
        )
        return inner.contains(local)

    # -- geometry --------------------------------------------------------------------------------

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt override
        margin = REGION_BORDER_GRAB
        return QRectF(-margin, -margin, self._w + 2 * margin, self._h + 2 * margin)

    def shape(self) -> QPainterPath:
        # Only the strip and the ring, so the body neither swallows a rubber band nor gets
        # picked by Qt — body presses are a mode's business, claimed before Qt sees them.
        ring = QPainterPath()
        ring.addRect(self.boundingRect())
        hole = QPainterPath()
        hole.addRect(
            QRectF(
                REGION_BORDER_GRAB,
                TITLE_STRIP_H,
                self._w - 2 * REGION_BORDER_GRAB,
                self._h - TITLE_STRIP_H - REGION_BORDER_GRAB,
            )
        )
        return ring.subtracted(hole)

    def itemChange(self, change: object, value: object) -> object:  # noqa: N802 - Qt override
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and isinstance(
            value, QPointF
        ):
            return QPointF(round(value.x() / GRID) * GRID, round(value.y() / GRID) * GRID)
        return super().itemChange(change, value)  # type: ignore[arg-type]

    # -- paint -----------------------------------------------------------------------------------

    def paint(
        self,
        painter: QPainter,
        _option: QStyleOptionGraphicsItem,
        _widget: QWidget | None = None,
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = live_palette(self)
        ink = palette.text().color()
        body = QRectF(0, 0, self._w, self._h)

        fill = QColor(ink)
        fill.setAlpha(REGION_FILL_ALPHA)
        border = QColor(palette.highlight().color())
        if not self.isSelected():
            border = QColor(ink)
            border.setAlpha(REGION_BORDER_ALPHA)
        painter.setBrush(fill)
        painter.setPen(QPen(border, 2.0 if self.isSelected() else 1.0))
        painter.drawRoundedRect(body, REGION_RADIUS, REGION_RADIUS)

        # The title strip, a shade deeper so "this part moves the frame" is discoverable.
        strip = QColor(ink)
        strip.setAlpha(REGION_STRIP_ALPHA)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(strip)
        strip_path = QPainterPath()
        strip_path.addRoundedRect(body, REGION_RADIUS, REGION_RADIUS)
        clip = QPainterPath()
        clip.addRect(QRectF(0, 0, self._w, TITLE_STRIP_H))
        painter.drawPath(strip_path.intersected(clip))

        faded = QColor(ink)
        faded.setAlpha(SECONDARY_ALPHA)
        painter.setPen(faded)
        metrics = painter.fontMetrics()
        title_rect = QRectF(PADDING, 0, self._w - 2 * PADDING, TITLE_STRIP_H)
        painter.drawText(
            title_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            metrics.elidedText(self._title, Qt.TextElideMode.ElideRight, int(title_rect.width())),
        )

        if self._hovered or self.isSelected():
            grip = QColor(ink)
            grip.setAlpha(REGION_BORDER_ALPHA + 40)
            painter.setPen(QPen(grip, 1.4))
            for inset in (5.0, 9.0):
                painter.drawLine(
                    QPointF(self._w - inset, self._h - 3.0),
                    QPointF(self._w - 3.0, self._h - inset),
                )

    def hoverEnterEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        self._hovered = True
        self.update()

    def hoverLeaveEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        self._hovered = False
        self.update()


class RegionPreviewItem(QGraphicsPathItem):
    """The dashed outline that follows a region being dragged out."""

    def __init__(self) -> None:
        super().__init__()
        self.setZValue(10)

    def aim(self, rect: QRectF) -> None:
        path = QPainterPath()
        path.addRoundedRect(rect, REGION_RADIUS, REGION_RADIUS)
        self.setPath(path)

    def paint(
        self,
        painter: QPainter,
        _option: QStyleOptionGraphicsItem,
        _widget: QWidget | None = None,
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        colour = QColor(live_palette(self).text().color())
        colour.setAlpha(SECONDARY_ALPHA)
        painter.setPen(QPen(colour, 1.4, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.path())
