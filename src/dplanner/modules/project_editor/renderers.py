"""How a step node looks: pure paint functions over a palette, a rect and the accent.

``StepNodeItem`` holds state and geometry; everything it draws is composed here from small
helpers that each take an explicit rect. A different look — a compact node, in-node editing
chrome — is a new composition of the same helpers, not a subclass: the seam is
:func:`paint_node`'s signature, and that is deliberately all there is.

The vocabulary is the canvas's own. :class:`NodeAccent` never names an aspect ("done",
"merged") — the composition root translates aspects into tones and texts, the same seam
``step_aspects`` uses for the subtitle. :class:`RenderHints` is the mode's voice: the mode
stack announces, the scene fans out, and no item ever reads which mode is current.
"""

from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPalette, QPen

from dplanner.modules.project_editor.positions import NODE_H, NODE_W

RADIUS = 8.0  # = theme.tokens.RADIUS_MD, matched by eye rather than import: this is a painter.
PADDING = 12.0
LINE_GAP = 4.0

# The link handle: a dot on the node's right edge. Dragging from it means "then", so an
# edge always runs left to right and its direction cannot be read the wrong way round.
HANDLE_R = 5.0
# Connect mode's hovered handle grows a touch, so the one under the cursor is unmissable.
HANDLE_EMPHASIS = 1.5

# Secondary text as opacity rather than a theme colour: a painter has only the palette, and
# an alpha-derived secondary is theme-independent by construction (DESIGN.md exception #1).
SECONDARY_ALPHA = 160
FILL_ALPHA = 28

# Low-alpha semantic tints that read on every theme (DESIGN.md exception #2).
VALID_TINT = QColor(120, 200, 140, 180)
INVALID_TINT = QColor(220, 110, 110, 180)
BUSY_TINT = QColor(110, 160, 220, 180)
BADGE_TINT = QColor(150, 130, 220, 70)
BADGE_BORDER = QColor(150, 130, 220, 160)
CHIP_INFO_TINT = QColor(90, 170, 200, 70)
CHIP_INFO_BORDER = QColor(90, 170, 200, 160)
CHIP_ATTENTION_TINT = QColor(220, 170, 90, 70)
CHIP_ATTENTION_BORDER = QColor(220, 170, 90, 160)

# A muted node: the same colours, further faded. What "muted" means is the caller's business.
MUTED_TEXT_ALPHA = 110
MUTED_SECONDARY_ALPHA = 80
MUTED_FILL_ALPHA = 14
MUTED_BORDER_ALPHA = 50

# The status bar: a slim strip inside the node's left edge, clipped to the rounded body.
BAR_W = 3.0

BADGE_H = 14.0
BADGE_PAD = 6.0
BADGE_INSET = 10.0  # From the node's right edge, clear of the link handle's corner.

# The chip on the bottom edge, left end — the badge's mirror, worn by a live agent run.
CHIP_H = 14.0

# The pill on the second line: a small status label (a PR, say) beside the subtitle.
PILL_H = 14.0
PILL_RADIUS = PILL_H / 2
PILL_PAD_X = 6.0
PILL_MARGIN = 6.0
PILL_FILL_ALPHA = 46
GLYPH_SIZE = 9.0
GLYPH_GAP = 5.0

BAR_TONES = {"good": VALID_TINT, "busy": BUSY_TINT, "bad": INVALID_TINT}
CHIP_TONES = {
    "info": (CHIP_INFO_TINT, CHIP_INFO_BORDER),
    "attention": (CHIP_ATTENTION_TINT, CHIP_ATTENTION_BORDER),
}


