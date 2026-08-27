"""What the canvas draws: a node per step, an arrow per edge, and the line under a link drag.

Each item owns its geometry and its paint and nothing else. Interaction lives in ``modes.py``,
one mode per behaviour, so no item and no scene grows a state machine.
"""

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
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
from dplanner.modules.project_editor.positions import GRID
from dplanner.modules.project_editor.selection import EdgeRef

NODE_W = 180.0
NODE_H = 56.0
RADIUS = 6.0
PADDING = 10.0
LINE_GAP = 4.0

# The link handle: a dot on the node's right edge. Dragging from it means "then", so an
# edge always runs left to right and its direction cannot be read the wrong way round.
HANDLE_R = 5.0
HANDLE_GRAB = 12.0

# Secondary text as opacity rather than a theme colour: a painter has only the palette, and
# an alpha-derived secondary is theme-independent by construction (DESIGN.md exception #1).
SECONDARY_ALPHA = 160
FILL_ALPHA = 28

# How wide a curve is to the mouse. An edge is drawn 1.4 px thin and no one can click that,
# so its shape() is the stroked path at this width — comfortably a target, still narrow
# enough that two edges through the same gap stay tellable apart.
EDGE_GRAB = 14.0

# Low-alpha semantic tints that read on every theme (DESIGN.md exception #2).
VALID_TINT = QColor(120, 200, 140, 180)
INVALID_TINT = QColor(220, 110, 110, 180)

# The pill and the branch glyph: small enough to decorate, never to compete with the title.
PILL_H = 14.0
PILL_RADIUS = PILL_H / 2
PILL_PAD_X = 6.0
PILL_MARGIN = 6.0
PILL_FILL_ALPHA = 46
GLYPH_SIZE = 9.0
GLYPH_GAP = 5.0


@dataclass(frozen=True)
class StepDecoration:
    """What a node wears beside its text: a pill and/or a small branch glyph.

    The vocabulary is deliberately the canvas's, not any aspect's — a tone is "good" or
    "bad", never "merged" — so whoever supplies decorations (the composition root, from
    whatever aspects exist) owns the mapping and this view stays feature-blind.
    """

    pill_text: str = ""  # "" → no pill.
    pill_tone: str = ""  # "" neutral | "good" | "bad".
    branch: bool = False  # Paint the branch glyph.


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
        self._decoration = StepDecoration()
        self._link_state = ""
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self._hovered = False

    def set_text(self, title: str, subtitle: str) -> None:
        if (title, subtitle) != (self._title, self._subtitle):
            self._title, self._subtitle = title, subtitle
            self.update()

    def set_decoration(self, decoration: StepDecoration) -> None:
        if decoration != self._decoration:
            self._decoration = decoration
            self.update()

    def set_link_state(self, state: str) -> None:
        """ "" while nothing is being dragged at this node, else "valid" or "invalid"."""
        if state != self._link_state:
            self._link_state = state
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
        margin = HANDLE_R + 2
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
        palette = live_palette(self)
        body = QRectF(0, 0, NODE_W, NODE_H)
        text_colour = QColor(palette.text().color())

        fill = QColor(text_colour)
        fill.setAlpha(FILL_ALPHA)
        border = QColor(palette.highlight().color())
        if self._link_state == "valid":
            border = VALID_TINT
        elif self._link_state == "invalid":
            border = INVALID_TINT
        elif not self.isSelected():
            border = QColor(text_colour)
            border.setAlpha(90)
        painter.setBrush(fill)
        painter.setPen(QPen(border, 2.0 if self.isSelected() or self._link_state else 1.0))
        painter.drawRoundedRect(body, RADIUS, RADIUS)

        metrics = painter.fontMetrics()
        inner = body.adjusted(PADDING, PADDING, -PADDING, -PADDING)
        faded = QColor(text_colour)
        faded.setAlpha(SECONDARY_ALPHA)
        painter.setPen(text_colour)
        painter.drawText(
            QRectF(inner.left(), inner.top(), inner.width(), metrics.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            metrics.elidedText(self._title, Qt.TextElideMode.ElideRight, int(inner.width())),
        )

        # The second line: subtitle on the left, decorations on the right. The decorations
        # take their width first so the subtitle's elision stays honest.
        deco = self._decoration
        second_top = inner.top() + metrics.height() + LINE_GAP
        pill_font = QFont(painter.font())
        pill_font.setPointSizeF(max(6.0, pill_font.pointSizeF() - 1))
        pill_w = (
            QFontMetricsF(pill_font).horizontalAdvance(deco.pill_text) + 2 * PILL_PAD_X
            if deco.pill_text
            else 0.0
        )
        glyph_w = GLYPH_SIZE + (GLYPH_GAP if pill_w else 0.0) if deco.branch else 0.0
        reserved = pill_w + glyph_w + (PILL_MARGIN if pill_w or glyph_w else 0.0)

        if self._subtitle:
            painter.setPen(faded)
            width = inner.width() - reserved
            painter.drawText(
                QRectF(inner.left(), second_top, width, metrics.height()),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                metrics.elidedText(self._subtitle, Qt.TextElideMode.ElideRight, int(width)),
            )
        if pill_w:
            pill = QRectF(
                inner.right() - pill_w,
                second_top + (metrics.height() - PILL_H) / 2,
                pill_w,
                PILL_H,
            )
            tone = {"good": VALID_TINT, "bad": INVALID_TINT}.get(deco.pill_tone)
            pill_fill = QColor(tone if tone is not None else text_colour)
            pill_fill.setAlpha(PILL_FILL_ALPHA)
            painter.setBrush(pill_fill)
            painter.setPen(QPen(QColor(tone) if tone is not None else faded, 1.0))
            painter.drawRoundedRect(pill, PILL_RADIUS, PILL_RADIUS)
            painter.save()
            painter.setFont(pill_font)
            painter.setPen(text_colour)
            painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), deco.pill_text)
            painter.restore()
        if deco.branch:
            glyph_right = inner.right() - (pill_w + GLYPH_GAP if pill_w else 0.0)
            self._paint_branch_glyph(
                painter,
                QRectF(
                    glyph_right - GLYPH_SIZE,
                    second_top + (metrics.height() - GLYPH_SIZE) / 2,
                    GLYPH_SIZE,
                    GLYPH_SIZE,
                ),
                faded,
            )

        if self._hovered or self._link_state:
            handle = QColor(palette.highlight().color())
            painter.setBrush(handle)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(NODE_W, NODE_H / 2), HANDLE_R, HANDLE_R)

    @staticmethod
    def _paint_branch_glyph(painter: QPainter, rect: QRectF, colour: QColor) -> None:
        """A tiny git-branch fork: a trunk, a curve out, and a dot at each tip."""
        radius = 1.5
        trunk = QPointF(rect.left() + radius, rect.bottom() - radius)
        tip = QPointF(rect.right() - radius, rect.top() + radius)
        path = QPainterPath(trunk)
        path.quadTo(QPointF(trunk.x(), tip.y()), tip)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(colour, 1.2))
        painter.drawPath(path)
        painter.setBrush(colour)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(trunk, radius, radius)
        painter.drawEllipse(tip, radius, radius)

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
