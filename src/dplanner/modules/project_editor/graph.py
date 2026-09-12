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

from PySide6.QtCore import QMimeData, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFocusEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsScene,
    QGraphicsSceneMouseEvent,
    QGraphicsView,
    QWidget,
)

from dplanner.core.signals import Signal
from dplanner.domain.model import EdgeEnd, Redirection, StepId
from dplanner.framework.widgets import install_ctrl_wheel_zoom
from dplanner.modules.project_editor.ground import paint_ground
from dplanner.modules.project_editor.items import (
    EdgeItem,
    LinkPreviewItem,
    OutlinePreviewItem,
    StepNodeItem,
)
from dplanner.modules.project_editor.keymap import bound_actions
from dplanner.modules.project_editor.look import DEFAULT_BACKGROUND
from dplanner.modules.project_editor.marks import Marks
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
from dplanner.modules.project_editor.positions import GRID, NODE_H, NODE_W, snapped
from dplanner.modules.project_editor.region_items import RegionItem
from dplanner.modules.project_editor.regions import Region
from dplanner.modules.project_editor.renderers import RING_STEP, NodeAccent, RenderHints
from dplanner.modules.project_editor.selection import CanvasSelection, EdgeRef, neighbourhood

# How often a live ring's dashes move: quick enough to read as motion, slow enough that an
# agent working for an hour costs the canvas nothing worth measuring.
RING_TICK_MS = 80

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
    x: float
    y: float
    accent: NodeAccent = field(default_factory=NodeAccent)
    ports: tuple[bool, bool] = (False, False)  # (something arrives, something leaves).
    size: tuple[float, float] = (NODE_W, NODE_H)  # The card's footprint, stored or default.


