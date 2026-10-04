"""The map in the canvas's corner: the whole graph, small, with the viewport on it.

The canvas is a plane you can pan across for as long as you like, and the price of that is
that a scroll bar can no longer say where you are. This says it instead — every node at a
glance, a frame around what you are looking through, and a click anywhere to go there.

**The canvas pushes; the map never pulls.** It is handed rectangles, and holds no reference
to a scene, an item or a graph — so it imports nothing from the rest of the module, it can
be driven in a test by two lists, and it cannot outlive what it is drawing.

Colours come from the palette, like the nodes' own, and the well it sits in comes from the
stylesheet — so it follows the theme without knowing that a theme exists.
"""

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QGraphicsView, QWidget

SIZE = QSize(180, 120)
# DESIGN.md's 4-point scale: 12 from the canvas's corner, 8 inside the well.
INSET = 12
MARGIN = 8.0
# Enough plane around what is drawn that a node at the edge still reads as being at an edge,
# rather than as being cut off by the frame.
PADDING = 60.0
NODE_RADIUS = 1.5
NODE_ALPHA = 150


@dataclass(frozen=True)
class _Fit:
    """The one mapping between the plane and the map, and its inverse."""

    scale: float
    dx: float
    dy: float

    def to_map(self, rect: QRectF) -> QRectF:
        return QRectF(
            rect.x() * self.scale + self.dx,
            rect.y() * self.scale + self.dy,
            rect.width() * self.scale,
            rect.height() * self.scale,
        )

    def to_plane(self, point: QPointF) -> QPointF:
        return QPointF((point.x() - self.dx) / self.scale, (point.y() - self.dy) / self.scale)


class Minimap(QWidget):
    """Where the graph is, where you are, and a way to get somewhere else."""

    def __init__(self, view: QGraphicsView) -> None:
        # Parented to the view rather than to its viewport, and raised over it. A child of
        # the viewport would be dragged along by every pan: QGraphicsView scrolls by
        # ``QWidget::scroll``, which moves the viewport's children with the pixels.
        super().__init__(view)
        self.setObjectName("CanvasMinimap")
        # A plain QWidget ignores a stylesheet background unless it is told to draw one.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # The canvas has no scroll bars, so this is also where somebody looking for a way to
        # get around will hover — which makes it the right place to name the pan gesture.
        self.setToolTip("Click to look somewhere else. Hold Space and drag to pan.")
        self.setFixedSize(SIZE)
        self.raise_()
        self._view = view
        self._nodes: list[QRectF] = []
        self._looking_at = QRectF()
        self.hide()

    def show_graph(self, nodes: list[QRectF], looking_at: QRectF) -> None:
        """Draw this graph, seen through this rectangle.

        An empty graph takes the map off screen rather than framing nothing — DESIGN.md's
        rule for a panel with nothing to say, one surface down.
        """
        self._nodes = nodes
        self._looking_at = looking_at
        self.setVisible(bool(nodes))
        self.update()

    def place(self) -> None:
        """Sit in the lower-left corner of the canvas. Called when the view is resized."""
        parent = self.parentWidget()
        if parent is not None:
            self.move(INSET, parent.height() - self.height() - INSET)

    # -- painting ------------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        super().paintEvent(event)  # The well, from the stylesheet.
        fit = self._fit()
        if fit is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = self.palette()

        ink = QColor(palette.text().color())
        ink.setAlpha(NODE_ALPHA)
        painter.setBrush(ink)
        painter.setPen(Qt.PenStyle.NoPen)
        for rect in self._nodes:
            painter.drawRoundedRect(fit.to_map(rect), NODE_RADIUS, NODE_RADIUS)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(palette.highlight().color(), 1.0))
        # Clipped to the well rather than left to fall off it: a viewport wider than the
        # graph then reads as a frame around everything, which is what it is.
        painter.drawRect(fit.to_map(self._looking_at).intersected(self._box()))

    # -- going somewhere -----------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        self._look_at(event.position())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._look_at(event.position())

    def _look_at(self, point: QPointF) -> None:
        fit = self._fit()
        if fit is not None:
            self._view.centerOn(fit.to_plane(point))

    # -- internals -----------------------------------------------------------------------------

    def _box(self) -> QRectF:
        return QRectF(self.rect()).adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)

    def _fit(self) -> _Fit | None:
        """How to draw the graph, and where in the well it goes.

        What is shown is the graph plus *the point you are standing on* — not plus the whole
        viewport. Uniting with the viewport would let zooming out shrink the graph to a row
        of specks, which is the one thing a map is for; uniting with its centre keeps the
        graph the size of the well until you actually pan off it, and then opens out just
        far enough to show that you have.
        """
        if not self._nodes:
            return None
        here = self._looking_at.center()
        shown = QRectF(here.x(), here.y(), 1.0, 1.0)
        for rect in self._nodes:
            shown = shown.united(rect)
        shown = shown.adjusted(-PADDING, -PADDING, PADDING, PADDING)
        box = self._box()
        scale = min(box.width() / shown.width(), box.height() / shown.height())
        return _Fit(
            scale=scale,
            dx=box.center().x() - shown.center().x() * scale,
            dy=box.center().y() - shown.center().y() * scale,
        )
