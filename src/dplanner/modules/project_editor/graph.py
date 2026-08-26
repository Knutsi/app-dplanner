"""The canvas: steps as nodes, edges as arrows, and what the user has picked out of them.

**Every item diffs by key.** :meth:`GraphScene.sync` reconciles nodes by step id and edges by
:class:`EdgeRef` — creating, updating and removing, never clearing — for one reason that covers
both: an item the user is holding on to must keep its identity. A node may be under the mouse
mid-drag; an edge may be selected, waiting for Delete. Rebuilding either wholesale throws that
away, and the edges used to be rebuilt wholesale, which is why they could not be selected.

**The scene reports; it never writes.** Every gesture ends in a signal, and the activity turns
that into a command on the undo stack. So a drag is undoable, and the model stays the only
thing that decides what a legal graph is — including during a link drag, where the mode asks
``link_refusal`` under the cursor rather than keeping a second copy of the rule.

**Input lives in :mod:`dplanner.modules.project_editor.modes`.** :class:`GraphView` normalises
each event and offers it to the current mode, then to the canvas keymap, then to Qt. What is
left of the scene's own mouse handling is the record of what Qt's item dragging did, which has
to run *after* Qt has updated the selection — so a mode that claims a press suppresses node
dragging for free, because the scene never sees it.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsScene,
    QGraphicsSceneMouseEvent,
    QGraphicsView,
    QWidget,
)

from dplanner.core.signals import Signal
from dplanner.domain.model import StepId
from dplanner.framework.widgets import install_ctrl_wheel_zoom
from dplanner.modules.project_editor.items import EdgeItem, LinkPreviewItem, StepNodeItem
from dplanner.modules.project_editor.keymap import bound_actions
from dplanner.modules.project_editor.modes import (
    CanvasDeps,
    CanvasEvent,
    CanvasKey,
    ModeBase,
    ModeStack,
    PanMode,
)
from dplanner.modules.project_editor.selection import CanvasSelection, EdgeRef

ZOOM_MIN = 0.4
ZOOM_MAX = 2.5
# The furthest the view zooms itself out to fit a graph; below this a node is unreadable
# and scrolling is the better answer.
ZOOM_READABLE = 0.75
FRAME_PADDING = 40.0
ZOOM_STEP = 1.15
SCENE_MARGIN = 300.0


@dataclass(frozen=True)
class NodeSpec:
    step_id: StepId
    title: str
    subtitle: str
    x: float
    y: float


class GraphScene(QGraphicsScene):
    """Items and what is picked. Everything it decides, it decides by asking the model."""

    def __init__(self, link_refusal: Callable[[StepId, StepId], str | None]) -> None:
        super().__init__()
        self._link_refusal = link_refusal
        self._nodes: dict[StepId, StepNodeItem] = {}
        self._edges: dict[EdgeRef, EdgeItem] = {}
        # Both the drag record and the "this node owns its own position" guard: one dict,
        # so the two can never disagree.
        self._press_at: dict[StepId, QPointF] = {}
        # Click order, which QGraphicsScene.selectedItems() does not preserve. It is what
        # makes `Context.selected_entities("step")` mean "the first, then the second".
        self._selection_order: list[StepId] = []
        self._preview = LinkPreviewItem()
        self._preview.hide()
        self.addItem(self._preview)

        self.nodes_moved: Signal[list[tuple[StepId, float, float]]] = Signal()
        # (source, target): the user connected source to target. Whether that is a legal link
        # is not this view's business — the action decides.
        self.link_requested: Signal[StepId, StepId] = Signal()
        self.create_requested: Signal[float, float] = Signal()
        # Everything picked, in the order it was picked: two steps is what a link verb reads.
        self.selection_changed: Signal[CanvasSelection] = Signal()

        self.selectionChanged.connect(self._on_selection)

    # -- what the activity puts in ---------------------------------------------------------

    def sync(self, nodes: list[NodeSpec], edges: list[EdgeRef]) -> None:
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
        for gone_node in set(self._nodes) - wanted:
            self.removeItem(self._nodes.pop(gone_node))

        drawable = {ref for ref in edges if ref.source in self._nodes and ref.waiter in self._nodes}
        for gone_edge in set(self._edges) - drawable:
            self.removeItem(self._edges.pop(gone_edge))
        for ref in drawable:
            edge = self._edges.get(ref)
            if edge is None:
                edge = self._edges[ref] = EdgeItem(
                    self._nodes[ref.source], self._nodes[ref.waiter], ref.kind
                )
                self.addItem(edge)
            else:
                edge.follow()  # A node may have moved under it since the last sync.
        self._extend_scene_rect()

    def reflow_edges(self, step_id: StepId) -> None:
        """Redraw the edges touching one node — called by the item while it is dragged."""
        for edge in self._edges.values():
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
        self.selection_changed.emit(self.selection())

    def selection(self) -> CanvasSelection:
        return CanvasSelection(steps=tuple(self._selection_order), edges=self._selected_edges())

    def selected_step(self) -> StepId | None:
        """The one selected step, or None when it is none or several."""
        return self._selection_order[0] if len(self._selection_order) == 1 else None

    # -- what a mode may ask ------------------------------------------------------------------

    def node_at(self, scene_pos: QPointF) -> StepNodeItem | None:
        for item in self.items(scene_pos):
            if isinstance(item, StepNodeItem):
                return item
        # A handle sticks out past the body, so a near miss still counts as its node.
        for node in self._nodes.values():
            if node.is_over_handle(scene_pos):
                return node
        return None

    def node(self, step_id: StepId) -> StepNodeItem | None:
        return self._nodes.get(step_id)

    def link_refusal(self, waiter: StepId, source: StepId) -> str | None:
        return self._link_refusal(waiter, source)

    def aim_preview(self, origin: QPointF, cursor: QPointF, ok: bool) -> None:
        self._preview.aim(origin, cursor, ok)
        self._preview.show()

    def hide_preview(self) -> None:
        self._preview.hide()

    def set_link_states(self, valid: StepId | None, invalid: StepId | None) -> None:
        for step_id, item in self._nodes.items():
            item.set_link_state(
                "valid" if step_id == valid else "invalid" if step_id == invalid else ""
            )

    # -- what Qt's own dragging did --------------------------------------------------------------
    #
    # Not a gesture: the modes own those. This is the record of what the default item drag
    # moved, and it has to be taken after Qt has updated the selection — which is exactly why
    # it stays here, where the event arrives already handled.

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        super().mousePressEvent(event)
        self._press_at = {
            item.step_id: item.pos()
            for item in self.selectedItems()
            if isinstance(item, StepNodeItem)
        }

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        moved = [
            (step_id, self._nodes[step_id].pos().x(), self._nodes[step_id].pos().y())
            for step_id, was in self._press_at.items()
            if step_id in self._nodes and self._nodes[step_id].pos() != was
        ]
        self._press_at = {}
        if moved:
            self.nodes_moved.emit(moved)
            self._extend_scene_rect()

    # -- internals ---------------------------------------------------------------------------

    def _selected_edges(self) -> tuple[EdgeRef, ...]:
        return tuple(
            sorted(item.ref for item in self.selectedItems() if isinstance(item, EdgeItem))
        )

    def _on_selection(self) -> None:
        current = {i.step_id for i in self.selectedItems() if isinstance(i, StepNodeItem)}
        kept = [step_id for step_id in self._selection_order if step_id in current]
        self._selection_order = kept + [s for s in current if s not in kept]
        self.selection_changed.emit(self.selection())

    def _extend_scene_rect(self) -> None:
        """Grow the scrollable area to hold the graph — and never shrink or shift it.

        Recomputing it from ``itemsBoundingRect`` moved its origin every time a node moved,
        the scroll bars re-ranged under a fixed value, and the whole canvas appeared to pan
        away under the node being dragged. So the rect is a floor: it only ever unions, and
        it is not touched at all while a drag is in flight.
        """
        if self._press_at:
            return
        bounds = self.itemsBoundingRect().adjusted(
            -SCENE_MARGIN, -SCENE_MARGIN, SCENE_MARGIN, SCENE_MARGIN
        )
        self.setSceneRect(bounds if self.sceneRect().isEmpty() else bounds.united(self.sceneRect()))


class GraphView(QGraphicsView):
    """The viewport, and where input is routed.

    Every event is offered to the current mode first, then to the canvas keymap, and only
    then to Qt — which is what still gives rubber-band selection, node dragging and
    hand-scrolling for nothing.
    """

    def __init__(
        self,
        scene: GraphScene,
        base_mode: Callable[[CanvasDeps], ModeBase],
        status: Callable[[str], None],
        run_action: Callable[[str], bool],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(scene, parent)
        self.setObjectName("GraphView")
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        # The other half of "do not pan when a node moves": with the default centring
        # alignment, a scene smaller than the viewport re-centres itself every time its rect
        # changes, so growing the rect slid the content sideways.
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._zoom = 1.0
        self._framed = False
        # The application's View ▸ Zoom is font size; a canvas zooms itself.
        install_ctrl_wheel_zoom(self, self.zoom_by)

        self.deps = CanvasDeps(canvas=scene, view=self, status=status, run_action=run_action)
        self.modes = ModeStack(base_mode(self.deps))
        # Space is released after the drag it started often enough that popping immediately
        # would strand the hand cursor mid-pan; the pop waits for the button.
        self._pan_release_pending = False

    # -- input -------------------------------------------------------------------------------

    def _event_of(self, event: QMouseEvent) -> CanvasEvent:
        return CanvasEvent(
            scene_pos=self.mapToScene(event.position().toPoint()),
            button=event.button(),
            buttons=event.buttons(),
            modifiers=event.modifiers(),
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if self.modes.current().mouse_press(self._event_of(event)):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if self.modes.current().mouse_move(self._event_of(event)):
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if self.modes.current().mouse_release(self._event_of(event)):
            event.accept()
        else:
            super().mouseReleaseEvent(event)
        if self._pan_release_pending and not event.buttons():
            self._pan_release_pending = False
            self.modes.pop()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if self.modes.current().double_click(self._event_of(event)):
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        key = CanvasKey(event.key(), event.modifiers(), event.isAutoRepeat())
        if self.modes.current().key_press(key) or self._canvas_key(key):
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        key = CanvasKey(event.key(), event.modifiers(), event.isAutoRepeat())
        if self.modes.current().key_release(key):
            event.accept()
            return
        if key.key == Qt.Key.Key_Space and not key.auto_repeat:
            if isinstance(self.modes.current(), PanMode):
                if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
                    self._pan_release_pending = True
                else:
                    self.modes.pop()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _canvas_key(self, key: CanvasKey) -> bool:
        """The layer under the modes: leaving one, entering pan, and the bound verbs."""
        if key.key == Qt.Key.Key_Escape:
            return self.modes.pop()
        if key.key == Qt.Key.Key_Space and not key.auto_repeat:
            if not isinstance(self.modes.current(), PanMode):
                self.modes.push(PanMode(self.deps))
            return True
        return any(self.deps.run_action(action_id) for action_id in self._bound(key))

    def _bound(self, key: CanvasKey) -> Sequence[str]:
        return bound_actions(key.key, key.modifiers)

    # -- looking at it -------------------------------------------------------------------------

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
