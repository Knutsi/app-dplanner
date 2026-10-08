"""What the canvas draws: a node per step, an arrow per edge, a frame per stack, and the line
under a link drag.

Each item owns its geometry and holds its state and nothing else. A step node's actual
painting is composed in ``renderers.py`` from pure helpers; interaction lives in
``modes.py``, one mode per behaviour, so no item and no scene grows a state machine.

**An arrow meets an item at a port** — a point and the way the arrow travels there. A card's
is its near edge, travelling across, which is every link into or out of a stack too: in at
its first card's side, out of its last card's, as into and out of any card. Only the chain
between a stack's cards is its own, drawn short and straight down the frame's middle
(``docs/architecture/canvas.md``'s *A stack's frame is the stack's handle*).
"""

from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt
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
    QGraphicsSceneHoverEvent,
    QStyleOptionGraphicsItem,
    QWidget,
)

from dplanner.domain.model import StepId
from dplanner.framework.motion.curves import out_cubic
from dplanner.modules.canvas.layouts.positions import NODE_H, NODE_W, STRIP_H
from dplanner.modules.canvas.marks import Marks
from dplanner.modules.canvas.renderers import (
    PAINT_MARGIN,
    PROBLEM_INK,
    EdgeAccent,
    NodeAccent,
    NodeState,
    RenderHints,
    paint_node,
)
from dplanner.modules.canvas.selection import EdgeRef
from dplanner.modules.canvas.stacks.stack import FRAME_PAD, Stack, member_seats
from dplanner.theme.cards import DIM_OPACITY, RADIUS
from dplanner.theme.icons import paint_glyph
from dplanner.theme.tokens import SECONDARY_ALPHA
from dplanner.theme.tones import INVALID_TINT, VALID_TINT

# How far a press may land from the handle's centre and still mean it.
HANDLE_GRAB = 12.0

# How long a playbook strip takes to grow out of a card's foot, or to fold back into it: long
# enough to see the edge move, short enough never to be waited on.
GROW_S = 0.2

# The resize band round a card's border: this far inside it, and EDGE_REACH outside. A press
# in the band grabs that edge — both bands at once grab the corner — and a press further in
# drags the card, the way a window's frame works. EDGE_REACH is also the item's hit shape:
# the outer half of the band, and the link handle that sticks out of the right edge.
GRAB_IN = 6.0
EDGE_REACH = 8.0

# The outline preview's wash: faint ink, so what it encloses still reads through it.
OUTLINE_FILL_ALPHA = 10

# An arrow hanging off the selection is *lit*: the accent that says "this one" on the picked
# card's border, a shade under a picked arrow's own so a link you chose and a link that merely
# touches what you chose stay tellable apart.
LIT_ALPHA = 190

# How wide a curve is to the mouse. An edge is drawn 1.4 px thin and no one can click that,
# so its shape() is the stroked path at this width — comfortably a target, still narrow
# enough that two edges through the same gap stay tellable apart.
EDGE_GRAB = 14.0

# A branch's lane is a band this wide under the arrow — inside EDGE_GRAB's margin, so an
# arrow wearing one keeps the bounds it had — at this much of its colour, so the ink on top
# still reads and a lit arrow is still lit.
LANE_W = 10.0
LANE_ALPHA = 0.35

# The least a curve's end reaches along its heading before it turns: what keeps an arrow
# between two cards side by side from arriving edge-on.
MIN_REACH = 40.0

# A stack's frame: a quiet wash of ink round its column, edged a shade lighter than a card,
# its corners rounder than a card's so the two never read as one shape.
FRAME_RADIUS = 12.0
FRAME_WASH_ALPHA = 12
FRAME_BORDER_ALPHA = 60
# The "+" set into the bottom edge: a disc the size of a medallion, straddling the edge.
ADD_R = 10.0
ADD_GLYPH = 12.0
# What Shift does to a stack's cards, said in its bottom pad while the pointer is over it,
# this far clear of the "+".
SHIFT_HINT = "Shift-drag to reorder"
HINT_GAP = 6.0
# How far inside the narrower of two cards a connector stays, when the frame's middle is
# past that card's right edge: clear of its rounded corner.
CONNECTOR_INSET = RADIUS + 4.0