class GraphScene(QGraphicsScene):
    """Items and what is picked. Everything it decides, it decides by asking the model."""

    def __init__(
        self,
        link_refusal: Callable[[StepId, StepId], str | None],
        redirection: Callable[[Sequence[EdgeRef], StepId, EdgeEnd], Redirection],
    ) -> None:
        super().__init__()
        self._link_refusal = link_refusal
        self._redirection = redirection
        self._hints = RenderHints()
        self._marks = Marks()
        # Whether gestures land on the grid — the user's setting, pushed by the module.
        self._snap = True
        # The spotlight, from its two sources: the user's look, and a key held for a moment.
        # Either lights it, so letting go of the key never switches the preference off.
        self._spotlight = False
        self._spotlight_held = False
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
        self._outline = OutlinePreviewItem()
        self._outline.hide()
        self.addItem(self._outline)

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
        # A card that finished resizing: seat and size together, since an edge may have
        # moved the seat — one gesture, one command.
        self.node_resized: Signal[StepId, float, float, float, float] = Signal()
        # The cards a divide pushed aside, at their new seats — one gesture, one command.
        self.graph_divided: Signal[list[tuple[StepId, float, float]]] = Signal()
        # The step the picked links are to hang off, and which of their ends moves.
        self.redirect_requested: Signal[StepId, EdgeEnd] = Signal()

        self.selectionChanged.connect(self._on_selection)

        # The live rings' clock: one timer for every node wearing one, running only while
        # there is one — an idle canvas ticks nothing. Sync settles it; nothing else does.
        self._ring_phase = 0.0
        self._ring_timer = QTimer(self)
        self._ring_timer.setInterval(RING_TICK_MS)
        self._ring_timer.timeout.connect(self.advance_rings)

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
                item.set_marks(self._marks)
                self.addItem(item)
            item.set_title(spec.title)
            item.set_accent(spec.accent)
            item.set_ports(spec.ports)
            # A node being dragged or resized owns its geometry until the gesture ends. The
            # model is authoritative everywhere else — including when the CLI writes mid-drag.
            if spec.step_id not in self._press_at and spec.step_id not in self._held_steps:
                item.setPos(spec.x, spec.y)
                item.set_size(*spec.size)
        for gone_node in set(self._nodes) - wanted:
            self.removeItem(self._nodes.pop(gone_node))
        self._settle_ring_timer()

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
        self._light_selection()  # The graph changed under the selection; re-derive.

    def advance_rings(self) -> None:
        """One tick: every live ring's dashes move on together."""
        self._ring_phase = (self._ring_phase + RING_STEP) % 1000.0
        for item in self._nodes.values():
            item.set_ring_phase(self._ring_phase)

    def _settle_ring_timer(self) -> None:
        live = any(item.wears_ring() for item in self._nodes.values())
        if live and not self._ring_timer.isActive():
            self._ring_timer.start()
        elif not live and self._ring_timer.isActive():
            self._ring_timer.stop()

    def reflow_edges(self, step_id: StepId) -> None:
        """Redraw the edges touching one node — called by the item while it is dragged."""
        for edge in self._edges.values():
            if edge.source.step_id == step_id or edge.waiter.step_id == step_id:
                edge.follow()

    def node_rects(self) -> list[QRectF]:
        """Where every card sits — the bodies, not the bounding rects with their margins
        for shadow and stat — for anything that draws or frames the graph."""
        return [item.body_scene_rect() for item in self._nodes.values()]

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

    def nodes(self) -> list[StepNodeItem]:
        """Every card — what a divide parts into the side that moves and the side that stays."""
        return list(self._nodes.values())

    def link_refusal(self, waiter: StepId, source: StepId) -> str | None:
        return self._link_refusal(waiter, source)

    def redirection(self, edges: Sequence[EdgeRef], anchor: StepId, end: EdgeEnd) -> Redirection:
        return self._redirection(edges, anchor, end)

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

    def set_marks(self, marks: Marks) -> None:
        """Fan the user's marks out to every node, the same way."""
        self._marks = marks
        for item in self._nodes.values():
            item.set_marks(marks)

    def set_spotlight(self, on: bool) -> None:
        """Whether the user's look fades what the selection is not linked to."""
        if on != self._spotlight:
            self._spotlight = on
            self._light_selection()

    def hold_spotlight(self, on: bool) -> None:
        """The same, for as long as a key is held — the view's Alt, and the view's to end."""
        if on != self._spotlight_held:
            self._spotlight_held = on
            self._light_selection()

    def set_snap(self, on: bool) -> None:
        """Whether gestures land on the grid from now on. Nothing already placed moves."""
        self._snap = on

    def snap(self, value: float) -> float:
        """A coordinate as a gesture should land it: on the grid while snapping, else as it
        is. Items and modes both run their numbers through this one door."""
        return snapped(value, GRID) if self._snap else value

    def nodes_touching(self, path: QPainterPath) -> list[StepNodeItem]:
        """The steps whose card the outline touches — what a lasso picks.

        By the card, not ``items(path)``: a node's hit shape is its bounding rect, which
        reaches the paint margin out on every side, and the edges are items too.
        """
        return [node for node in self._nodes.values() if path.intersects(node.body_scene_rect())]

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
            node for node in self._nodes.values() if rect.contains(node.body_scene_rect().center())
        ]

    def aim_outline(self, path: QPainterPath) -> None:
        self._outline.aim(path)
        self._outline.show()

    def hide_outline(self) -> None:
        self._outline.hide()

    def hold(self, region_id: str | None, step_ids: set[StepId]) -> None:
        """A mode owns this region's geometry — and these steps' — until it releases."""
        self._held_region = region_id
        self._held_steps = step_ids

    def release(self) -> None:
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

    def _light_selection(self) -> None:
        """Light the selection's arrows, and fade what the spotlight leaves out.

        One derivation, two readers. The arrows hanging off a picked step are lit whatever
        the look says — that is how a card says what it is connected to — and the spotlight,
        from the preference or the held key, fades every node and arrow the neighbourhood
        does not name. **Nothing picked lights nothing**: the neighbourhood of an empty
        selection is empty, so a spotlight over one dims nothing rather than everything.
        """
        near = neighbourhood(self._edges, self._selection_order)
        dim = (self._spotlight or self._spotlight_held) and bool(near.steps)
        for step_id, item in self._nodes.items():
            item.set_dimmed(dim and step_id not in near.steps)
        for ref, edge in self._edges.items():
            edge.set_lit(ref in near.edges)
            edge.set_dimmed(dim and ref not in near.edges)

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
        self._light_selection()
        self.selection_changed.emit(self.selection())


