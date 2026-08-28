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
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter, QResizeEvent
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
from dplanner.modules.project_editor.items import (
    EdgeItem,
    LinkPreviewItem,
    RegionItem,
    RegionPreviewItem,
    StepNodeItem,
)
from dplanner.modules.project_editor.keymap import bound_actions
from dplanner.modules.project_editor.minimap import Minimap
from dplanner.modules.project_editor.modes import (
    HINTS_BY_MODE,
    CanvasDeps,
    CanvasEvent,
    CanvasKey,
    ModeBase,
    ModeStack,
    PanMode,
)
from dplanner.modules.project_editor.regions import Region
from dplanner.modules.project_editor.renderers import NodeAccent, RenderHints
from dplanner.modules.project_editor.selection import CanvasSelection, EdgeRef

ZOOM_MIN = 0.4
ZOOM_MAX = 2.5
# The furthest the view zooms itself out to fit a graph; below this a node is unreadable
# and scrolling is the better answer.
ZOOM_READABLE = 0.75
FRAME_PADDING = 40.0
ZOOM_STEP = 1.15
# The canvas is a plane, not a page: the scrollable area is this far out in every direction
# from the origin and never moves, so panning stops nowhere anybody will reach and no graph
# can change where the edges are. Large enough to be unbounded in practice, small enough
# that the scroll ranges stay well inside an int at maximum zoom.
CANVAS_EXTENT = 100_000.0


@dataclass(frozen=True)
class NodeSpec:
    step_id: StepId
    title: str
    subtitle: str
    x: float
    y: float
    accent: NodeAccent = field(default_factory=NodeAccent)