# Which way an arrow travels where it meets an item: across a card, down through a stack.
ACROSS = QPointF(1.0, 0.0)
DOWN = QPointF(0.0, 1.0)

# Where an arrow meets an item, and the way it travels there.
type Port = tuple[QPointF, QPointF]


def snapped_point(scene: object, point: QPointF) -> QPointF:
    """``point`` on the grid if the scene it is in is snapping, else itself.

    Asked of the scene by duck type, as ``reflow_edges`` is: an item cannot import the
    scene that imports it, and a scene that has no opinion (a bare ``QGraphicsScene`` in a
    test) snaps nothing.
    """
    snap = getattr(scene, "snap", None)
    if snap is None:
        return point
    return QPointF(snap(point.x()), snap(point.y()))


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
    """One step. Movable and selectable; Qt does the dragging.

    Its size is the card's own — pushed by the scene from what the step stored, or the
    default footprint, with a branch strip's height under it when the card wears one — and
    every rect below is measured from it, never from ``NODE_W``. The body is the card less
    that strip: arrows, the handle and the marks meet its middle, and a resize stores it.

    Under all of it a running playbook's strip grows out of the card's foot on the scene's
    motion clock, and folds back when the pass is no longer shown. It is no part of the
    footprint the scene pushes (a pass is transient, and an arrangement must not move for
    one): the card adds it to what it draws, hits and hands its stack as its :meth:`size`.
    """

    def __init__(self, step_id: StepId) -> None:
        super().__init__()
        self.step_id = step_id
        self._size = (NODE_W, NODE_H)
        self._title = ""
        self._link_state = ""
        self._accent = NodeAccent()
        self._hints = RenderHints()
        self._phase = 0.0
        self._ports = (False, False)
        self._marks = Marks()
        # The frame of the stack this card stands in, set by the scene every sync.
        self._frame: StackItem | None = None
        # Whether its seat is derived — Wave view's — so no hand may move or resize it.
        self._pinned = False
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self._hovered = False
        # The playbook strip: how far it has grown (0..1, in time), where it is going, and
        # the accent it last showed — still painted while it folds away.
        self._grow = 0.0
        self._grow_to = 0.0
        self._band = ("", "", "")

    def set_title(self, title: str) -> None:
        if title != self._title:
            self._title = title
            self.update()

    def set_size(self, w: float, h: float) -> None:
        """Resize the card. Geometry changes, so Qt is told before the rect moves, and the
        edges touching it are redrawn — a resize moves their anchors like a drag does."""
        if (w, h) != self._size:
            self.prepareGeometryChange()
            self._size = (w, h)
            self.update()
            scene = self.scene()
            if scene is not None and hasattr(scene, "reflow_edges"):
                scene.reflow_edges(self.step_id)

    def size(self) -> tuple[float, float]:
        """The card as drawn: its footprint and as much playbook strip as has grown."""
        return self._size[0], self._size[1] + self._grown()

    def footprint(self) -> tuple[float, float]:
        """The card as the scene sized it: the body and the branch strip, no playbook strip."""
        return self._size

    def body_size(self) -> tuple[float, float]:
        """The card less its strip: what the step stores as its size."""
        return self._size[0], self._size[1] - self._strip_h()

    def _strip_h(self) -> float:
        return STRIP_H if self._accent.strip else 0.0

    def _middle_y(self) -> float:
        """Where arrows, the handle and the marks meet the card: the body's middle."""
        return (self._size[1] - self._strip_h()) / 2

    def name(self) -> str:
        """What a status line calls this card: its key, else its title."""
        return self._accent.key_text or self._title or "Untitled step"

    def set_accent(self, accent: NodeAccent) -> None:
        if accent != self._accent:
            moved = bool(accent.strip) != bool(self._accent.strip)
            self._accent = accent
            if accent.playbook[0]:
                self._band = accent.playbook
            self._grow_toward(1.0 if accent.playbook[0] else 0.0)
            self.update()
            scene = self.scene()
            if moved and scene is not None and hasattr(scene, "reflow_edges"):
                scene.reflow_edges(self.step_id)  # A strip moves the body's middle.

    def _grow_toward(self, target: float) -> None:
        """Start the playbook strip growing or folding — at once for a card not on a canvas
        yet (a tab opening animates nothing) and while the user has motion reduced."""
        if target == self._grow_to:
            return
        self._grow_to = target
        scene = self.scene()
        if scene is None or getattr(scene, "motion_reduced", True):
            self._set_grow(target)

    def growing(self) -> bool:
        return self._grow != self._grow_to

    def advance(self, seconds: float) -> None:
        """Move the playbook strip on by ``seconds`` of the scene's motion clock."""
        if self.growing():
            step = seconds / GROW_S
            self._set_grow(
                min(self._grow + step, 1.0) if self._grow_to else max(self._grow - step, 0.0)
            )

    def _set_grow(self, grow: float) -> None:
        self.prepareGeometryChange()
        self._grow = grow
        self.update()
        scene = self.scene()
        if scene is not None and hasattr(scene, "reflow_edges"):
            scene.reflow_edges(self.step_id)  # A stack's column makes room for it.

    def _shown(self) -> float:
        """The strip's growth as drawn: eased out both ways, so the edge arrives gently."""
        if self._grow_to:
            return out_cubic(self._grow)
        return 1.0 - out_cubic(1.0 - self._grow)

    def _grown(self) -> float:
        return STRIP_H * self._shown() if self._grow else 0.0

    def playbook_tip_at(self, scene_pos: QPointF) -> str:
        """The playbook's stages, when ``scene_pos`` is on the strip that names its pass."""
        if not self._accent.playbook[0] or not self._grow:
            return ""
        band = self.body_rect()
        band.setTop(band.bottom() - self._grown())
        return self._accent.playbook[2] if band.contains(self.mapFromScene(scene_pos)) else ""

    def wears_ring(self) -> bool:
        """Whether this node has a live agent run, and so wears the marching ring."""
        return bool(self._accent.chip_text)

    def moves(self) -> bool:
        """Whether anything on this card moves — the ring, the pulse or its playbook strip
        growing — which is what keeps the scene's motion clock running."""
        return self.wears_ring() or self._accent.pulse or self.growing()

    def set_phase(self, phase: float) -> None:
        """Where the scene's motion clock stands — the ring's dashes, the pulse's breath —
        pushed by its tick, one number for all."""
        if phase != self._phase:
            self._phase = phase
            if self.moves():
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

    def set_ports(self, ports: tuple[bool, bool]) -> None:
        """(something arrives, something leaves) — derived by the activity every sync."""
        if ports != self._ports:
            self._ports = ports
            self.update()

    def set_marks(self, marks: Marks) -> None:
        """Which marks the user has on — pushed by the scene, like the render hints."""
        if marks != self._marks:
            self._marks = marks
            self.update()

    def ports(self) -> tuple[bool, bool]:
        return self._ports

    def set_frame(self, frame: "StackItem | None") -> None:
        """The stack this card stands in, or None — pushed by the scene every sync.

        A member is never dragged by Qt on its own: its stack moves whole, through a mode.
        """
        if frame is not self._frame:
            self.prepareGeometryChange()  # Its shape reaches out on fewer sides in a stack.
            self._frame = frame
            self._settle_movable()
            self.update()

    def set_pinned(self, pinned: bool) -> None:
        """Whether this card's seat is derived rather than the hand's — Wave view's. A pinned
        card is picked like any other but never dragged or resized: its seat would be
        overwritten by the next sync, and nothing it did would be saved."""
        if pinned != self._pinned:
            self.prepareGeometryChange()  # A pinned card has no resize band to reach out to.
            self._pinned = pinned
            self._settle_movable()

    @property
    def pinned(self) -> bool:
        return self._pinned

    def _settle_movable(self) -> None:
        loose = self._frame is None and not self._pinned
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, loose)

    @property
    def stack(self) -> Stack | None:
        """The stack this card stands in, with its order and its gaps — None for a loose one."""
        return None if self._frame is None else self._frame.stack

    def has_handle(self) -> bool:
        """Whether a link may be dragged out of this card: a loose one, or a stack's last."""
        return self._frame is None or self._frame.stack.members[-1] == self.step_id

    def port(self, other: "StepNodeItem", *, leaving: bool) -> Port:
        """Where an arrow to or from ``other`` meets this card, and which way it travels.

        The near edge, travelling across — unless this card's stack answers for it.
        """
        if self._frame is not None:
            port = self._frame.port(self.step_id, other.step_id, leaving=leaving)
            if port is not None:
                return port
        return self.anchor_toward(other.scenePos()), ACROSS

    def set_dimmed(self, dimmed: bool) -> None:
        """Fade the whole card: the spotlight is on and this step is not in it.

        Item opacity rather than a paint-level flag — one number fades fill, border, title,
        every medallion and the shadow together, which is what receding *is*, and the
        renderer never learns that a spotlight exists. The coverage trace dims its cards
        the same way, off the same constant.
        """
        self.setOpacity(DIM_OPACITY if dimmed else 1.0)

    def body_rect(self) -> QRectF:
        """The card, in its own coordinates: the rect every painter measures from."""
        return QRectF(0.0, 0.0, *self.size())

    def handle_scene_pos(self) -> QPointF:
        return self.mapToScene(QPointF(self._size[0], self._middle_y()))

    def body_scene_rect(self) -> QRectF:
        """The card itself, in scene coordinates — what a lasso has to touch. Not the
        bounding rect, which reaches ``PAINT_MARGIN`` further out on every side."""
        return self.mapRectToScene(self.body_rect())

    def is_over_handle(self, scene_pos: QPointF) -> bool:
        if not self.has_handle():
            return False
        delta = scene_pos - self.handle_scene_pos()
        return bool(delta.manhattanLength() <= HANDLE_GRAB)

    def edge_at(self, scene_pos: QPointF) -> str:
        """Which part of the frame a point grabs: "left", "bottom-right", … or "" for the
        body and for anywhere off the card. The band is ``GRAB_IN`` inside the border and
        ``EDGE_REACH`` outside it; a point in two bands at once is at a corner.

        A card in a stack grows only right and down: its column keeps its left edge and its
        order, and a member below the first stores no seat for a left or top drag to move. A
        pinned card grows nowhere.
        """
        if self._pinned:
            return ""
        local = self.mapFromScene(scene_pos)
        w, h = self.size()
        reach = QRectF(-EDGE_REACH, -EDGE_REACH, w + 2 * EDGE_REACH, h + 2 * EDGE_REACH)
        if not reach.contains(local):
            return ""
        across = "left" if local.x() <= GRAB_IN else "right" if local.x() >= w - GRAB_IN else ""
        down = "top" if local.y() <= GRAB_IN else "bottom" if local.y() >= h - GRAB_IN else ""
        if self._frame is not None:
            across = "" if across == "left" else across
            down = "" if down == "top" else down
        return "-".join(part for part in (down, across) if part)

    def anchor_toward(self, other: QPointF) -> QPointF:
        """Where an edge should touch this node: the near edge, not the centre."""
        w, middle = self._size[0], self._middle_y()
        centre = self.mapToScene(QPointF(w / 2, middle))
        return self.mapToScene(QPointF(w if other.x() >= centre.x() else 0.0, middle))

    def shape(self) -> QPainterPath:
        # What a press, a hover and a rubber band hit: the card and the outer half of its
        # resize band — not the bounding rect, which reaches PAINT_MARGIN further out to
        # hold the shadow and the stat line, and would make empty canvas beside a card
        # select it. A card in a stack grows only right and down, so it reaches out only
        # there, and the frame's pad on its other sides stays the frame's to grab. A pinned
        # card has no band at all.
        reach = 0.0 if self._frame is not None or self._pinned else EDGE_REACH
        grows = 0.0 if self._pinned else EDGE_REACH
        path = QPainterPath()
        path.addRect(self.body_rect().adjusted(-reach, -reach, grows, grows))
        return path

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt override
        # Constant, whatever the accent or the selection: PAINT_MARGIN is the furthest any
        # decoration reaches out of the body, worked out where they are drawn. Constant
        # matters — a rect that grew on selection would invalidate the wrong region and
        # leave the shadow behind when the selection moved on.
        return self.body_rect().adjusted(-PAINT_MARGIN, -PAINT_MARGIN, PAINT_MARGIN, PAINT_MARGIN)

    def itemChange(self, change: object, value: object) -> object:  # noqa: N802 - Qt override
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and isinstance(
            value, QPointF
        ):
            # Snap while dragging, so what the user sees is what gets stored. Whether to
            # is the scene's to say: it holds the user's Snap to Grid setting.
            return snapped_point(self.scene(), value)
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            # A lifted node sits over its neighbours, shadow and all. Nodes are all at 0
            # otherwise, where the stacking order is whichever sync happened to add last.
            self.setZValue(1.0 if value else 0.0)
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
        # A strip folding away still says what it said until it is gone.
        accent = self._accent
        if not accent.playbook[0] and self._grow:
            accent = replace(accent, playbook=self._band)
        paint_node(
            painter,
            live_palette(self),
            self.body_rect(),
            self._title,
            accent,
            NodeState(
                selected=self.isSelected(),
                hovered=self._hovered,
                link_state=self._link_state,
                hints=self._hints,
                phase=self._phase,
                ports=self._ports,
                marks=self._marks,
                handle=self.has_handle(),
                grow=self._shown() if self._grow else 0.0,
            ),
        )

    def hoverEnterEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        self._hovered = True
        self.update()

    def hoverMoveEvent(self, event: QGraphicsSceneHoverEvent) -> None:  # noqa: N802 - Qt override
        # The playbook strip's stages, over the strip alone: the rest of the card is the step.
        self.setToolTip(self.playbook_tip_at(event.scenePos()))
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        self._hovered = False
        self.update()


