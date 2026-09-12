"""Four lanes of cards joined by lines: the coverage trace, drawn.

One ``QGraphicsScene``, four :class:`LaneItem`\\ s side by side, each a clipped column that
scrolls on its own — the wheel over a lane moves that lane, a thumb on its right edge
shows how much is out of view — and between neighbouring lanes a :class:`GutterItem`
holding the :class:`LinkItem`\\ s. A link runs from a lane's right edge to the next lane's
left edge, at the height of the cards it joins; a card scrolled out of view carries its
end of the line past the gutter's clip, so the line is cut at the gutter's edge rather
than drawn over a caption. The view never scrolls: the lanes do.

**Picking lights a path and scrolls the other lanes to it.** The scene asks the trace
(:meth:`~dplanner.modules.coverage.trace.Trace.path`) and dims everything else to a
fraction; every lane but the one the pick landed in brings its first lit card into view.
The picked lane never moves — the card under the pointer stays under the pointer.

Every colour is read from the scene's palette at paint time (``items.live_palette``'s
discipline), so a theme switch repaints the picture with nothing stored to go stale. Card
metrics and the shadow are ``theme/cards.py``'s, shared with the canvas; the state a card
wears is a mark — a dot, a ring — never a phrase.
"""

from collections.abc import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSceneHoverEvent,
    QGraphicsSceneMouseEvent,
    QGraphicsSceneWheelEvent,
    QStyleOptionGraphicsItem,
    QWidget,
)

from dplanner.modules.coverage.trace import COLUMN_TITLES, Item, Trace
from dplanner.theme.cards import (
    DIM_OPACITY,
    FILL_ALPHA,
    LIFT,
    LIFTED_SHADOW,
    LINE_GAP,
    PAD_Y,
    PADDING,
    RADIUS,
    RESTING_SHADOW,
    SELECTED_BORDER_W,
    SELECTED_FILL_GAIN,
    over,
    paint_shadow,
    title_font,
    title_lines,
)
from dplanner.theme.icons import paint_beaker_glyph, paint_layers_glyph, paint_tag_glyph
from dplanner.theme.tokens import SECONDARY_ALPHA
from dplanner.theme.tones import GOOD_BORDER, toned

# DESIGN.md's 4-point scale: the tab page's 16, a lane's 12 inside, 12 between cards.
MARGIN = 16.0
LANE_PAD = 12.0
CARD_GAP = 12.0
GUTTER = 56.0  # Room for a curve to read as a curve…
GUTTER_NARROW = 32.0  # …and what it gives up on a narrow viewport before the lanes do.
LANE_MIN_W = 168.0  # Two words of title beside a medallion; narrower is unreadable.
NARROW_VIEWPORT = 1100.0
CAPTION_H = 28.0
THUMB_W = 4.0
THUMB_INSET = 4.0
THUMB_MIN = 24.0
WHEEL_STEP = 48.0  # Scene units per wheel notch.

# The medallion a kind wears, like the canvas's, and the mark a state wears.
MEDALLION_D = 20.0
MARK_D = 8.0
GLYPHS = {"feature": paint_layers_glyph, "milestone": paint_tag_glyph, "test": paint_beaker_glyph}

# What is not on the path fades to ``DIM_OPACITY`` (theme/cards.py, shared with the canvas's
# spotlight); a lit link thickens like a selected edge.
LINK_ALPHA = 70
LINK_W = 1.4
LINK_LIT_W = 2.4

# Semantic marks: constant tints that read on every theme (DESIGN.md exception #2).
BAD = QColor(220, 110, 110)
MUTED_FILL_ALPHA = 14
MUTED_BORDER_ALPHA = 50

# How far a card's paint reaches outside its body: the lifted shadow, and the lift.
CARD_MARGIN = LIFTED_SHADOW.drop + LIFTED_SHADOW.spread + 1.0 + LIFT


def kind_of(item: Item) -> str:
    return item.id.split(":", 1)[0]