@dataclass(frozen=True)
class NodeAccent:
    """How a node should look beyond its text, in the canvas's own vocabulary.

    The canvas never learns which aspect means "muted", what a badge says, or which
    aspect a pill stands for — the composition root translates aspects into this, the
    same seam ``step_aspects`` uses for the subtitle. A ``badge`` sits on the top edge
    (a release label); a ``chip`` sits on the bottom edge (a live agent run); a ``pill``
    sits on the second line with a tone that is "good" or "bad", never "merged";
    ``branch`` and ``spark`` ask for the small glyphs beside it; ``bar_tone`` is the slim
    strip inside the left edge.
    """

    muted: bool = False
    badge: str = ""
    pill_text: str = ""  # "" → no pill.
    pill_tone: str = ""  # "" neutral | "good" | "bad".
    branch: bool = False  # Paint the branch glyph.
    bar_tone: str = ""  # "" none | "good" | "busy" | "bad".
    spark: bool = False  # Paint the spark glyph: there is machine guidance here.
    chip_text: str = ""  # "" → no chip.
    chip_tone: str = ""  # "" neutral | "info" | "attention".


@dataclass(frozen=True)
class RenderHints:
    """What the current canvas mode wants every node to show.

    Pushed by the scene when the mode stack changes — an item holds the hints as data and
    never asks which mode is current. ``handles``: "hover" shows the link handle on the
    hovered node only (idle), "always" fades one onto every node (connect mode, where
    every handle is a target), "hidden" suppresses them (pan and the region modes, whose
    presses do not link).
    """

    handles: str = "hover"  # "hover" | "always" | "hidden"


@dataclass(frozen=True)
class NodeState:
    """The transient half of a node's look: selection, hover, link aim, and mode hints."""

    selected: bool = False
    hovered: bool = False
    link_state: str = ""  # "" | "valid" | "invalid"
    hints: RenderHints = field(default_factory=RenderHints)


def paint_node(
    painter: QPainter,
    palette: QPalette,
    title: str,
    subtitle: str,
    accent: NodeAccent,
    state: NodeState,
) -> None:
    """The default node: body, two text lines, edge decorations, and the link handle."""
    body = QRectF(0, 0, NODE_W, NODE_H)
    text_colour = QColor(palette.text().color())
    if accent.muted:
        text_colour.setAlpha(MUTED_TEXT_ALPHA)
    faded = QColor(palette.text().color())
    faded.setAlpha(MUTED_SECONDARY_ALPHA if accent.muted else SECONDARY_ALPHA)

    paint_body(painter, palette, body, accent, state)
    inner = body.adjusted(PADDING, PADDING, -PADDING, -PADDING)
    paint_title_line(painter, inner, title, text_colour, accent.muted)
    paint_second_line(painter, inner, subtitle, accent, text_colour, faded)
    if accent.badge:
        paint_badge(painter, palette, accent.badge)
    if accent.chip_text:
        paint_chip(painter, palette, accent.chip_text, accent.chip_tone)
    paint_handle(painter, palette, state)


def paint_body(
    painter: QPainter, palette: QPalette, body: QRectF, accent: NodeAccent, state: NodeState
) -> None:
    """The rounded rect: fill, border (selection and link aim win), and the status bar."""
    muted = accent.muted
    fill = QColor(palette.text().color())
    fill.setAlpha(MUTED_FILL_ALPHA if muted else FILL_ALPHA)
    border = QColor(palette.highlight().color())
    if state.link_state == "valid":
        border = VALID_TINT
    elif state.link_state == "invalid":
        border = INVALID_TINT
    elif not state.selected:
        border = QColor(palette.text().color())
        border.setAlpha(MUTED_BORDER_ALPHA if muted else 90)
    painter.setBrush(fill)
    painter.setPen(QPen(border, 2.0 if state.selected or state.link_state else 1.0))
    painter.drawRoundedRect(body, RADIUS, RADIUS)
    if accent.bar_tone in BAR_TONES:
        paint_status_bar(painter, body, accent.bar_tone)


def paint_status_bar(painter: QPainter, body: QRectF, tone: str) -> None:
    """A slim strip inside the left edge, clipped to the rounded body."""
    clip = QPainterPath()
    clip.addRoundedRect(body, RADIUS, RADIUS)
    painter.save()
    painter.setClipPath(clip)
    painter.fillRect(QRectF(body.left(), body.top(), BAR_W, body.height()), BAR_TONES[tone])
    painter.restore()


