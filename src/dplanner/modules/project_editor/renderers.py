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
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
)

from dplanner.modules.project_editor.positions import NODE_H, NODE_W
from dplanner.theme.icons import (
    paint_beaker_glyph,
    paint_layers_glyph,
    paint_shield_glyph,
    paint_spark_glyph,
    paint_tag_glyph,
)

RADIUS = 8.0  # = theme.tokens.RADIUS_MD, matched by eye rather than import: this is a painter.
PADDING = 12.0
LINE_GAP = 4.0

# A selected node is *lifted*: it draws this far up from where it sits, over a soft shadow
# left behind at the seat. Two pixels is the whole effect — enough that the eye reads a card
# picked up off the table, small enough that nothing appears to have moved. The edges still
# meet the seat, which is what keeps the graph from twitching as the selection travels.
LIFT = 2.0
# The shadow under it: concentric rounded rects, each fainter and wider than the last, since
# a QPainter has no blur. Constant black at low alpha, like every other semantic tint here
# (DESIGN.md exception #2) — it darkens the ground under the card on any theme.
SHADOW_LAYERS = 4
SHADOW_SPREAD = 5.0  # How far the softest ring reaches past the body.
SHADOW_DROP = 4.0  # How far below the seat the shadow falls.
SHADOW_ALPHA = 30  # The innermost ring's; the outer ones fade from it.

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
# A toned body colours the whole node, so its kind reads at any zoom. "highlight" is the
# badge's purple family — a milestone node, its badge and the order table's milestone row
# are one identity; "good" is the green family — finished work recedes into a calm green
# column the eye can skip; "feature" is teal — the other collector, one rank down.
#
# Teal because of where the hues already are: it sits 76° from the milestone's violet, so
# the two collectors never read as one, and 42° from the done green — which additionally
# *mutes* its node, so the pair is told apart by weight as well as by hue, and a feature
# still wears its layer medallion. The nearest claimed hue is the agent-run chip's teal,
# and that is a labelled pill on the bottom edge of a running step, never a body.
# Fill low-alpha, border full-strength.
HIGHLIGHT_FILL = QColor(150, 130, 220, 36)
GOOD_FILL = QColor(120, 200, 140, 36)
GOOD_BORDER = QColor(120, 200, 140, 160)
FEATURE_FILL = QColor(80, 180, 175, 36)
FEATURE_BORDER = QColor(80, 180, 175, 160)
BODY_TONES = {
    "highlight": (HIGHLIGHT_FILL, BADGE_BORDER),
    "good": (GOOD_FILL, GOOD_BORDER),
    "feature": (FEATURE_FILL, FEATURE_BORDER),
}
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

# Selection: a thicker outline in the accent, and half again the fill the node already had.
# A *gain* rather than a colour of its own is what lets a picked milestone stay purple and a
# picked done step stay green — the accent is already saying "this one" at the border.
SELECTED_BORDER_W = 2.5
SELECTED_FILL_GAIN = 1.6

# The chip on the bottom edge, left end — the badge's mirror, worn by a live agent run.
CHIP_H = 14.0

# The icon medallions on the top edge, left end: one small circle per aspect kind a step
# carries. Sized like the badge, and bound by the same boundingRect inequality.
ICON_D = 14.0
ICON_GAP = 4.0

# The pill on the second line: a small status label (a PR, say) beside the subtitle.
PILL_H = 14.0
PILL_RADIUS = PILL_H / 2
PILL_PAD_X = 6.0
PILL_MARGIN = 6.0
PILL_FILL_ALPHA = 46
GLYPH_SIZE = 9.0
GLYPH_GAP = 5.0

# How far paint reaches outside the body, in every direction: the link handle (grown by
# connect mode's emphasis), a badge's rise or a chip's fall, the lift, and the shadow. It is
# what ``StepNodeItem.boundingRect`` is made of, so a new decoration is measured here or it
# is clipped there.
PAINT_MARGIN = max(
    HANDLE_R + 4.0, BADGE_H / 2 + 1.0 + LIFT, CHIP_H / 2 + 1.0, SHADOW_DROP + SHADOW_SPREAD + 1.0
)

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
    (a milestone label); a ``chip`` sits on the bottom edge (a live agent run); a ``pill``
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
    chip_text: str = ""  # "" → no chip.
    chip_tone: str = ""  # "" neutral | "info" | "attention".
    body_tone: str = ""  # "" plain | "highlight" | "good" | "feature": the node is a kind.
    # Icon medallions on the top edge, left end, in order: "tag" (a milestone the graph
    # aims at), "layers" (a feature: it collects the work behind it), "spark" (there is
    # machine guidance here), "beaker" (this step keeps tests), "shield" (a check: it
    # stands for everything behind it passing).
    icons: tuple[str, ...] = ()
    stat_text: str = ""  # The one number a step answers with — full ink, never faded.
    stat_strong: bool = False  # Bold the stat: this node's number is the point of it.


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
    """The default node: body, two text lines, edge decorations, and the link handle.

    A selected node is drawn :data:`LIFT` above its seat with a shadow left at it, so the
    whole composition — badge, chip, medallions, handle — travels together. The shadow is
    painted first and *unlifted*: it is the ground, not part of the card.
    """
    body = QRectF(0, 0, NODE_W, NODE_H)
    text_colour = QColor(palette.text().color())
    if accent.muted:
        text_colour.setAlpha(MUTED_TEXT_ALPHA)
    faded = QColor(palette.text().color())
    faded.setAlpha(MUTED_SECONDARY_ALPHA if accent.muted else SECONDARY_ALPHA)

    if state.selected:
        paint_shadow(painter, body)
        painter.save()
        painter.translate(0.0, -LIFT)

    paint_body(painter, palette, body, accent, state)
    inner = body.adjusted(PADDING, PADDING, -PADDING, -PADDING)
    paint_title(painter, inner, title, text_colour, accent.muted)
    paint_detail_line(painter, inner, subtitle, accent, text_colour, faded)
    paint_icon_medallions(painter, palette, accent.icons)
    if accent.badge:
        paint_badge(painter, palette, accent.badge)
    if accent.chip_text:
        paint_chip(painter, palette, accent.chip_text, accent.chip_tone)
    paint_handle(painter, palette, state)
    if state.selected:
        painter.restore()