class EdgeItem(QGraphicsPathItem):
    """An arrow from the step waited on to the step that waits.

    ``requires`` is solid with a head because it orders the graph; ``relates`` is dashed
    without one because it does not — what ``EDGE_KINDS`` means. An :class:`EdgeAccent`
    says the rest, translated by the composition root: a *lane* is a translucent band of a
    colour under the whole arrow (a feature branch it is work on).
    """

    def __init__(self, source: StepNodeItem, waiter: StepNodeItem, kind: str) -> None:
        super().__init__()
        self.source = source
        self.waiter = waiter
        self.kind = kind
        self.ref = EdgeRef(waiter=waiter.step_id, kind=kind, source=source.step_id)
        self._head: QPolygonF | None = None
        self._hovered = False
        self._lit = False
        self._accent = EdgeAccent()
        self._ends: tuple[float, ...] | None = None
        self.setZValue(-1)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.follow()

    def set_lit(self, lit: bool) -> None:
        """Whether this arrow hangs off a picked step — the scene derives it every time the
        selection or the graph changes."""
        if lit != self._lit:
            self._lit = lit
            self.update()

    def set_dimmed(self, dimmed: bool) -> None:
        """Fade the arrow: the spotlight is on and the selection does not touch it."""
        self.setOpacity(DIM_OPACITY if dimmed else 1.0)

    def set_accent(self, accent: EdgeAccent) -> None:
        """How the arrow looks beyond its kind — the scene hands it over on every sync."""
        if accent != self._accent:
            self._accent = accent
            self.update()

    def accent(self) -> EdgeAccent:
        return self._accent

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
        start, out = self.source.port(self.waiter, leaving=True)
        end, into = self.waiter.port(self.source, leaving=False)
        # Every sync asks every arrow to follow, and most have not moved: the curve is a
        # function of its two ports, so an arrow whose ports stand keeps what it drew.
        ends = (start.x(), start.y(), end.x(), end.y(), out.y(), into.y())
        if ends == self._ends:
            return
        self._ends = ends
        path = QPainterPath(start)
        if out == into == DOWN and start.x() == end.x():
            path.lineTo(end)  # A stack's own link, from one card down to the next.
        else:
            path.cubicTo(
                start + out * _reach(start, end, out), end - into * _reach(start, end, into), end
            )
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
        if self.isSelected() or self._lit:
            colour = QColor(palette.highlight().color())
            if not self.isSelected():
                colour.setAlpha(LIT_ALPHA)
        else:
            colour = QColor(palette.text().color())
            colour.setAlpha(200 if self._hovered else 130)
        style = Qt.PenStyle.SolidLine if self.kind == "requires" else Qt.PenStyle.DashLine
        stressed = self.isSelected() or self._hovered or self._lit
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self._accent.lane:
            band = QColor(self._accent.lane)
            band.setAlphaF(LANE_ALPHA)
            lane = QPen(band, LANE_W)
            lane.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(lane)
            painter.drawPath(self.path())
        painter.setPen(QPen(colour, 2.4 if stressed else 1.4, style))
        painter.drawPath(self.path())
        if self._head is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colour)
            painter.drawPolygon(self._head)