def paint_title_line(
    painter: QPainter, inner: QRectF, title: str, text_colour: QColor, muted: bool
) -> None:
    metrics = painter.fontMetrics()
    title_left = inner.left()
    painter.setPen(text_colour)
    if muted:
        # A check before the title says "done" without a word taking subtitle space.
        check = "✓"
        painter.drawText(
            QRectF(title_left, inner.top(), inner.width(), metrics.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            check,
        )
        title_left += metrics.horizontalAdvance(check + " ")
    title_width = inner.right() - title_left
    painter.drawText(
        QRectF(title_left, inner.top(), title_width, metrics.height()),
        int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        metrics.elidedText(title, Qt.TextElideMode.ElideRight, int(title_width)),
    )


def paint_second_line(
    painter: QPainter,
    inner: QRectF,
    subtitle: str,
    accent: NodeAccent,
    text_colour: QColor,
    faded: QColor,
) -> None:
    """Subtitle on the left; pill, then branch and spark glyphs, right-aligned.

    The decorations take their width first so the subtitle's elision stays honest.
    """
    metrics = painter.fontMetrics()
    second_top = inner.top() + metrics.height() + LINE_GAP
    pill_font = QFont(painter.font())
    pill_font.setPointSizeF(max(6.0, pill_font.pointSizeF() - 1))
    pill_w = (
        QFontMetricsF(pill_font).horizontalAdvance(accent.pill_text) + 2 * PILL_PAD_X
        if accent.pill_text
        else 0.0
    )
    glyphs = int(accent.branch) + int(accent.spark)
    glyph_w = glyphs * GLYPH_SIZE + (glyphs - (0 if pill_w else 1)) * GLYPH_GAP if glyphs else 0.0
    reserved = pill_w + glyph_w + (PILL_MARGIN if pill_w or glyph_w else 0.0)

    if subtitle:
        painter.setPen(faded)
        width = inner.width() - reserved
        painter.drawText(
            QRectF(inner.left(), second_top, width, metrics.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
            metrics.elidedText(subtitle, Qt.TextElideMode.ElideRight, int(width)),
        )
    right = inner.right()
    if pill_w:
        pill = QRectF(right - pill_w, second_top + (metrics.height() - PILL_H) / 2, pill_w, PILL_H)
        tone = {"good": VALID_TINT, "bad": INVALID_TINT}.get(accent.pill_tone)
        pill_fill = QColor(tone if tone is not None else text_colour)
        pill_fill.setAlpha(PILL_FILL_ALPHA)
        painter.setBrush(pill_fill)
        painter.setPen(QPen(QColor(tone) if tone is not None else faded, 1.0))
        painter.drawRoundedRect(pill, PILL_RADIUS, PILL_RADIUS)
        painter.save()
        painter.setFont(pill_font)
        painter.setPen(text_colour)
        painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), accent.pill_text)
        painter.restore()
        right -= pill_w + GLYPH_GAP
    glyph_top = second_top + (metrics.height() - GLYPH_SIZE) / 2
    if accent.branch:
        paint_branch_glyph(
            painter, QRectF(right - GLYPH_SIZE, glyph_top, GLYPH_SIZE, GLYPH_SIZE), faded
        )
        right -= GLYPH_SIZE + GLYPH_GAP
    if accent.spark:
        paint_spark_glyph(
            painter, QRectF(right - GLYPH_SIZE, glyph_top, GLYPH_SIZE, GLYPH_SIZE), faded
        )