class GraphView(QGraphicsView):
    """The viewport, and where input is routed.

    Every event is offered to the current mode first, then to the canvas keymap, and only
    then to Qt — which is what still gives rubber-band selection, node dragging and
    hand-scrolling for nothing.

    **It looks onto a plane, so it has no scroll bars.** On a scrollable area whose extent is
    two hundred viewports across, a scroll bar is a nub that says nothing true about where
    you are; the minimap in the corner says it instead, and the wheel still scrolls because
    a hidden scroll bar is still a scroll bar. Ctrl+wheel zooms; holding Space and dragging,
    or Space with the arrows or ``hjkl``, moves the plane by hand.

    **Alt spotlights while it is held.** Not a mode and not a verb: it changes nothing about
    what input means, so it is the same look ``canvas.spotlight`` switches on for good, lent
    for as long as the key is down. The view holds it because only the view knows when the
    keyboard goes — and Alt+Tab is precisely Alt held and then taken away.
    """

    def __init__(
        self,
        scene: GraphScene,
        base_mode: Callable[[CanvasDeps], ModeBase],
        status: Callable[[str], None],
        run_action: Callable[[str], bool],
        parent: QWidget | None = None,
        accepts: Callable[[QMimeData], bool] = lambda _mime: False,
        dropped: Callable[[QMimeData, QPointF], None] = lambda _mime, _pos: None,
    ) -> None:
        super().__init__(scene, parent)
        self.setObjectName("GraphView")
        # A drop is a one-shot gesture, not a mode: Qt's drag events never reach the
        # mouse handlers below, and a mode has state to enter and leave where a drop has
        # neither. So it takes the double-click's road — record the point, hand it up.
        self._accepts = accepts
        self._dropped = dropped
        self.setAcceptDrops(True)
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
        # What lies under the graph — the user's look, pushed by the activity like the marks.
        self._background = DEFAULT_BACKGROUND
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
        # Where the user last pointed at the plane, in scene coordinates — what New places
        # a node at. Recorded for every button, before the mode stack gets a say: "where I
        # last clicked" is true whether or not a mode claimed the press, and a right-click
        # has to count or the menu's own New would land somewhere else.
        self.last_click: QPointF | None = None

    # -- input -------------------------------------------------------------------------------

    def _event_of(self, event: QMouseEvent) -> CanvasEvent:
        return CanvasEvent(
            scene_pos=self.mapToScene(event.position().toPoint()),
            view_pos=event.position(),
            button=event.button(),
            buttons=event.buttons(),
            modifiers=event.modifiers(),
        )

    def note_click(self, scene_pos: QPointF) -> None:
        """Remember a point as the last one pointed at — also called for a context menu
        raised by the keyboard, which sends no press."""
        self.last_click = scene_pos

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - Qt override
        if self._accepts(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802 - Qt override
        if self._accepts(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 - Qt override
        if not self._accepts(event.mimeData()):
            super().dropEvent(event)
            return
        scene_pos = self.mapToScene(event.position().toPoint())
        self.note_click(scene_pos)
        self._dropped(event.mimeData(), scene_pos)
        event.acceptProposedAction()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        self.note_click(self.mapToScene(event.position().toPoint()))
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
        if key.key == Qt.Key.Key_Alt and not key.auto_repeat:
            self._hold_spotlight(False)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt override
        # A held key ends when the keyboard does: Alt+Tab is Alt held and then taken away,
        # and its release is delivered to whatever the user switched to. Without this the
        # canvas would still be spotlit when they came back.
        self._hold_spotlight(False)
        super().focusOutEvent(event)

    def _hold_spotlight(self, on: bool) -> None:
        scene = self.scene()
        if isinstance(scene, GraphScene):
            scene.hold_spotlight(on)

    def _canvas_key(self, key: CanvasKey) -> bool:
        """The layer under the modes: leaving one, entering pan, spotlighting, and the
        bound verbs."""
        if key.key == Qt.Key.Key_Escape:
            return self.modes.pop()
        if key.key == Qt.Key.Key_Space and not key.auto_repeat:
            if not isinstance(self.modes.current(), PanMode):
                self.modes.push(PanMode(self.deps))
            return True
        if key.key == Qt.Key.Key_Alt and not key.auto_repeat:
            self._hold_spotlight(True)
            return True
        return any(self.deps.run_action(action_id) for action_id in self._bound(key))

    def _bound(self, key: CanvasKey) -> Sequence[str]:
        return bound_actions(key.key, key.modifiers)

    # -- looking at it -------------------------------------------------------------------------

    def set_background(self, name: str) -> None:
        """Change what is drawn under the graph — a ``look.BACKGROUNDS`` name. Snapping is
        the scene's half of the same look; the activity pushes both."""
        if name != self._background:
            self._background = name
            self.viewport().update()

    def drawBackground(self, painter: QPainter, rect: QRectF | QRect) -> None:  # noqa: N802
        # The plain ground first (the stylesheet's colour), then the grid over it. The
        # palette is the view's own, read now, so a theme switch repaints the grid with the
        # graph — the same rule as items.live_palette.
        super().drawBackground(painter, rect)
        paint_ground(painter, QRectF(rect), self.palette(), self._background, self._zoom)

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
            self.minimap.show_graph(scene.node_rects(), self._looking_at(), scene.region_rects())

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