class CardItem(QGraphicsObject):
    """One item of the trace as a card: title, one secondary line, a medallion for its
    kind and a mark for its state. It reports presses; the scene decides what they mean."""

    clicked = Signal(str)
    double_clicked = Signal(str)
    menu_requested = Signal(str, QPointF)

    def __init__(self, item: Item, width: float) -> None:
        super().__init__()
        self.item = item
        self.width = width
        self.height = 0.0
        self.selected = False
        self.hovered = False
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)

    # -- geometry ------------------------------------------------------------------------

    def measure(self, base: QFont) -> float:
        """The card's height for its width and this font — the layout asks, once."""
        titles = QFontMetricsF(title_font(base))
        chrome = QFontMetricsF(base)
        lines = len(title_lines(titles, self.item.title, self._title_width(), max_lines=2))
        height = PAD_Y * 2 + lines * titles.height()
        if self.item.detail:
            height += LINE_GAP + chrome.height()
        self.height = max(height, MEDALLION_D + PAD_Y * 2)
        return self.height

    def body(self) -> QRectF:
        return QRectF(0.0, 0.0, self.width, self.height)

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt override
        return self.body().adjusted(-CARD_MARGIN, -CARD_MARGIN, CARD_MARGIN, CARD_MARGIN)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(self.body(), RADIUS, RADIUS)
        return path

    def _title_width(self) -> float:
        glyph = MEDALLION_D + PADDING / 2 if kind_of(self.item) in GLYPHS else 0.0
        return self.width - 2 * PADDING - glyph - MARK_D - PADDING / 2

    # -- look ----------------------------------------------------------------------------

    def set_selected(self, selected: bool) -> None:
        if selected != self.selected:
            self.selected = selected
            self.setZValue(1.0 if selected else 0.0)
            self.update()

    def paint(
        self,
        painter: QPainter,
        _option: QStyleOptionGraphicsItem,
        _widget: QWidget | None = None,
    ) -> None:
        palette = self._palette()
        body = self.body()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.save()
        paint_shadow(painter, body, LIFTED_SHADOW if self.selected else RESTING_SHADOW)
        if self.selected:
            painter.translate(0.0, -LIFT)
        self._paint_body(painter, palette, body)
        inner = body.adjusted(PADDING, PAD_Y, -PADDING, -PAD_Y)
        text = QColor(palette.text().color())
        faded = QColor(text)
        faded.setAlpha(SECONDARY_ALPHA)
        if self.item.muted:
            text.setAlpha(SECONDARY_ALPHA)
        left = inner.left()
        glyph = GLYPHS.get(kind_of(self.item))
        if glyph is not None:
            self._paint_medallion(
                painter,
                palette,
                QPointF(left + MEDALLION_D / 2, inner.top() + MEDALLION_D / 2),
                glyph,
            )
            left += MEDALLION_D + PADDING / 2
        self._paint_mark(
            painter, palette, QPointF(inner.right() - MARK_D / 2, inner.top() + MARK_D / 2 + 2)
        )
        painter.setPen(text)
        font = title_font(painter.font())
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        y = inner.top()
        for line in title_lines(metrics, self.item.title, self._title_width(), max_lines=2):
            painter.drawText(QPointF(left, y + metrics.ascent()), line)
            y += metrics.height()
        if self.item.detail:
            painter.setFont(_base_font(painter.font()))
            painter.setPen(faded)
            chrome = QFontMetricsF(painter.font())
            detail = chrome.elidedText(
                self.item.detail, Qt.TextElideMode.ElideRight, int(inner.right() - left)
            )
            painter.drawText(QPointF(left, y + LINE_GAP + chrome.ascent()), detail)
        painter.restore()

    def _paint_body(self, painter: QPainter, palette: QPalette, body: QRectF) -> None:
        # A milestone card recolours its tone to its own shade, exactly as its card on the
        # canvas does — one resolver, so the two lanes cannot disagree.
        tone = toned(self.item.tone, self.item.color)
        if tone is not None:
            tint = QColor(tone[0])
        else:
            tint = QColor(palette.text().color())
            tint.setAlpha(MUTED_FILL_ALPHA if self.item.muted else FILL_ALPHA)
        if self.selected:
            tint.setAlpha(min(255, round(tint.alpha() * SELECTED_FILL_GAIN)))
            border, width = QColor(palette.highlight().color()), SELECTED_BORDER_W
        elif tone is not None:
            border, width = QColor(tone[1]), 1.5
        else:
            border = QColor(palette.text().color())
            border.setAlpha(MUTED_BORDER_ALPHA if self.item.muted else 90)
            width = 1.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(over(palette.window().color(), tint))
        painter.drawRoundedRect(body, RADIUS, RADIUS)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(border, width)
        if self.item.state in ("lost", "missing"):
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRoundedRect(body, RADIUS, RADIUS)

    def _paint_medallion(
        self, painter: QPainter, palette: QPalette, centre: QPointF, glyph: object
    ) -> None:
        ring = QColor(palette.text().color())
        ring.setAlpha(90)
        painter.setPen(QPen(ring, 1.0))
        painter.setBrush(over(palette.window().color(), QColor(0, 0, 0, 0)))
        painter.drawEllipse(centre, MEDALLION_D / 2, MEDALLION_D / 2)
        size = MEDALLION_D * 4 / 7
        rect = QRectF(centre.x() - size / 2, centre.y() - size / 2, size, size)
        ink = QColor(palette.text().color())
        ink.setAlpha(SECONDARY_ALPHA)
        glyph(painter, rect, ink)  # type: ignore[operator]

    def _paint_mark(self, painter: QPainter, palette: QPalette, centre: QPointF) -> None:
        """One mark for one state: the accent hollow for *behind* and *never*, the accent
        filled for *drifted* and *stale*, green for *ok*, red for *failed* and *lost*, a
        faint dot for *skipped*, a faint ring for *pending*. Nothing for the quiet states."""
        state = self.item.state
        accent = QColor(palette.highlight().color())
        faint = QColor(palette.text().color())
        faint.setAlpha(SECONDARY_ALPHA)
        hollow = {"behind": accent, "never": accent, "pending": faint}
        filled = {
            "drifted": accent,
            "stale": accent,
            "ok": GOOD_BORDER,
            "failed": BAD,
            "lost": BAD,
            "missing": BAD,
            "skipped": faint,
        }
        radius = MARK_D / 2
        if state in hollow:
            painter.setPen(QPen(hollow[state], 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(centre, radius - 0.75, radius - 0.75)
        elif state in filled:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(filled[state])
            painter.drawEllipse(centre, radius, radius)

    def _palette(self) -> QPalette:
        scene = self.scene()
        return scene.palette() if scene is not None else QPalette()

    # -- input ---------------------------------------------------------------------------

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent) -> None:  # noqa: N802
        self.hovered = True
        self.update()

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent) -> None:  # noqa: N802
        self.hovered = False
        self.update()

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.item.id)
        elif event.button() == Qt.MouseButton.RightButton:
            self.menu_requested.emit(self.item.id, event.screenPos())
        event.accept()

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.item.id)
        event.accept()