class GraphScene(QGraphicsScene):
    """Items and what is picked. Everything it decides, it decides by asking the model."""

    def __init__(self, link_refusal: Callable[[StepId, StepId], str | None]) -> None:
        super().__init__()
        self._link_refusal = link_refusal
        self._hints = RenderHints()
        self._nodes: dict[StepId, StepNodeItem] = {}
        self._edges: dict[EdgeRef, EdgeItem] = {}
        self._regions: dict[str, RegionItem] = {}
        # Both the drag record and the "this node owns its own position" guard: one dict,
        # so the two can never disagree.
        self._press_at: dict[StepId, QPointF] = {}
        # The same pair for regions: Qt-driven frame drags are recorded here, and a mode
        # holding a gesture (a body drag, a resize) registers what it owns so sync leaves
        # the geometry alone until the gesture ends.
        self._region_press: dict[str, QPointF] = {}
        self._held_region: str | None = None
        self._held_steps: set[StepId] = set()
        # Click order, which QGraphicsScene.selectedItems() does not preserve. It is what
        # makes `Context.selected_entities("step")` mean "the first, then the second".
        self._selection_order: list[StepId] = []
        self.setSceneRect(
            QRectF(-CANVAS_EXTENT, -CANVAS_EXTENT, 2 * CANVAS_EXTENT, 2 * CANVAS_EXTENT)
        )
        self._preview = LinkPreviewItem()
        self._preview.hide()
        self.addItem(self._preview)
        self._region_preview = RegionPreviewItem()
        self._region_preview.hide()
        self.addItem(self._region_preview)

        self.nodes_moved: Signal[list[tuple[StepId, float, float]]] = Signal()
        # (source, target): the user connected source to target. Whether that is a legal link
        # is not this view's business — the action decides.
        self.link_requested: Signal[StepId, StepId] = Signal()
        self.create_requested: Signal[float, float] = Signal()
        # Everything picked, in the order it was picked: two steps is what a link verb reads.
        self.selection_changed: Signal[CanvasSelection] = Signal()
        self.region_create_requested: Signal[float, float, float, float] = Signal()
        # Regions that finished moving, with the steps a body drag carried — one gesture,
        # one emission, so the activity can make it one undo step.
        self.regions_moved: Signal[
            list[tuple[str, float, float]], list[tuple[StepId, float, float]]
        ] = Signal()
        self.region_resized: Signal[str, float, float, float, float] = Signal()

        self.selectionChanged.connect(self._on_selection)

    # -- what the activity puts in ---------------------------------------------------------

    def sync(
        self, nodes: list[NodeSpec], edges: list[EdgeRef], regions: Sequence[Region] = ()
    ) -> None:
        wanted = {spec.step_id for spec in nodes}
        for spec in nodes:
            item = self._nodes.get(spec.step_id)
            if item is None:
                item = self._nodes[spec.step_id] = StepNodeItem(spec.step_id)
                item.set_render_hints(self._hints)  # A node born mid-mode dresses for it.
                self.addItem(item)
            item.set_text(spec.title, spec.subtitle)
            item.set_accent(spec.accent)
            # A node being dragged owns its position until the gesture ends. The model is
            # authoritative everywhere else — including when the CLI writes mid-drag.
            if spec.step_id not in self._press_at and spec.step_id not in self._held_steps:
                item.setPos(spec.x, spec.y)
        for gone_node in set(self._nodes) - wanted:
            self.removeItem(self._nodes.pop(gone_node))

        wanted_regions = {region.id for region in regions}
        for region in regions:
            frame = self._regions.get(region.id)
            if frame is None:
                frame = self._regions[region.id] = RegionItem(region.id)
                self.addItem(frame)
            frame.set_title(region.title)
            # Same guard as a node's: a region mid-gesture owns its own geometry.
            if region.id not in self._region_press and region.id != self._held_region:
                frame.setPos(region.x, region.y)
                frame.set_rect(region.w, region.h)
        for gone_region in set(self._regions) - wanted_regions:
            self.removeItem(self._regions.pop(gone_region))

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

    def reflow_edges(self, step_id: StepId) -> None:
        """Redraw the edges touching one node — called by the item while it is dragged."""
        for edge in self._edges.values():
            if edge.source.step_id == step_id or edge.waiter.step_id == step_id:
                edge.follow()

    def node_rects(self) -> list[QRectF]:
        """Where every node sits, for anything that draws the graph small."""
        return [item.sceneBoundingRect() for item in self._nodes.values()]

    def region_rects(self) -> list[QRectF]:
        """Where every region sits — the faint outlines behind the minimap's dots."""
        return [item.sceneBoundingRect() for item in self._regions.values()]

    def content_rect(self) -> QRectF:
        """What the graph actually occupies — regions included, so framing shows them."""
        rect = QRectF()
        for item in self.node_rects() + self.region_rects():
            rect = rect.united(item)
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
        return CanvasSelection(
            steps=tuple(self._selection_order),
            edges=self._selected_edges(),
            regions=self._selected_regions(),
        )

    def select_region(self, region_id: str) -> None:
        """Make one region the whole selection — a body click, or a rename about to ask."""
        self.clearSelection()
        self._selection_order = []
        item = self._regions.get(region_id)
        if item is not None:
            item.setSelected(True)

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

    def set_render_hints(self, hints: "RenderHints") -> None:
        """Fan the current mode's wishes out to every node — the set_link_states shape."""
        self._hints = hints
        for item in self._nodes.values():
            item.set_render_hints(hints)

    def region_at(self, scene_pos: QPointF) -> RegionItem | None:
        """The region under this point — by the full rect, not Qt's hit shape, because a
        body press is exactly what the hit shape hides from Qt. Later-created wins, matching
        what is painted on top."""
        for item in reversed(list(self._regions.values())):
            if item.contains_point(scene_pos):
                return item
        return None

    def nodes_inside(self, region: RegionItem) -> list[StepNodeItem]:
        """The steps whose centres lie inside — what a body drag carries."""
        origin = region.pos()
        w, h = region.size()
        rect = QRectF(origin.x(), origin.y(), w, h)
        return [
            node
            for node in self._nodes.values()
            if rect.contains(node.sceneBoundingRect().center())
        ]

    def aim_region_preview(self, rect: QRectF) -> None:
        self._region_preview.aim(rect)
        self._region_preview.show()

    def hide_region_preview(self) -> None:
        self._region_preview.hide()

    def hold_region(self, region_id: str, step_ids: set[StepId]) -> None:
        """A mode owns this region's geometry — and these steps' — until it releases."""
        self._held_region = region_id
        self._held_steps = step_ids

    def release_region(self) -> None:
        self._held_region = None
        self._held_steps = set()

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
        self._region_press = {
            item.region_id: item.pos()
            for item in self.selectedItems()
            if isinstance(item, RegionItem)
        }

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        moved = [
            (step_id, self._nodes[step_id].pos().x(), self._nodes[step_id].pos().y())
            for step_id, was in self._press_at.items()
            if step_id in self._nodes and self._nodes[step_id].pos() != was
        ]
        self._press_at = {}
        region_moves = [
            (region_id, self._regions[region_id].pos().x(), self._regions[region_id].pos().y())
            for region_id, was in self._region_press.items()
            if region_id in self._regions and self._regions[region_id].pos() != was
        ]
        self._region_press = {}
        if moved:
            self.nodes_moved.emit(moved)
        if region_moves:
            # A Qt-driven drag grabbed the strip or border, so the frame moved alone.
            self.regions_moved.emit(region_moves, [])

    # -- internals ---------------------------------------------------------------------------

    def _selected_edges(self) -> tuple[EdgeRef, ...]:
        return tuple(
            sorted(item.ref for item in self.selectedItems() if isinstance(item, EdgeItem))
        )

    def _selected_regions(self) -> tuple[str, ...]:
        return tuple(
            sorted(item.region_id for item in self.selectedItems() if isinstance(item, RegionItem))
        )

    def _on_selection(self) -> None:
        current = {i.step_id for i in self.selectedItems() if isinstance(i, StepNodeItem)}
        kept = [step_id for step_id in self._selection_order if step_id in current]
        self._selection_order = kept + [s for s in current if s not in kept]
        self.selection_changed.emit(self.selection())


