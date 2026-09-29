"""The canvas: steps as nodes, edges as arrows, stacks as frames round their cards, and what
the user has picked out of them.

**Every item diffs by key.** :meth:`GraphScene.sync` reconciles nodes by step id, frames by
stack id and edges by :class:`EdgeRef` — creating, updating and removing, never clearing — for
one reason that covers them all: an item the user is holding on to must keep its identity. A
node may be under the mouse mid-drag; an edge may be selected, waiting for Delete. Rebuilding
either wholesale throws that away, and the edges used to be rebuilt wholesale, which is why
they could not be selected.

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

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
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
from dplanner.domain.model import WAITER, EdgeEnd, Redirection, StepId
from dplanner.framework.widgets import install_ctrl_wheel_zoom
from dplanner.modules.project_editor.ground import paint_ground
from dplanner.modules.project_editor.items import (
    EdgeItem,
    LinkPreviewItem,
    OutlinePreviewItem,
    StackAddItem,
    StackItem,
    StepNodeItem,
)
from dplanner.modules.project_editor.keymap import bound_actions
from dplanner.modules.project_editor.look import DEFAULT_BACKGROUND
from dplanner.modules.project_editor.marks import Marks
from dplanner.modules.project_editor.minimap import Minimap
from dplanner.modules.project_editor.modes import (
    HINTS_BY_MODE,
    IDLE,
    CanvasDeps,
    CanvasEvent,
    CanvasKey,
    ModeBase,
    ModeStack,
    PanMode,
)
from dplanner.modules.project_editor.positions import GRID, NODE_H, NODE_W, snapped
from dplanner.modules.project_editor.renderers import (
    RING_STEP,
    EdgeAccent,
    NodeAccent,
    RenderHints,
)
from dplanner.modules.project_editor.ruler import RULER_H, Heading, WaveRuler
from dplanner.modules.project_editor.selection import CanvasSelection, EdgeRef, neighbourhood
from dplanner.modules.project_editor.sorts import H_GAP
from dplanner.modules.project_editor.stacks import Stack

# How often the canvas's motion clock ticks — a live ring's dashes, a flowing arrow's
# chevrons, a pulse's breath: quick enough to read as motion, slow enough that an agent
# working for an hour costs the canvas nothing worth measuring.
MOTION_TICK_MS = 80

# An arrow the sync names no accent for.
PLAIN_EDGE = EdgeAccent()

ZOOM_MIN = 0.4
ZOOM_MAX = 2.5
# The furthest the view zooms itself out to fit a graph; below this a node is unreadable
# and scrolling is the better answer.
ZOOM_READABLE = 0.75
FRAME_PADDING = 40.0
ZOOM_STEP = 1.15
# Wave view's band behind every other column: text ink at about 12 %, so the columns read at
# a glance in both house themes — the guide's 2 % was too faint to see (N179).
BAND_ALPHA = 30
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
        stack_refusal: Callable[[Stack, StepId | None], str | None],
    ) -> None:
        super().__init__()
        self._link_refusal = link_refusal
        self._redirection = redirection
        self._stack_refusal = stack_refusal
        self._hints = RenderHints()
        self._marks = Marks()
        # Whether gestures land on the grid — the user's setting, pushed by the module.
        self._snap = True
        # Whether every card's seat is derived (Wave view), so none is dragged or resized.
        self._pinned = False
        # The spotlight, from its two sources: the user's look, and a key held for a moment.
        # Either lights it, so letting go of the key never switches the preference off.
        self._spotlight = False
        self._spotlight_held = False
        self._nodes: dict[StepId, StepNodeItem] = {}
        self._edges: dict[EdgeRef, EdgeItem] = {}
        # Every stack's frame by stack id, and the frame each member stands in.
        self._frames: dict[str, StackItem] = {}
        self._frame_of: dict[StepId, StackItem] = {}
        # The frame saying what Shift does, because the pointer is over it.
        self._hinted: StackItem | None = None
        # A card in the hand of a restack, whose arrows are not drawn until it lands: every
        # drop rewires them, and drawn meanwhile they would run to where it no longer stands.
        self._lifted: StepId | None = None
        # True while sync places the cards: a moved card's stack is laid out once, after,
        # over the membership the sync brings — never over the one it is replacing.
        self._syncing = False
        # Both the drag record and the "this node owns its own position" guard: one dict,
        # so the two can never disagree.
        self._press_at: dict[StepId, QPointF] = {}
        # What a mode holding a gesture (a resize, a divide) owns, so sync leaves that
        # geometry alone until the gesture ends.
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
        # (sources, target): the user connected every source to target. Whether that is a
        # legal link is not this view's business — the action decides.
        self.link_requested: Signal[tuple[StepId, ...], StepId] = Signal()
        self.create_requested: Signal[float, float] = Signal()
        # Everything picked, in pick order: a link verb makes the last one wait on the rest.
        self.selection_changed: Signal[CanvasSelection] = Signal()
        # A card that finished resizing: seat and size together, since an edge may have
        # moved the seat — one gesture, one command.
        self.node_resized: Signal[StepId, float, float, float, float] = Signal()
        # The cards a divide pushed aside, at their new seats — one gesture, one command.
        self.graph_divided: Signal[list[tuple[StepId, float, float]]] = Signal()
        # The cards a contract pulled up to the other side, the same way.
        self.graph_contracted: Signal[list[tuple[StepId, float, float]]] = Signal()
        # The step the picked links are to hang off, and which of their ends moves.
        self.redirect_requested: Signal[StepId, EdgeEnd] = Signal()
        # A stack's "+" was pressed: a step is wanted below this one, its last.
        self.stack_add_requested: Signal[StepId] = Signal()
        # A card restacked and let go in the stack with this id, at this slot — to move
        # there if it is a member, to join if it is not.
        self.dropped_into_stack: Signal[StepId, str, int] = Signal()
        # A stack's card restacked out past its frame and let go at this seat.
        self.dropped_out_of_stack: Signal[StepId, float, float] = Signal()

        self.selectionChanged.connect(self._on_selection)
        # True while select_steps reconciles Qt's selection item by item, so
        # the per-item selectionChanged is not announced — one gesture, one announcement.
        self._reselecting = False

        # The canvas's one motion clock: one timer for every card that rings or pulses and
        # every arrow whose chevrons flow, running only while one does — an idle canvas
        # ticks nothing. Sync settles it; nothing else does.
        self._phase = 0.0
        self._motion_clock = QTimer(self)
        self._motion_clock.setInterval(MOTION_TICK_MS)
        self._motion_clock.timeout.connect(self.advance_motion)

    # -- what the activity puts in ---------------------------------------------------------

    def sync(
        self,
        nodes: list[NodeSpec],
        edges: list[EdgeRef],
        edge_accents: Mapping[EdgeRef, EdgeAccent] | None = None,
        stacks: Sequence[Stack] = (),
    ) -> None:
        """Make the scene the graph: ``edge_accents`` dresses the arrows it names, and an
        arrow it leaves out is plain. Cards first, then the stacks' frames round them, then
        the arrows — each over what the one before it has just placed."""
        accents = edge_accents or {}
        wanted = {spec.step_id for spec in nodes}
        self._syncing = True
        try:
            for spec in nodes:
                item = self._nodes.get(spec.step_id)
                if item is None:
                    item = self._nodes[spec.step_id] = StepNodeItem(spec.step_id)
                    item.set_render_hints(self._hints)  # A node born mid-mode dresses for it.
                    item.set_marks(self._marks)
                    item.set_pinned(self._pinned)
                    self.addItem(item)
                item.set_title(spec.title)
                item.set_accent(spec.accent)
                item.set_ports(spec.ports)
                # A node being dragged or resized owns its geometry until the gesture ends.
                # The model is authoritative everywhere else — including a CLI write mid-drag.
                if spec.step_id not in self._press_at and spec.step_id not in self._held_steps:
                    item.setPos(spec.x, spec.y)
                    item.set_size(*spec.size)
            for gone_node in set(self._nodes) - wanted:
                self.removeItem(self._nodes.pop(gone_node))
        finally:
            self._syncing = False
        self._sync_frames(stacks)

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
            edge.set_accent(accents.get(ref, PLAIN_EDGE))
        self._settle_motion_clock()
        self._light_selection()  # The graph changed under the selection; re-derive.

    def advance_motion(self) -> None:
        """One tick: every live ring's dashes, every pulse's breath and every flowing arrow's
        chevrons move on together."""
        self._phase = (self._phase + RING_STEP) % 1000.0
        for item in self._nodes.values():
            item.set_phase(self._phase)
        for edge in self._edges.values():
            edge.set_phase(self._phase)

    def _settle_motion_clock(self) -> None:
        live = any(item.moves() for item in self._nodes.values()) or any(
            edge.flows() for edge in self._edges.values()
        )
        if live and not self._motion_clock.isActive():
            self._motion_clock.start()
        elif not live and self._motion_clock.isActive():
            self._motion_clock.stop()

    def _sync_frames(self, stacks: Sequence[Stack]) -> None:
        """One frame per stack whose every member has a card, diffed by stack id like the
        cards, each told its members and laid out round them."""
        wanted = {s.id: s for s in stacks if all(m in self._nodes for m in s.members)}
        for gone in set(self._frames) - set(wanted):
            stale = self._frames.pop(gone)
            if stale is self._hinted:
                self._hinted = None
            self.removeItem(stale.add)
            self.removeItem(stale)
        self._frame_of = {}
        for stack in wanted.values():
            frame = self._frames.get(stack.id)
            if frame is None:
                frame = self._frames[stack.id] = StackItem(stack)
                self.addItem(frame)
                self.addItem(frame.add)
            frame.set_stack(stack, [self._nodes[member] for member in stack.members])
            for member in stack.members:
                self._frame_of[member] = frame
        for step_id, node in self._nodes.items():
            node.set_frame(self._frame_of.get(step_id))
        for frame in self._frames.values():
            frame.follow()

    def reflow_edges(self, step_id: StepId) -> None:
        """Redraw what touches one node — called by the item while it moves or resizes.

        A card in a stack moves its stack's column and frame first, and then every arrow
        touching any member: the frame's middle, where its ports are, depends on them all.
        """
        if self._syncing:
            return  # Sync lays out every frame and follows every arrow once it is done.
        frame = self._frame_of.get(step_id)
        if frame is not None:
            if frame.following():
                return  # The frame is moving its own members; it follows once, after.
            frame.follow()
            touched = set(frame.stack.members)
        else:
            touched = {step_id}
        for edge in self._edges.values():
            if edge.source.step_id in touched or edge.waiter.step_id in touched:
                edge.follow()

    def node_rects(self) -> list[QRectF]:
        """Where every card sits — the bodies, not the bounding rects with their margins
        for shadow and stat — for anything that draws or frames the graph."""
        return [item.body_scene_rect() for item in self._nodes.values()]

    def content_rect(self) -> QRectF:
        """What the graph actually occupies — what framing fits the view to."""
        rect = QRectF()
        for item in self.node_rects():
            rect = rect.united(item)
        return rect

    def select_step(self, step_id: StepId | None) -> None:
        self.select_steps([] if step_id is None else [step_id])

    def select_steps(self, step_ids: list[StepId]) -> None:
        """Select these, in this order — which is what a two-step verb reads back."""
        self._select(step_ids, ())

    def select_edges(self, refs: Sequence[EdgeRef]) -> None:
        """Pick these arrows and nothing else — a right-click on one, or *Only Links*."""
        self._select((), refs)

    def _select(self, step_ids: Sequence[StepId], refs: Sequence[EdgeRef]) -> None:
        self._reselecting = True
        try:
            self.clearSelection()
            for step_id in step_ids:
                item = self._nodes.get(step_id)
                if item is not None:
                    item.setSelected(True)
            for ref in refs:
                edge = self._edges.get(ref)
                if edge is not None:
                    edge.setSelected(True)
        finally:
            self._reselecting = False
        # setSelected fires selectionChanged one item at a time and Qt reports the set
        # unordered, so the order asked for is restored here, lit and announced once.
        self._selection_order = [s for s in step_ids if s in self._nodes]
        self._light_selection()
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

    def edge_at(self, scene_pos: QPointF) -> EdgeItem | None:
        """The arrow under a point, by its stroked shape. A card drawn over one wins, so
        ask :meth:`node_at` first."""
        for item in self.items(scene_pos):
            if isinstance(item, EdgeItem):
                return item
        return None

    def node(self, step_id: StepId) -> StepNodeItem | None:
        return self._nodes.get(step_id)

    def stacks(self) -> list[Stack]:
        """The stacks drawn now — every one whose members all have a card."""
        return [frame.stack for frame in self._frames.values()]

    def frame(self, stack_id: str) -> StackItem | None:
        return self._frames.get(stack_id)

    def stack_refusal(self, stack: Stack, joining: StepId | None) -> str | None:
        """Why this stack cannot be reordered — or cannot take ``joining`` — or None: the
        builders' own refusal, asked once as a gesture begins or finds a new stack."""
        return self._stack_refusal(stack, joining)

    def hint_at(self, scene_pos: QPointF | None) -> None:
        """Let the frame round this point say what Shift does, and every other be quiet. By
        the frame's rect, not what is drawn on top, so crossing its chain never flickers it."""
        frame = None
        if scene_pos is not None:
            frame = next(
                (f for f in self._frames.values() if f.frame_scene_rect().contains(scene_pos)),
                None,
            )
        if frame is not self._hinted:
            if self._hinted is not None:
                self._hinted.set_hinted(False)
            if frame is not None:
                frame.set_hinted(True)
            self._hinted = frame

    def lift_links(self, step_id: StepId | None) -> None:
        """Stop drawing this step's arrows until it lands — or, with None, draw them all."""
        if step_id != self._lifted:
            self._lifted = step_id
            self._light_selection()

    def frame_at(self, scene_pos: QPointF) -> Stack | None:
        """The stack whose frame (or its "+") is the topmost thing at a point — None when a
        card or an arrow is drawn over it there, which is then what the point means."""
        for item in self.items(scene_pos):
            if isinstance(item, StackItem):
                return item.stack
            if isinstance(item, StackAddItem):
                return item.frame.stack
            if isinstance(item, (StepNodeItem, EdgeItem)):
                return None
        return None

    def add_at(self, scene_pos: QPointF) -> Stack | None:
        """The stack whose "+" is under a point, unless a card is lifted over it."""
        for item in self.items(scene_pos):
            if isinstance(item, StackAddItem):
                return item.frame.stack
            if isinstance(item, (StepNodeItem, EdgeItem, StackItem)):
                return None
        return None

    def link_end(self, step_id: StepId, end: EdgeEnd) -> StepId:
        """The card a link end means when it lands on ``step_id``: a stack takes its links in
        at its first step and sends them out from its last, so an arrowhead aimed anywhere
        in one lands on the first and a tail on the last. A loose card is itself."""
        frame = self._frame_of.get(step_id)
        if frame is None:
            return step_id
        members = frame.stack.members
        return members[0] if end == WAITER else members[-1]

    def link_target_at(self, scene_pos: QPointF, end: EdgeEnd) -> StepNodeItem | None:
        """The card a link end at this point lands on: the card under it, or the stack it is
        on or over — its frame, its "+" — by :meth:`link_end`."""
        node = self.node_at(scene_pos)
        if node is not None:
            step_id = node.step_id
        else:
            stack = next(
                (
                    item.stack if isinstance(item, StackItem) else item.frame.stack
                    for item in self.items(scene_pos)
                    if isinstance(item, (StackItem, StackAddItem))
                ),
                None,
            )
            if stack is None:
                return None
            step_id = stack.head
        return self._nodes.get(self.link_end(step_id, end))

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

    def set_pinned(self, on: bool) -> None:
        """Whether every card's seat is derived rather than the hand's — Wave view's, whose
        seats the activity substitutes on every sync. Cards are still picked, linked and
        opened; none is dragged or resized, since nothing the hand did would be kept."""
        self._pinned = on
        for item in self._nodes.values():
            item.set_pinned(on)

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

    def aim_outline(self, path: QPainterPath) -> None:
        self._outline.aim(path)
        self._outline.show()

    def hide_outline(self) -> None:
        self._outline.hide()

    def hold(self, step_ids: set[StepId]) -> None:
        """A mode owns these steps' geometry until it releases."""
        self._held_steps = step_ids

    def release(self) -> None:
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

    # -- internals ---------------------------------------------------------------------------

    def _light_selection(self) -> None:
        """Light the selection's arrows, and fade what the spotlight leaves out.

        One derivation, two readers. The arrows hanging off a picked step are lit whatever
        the look says — that is how a card says what it is connected to — and the spotlight,
        from the preference or the held key, fades every node and arrow the neighbourhood
        does not name. **Nothing picked lights nothing**: the neighbourhood of an empty
        selection is empty, so a spotlight over one dims nothing rather than everything. A
        card in the hand of a restack draws none of its arrows until it lands.
        """
        near = neighbourhood(self._edges, self._selection_order)
        dim = (self._spotlight or self._spotlight_held) and bool(near.steps)
        for step_id, item in self._nodes.items():
            item.set_dimmed(dim and step_id not in near.steps)
        for ref, edge in self._edges.items():
            edge.set_lit(ref in near.edges)
            edge.set_dimmed(dim and ref not in near.edges)
            edge.setVisible(self._lifted not in (ref.source, ref.waiter))
        for frame in self._frames.values():
            frame.set_dimmed(dim and not near.steps.intersection(frame.stack.members))

    def _selected_edges(self) -> tuple[EdgeRef, ...]:
        return tuple(
            sorted(item.ref for item in self.selectedItems() if isinstance(item, EdgeItem))
        )

    def _on_selection(self) -> None:
        if self._reselecting:
            return
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
        self._centred_on: StepId | None = None
        # What lies under the graph — the user's look, pushed by the activity like the marks.
        self._background = DEFAULT_BACKGROUND
        # The application's View ▸ Zoom is font size; a canvas zooms itself.
        install_ctrl_wheel_zoom(self, self.zoom_by)
        self.minimap = Minimap(self)
        # Wave view's column headings, and the band behind every other column: both
        # empty — the ruler off screen — in Free view.
        self.ruler = WaveRuler(self)
        self._bands: list[tuple[float, float]] = []
        scene.changed.connect(self._on_scene_changed)
        # The plane is centred on the origin and the automatic layout starts there, so this
        # is where the graph will be even before there is one to frame.
        self.centerOn(QPointF(0.0, 0.0))

        self.deps = CanvasDeps(
            canvas=scene,
            view=self,
            status=status,
            run_action=run_action,
        )
        self.modes = ModeStack(base_mode(self.deps))

        # The mode's look reaches the nodes here: one subscription on the stack, not
        # per-mode enter/exit — Space stacks Pan over Connect, and popping back must
        # restore Connect's hints, which only the stack's current answer gets right. A
        # frame's Shift hint says what an idle press does, so any other mode quiets it.
        def on_mode(name: str) -> None:
            scene.set_render_hints(HINTS_BY_MODE.get(name, RenderHints()))
            if name != IDLE:
                scene.hint_at(None)

        self.modes.changed.connect(on_mode)
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

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        scene = self.scene()
        if isinstance(scene, GraphScene):
            scene.hint_at(None)
        super().leaveEvent(event)

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
        if self._bands:
            # Every other wave's column, the full height — painted with the ground rather
            # than as items, so it is never picked, framed or hit.
            band = QColor(self.palette().text().color())
            band.setAlpha(BAND_ALPHA)
            area = QRectF(rect)
            for left, right in self._bands:
                if right >= area.left() and left <= area.right():
                    painter.fillRect(QRectF(left, area.top(), right - left, area.height()), band)

    def show_waves(self, headings: Sequence[Heading]) -> None:
        """Wave view's chrome: the ruler saying these headings, and a band behind every
        other column. Nothing takes both away — Free view."""
        self.ruler.show_headings(headings)
        bands = [(h.left - H_GAP / 2, h.right + H_GAP / 2) for h in headings[1::2]]
        if bands != self._bands:
            self._bands = bands
            self.viewport().update()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self.minimap.place()
        self.ruler.place()
        self._follow_overlays()

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # noqa: N802 - Qt override
        super().scrollContentsBy(dx, dy)
        self._follow_overlays()

    def _on_scene_changed(self, _rects: list[QRectF]) -> None:
        self._refresh_minimap()

    def _follow_overlays(self) -> None:
        """The plane moved under the chrome: the map redraws where you are, and the ruler's
        headings follow their columns across."""
        self._refresh_minimap()
        self.ruler.update()

    def _refresh_minimap(self) -> None:
        """Hand the map what to draw.

        Asked of the scene here rather than fetched by the map, so that the one object that
        knows whether there is still a scene to ask is the one that asks. A view whose scene
        has gone — which is what tearing a tab down looks like from here — simply says
        nothing, and the map keeps its last picture until it goes too.
        """
        scene = self.scene()
        if isinstance(scene, GraphScene):
            self.minimap.show_graph(scene.node_rects(), self._looking_at())

    def _looking_at(self) -> QRectF:
        return self.mapToScene(self.viewport().rect()).boundingRect()

    def showEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)  # type: ignore[arg-type]
        if not self._framed:
            self._framed = True
            # Deferred to the next turn of the event loop rather than done here: at show
            # time the splitter has not given the viewport its real width yet, and fitting
            # a graph to a half-laid-out box zooms a readable one down to nothing.
            QTimer.singleShot(0, self._first_look)

    def _first_look(self) -> None:
        """Frame the graph — unless a step was asked for before the view had its size.

        A reveal that opens this tab centres at once, against a viewport not laid out yet,
        and the frame a turn later would put the whole graph over it. So the first look
        lands on that step again, now that the viewport is the size it will be.
        """
        if self._centred_on is None:
            self.frame_content()
        else:
            self.centre_on_step(self._centred_on)

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
        # The ruler covers the top of the view while it stands; the graph is framed below it.
        clear = RULER_H if self.ruler.headings() else 0
        fits = min(
            viewport.width() / max(padded.width(), 1.0),
            (viewport.height() - clear) / max(padded.height(), 1.0),
        )
        # Never magnify, and never shrink past legibility — a graph too big for the window
        # is scrolled, not squinted at.
        wanted = max(ZOOM_READABLE, min(1.0, fits))
        if wanted != self._zoom:
            self.scale(wanted / self._zoom, wanted / self._zoom)
            self._zoom = wanted
        self.centerOn(content.center() - QPointF(0.0, clear / 2 / self._zoom))
        self._follow_overlays()

    def centre_on_step(self, step_id: StepId) -> None:
        """Put the viewport on one step, at the zoom the user left it.

        What *Jump to* lands with, and what ``steps.reveal`` has done since: selecting a
        node that is off screen selects something nobody can see. The zoom is untouched —
        Frame is the verb that changes how much of the graph is in view, and a jump that
        also zoomed would lose the scale somebody had chosen to work at. Remembered for the
        view's first look, which would otherwise frame the graph over it.
        """
        scene = self.scene()
        if not isinstance(scene, GraphScene):
            return
        node = scene.node(step_id)
        if node is None:
            return
        self._centred_on = step_id
        self.centerOn(node.body_scene_rect().center())
        self._follow_overlays()

    def zoom_by(self, steps: int) -> None:
        factor = ZOOM_STEP**steps
        wanted = max(ZOOM_MIN, min(ZOOM_MAX, self._zoom * factor))
        if wanted != self._zoom:
            self.scale(wanted / self._zoom, wanted / self._zoom)
            self._zoom = wanted
            self._follow_overlays()