def paint_badge(painter: QPainter, palette: QPalette, text: str) -> None:
    """A pill on the top edge, right end: the release label, sitting on the border.

    It rises half its height above the node, which is why it must stay inside the item's
    ``boundingRect`` margin — ``BADGE_H / 2 + 1 <= HANDLE_R + 4`` keeps that true, and the
    chip on the bottom edge owes the same inequality.
    """
    font = painter.font()
    small = painter.font()
    small.setPointSizeF(max(6.0, font.pointSizeF() - 2.0))
    painter.setFont(small)
    metrics = painter.fontMetrics()
    shown = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(NODE_W * 0.6))
    width = metrics.horizontalAdvance(shown) + 2 * BADGE_PAD
    pill = QRectF(NODE_W - BADGE_INSET - width, -BADGE_H / 2, width, BADGE_H)
    painter.setBrush(BADGE_TINT)
    painter.setPen(QPen(BADGE_BORDER, 1.0))
    painter.drawRoundedRect(pill, BADGE_H / 2, BADGE_H / 2)
    painter.setPen(QColor(palette.text().color()))
    painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), shown)
    painter.setFont(font)


def paint_chip(painter: QPainter, palette: QPalette, text: str, tone: str) -> None:
    """A pill on the bottom edge, left end: the badge's mirror, worn by a live agent run."""
    font = painter.font()
    small = painter.font()
    small.setPointSizeF(max(6.0, font.pointSizeF() - 2.0))
    painter.setFont(small)
    metrics = painter.fontMetrics()
    shown = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(NODE_W * 0.5))
    width = metrics.horizontalAdvance(shown) + 2 * BADGE_PAD
    pill = QRectF(BADGE_INSET, NODE_H - CHIP_H / 2, width, CHIP_H)
    ink = QColor(palette.text().color())
    faded_ink = QColor(ink)
    faded_ink.setAlpha(SECONDARY_ALPHA)
    fill, border = CHIP_TONES.get(tone, (QColor(ink.red(), ink.green(), ink.blue(), 24), faded_ink))
    painter.setBrush(fill)
    painter.setPen(QPen(border, 1.0))
    painter.drawRoundedRect(pill, CHIP_H / 2, CHIP_H / 2)
    painter.setPen(ink)
    painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), shown)
    painter.setFont(font)


def paint_handle(painter: QPainter, palette: QPalette, state: NodeState) -> None:
    """The link dot on the right edge — what the hints say the mode wants of it.

    "hidden" paints none, whatever the cursor does. "hover" (idle) paints the hovered
    node's, full. "always" (connect) fades one onto every node and grows the hovered one:
    every handle is a target, and the one under the cursor is unmissable.
    """
    hints = state.hints
    if hints.handles == "hidden":
        return
    centre = QPointF(NODE_W, NODE_H / 2)
    active = state.hovered or bool(state.link_state)
    if active:
        painter.setBrush(QColor(palette.highlight().color()))
        painter.setPen(Qt.PenStyle.NoPen)
        radius = HANDLE_R + (HANDLE_EMPHASIS if hints.handles == "always" else 0.0)
        painter.drawEllipse(centre, radius, radius)
    elif hints.handles == "always":
        faded = QColor(palette.highlight().color())
        faded.setAlpha(120)
        painter.setBrush(faded)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(centre, HANDLE_R, HANDLE_R)


def paint_branch_glyph(painter: QPainter, rect: QRectF, colour: QColor) -> None:
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


def paint_spark_glyph(painter: QPainter, rect: QRectF, colour: QColor) -> None:
    """A four-pointed spark: there is machine guidance — an agent instruction — here."""
    cx, cy = rect.center().x(), rect.center().y()
    pull = rect.width() * 0.14
    path = QPainterPath(QPointF(cx, rect.top()))
    path.quadTo(QPointF(cx + pull, cy - pull), QPointF(rect.right(), cy))
    path.quadTo(QPointF(cx + pull, cy + pull), QPointF(cx, rect.bottom()))
    path.quadTo(QPointF(cx - pull, cy + pull), QPointF(rect.left(), cy))
    path.quadTo(QPointF(cx - pull, cy - pull), QPointF(cx, rect.top()))
    painter.setBrush(colour)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawPath(path)