def _base_font(font: QFont) -> QFont:
    """The chrome face back from the title face: the painter's font, unshifted."""
    base = QFont(font)
    if base.pointSizeF() > 0:
        base.setPointSizeF(base.pointSizeF() - 2.0)
    return base


class LinkItem(QGraphicsPathItem):
    """A curve from one lane's edge to the next, at the height of the cards it joins."""

    def __init__(self, index: int, source: CardItem, target: CardItem) -> None:
        super().__init__()
        self.index = index
        self.source = source
        self.target = target
        self.lit: bool | None = None
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def follow(self, left_x: float, right_x: float) -> None:
        """Lay the curve between the gutter's two edges at the cards' current heights."""
        start = QPointF(left_x, self._mid_y(self.source))
        end = QPointF(right_x, self._mid_y(self.target))
        path = QPainterPath(start)
        reach = max(24.0, (end.x() - start.x()) / 2)
        path.cubicTo(QPointF(start.x() + reach, start.y()), QPointF(end.x() - reach, end.y()), end)
        self.setPath(path)

    def _mid_y(self, card: CardItem) -> float:
        parent = self.parentItem()
        point = card.mapToScene(QPointF(0.0, card.height / 2))
        return parent.mapFromScene(point).y() if parent is not None else point.y()

    def set_lit(self, lit: bool | None) -> None:
        if lit != self.lit:
            self.lit = lit
            self.setOpacity(DIM_OPACITY if lit is False else 1.0)
            self.update()

    def paint(
        self,
        painter: QPainter,
        _option: QStyleOptionGraphicsItem,
        _widget: QWidget | None = None,
    ) -> None:
        scene = self.scene()
        palette = scene.palette() if scene is not None else QPalette()
        if self.lit:
            colour, width = QColor(palette.highlight().color()), LINK_LIT_W
        else:
            colour = QColor(palette.text().color())
            colour.setAlpha(LINK_ALPHA)
            width = LINK_W
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(colour, width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.path())


