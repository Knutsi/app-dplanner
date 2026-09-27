"""What the canvas draws: a node per step, an arrow per edge, and the line under a link drag.

Each item owns its geometry and holds its state and nothing else. A step node's actual
painting is composed in ``renderers.py`` from pure helpers; interaction lives in
``modes.py``, one mode per behaviour, so no item and no scene grows a state machine.
"""

from math import hypot

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
from dplanner.modules.project_editor.marks import Marks
from dplanner.modules.project_editor.positions import NODE_H, NODE_W
from dplanner.modules.project_editor.renderers import (
    PAINT_MARGIN,
    EdgeAccent,
    NodeAccent,
    NodeState,
    RenderHints,
    paint_node,
)
from dplanner.modules.project_editor.selection import EdgeRef
from dplanner.theme.cards import DIM_OPACITY
from dplanner.theme.tokens import SECONDARY_ALPHA
from dplanner.theme.tones import INVALID_TINT, VALID_TINT

# How far a press may land from the handle's centre and still mean it.
HANDLE_GRAB = 12.0

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

# A doubled arrow — work that moves along it on its own — is two rails this far apart,
# centre to centre, with a chevron every CHEVRON_PITCH between them pointing at the step
# that waits. The rails read from across the graph, where a medallion at the middle would
# be a dot; the chevrons say which way, close up. Both stay inside EDGE_GRAB's margin.
RAIL_GAP = 6.0
CHEVRON_PITCH = 14.0
CHEVRON_ARM = 2.2  # Half the chevron's height, clear of the rails' inner edges.
# Clear of the tail where it leaves the card, and of the head where it arrives.
CHEVRON_TAIL = 6.0
CHEVRON_HEAD = 12.0
# How far the chevrons travel per step of the scene's ring phase: the pace of the ring's
# own dashes (RING_STEP of a dash measured in 1.5 px pens), so the two motions are one.
FLOW_PER_PHASE = 1.5


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
    default footprint — and every rect below is measured from it, never from ``NODE_W``.
    """

    def __init__(self, step_id: StepId) -> None:
        super().__init__()
        self.step_id = step_id
        self._size = (NODE_W, NODE_H)
        self._title = ""
        self._link_state = ""
        self._accent = NodeAccent()
        self._hints = RenderHints()
        self._ring_phase = 0.0
        self._ports = (False, False)
        self._marks = Marks()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self._hovered = False

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
        return self._size

    def name(self) -> str:
        """What a status line calls this card: its key, else its title."""
        return self._accent.key_text or self._title or "Untitled step"

    def set_accent(self, accent: NodeAccent) -> None:
        if accent != self._accent:
            self._accent = accent
            self.update()

    def wears_ring(self) -> bool:
        """Whether this node has a live agent run — the one thing the scene animates."""
        return bool(self._accent.chip_text)

    def set_ring_phase(self, phase: float) -> None:
        """Where the ring's dashes are — pushed by the scene's tick, one number for all."""
        if phase != self._ring_phase:
            self._ring_phase = phase
            if self.wears_ring():
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
        return QRectF(0.0, 0.0, self._size[0], self._size[1])

    def handle_scene_pos(self) -> QPointF:
        return self.mapToScene(QPointF(self._size[0], self._size[1] / 2))

    def body_scene_rect(self) -> QRectF:
        """The card itself, in scene coordinates — what a lasso has to touch. Not the
        bounding rect, which reaches ``PAINT_MARGIN`` further out on every side."""
        return self.mapRectToScene(self.body_rect())

    def is_over_handle(self, scene_pos: QPointF) -> bool:
        delta = scene_pos - self.handle_scene_pos()
        return bool(delta.manhattanLength() <= HANDLE_GRAB)

    def edge_at(self, scene_pos: QPointF) -> str:
        """Which part of the frame a point grabs: "left", "bottom-right", … or "" for the
        body and for anywhere off the card. The band is ``GRAB_IN`` inside the border and
        ``EDGE_REACH`` outside it; a point in two bands at once is at a corner."""
        local = self.mapFromScene(scene_pos)
        w, h = self._size
        reach = QRectF(-EDGE_REACH, -EDGE_REACH, w + 2 * EDGE_REACH, h + 2 * EDGE_REACH)
        if not reach.contains(local):
            return ""
        across = "left" if local.x() <= GRAB_IN else "right" if local.x() >= w - GRAB_IN else ""
        down = "top" if local.y() <= GRAB_IN else "bottom" if local.y() >= h - GRAB_IN else ""
        return "-".join(part for part in (down, across) if part)

    def anchor_toward(self, other: QPointF) -> QPointF:
        """Where an edge should touch this node: the near edge, not the centre."""
        w, h = self._size
        centre = self.mapToScene(QPointF(w / 2, h / 2))
        return self.mapToScene(QPointF(w if other.x() >= centre.x() else 0.0, h / 2))

    def shape(self) -> QPainterPath:
        # What a press, a hover and a rubber band hit: the card and the outer half of its
        # resize band — not the bounding rect, which reaches PAINT_MARGIN further out to
        # hold the shadow and the stat line, and would make empty canvas beside a card
        # select it.
        path = QPainterPath()
        path.addRect(self.body_rect().adjusted(-EDGE_REACH, -EDGE_REACH, EDGE_REACH, EDGE_REACH))
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
        paint_node(
            painter,
            live_palette(self),
            self.body_rect(),
            self._title,
            self._accent,
            NodeState(
                selected=self.isSelected(),
                hovered=self._hovered,
                link_state=self._link_state,
                hints=self._hints,
                ring_phase=self._ring_phase,
                ports=self._ports,
                marks=self._marks,
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
    without one because it does not — what ``EDGE_KINDS`` means. An :class:`EdgeAccent`
    says the rest, translated by the composition root: a *doubled* arrow is two rails with
    chevrons between them (the work moves along it on its own — an auto-progress link),
    and a *flowing* one moves its chevrons on the scene's ring clock (that work is being
    done right now).
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
        self._phase = 0.0
        # A doubled arrow's two drawings, kept with the path and redrawn only when it moves
        # or its chevrons do.
        self._rails = QPainterPath()
        self._chevrons = QPainterPath()
        # The curve flattened to a polyline, kept while the path stands: the chevrons are
        # placed by walking it, since asking Qt for a point at a length costs ~40 µs a time.
        self._track: list[QPointF] = []
        self._ends: tuple[float, float, float, float] | None = None
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
            self._dress()
            self.update()

    def accent(self) -> EdgeAccent:
        return self._accent

    def flows(self) -> bool:
        """Whether this arrow's chevrons move — what keeps the scene's ring clock running."""
        return self._accent.doubled and self._accent.flowing

    def set_flow_phase(self, phase: float) -> None:
        """One tick of the scene's ring clock: a flowing arrow's chevrons move on."""
        if self.flows():
            self._phase = phase
            self._chevrons = self._chevron_marks()
            self.update()

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
        # Every sync asks every arrow to follow, and most have not moved: the curve is a
        # function of its two ends, so an arrow whose ends stand keeps what it drew.
        ends = (start.x(), start.y(), end.x(), end.y())
        if ends == self._ends:
            return
        self._ends = ends
        path = QPainterPath(start)
        reach = max(40.0, abs(end.x() - start.x()) / 2)
        path.cubicTo(QPointF(start.x() + reach, start.y()), QPointF(end.x() - reach, end.y()), end)
        self.setPath(path)
        # The head is kept apart from the curve rather than added to its path: one filled
        # path containing both would fill the area under the curve as well.
        self._head = (
            _arrow_head(path.pointAtPercent(0.92), end) if self.kind == "requires" else None
        )
        self._dress()

    def _dress(self) -> None:
        """The doubled arrow's rails and chevrons, over the current path — or nothing."""
        if not self._accent.doubled:
            self._rails = self._chevrons = QPainterPath()
            self._track = []
            return
        stroker = QPainterPathStroker()
        stroker.setWidth(RAIL_GAP)
        stroker.setCapStyle(Qt.PenCapStyle.FlatCap)
        self._rails = stroker.createStroke(self.path()).simplified()
        polygons = self.path().toSubpathPolygons()
        curve = polygons[0] if polygons else QPolygonF()
        self._track = [curve.at(index) for index in range(curve.size())]
        self._chevrons = self._chevron_marks()

    def _chevron_marks(self) -> QPainterPath:
        """A chevron every CHEVRON_PITCH along the track, pointing at the step that waits
        and shifted along by the flow's phase — each one a short open polyline."""
        marks = QPainterPath()
        segments = []
        for start, end in zip(self._track, self._track[1:], strict=False):
            dx, dy = end.x() - start.x(), end.y() - start.y()
            if length := hypot(dx, dy):
                segments.append((start, dx, dy, length))
        stop = sum(length for *_rest, length in segments) - CHEVRON_HEAD
        at = CHEVRON_TAIL + ((self._phase * FLOW_PER_PHASE) % CHEVRON_PITCH if self.flows() else 0)
        walked = 0.0
        for start, dx, dy, length in segments:
            while at < min(walked + length, stop):
                share = (at - walked) / length
                ahead = QPointF(dx / length, dy / length)
                across = QPointF(-ahead.y(), ahead.x())
                tip = start + QPointF(dx * share, dy * share) + ahead * CHEVRON_ARM * 0.6
                marks.moveTo(tip - ahead * CHEVRON_ARM + across * CHEVRON_ARM)
                marks.lineTo(tip)
                marks.lineTo(tip - ahead * CHEVRON_ARM - across * CHEVRON_ARM)
                at += CHEVRON_PITCH
            walked += length
        return marks

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
        if self._accent.doubled:
            # Thinner than a single line, since there are two of them and the chevrons.
            painter.setPen(QPen(colour, 1.6 if stressed else 1.0, style))
            painter.drawPath(self._rails)
            chevron = QPen(colour, 1.4 if stressed else 1.1)
            chevron.setCapStyle(Qt.PenCapStyle.RoundCap)
            chevron.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(chevron)
            painter.drawPath(self._chevrons)
        else:
            painter.setPen(QPen(colour, 2.4 if stressed else 1.4, style))
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


def _arrow_head(start: QPointF, end: QPointF, size: float = 8.0) -> QPolygonF:
    direction = end - start
    length = (direction.x() ** 2 + direction.y() ** 2) ** 0.5 or 1.0
    unit = QPointF(direction.x() / length, direction.y() / length)
    normal = QPointF(-unit.y(), unit.x())
    base = end - unit * size
    return QPolygonF([end, base + normal * size * 0.5, base - normal * size * 0.5])