def paint_shadow(painter: QPainter, body: QRectF) -> None:
    """The soft dark ground a lifted node casts: rings of black, each wider and fainter.

    Widest first so the tight, darkest ring lands on top; a QPainter has no blur, and four
    rings at these alphas are indistinguishable from one at the sizes a node is drawn.

    **Clipped to the ground around the card**, because a node's fill is translucent: rings
    left under it would darken the fill itself and a selected step would read as a hole
    rather than as a card off the table.
    """
    card = QPainterPath()
    card.addRoundedRect(body.translated(0.0, -LIFT), RADIUS, RADIUS)
    ground = QPainterPath()
    ground.addRect(
        body.adjusted(
            -SHADOW_SPREAD, -SHADOW_SPREAD - LIFT, SHADOW_SPREAD, SHADOW_SPREAD + SHADOW_DROP
        )
    )
    painter.save()
    painter.setClipPath(ground.subtracted(card))
    painter.setPen(Qt.PenStyle.NoPen)
    for layer in range(SHADOW_LAYERS, 0, -1):
        spread = SHADOW_SPREAD * layer / SHADOW_LAYERS
        painter.setBrush(QColor(0, 0, 0, round(SHADOW_ALPHA / layer)))
        painter.drawRoundedRect(
            body.adjusted(-spread, -spread + SHADOW_DROP, spread, spread + SHADOW_DROP),
            RADIUS + spread,
            RADIUS + spread,
        )
    painter.restore()


def paint_body(
    painter: QPainter, palette: QPalette, body: QRectF, accent: NodeAccent, state: NodeState
) -> None:
    """The rounded rect: fill, border (selection and link aim win), and the status bar.

    A body tone tints the whole node and strengthens its border — this node is a
    different kind of thing, legible at any zoom — but selection and a link drag's
    verdict still outrank it. Selection *deepens* whatever fill the node had rather than
    painting one of its own, so a picked milestone is still purple and a picked done step
    still green — and still recognisably fainter than the work around it.
    """
    muted = accent.muted
    toned = BODY_TONES.get(accent.body_tone)
    if toned is not None:
        fill = QColor(toned[0])
    else:
        fill = QColor(palette.text().color())
        fill.setAlpha(MUTED_FILL_ALPHA if muted else FILL_ALPHA)
    border = QColor(palette.highlight().color())
    width = SELECTED_BORDER_W if state.selected else (2.0 if state.link_state else 1.0)
    if state.link_state == "valid":
        border = VALID_TINT
    elif state.link_state == "invalid":
        border = INVALID_TINT
    elif not state.selected:
        if toned is not None:
            border = QColor(toned[1])
            width = 1.5
        else:
            border = QColor(palette.text().color())
            border.setAlpha(MUTED_BORDER_ALPHA if muted else 90)
    if state.selected:
        fill.setAlpha(min(255, round(fill.alpha() * SELECTED_FILL_GAIN)))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(fill)
    painter.drawRoundedRect(body, RADIUS, RADIUS)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(border, width))
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


def title_lines(metrics: QFontMetrics | QFontMetricsF, title: str, width: float) -> list[str]:
    """The title wrapped onto at most two lines, the second elided.

    Word-accumulation, so a name breaks where a person would break it; a single word too
    wide for a line is left to the elision. Pure, so it can be tested without a painter.
    """
    if metrics.horizontalAdvance(title) <= width:
        return [title]
    words = title.split()
    first = ""
    for index, word in enumerate(words):
        attempt = f"{first} {word}".strip()
        if first and metrics.horizontalAdvance(attempt) > width:
            rest = " ".join(words[index:])
            return [first, metrics.elidedText(rest, Qt.TextElideMode.ElideRight, int(width))]
        first = attempt
    return [metrics.elidedText(title, Qt.TextElideMode.ElideRight, int(width))]