class GutterItem(QGraphicsRectItem):
    """The space between two lanes, clipping the links it holds to its own rect."""

    def __init__(self) -> None:
        super().__init__()
        self.setPen(Qt.PenStyle.NoPen)
        self.setBrush(Qt.BrushStyle.NoBrush)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape, True)
        self.setZValue(-1.0)


class LaneItem(QGraphicsObject):
    """One column: a captioned lane with its own scroll, holding its cards under a clip."""

    scrolled = Signal()

    def __init__(self, column: int, title: str) -> None:
        super().__init__()
        self.column = column
        self.title = title
        self.rect = QRectF()
        self.offset = 0.0
        self.content_height = 0.0
        self.cards: list[CardItem] = []
        self.clip = QGraphicsRectItem(self)
        self.clip.setPen(Qt.PenStyle.NoPen)
        self.clip.setBrush(Qt.BrushStyle.NoBrush)
        self.clip.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape, True)
        self.holder = QGraphicsRectItem(self.clip)
        self.holder.setPen(Qt.PenStyle.NoPen)
        self.holder.setBrush(Qt.BrushStyle.NoBrush)
        self._dragging: float | None = None
        self.setAcceptHoverEvents(True)

    # -- geometry ------------------------------------------------------------------------

    def place(self, rect: QRectF, base: QFont) -> None:
        """Take a rect; stack the cards inside it; keep the scroll in range."""
        self.prepareGeometryChange()
        self.rect = rect
        self.setPos(rect.topLeft())
        width = rect.width() - 2 * LANE_PAD
        y = 0.0
        for card in self.cards:
            card.width = width
            card.measure(base)
            card.setPos(LANE_PAD, y)
            y += card.height + CARD_GAP
        self.content_height = max(0.0, y - CARD_GAP)
        self.clip.setRect(
            QRectF(0.0, CAPTION_H, rect.width(), max(0.0, rect.height() - CAPTION_H - LANE_PAD))
        )
        self.set_offset(self.offset)

    def visible_height(self) -> float:
        return self.clip.rect().height() - LANE_PAD

    def max_offset(self) -> float:
        return max(0.0, self.content_height - self.visible_height())

    def set_offset(self, offset: float) -> None:
        self.offset = max(0.0, min(self.max_offset(), offset))
        self.holder.setPos(0.0, CAPTION_H + LANE_PAD - self.offset)
        self.update()
        self.scrolled.emit()

    def scroll_into_view(self, card: CardItem) -> None:
        top = card.y()
        bottom = top + card.height
        if top < self.offset:
            self.set_offset(top)
        elif bottom > self.offset + self.visible_height():
            self.set_offset(bottom - self.visible_height())

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt override
        return QRectF(0.0, 0.0, self.rect.width(), self.rect.height())

    def thumb(self) -> QRectF | None:
        """Where the scroll thumb is, or None while everything fits."""
        if self.max_offset() <= 0.0:
            return None
        track = self.clip.rect().adjusted(0.0, 0.0, 0.0, -LANE_PAD)
        share = self.visible_height() / max(self.content_height, 1.0)
        length = max(THUMB_MIN, track.height() * share)
        travel = track.height() - length
        top = track.top() + travel * (self.offset / self.max_offset())
        return QRectF(self.rect.width() - THUMB_INSET - THUMB_W, top, THUMB_W, length)

    # -- look ----------------------------------------------------------------------------

    def paint(
        self,
        painter: QPainter,
        _option: QStyleOptionGraphicsItem,
        _widget: QWidget | None = None,
    ) -> None:
        scene = self.scene()
        palette = scene.palette() if scene is not None else QPalette()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # The lane: a list on a tab page needs its own ground (DESIGN.md's #ProgressionLane).
        painter.setPen(QPen(QColor(palette.mid().color()), 1.0))
        painter.setBrush(QColor(palette.alternateBase().color()))
        painter.drawRoundedRect(self.boundingRect().adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
        caption = QColor(palette.text().color())
        caption.setAlpha(SECONDARY_ALPHA)
        font = QFont(painter.font())
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(caption)
        painter.drawText(
            QRectF(LANE_PAD, 0.0, self.rect.width() - 2 * LANE_PAD, CAPTION_H),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self.title,
        )
        thumb = self.thumb()
        if thumb is not None:
            ink = QColor(palette.text().color())
            ink.setAlpha(120 if self._dragging is not None or self.isUnderMouse() else 60)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ink)
            painter.drawRoundedRect(thumb, THUMB_W / 2, THUMB_W / 2)

    # -- input ---------------------------------------------------------------------------

    def wheelEvent(self, event: QGraphicsSceneWheelEvent) -> None:  # noqa: N802
        notches = event.delta() / 120.0
        self.set_offset(self.offset - notches * WHEEL_STEP)
        event.accept()

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        thumb = self.thumb()
        if (
            thumb is not None
            and thumb.contains(event.pos())
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._dragging = event.pos().y() - thumb.top()
            event.accept()
            return
        event.ignore()  # The ground: the scene clears the path.

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        if self._dragging is None:
            return
        thumb = self.thumb()
        if thumb is None:
            return
        track = self.clip.rect().adjusted(0.0, 0.0, 0.0, -LANE_PAD)
        travel = max(1.0, track.height() - thumb.height())
        top = event.pos().y() - self._dragging - track.top()
        self.set_offset(self.max_offset() * max(0.0, min(1.0, top / travel)))

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        self._dragging = None
        self.update()


class CoverageScene(QGraphicsScene):
    """The trace as lanes, cards and links; picks, scrolls and lights them."""

    picked = Signal(str)  # An item id, or "" when the path is cleared.
    activated = Signal(str)
    menu_requested = Signal(str, QPointF)

    def __init__(self) -> None:
        super().__init__()
        self.trace: Trace | None = None
        self.lanes = [LaneItem(column, title) for column, title in enumerate(COLUMN_TITLES)]
        self.gutters = [GutterItem() for _ in range(len(COLUMN_TITLES) - 1)]
        for lane in self.lanes:
            self.addItem(lane)
            lane.scrolled.connect(self._follow_links)
        for gutter in self.gutters:
            self.addItem(gutter)
        self.cards: dict[str, CardItem] = {}
        self.links: list[LinkItem] = []
        self.lit: str | None = None
        self._viewport = (900.0, 600.0)
        self._font = QFont()

    # -- what is shown ---------------------------------------------------------------------

    def show_trace(self, trace: Trace, base: QFont | None = None) -> None:
        """Rebuild wholesale; keep the lit path by id where the id survives."""
        if base is not None:
            self._font = base
        self.trace = trace
        for lane in self.lanes:
            for card in lane.cards:
                self.removeItem(card)
            lane.cards = []
        for link in self.links:
            self.removeItem(link)
        self.links = []
        self.cards = {}
        for item in trace.items:
            card = CardItem(item, LANE_MIN_W)
            card.setParentItem(self.lanes[item.column].holder)
            card.clicked.connect(self.pick)
            card.double_clicked.connect(self.activated)
            card.menu_requested.connect(self.menu_requested)
            self.lanes[item.column].cards.append(card)
            self.cards[item.id] = card
        for index, edge in enumerate(trace.links):
            source, target = self.cards.get(edge.source), self.cards.get(edge.target)
            if source is None or target is None:
                continue
            drawn = LinkItem(index, source, target)
            drawn.setParentItem(self.gutters[source.item.column])
            self.links.append(drawn)
        self.relayout()
        self.pick(self.lit if self.lit in self.cards else None, scroll=False)

    def relayout(self, viewport: tuple[float, float] | None = None) -> None:
        """Lay the lanes across the viewport's width; never inside a paint."""
        if viewport is not None:
            self._viewport = viewport
        width, height = self._viewport
        lanes = len(self.lanes)
        lane_w = max(LANE_MIN_W, (width - 2 * MARGIN - (lanes - 1) * GUTTER) / lanes)
        lane_h = max(CAPTION_H + LANE_PAD * 2, height - 2 * MARGIN)
        x = MARGIN
        for index, lane in enumerate(self.lanes):
            lane.place(QRectF(x, MARGIN, lane_w, lane_h), self._font)
            if index < len(self.gutters):
                self.gutters[index].setRect(
                    QRectF(x + lane_w, MARGIN + CAPTION_H, GUTTER, lane_h - CAPTION_H - LANE_PAD)
                )
            x += lane_w + GUTTER
        self.setSceneRect(
            QRectF(0.0, 0.0, max(width, x - GUTTER + MARGIN), max(height, lane_h + 2 * MARGIN))
        )
        self._follow_links()

    def _follow_links(self) -> None:
        for link in self.links:
            gutter = self.gutters[link.source.item.column]
            rect = gutter.rect()
            link.follow(rect.left(), rect.right())

    # -- picking ---------------------------------------------------------------------------

    def pick(self, item_id: str | None, *, scroll: bool = True) -> None:
        """Light ``item_id``'s path — or clear it — and bring the rest of it into view
        in every lane but the one it is in."""
        self.lit = item_id if item_id in self.cards else None
        path = self.trace.path(self.lit) if self.trace is not None and self.lit else None
        for card_id, card in self.cards.items():
            card.set_selected(card_id == self.lit)
            card.setOpacity(1.0 if path is None or card_id in path.items else DIM_OPACITY)
        for link in self.links:
            link.set_lit(None if path is None else link.index in path.links)
        if scroll and path is not None and self.lit is not None:
            picked_column = self.cards[self.lit].item.column
            self._scroll_to(path.items, skip=picked_column)
        self.picked.emit(self.lit or "")

    def focus(self, item_id: str) -> None:
        """Light the path and bring the item itself into view too — a jump's landing."""
        if item_id not in self.cards:
            return
        self.pick(item_id)
        card = self.cards[item_id]
        self.lanes[card.item.column].scroll_into_view(card)

    def _scroll_to(self, lit: frozenset[str], *, skip: int) -> None:
        for lane in self.lanes:
            if lane.column == skip:
                continue
            first = next((card for card in lane.cards if card.item.id in lit), None)
            if first is not None:
                lane.scroll_into_view(first)

    def lane_cards(self, column: int) -> Sequence[CardItem]:
        return self.lanes[column].cards

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        super().mousePressEvent(event)
        if not event.isAccepted() and event.button() == Qt.MouseButton.LeftButton:
            self.pick(None)
