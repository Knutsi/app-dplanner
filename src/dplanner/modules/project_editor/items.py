"""What the canvas draws: a node per step, an arrow per edge, and the line under a link drag.

Each item owns its geometry and holds its state and nothing else. A step node's actual
painting is composed in ``renderers.py`` from pure helpers; interaction lives in
``modes.py``, one mode per behaviour, so no item and no scene grows a state machine.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPalette,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsPathItem,
    QStyleOptionGraphicsItem,
    QWidget,
)

from dplanner.domain.model import StepId
from dplanner.modules.project_editor.positions import GRID, NODE_H, NODE_W
from dplanner.modules.project_editor.renderers import (
    HANDLE_R,
    INVALID_TINT,
    VALID_TINT,
    NodeAccent,
    NodeState,
    RenderHints,
    paint_node,
)
from dplanner.modules.project_editor.selection import EdgeRef

# How far a press may land from the handle's centre and still mean it.
HANDLE_GRAB = 12.0

# How wide a curve is to the mouse. An edge is drawn 1.4 px thin and no one can click that,
# so its shape() is the stroked path at this width — comfortably a target, still narrow
# enough that two edges through the same gap stay tellable apart.
EDGE_GRAB = 14.0


def live_palette(item: QGraphicsItem) -> QPalette:
    """The colours to paint from, as they are now.

    **Never ``option.palette``.** Qt fills that field once, when the scene is created, and
    never refreshes it, so every node and edge kept the colours of whatever theme was
    current when the tab opened — a light theme drew the whole graph in the dark theme's
    ink and it vanished. The scene's palette follows the application's.
    """
    scene = item.scene()
    return scene.palette() if scene is not None else QApplication.palette()


class StepNodeItem(QGraphicsItem):
    """One step. Movable and selectable; Qt does the dragging."""

    def __init__(self, step_id: StepId) -> None:
        super().__init__()
        self.step_id = step_id
        self._title = ""
        self._subtitle = ""
        self._link_state = ""
        self._accent = NodeAccent()
        self._hints = RenderHints()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self._hovered = False

    def set_text(self, title: str, subtitle: str) -> None:
        if (title, subtitle) != (self._title, self._subtitle):
            self._title, self._subtitle = title, subtitle
            self.update()

    def set_accent(self, accent: NodeAccent) -> None:
        if accent != self._accent:
            self._accent = accent
            self.update()

    def set_link_state(self, state: str) -> None:
        """ "" while nothing is being dragged at this node, else "valid" or "invalid"."""
        if state != self._link_state:
            self._link_state = state
            self.update()

    def set_render_hints(self, hints: RenderHints) -> None:
        """What the current mode wants shown — pushed by the scene, never read back."""
        if hints != self._hints:
            self._hints = hints
            self.update()

    def handle_scene_pos(self) -> QPointF:
        return self.mapToScene(QPointF(NODE_W, NODE_H / 2))

    def is_over_handle(self, scene_pos: QPointF) -> bool:
        delta = scene_pos - self.handle_scene_pos()
        return bool(delta.manhattanLength() <= HANDLE_GRAB)

    def anchor_toward(self, other: QPointF) -> QPointF:
        """Where an edge should touch this node: the near edge, not the centre."""
        centre = self.mapToScene(QPointF(NODE_W / 2, NODE_H / 2))
        return self.mapToScene(QPointF(NODE_W if other.x() >= centre.x() else 0.0, NODE_H / 2))

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt override
        # Constant, whatever the accent: room for the handle (even grown by connect
        # mode's emphasis), a badge's rise above the top edge and a chip's fall below it
        # (each half its height plus a stroke — BADGE_H / 2 + 1 and CHIP_H / 2 + 1 must
        # both stay <= this margin), so paint never leaves the rect.
        margin = HANDLE_R + 4
        return QRectF(-margin, -margin, NODE_W + 2 * margin, NODE_H + 2 * margin)

    def itemChange(self, change: object, value: object) -> object:  # noqa: N802 - Qt override
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and isinstance(
            value, QPointF
        ):
            # Snap while dragging, so what the user sees is what gets stored.
            return QPointF(round(value.x() / GRID) * GRID, round(value.y() / GRID) * GRID)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            scene = self.scene()
            if scene is not None and hasattr(scene, "reflow_edges"):
                scene.reflow_edges(self.step_id)
        return super().itemChange(change, value)  # type: ignore[arg-type]

    def paint(
        self,
        painter: QPainter,
        _option: QStyleOptionGraphicsItem,
        _widget: QWidget | None = None,
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        paint_node(
            painter,
            live_palette(self),
            self._title,
            self._subtitle,
            self._accent,
            NodeState(
                selected=self.isSelected(),
                hovered=self._hovered,
                link_state=self._link_state,
                hints=self._hints,
            ),
        )

    def hoverEnterEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        self._hovered = True
        self.update()

    def hoverLeaveEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        self._hovered = False
        self.update()


class EdgeItem(QGraphicsPathItem):
    """An arrow from the step waited on to the step that waits.

    ``requires`` is solid with a head because it orders the graph; ``relates`` is dashed
    without one because it does not. That is the whole visual vocabulary, and it matches
    what ``EDGE_KINDS`` means.
    """

    def __init__(self, source: StepNodeItem, waiter: StepNodeItem, kind: str) -> None:
        super().__init__()
        self.source = source
        self.waiter = waiter
        self.kind = kind
        self.ref = EdgeRef(waiter=waiter.step_id, kind=kind, source=source.step_id)
        self._head: QPolygonF | None = None
        self._hovered = False
        self.setZValue(-1)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.follow()

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(EDGE_GRAB)
        return stroker.createStroke(self.path())

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt override
        margin = EDGE_GRAB / 2
        return self.path().boundingRect().adjusted(-margin, -margin, margin, margin)

    def hoverEnterEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        self._hovered = True
        self.update()

    def hoverLeaveEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        self._hovered = False
        self.update()

    def follow(self) -> None:
        start = self.source.anchor_toward(self.waiter.scenePos())
        end = self.waiter.anchor_toward(self.source.scenePos())
        path = QPainterPath(start)
        reach = max(40.0, abs(end.x() - start.x()) / 2)
        path.cubicTo(QPointF(start.x() + reach, start.y()), QPointF(end.x() - reach, end.y()), end)
        self.setPath(path)
        # The head is kept apart from the curve rather than added to its path: one filled
        # path containing both would fill the area under the curve as well.
        self._head = (
            _arrow_head(path.pointAtPercent(0.92), end) if self.kind == "requires" else None
        )

    def paint(
        self,
        painter: QPainter,
        _option: QStyleOptionGraphicsItem,
        _widget: QWidget | None = None,
    ) -> None:
        palette = live_palette(self)
        if self.isSelected():
            colour = QColor(palette.highlight().color())
        else:
            colour = QColor(palette.text().color())
            colour.setAlpha(200 if self._hovered else 130)
        style = Qt.PenStyle.SolidLine if self.kind == "requires" else Qt.PenStyle.DashLine
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(colour, 2.4 if self.isSelected() or self._hovered else 1.4, style))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.path())
        if self._head is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colour)
            painter.drawPolygon(self._head)


class LinkPreviewItem(QGraphicsPathItem):
    """The line that follows the cursor while a link is being dragged."""

    def __init__(self) -> None:
        super().__init__()
        self.setZValue(10)
        self._ok = True

    def aim(self, origin: QPointF, cursor: QPointF, ok: bool) -> None:
        self._ok = ok
        path = QPainterPath(origin)
        reach = max(40.0, abs(cursor.x() - origin.x()) / 2)
        path.cubicTo(
            QPointF(origin.x() + reach, origin.y()), QPointF(cursor.x() - reach, cursor.y()), cursor
        )
        self.setPath(path)

    def paint(
        self,
        painter: QPainter,
        _option: QStyleOptionGraphicsItem,
        _widget: QWidget | None = None,
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(VALID_TINT if self._ok else INVALID_TINT, 2.0, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.path())


def _arrow_head(start: QPointF, end: QPointF, size: float = 8.0) -> QPolygonF:
    direction = end - start
    length = (direction.x() ** 2 + direction.y() ** 2) ** 0.5 or 1.0
    unit = QPointF(direction.x() / length, direction.y() / length)
    normal = QPointF(-unit.y(), unit.x())
    base = end - unit * size
    return QPolygonF([end, base + normal * size * 0.5, base - normal * size * 0.5])