class GraphView(QGraphicsView):
    """The viewport, and where input is routed.

    Every event is offered to the current mode first, then to the canvas keymap, and only
    then to Qt — which is what still gives rubber-band selection, node dragging and
    hand-scrolling for nothing.

    **It looks onto a plane, so it has no scroll bars.** On a scrollable area whose extent is
    two hundred viewports across, a scroll bar is a nub that says nothing true about where
    you are; the minimap in the corner says it instead, and the wheel still scrolls because
    a hidden scroll bar is still a scroll bar.
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
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._zoom = 1.0
        self._framed = False
        # The application's View ▸ Zoom is font size; a canvas zooms itself.
        install_ctrl_wheel_zoom(self, self.zoom_by)
        self.minimap = Minimap(self)
        scene.changed.connect(self._on_scene_changed)
        # The plane is centred on the origin and the automatic layout starts there, so this
        # is where the graph will be even before there is one to frame.
        self.centerOn(QPointF(0.0, 0.0))

        self.deps = CanvasDeps(canvas=scene, view=self, status=status, run_action=run_action)
        self.modes = ModeStack(base_mode(self.deps))
        # The mode's look reaches the nodes here: one subscription on the stack, not
        # per-mode enter/exit — Space stacks Pan over Connect, and popping back must
        # restore Connect's hints, which only the stack's current answer gets right.
        self.modes.changed.connect(
            lambda name: scene.set_render_hints(HINTS_BY_MODE.get(name, RenderHints()))
        )
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

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self.minimap.place()
        self._refresh_minimap()

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # noqa: N802 - Qt override
        super().scrollContentsBy(dx, dy)
        self._refresh_minimap()

    def _on_scene_changed(self, _regions: list[QRectF]) -> None:
        self._refresh_minimap()

    def _refresh_minimap(self) -> None:
        """Hand the map what to draw.

        Asked of the scene here rather than fetched by the map, so that the one object that
        knows whether there is still a scene to ask is the one that asks. A view whose scene
        has gone — which is what tearing a tab down looks like from here — simply says
        nothing, and the map keeps its last picture until it goes too.
        """
        scene = self.scene()
        if isinstance(scene, GraphScene):
            self.minimap.show_graph(
                scene.node_rects(), self._looking_at(), scene.region_rects()
            )

    def _looking_at(self) -> QRectF:
        return self.mapToScene(self.viewport().rect()).boundingRect()

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
            self.centerOn(QPointF(0.0, 0.0))
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
        self._refresh_minimap()

    def zoom_by(self, steps: int) -> None:
        factor = ZOOM_STEP**steps
        wanted = max(ZOOM_MIN, min(ZOOM_MAX, self._zoom * factor))
        if wanted != self._zoom:
            self.scale(wanted / self._zoom, wanted / self._zoom)
            self._zoom = wanted
            self._refresh_minimap()