def paint_title(
    painter: QPainter, inner: QRectF, title: str, text_colour: QColor, muted: bool
) -> None:
    """Up to two lines of name, so most steps read in full."""
    metrics = painter.fontMetrics()
    title_left = inner.left()
    painter.setPen(text_colour)
    if muted:
        # A check before the title says "done" without a word taking detail space.
        check = "✓"
        painter.drawText(
            QRectF(title_left, inner.top(), inner.width(), metrics.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            check,
        )
        title_left += metrics.horizontalAdvance(check + " ")
    width = inner.right() - title_left
    for row, line in enumerate(title_lines(metrics, title, width)):
        painter.drawText(
            QRectF(title_left, inner.top() + row * metrics.height(), width, metrics.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            line,
        )


def paint_detail_line(
    painter: QPainter,
    inner: QRectF,
    subtitle: str,
    accent: NodeAccent,
    text_colour: QColor,
    faded: QColor,
) -> None:
    """The bottom line: subtitle on the left; stat, pill and branch glyph right-aligned.

    Anchored to the node's bottom, so a one-line title just leaves air above it. The
    decorations take their width first so the subtitle's elision stays honest, and the
    stat — the one number the step answers with — is the rightmost and the only full-ink
    text on the line.
    """
    metrics = painter.fontMetrics()
    line_top = inner.bottom() - metrics.height()
    stat_font = QFont(painter.font())
    stat_font.setBold(accent.stat_strong)
    stat_w = (
        QFontMetricsF(stat_font).horizontalAdvance(accent.stat_text) if accent.stat_text else 0.0
    )
    pill_font = QFont(painter.font())
    pill_font.setPointSizeF(max(6.0, pill_font.pointSizeF() - 1))
    pill_w = (
        QFontMetricsF(pill_font).horizontalAdvance(accent.pill_text) + 2 * PILL_PAD_X
        if accent.pill_text
        else 0.0
    )
    glyph_w = GLYPH_SIZE if accent.branch else 0.0
    parts = [w for w in (stat_w, pill_w, glyph_w) if w]
    reserved = sum(parts) + GLYPH_GAP * max(0, len(parts) - 1) + (PILL_MARGIN if parts else 0.0)

    if subtitle:
        painter.setPen(faded)
        width = inner.width() - reserved
        painter.drawText(
            QRectF(inner.left(), line_top, width, metrics.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            metrics.elidedText(subtitle, Qt.TextElideMode.ElideRight, int(width)),
        )
    right = inner.right()
    if stat_w:
        painter.save()
        painter.setFont(stat_font)
        painter.setPen(text_colour)
        painter.drawText(
            QRectF(right - stat_w, line_top, stat_w, metrics.height()),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            accent.stat_text,
        )
        painter.restore()
        right -= stat_w + GLYPH_GAP
    if pill_w:
        pill = QRectF(right - pill_w, line_top + (metrics.height() - PILL_H) / 2, pill_w, PILL_H)
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
    if accent.branch:
        glyph_top = line_top + (metrics.height() - GLYPH_SIZE) / 2
        paint_branch_glyph(
            painter, QRectF(right - GLYPH_SIZE, glyph_top, GLYPH_SIZE, GLYPH_SIZE), faded
        )


def paint_badge(painter: QPainter, palette: QPalette, text: str) -> None:
    """A pill on the top edge, right end: the milestone label, sitting on the border.

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


def paint_icon_medallions(painter: QPainter, palette: QPalette, icons: tuple[str, ...]) -> None:
    """One small circle per aspect kind, on the top edge's left end — the badge's opposite.

    A glance at a node's top-left corner answers "what is this step": a tag means a
    milestone, a spark means machine guidance, nothing means a plain step.
    """
    ink = QColor(palette.text().color())
    faded = QColor(ink)
    faded.setAlpha(SECONDARY_ALPHA)
    x = BADGE_INSET
    for kind in icons:
        centre = QPointF(x + ICON_D / 2, 0.0)
        border = QColor(BADGE_BORDER) if kind == "tag" else faded
        fill = QColor(BADGE_TINT) if kind == "tag" else QColor(palette.window().color())
        painter.setBrush(fill)
        painter.setPen(QPen(border, 1.0))
        painter.drawEllipse(centre, ICON_D / 2, ICON_D / 2)
        glyph = QRectF(centre.x() - 4.0, centre.y() - 4.0, 8.0, 8.0)
        if kind == "tag":
            paint_tag_glyph(painter, glyph, ink)
        elif kind == "spark":
            paint_spark_glyph(painter, glyph, faded)
        elif kind == "layers":
            paint_layers_glyph(painter, glyph, faded)
        elif kind == "beaker":
            paint_beaker_glyph(painter, glyph, faded)
        elif kind == "shield":
            paint_shield_glyph(painter, glyph, faded)
        x += ICON_D + ICON_GAP


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
