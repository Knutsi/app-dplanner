"""The canvas: steps as nodes, edges as arrows, and the three gestures that edit them.

**Nodes diff, edges rebuild.** :meth:`GraphScene.sync` reconciles node items by step id —
creating, updating and removing, never clearing — because a node may be under the mouse
mid-drag and must keep its identity. Edges are never mid-gesture and a project holds tens of
them, so they are thrown away and rebuilt wholesale. That asymmetry is what stops this file
from becoming a diffing engine.

**The scene reports; it never writes.** Every gesture ends in a signal, and the activity turns
that into a command on the undo stack. So a drag is undoable, and the model stays the only
thing that decides what a legal graph is — including during a link drag, where the scene asks
``link_refusal`` under the cursor rather than keeping a second copy of the rule.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QPainter
from PySide6.QtWidgets import (
    QGraphicsScene,
    QGraphicsSceneMouseEvent,
    QGraphicsView,
    QWidget,
)

from dplanner.core.signals import Signal
from dplanner.domain.model import StepId
from dplanner.framework.widgets import install_ctrl_wheel_zoom
from dplanner.modules.project_editor.items import (
    NODE_H,
    NODE_W,
    EdgeItem,
    LinkPreviewItem,
    StepNodeItem,
)

ZOOM_MIN = 0.4
ZOOM_MAX = 2.5
# The furthest the view zooms itself out to fit a graph; below this a node is unreadable
# and scrolling is the better answer.
ZOOM_READABLE = 0.75
FRAME_PADDING = 40.0
MIN_FRAMEABLE_WIDTH = 200
ZOOM_STEP = 1.15
SCENE_MARGIN = 300.0


@dataclass(frozen=True)
class NodeSpec:
    step_id: StepId
    title: str
    subtitle: str
    x: float
    y: float


@dataclass(frozen=True)
class EdgeSpec:
    waiter: StepId  # The step that waits.
    source: StepId  # The step it waits on.
    kind: str


class GraphScene(QGraphicsScene):
    """Items and gestures. Everything it decides, it decides by asking the model."""

    def __init__(self, link_refusal: Callable[[StepId, StepId], str | None]) -> None:
        super().__init__()
        self._link_refusal = link_refusal
        self._nodes: dict[StepId, StepNodeItem] = {}
        self._edges: list[EdgeItem] = []
        # Both the drag record and the "this node owns its own position" guard: one dict,
        # so the two can never disagree.
        self._press_at: dict[StepId, QPointF] = {}
        self._link_from: StepNodeItem | None = None
        # Click order, which QGraphicsScene.selectedItems() does not preserve. It is what
        # makes `Context.selected_entities("step")` mean "the first, then the second".
        self._selection_order: list[StepId] = []
        self._preview = LinkPreviewItem()
        self._preview.hide()
        self.addItem(self._preview)

        self.nodes_moved: Signal[list[tuple[StepId, float, float]]] = Signal()
        # (source, target): the user dragged from source's handle onto target. Whether that
        # is a legal link is not this view's business — the action decides.
        self.link_requested: Signal[StepId, StepId] = Signal()
        self.create_requested: Signal[float, float] = Signal()
        # The whole selection, in the order it was made: two steps is what a link verb reads.
        self.focus_changed: Signal[list[StepId]] = Signal()
        self.delete_requested: Signal[list[StepId]] = Signal()

        self.selectionChanged.connect(self._on_selection)

    # -- what the activity puts in ---------------------------------------------------------

    def sync(self, nodes: list[NodeSpec], edges: list[EdgeSpec]) -> None:
        wanted = {spec.step_id for spec in nodes}
        for spec in nodes:
            item = self._nodes.get(spec.step_id)
            if item is None:
                item = self._nodes[spec.step_id] = StepNodeItem(spec.step_id)
                self.addItem(item)
            item.set_text(spec.title, spec.subtitle)
            # A node being dragged owns its position until the gesture ends. The model is
            # authoritative everywhere else — including when the CLI writes mid-drag.
            if spec.step_id not in self._press_at:
                item.setPos(spec.x, spec.y)
        for gone in set(self._nodes) - wanted:
            self.removeItem(self._nodes.pop(gone))

        for edge in self._edges:
            self.removeItem(edge)
        self._edges = [
            EdgeItem(self._nodes[spec.source], self._nodes[spec.waiter], spec.kind)
            for spec in edges
            if spec.source in self._nodes and spec.waiter in self._nodes
        ]
        for edge in self._edges:
            self.addItem(edge)
        self._grow_scene_rect()

    def reflow_edges(self, step_id: StepId) -> None:
        """Redraw the edges touching one node — called by the item while it is dragged."""
        for edge in self._edges:
            if edge.source.step_id == step_id or edge.waiter.step_id == step_id:
                edge.follow()

    def content_rect(self) -> QRectF:
        """What the nodes actually occupy, for a view deciding where to look."""
        rect = QRectF()
        for item in self._nodes.values():
            rect = rect.united(item.sceneBoundingRect())
        return rect

    def select_step(self, step_id: StepId | None) -> None:
        self.select_steps([] if step_id is None else [step_id])

    def select_steps(self, step_ids: list[StepId]) -> None:
        """Select these, in this order — which is what a two-step verb reads back."""
        self.clearSelection()
        self._selection_order = []
        for step_id in step_ids:
            item = self._nodes.get(step_id)
            if item is not None:
                item.setSelected(True)
        # setSelected fires selectionChanged one item at a time and Qt reports the set
        # unordered, so the order asked for is restored here and announced once.
        self._selection_order = [s for s in step_ids if s in self._nodes]
        self.focus_changed.emit(list(self._selection_order))

    def selected_steps(self) -> list[StepId]:
        return list(self._selection_order)

    def selected_step(self) -> StepId | None:
        """The one selected step, or None when it is none or several."""
        return self._selection_order[0] if len(self._selection_order) == 1 else None

    # -- gestures ----------------------------------------------------------------------------

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        node = self._node_at(event.scenePos())
        if node is not None and node.is_over_handle(event.scenePos()):
            # Consumed before Qt sees it, so no move and no rubber band starts.
            self._link_from = node
            self._preview.aim(node.handle_scene_pos(), event.scenePos(), True)
            self._preview.show()
            event.accept()
            return
        super().mousePressEvent(event)
        self._press_at = {
            item.step_id: item.pos()
            for item in self.selectedItems()
            if isinstance(item, StepNodeItem)
        }

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        if self._link_from is None:
            super().mouseMoveEvent(event)
            return
        target = self._node_at(event.scenePos())
        ok = target is not None and self._refusal_between(self._link_from, target) is None
        for item in self._nodes.values():
            item.set_link_state("")
        if target is not None and target is not self._link_from:
            target.set_link_state("valid" if ok else "invalid")
        self._preview.aim(self._link_from.handle_scene_pos(), event.scenePos(), ok)
        event.accept()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        if self._link_from is not None:
            source, self._link_from = self._link_from, None
            self._preview.hide()
            for item in self._nodes.values():
                item.set_link_state("")
            target = self._node_at(event.scenePos())
            if target is not None and target is not source:
                self.link_requested.emit(source.step_id, target.step_id)
            event.accept()
            return

        super().mouseReleaseEvent(event)
        moved = [
            (step_id, self._nodes[step_id].pos().x(), self._nodes[step_id].pos().y())
            for step_id, was in self._press_at.items()
            if step_id in self._nodes and self._nodes[step_id].pos() != was
        ]
        self._press_at = {}
        if moved:
            self.nodes_moved.emit(moved)

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        if self._node_at(event.scenePos()) is None:
            point = event.scenePos()
            self.create_requested.emit(point.x() - NODE_W / 2, point.y() - NODE_H / 2)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            chosen = [i.step_id for i in self.selectedItems() if isinstance(i, StepNodeItem)]
            if chosen:
                self.delete_requested.emit(chosen)
                event.accept()
                return
        super().keyPressEvent(event)

    # -- internals ---------------------------------------------------------------------------

    def _refusal_between(self, source: StepNodeItem, target: StepNodeItem) -> str | None:
        """Why dragging from ``source`` to ``target`` would not work, for the drag preview.

        Both ends are arguments rather than one of them being read off the gesture: this used
        to read ``self._link_from``, which the release handler clears on its first line, so
        every drop refused itself.
        """
        if target is source:
            return "a step cannot depend on itself"
        return self._link_refusal(target.step_id, source.step_id)

    def _node_at(self, scene_pos: QPointF) -> StepNodeItem | None:
        for item in self.items(scene_pos):
            if isinstance(item, StepNodeItem):
                return item
        # A handle sticks out past the body, so a near miss still counts as its node.
        for item in self._nodes.values():
            if item.is_over_handle(scene_pos):
                return item
        return None

    def _on_selection(self) -> None:
        current = {i.step_id for i in self.selectedItems() if isinstance(i, StepNodeItem)}
        kept = [step_id for step_id in self._selection_order if step_id in current]
        self._selection_order = kept + [s for s in current if s not in kept]
        self.focus_changed.emit(list(self._selection_order))

    def _grow_scene_rect(self) -> None:
        bounds = self.itemsBoundingRect()
        self.setSceneRect(bounds.adjusted(-SCENE_MARGIN, -SCENE_MARGIN, SCENE_MARGIN, SCENE_MARGIN))


class GraphView(QGraphicsView):
    """The viewport: rubber-band selection, and Ctrl+wheel zoom like every other surface."""

    def __init__(self, scene: GraphScene, parent: QWidget | None = None) -> None:
        super().__init__(scene, parent)
        self.setObjectName("GraphView")
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self._zoom = 1.0
        self._framed = False
        # The application's View ▸ Zoom is font size; a canvas zooms itself.
        install_ctrl_wheel_zoom(self, self.zoom_by)

    def showEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)  # type: ignore[arg-type]
        if not self._framed:
            self._framed = True
            # Deferred to the next turn of the event loop rather than done here: at show
            # time the splitter has not given the viewport its real width yet, and fitting
            # a graph to a half-laid-out box zooms a readable one down to nothing.
            QTimer.singleShot(0, self.frame_content)

    def frame_content(self) -> None:
        """Look at the graph: centred, and zoomed out only as far as stays readable."""
        scene = self.scene()
        if not isinstance(scene, GraphScene):
            return
        content = scene.content_rect()
        if content.isEmpty():
            return
        padded = content.adjusted(-FRAME_PADDING, -FRAME_PADDING, FRAME_PADDING, FRAME_PADDING)
        viewport = self.viewport().rect()
        fits = min(
            viewport.width() / max(padded.width(), 1.0),
            viewport.height() / max(padded.height(), 1.0),
        )
        # Never magnify, and never shrink past legibility — a graph too big for the window
        # is scrolled, not squinted at.
        wanted = max(ZOOM_READABLE, min(1.0, fits))
        if wanted != self._zoom:
            self.scale(wanted / self._zoom, wanted / self._zoom)
            self._zoom = wanted
        self.centerOn(content.center())

    def zoom_by(self, steps: int) -> None:
        factor = ZOOM_STEP**steps
        wanted = max(ZOOM_MIN, min(ZOOM_MAX, self._zoom * factor))
        if wanted != self._zoom:
            self.scale(wanted / self._zoom, wanted / self._zoom)
            self._zoom = wanted