class StackItem(QGraphicsItem):
    """A stack's frame: the shaded ground its column of cards stands on, and what a press on
    it drags.

    It holds its member cards and is the one place their column lives on screen:
    :meth:`follow` lays every member under the first by ``stack.member_seats`` at the
    cards' current sizes, then fits the frame round them — so a sync, a card being resized
    and any gesture moving the first card all show the column the model derives, live. It
    answers for the ports of the chain between its cards, and places its "+"
    (:class:`StackAddItem`, an item of its own so it sits over the arrows). Behind the
    arrows and the cards; never selectable — a click on it picks its members, which is a
    mode's business.

    A gesture reordering the column borrows it: :meth:`stand` puts the frame round the
    column the drop would make and leaves the cards to the gesture, and :meth:`free` gives
    it back.
    """

    def __init__(self, stack: Stack) -> None:
        super().__init__()
        self.stack = stack
        self._members: list[StepNodeItem] = []
        self._size = (0.0, 0.0)
        self._following = False
        # True while a gesture has the column: follow() leaves the cards where it puts them.
        self._stood = False
        # Whether the pointer is over the stack, so the frame says what Shift does.
        self._hinted = False
        self.add = StackAddItem(self)
        self.setZValue(-2)

    def set_stack(self, stack: Stack, members: list[StepNodeItem]) -> None:
        """Its order, its gaps and its cards, as the model has them now."""
        self.stack = stack
        self._members = members
        self.update()
        self.add.update()

    def set_dimmed(self, dimmed: bool) -> None:
        """Fade with its cards: the spotlight is on and none of them is in it."""
        opacity = DIM_OPACITY if dimmed else 1.0
        self.setOpacity(opacity)
        self.add.setOpacity(opacity)

    def following(self) -> bool:
        """True while :meth:`follow` is moving the members — their own moves are its echo."""
        return self._following

    def follow(self) -> None:
        """Lay the column under its first card and fit the frame round it — unless a
        gesture has the column, which places the cards itself."""
        if not self._members or self._following or self._stood:
            return
        self._following = True
        try:
            sizes = {node.step_id: node.size() for node in self._members}
            head = self._members[0].pos()
            seats = member_seats(self.stack, (head.x(), head.y()), sizes.__getitem__)
            for node in self._members[1:]:
                seat = QPointF(*seats[node.step_id])
                if node.pos() != seat:
                    node.setPos(seat)
            rect = QRectF()
            for node in self._members:
                rect = rect.united(node.body_scene_rect())
            self._place(rect.adjusted(-FRAME_PAD, -FRAME_PAD, FRAME_PAD, FRAME_PAD))
        finally:
            self._following = False

    def stand(self, rect: QRectF) -> None:
        """Lend the column to a gesture: the frame stands at ``rect`` — round the column the
        drop would make — and the cards go wherever the gesture puts them. An empty rect
        hides it, for a stack whose last card is leaving."""
        self._stood = True
        self._place(rect)

    def free(self, *, lay: bool) -> None:
        """Take the column back. ``lay`` lays it out as the model has it now; a gesture that
        dropped leaves that to the sync its command brings, since the model has not changed
        yet and laying the old order now would flash it."""
        self._stood = False
        if lay:
            self.follow()

    def set_hinted(self, hinted: bool) -> None:
        if hinted != self._hinted:
            self._hinted = hinted
            self.update()

    def _place(self, rect: QRectF) -> None:
        shown = not rect.isEmpty()
        self.setVisible(shown)
        self.add.setVisible(shown)
        if (rect.width(), rect.height()) != self._size:
            self.prepareGeometryChange()
            self._size = (rect.width(), rect.height())
        self.setPos(rect.topLeft())
        self.add.setPos(QPointF(rect.center().x(), rect.bottom()))
        self.update()

    def frame_scene_rect(self) -> QRectF:
        return QRectF(self.pos(), QSizeF(*self._size))

    def port(self, member: StepId, other: StepId, *, leaving: bool) -> Port | None:
        """Where the chain's link between ``member`` and its neighbour ``other`` meets it —
        the bottom of the upper card, the top of the lower — or None for any other link,
        which meets the card's own side as it would any card's."""
        members = self.stack.members
        at = members.index(member)
        if leaving and at + 1 < len(members) and members[at + 1] == other:
            return QPointF(
                self._connector_x(at), self._members[at].body_scene_rect().bottom()
            ), DOWN
        if not leaving and at > 0 and members[at - 1] == other:
            return QPointF(
                self._connector_x(at - 1), self._members[at].body_scene_rect().top()
            ), DOWN
        return None

    def _connector_x(self, upper: int) -> float:
        """Where the connector below member ``upper`` runs: the frame's middle, kept inside
        the narrower of the two cards it joins."""
        pair = self._members[upper : upper + 2]
        left = pair[0].body_scene_rect().left()
        narrowest = min(node.size()[0] for node in pair)
        return min(self.frame_scene_rect().center().x(), left + narrowest - CONNECTOR_INSET)

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt override
        w, h = self._size
        return QRectF(-1.0, -1.0, w + 2.0, h + 2.0)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.0, 0.0, *self._size), FRAME_RADIUS, FRAME_RADIUS)
        return path

    def paint(
        self,
        painter: QPainter,
        _option: QStyleOptionGraphicsItem,
        _widget: QWidget | None = None,
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = live_palette(self)
        ink = QColor(palette.text().color())
        wash, border = QColor(ink), QColor(ink)
        wash.setAlpha(FRAME_WASH_ALPHA)
        border.setAlpha(FRAME_BORDER_ALPHA)
        frame = QRectF(0.0, 0.0, *self._size).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(wash)
        painter.drawRoundedRect(frame, FRAME_RADIUS, FRAME_RADIUS)
        self._paint_gaps(painter)
        if self._hinted and not self._stood:
            self._paint_hint(painter, palette)

    def _paint_hint(self, painter: QPainter, palette: QPalette) -> None:
        """What Shift does, in small secondary ink in the bottom pad left of the "+" —
        only while the pointer is over the stack, so a canvas of stacks stays quiet."""
        w, h = self._size
        room = QRectF(FRAME_PAD, h - FRAME_PAD, w / 2 - ADD_R - HINT_GAP - FRAME_PAD, FRAME_PAD)
        if room.width() <= 0:
            return
        font = painter.font()
        small = painter.font()
        small.setPointSizeF(max(6.0, font.pointSizeF() - 2.0))
        painter.setFont(small)
        shown = painter.fontMetrics().elidedText(
            SHIFT_HINT, Qt.TextElideMode.ElideRight, int(room.width())
        )
        ink = QColor(palette.text().color())
        ink.setAlpha(SECONDARY_ALPHA)
        painter.setPen(ink)
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        painter.drawText(room, int(align), shown)
        painter.setFont(font)

    def _paint_gaps(self, painter: QPainter) -> None:
        """Where the chain is broken, a dashed break in the refusal red, where its link
        would run: the stack is drawn as it is, and lint names it."""
        at = {member: index for index, member in enumerate(self.stack.members)}
        pen = QPen(PROBLEM_INK, 1.4, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        for before, then in self.stack.gaps:
            upper, lower = at.get(before), at.get(then)
            if upper is None or lower is None or lower != upper + 1:
                continue
            x = self._connector_x(upper)
            top = self._members[upper].body_scene_rect().bottom()
            bottom = self._members[lower].body_scene_rect().top()
            painter.drawLine(
                self.mapFromScene(QPointF(x, top)), self.mapFromScene(QPointF(x, bottom))
            )


class StackAddItem(QGraphicsItem):
    """The "+" set into a stack's bottom edge: add a step at the end of the stack.

    An item of its own, over the arrows and resting cards, so nothing drawn is ever on top of
    it and its hover is its own. What a press on it means is ``IdleMode``'s to say.
    """

    def __init__(self, frame: StackItem) -> None:
        super().__init__()
        self.frame = frame
        self._hovered = False
        self.setZValue(0.5)
        self.setAcceptHoverEvents(True)

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt override
        reach = ADD_R + 2.0
        return QRectF(-reach, -reach, 2 * reach, 2 * reach)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addEllipse(QPointF(0.0, 0.0), ADD_R, ADD_R)
        return path

    def paint(
        self,
        painter: QPainter,
        _option: QStyleOptionGraphicsItem,
        _widget: QWidget | None = None,
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = live_palette(self)
        accent = QColor(palette.highlight().color())
        ink = QColor(palette.text().color())
        ink.setAlpha(SECONDARY_ALPHA)
        border = QColor(ink)
        border.setAlpha(FRAME_BORDER_ALPHA * 2)
        if self._hovered:
            border, ink = accent, accent
        painter.setBrush(QColor(palette.window().color()))
        painter.setPen(QPen(border, 1.0))
        painter.drawEllipse(QPointF(0.0, 0.0), ADD_R, ADD_R)
        glyph = QRectF(-ADD_GLYPH / 2, -ADD_GLYPH / 2, ADD_GLYPH, ADD_GLYPH)
        paint_glyph(painter, glyph, "plus", ink)

    def hoverEnterEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        self._hovered = True
        self.update()

    def hoverLeaveEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        self._hovered = False
        self.update()


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


class OutlinePreviewItem(QGraphicsPathItem):
    """The dashed outline that follows a gesture drawing an area: a lasso being drawn, the
    room a divide is making. One item, since one gesture runs at a time."""

    def __init__(self) -> None:
        super().__init__()
        self.setZValue(10)

    def aim(self, path: QPainterPath) -> None:
        self.setPath(path)

    def paint(
        self,
        painter: QPainter,
        _option: QStyleOptionGraphicsItem,
        _widget: QWidget | None = None,
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        ink = QColor(live_palette(self).text().color())
        wash = QColor(ink)
        wash.setAlpha(OUTLINE_FILL_ALPHA)
        ink.setAlpha(SECONDARY_ALPHA)
        painter.setPen(QPen(ink, 1.4, Qt.PenStyle.DashLine))
        painter.setBrush(wash)
        painter.drawPath(self.path())


def _reach(start: QPointF, end: QPointF, heading: QPointF) -> float:
    """How far a curve's end runs along its heading before turning: half the distance it
    covers that way, and never less than :data:`MIN_REACH`."""
    along = (end.x() - start.x()) * heading.x() + (end.y() - start.y()) * heading.y()
    return max(MIN_REACH, abs(along) / 2)


def _arrow_head(start: QPointF, end: QPointF, size: float = 8.0) -> QPolygonF:
    direction = end - start
    length = (direction.x() ** 2 + direction.y() ** 2) ** 0.5 or 1.0
    unit = QPointF(direction.x() / length, direction.y() / length)
    normal = QPointF(-unit.y(), unit.x())
    base = end - unit * size
    return QPolygonF([end, base + normal * size * 0.5, base - normal * size * 0.5])
