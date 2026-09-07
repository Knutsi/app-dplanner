"""How a step node looks: pure paint functions over a palette, a rect and the accent.

``StepNodeItem`` holds state and geometry; everything it draws is composed here from small
helpers that each take an explicit rect. A different look — a compact node, in-node editing
chrome — is a new composition of the same helpers, not a subclass: the seam is
:func:`paint_node`'s signature, and that is deliberately all there is.

The vocabulary is the canvas's own. :class:`NodeAccent` never names an aspect ("done",
"merged") — the composition root translates aspects into tones and texts, the same seam
``step_aspects`` uses for the subtitle. :class:`RenderHints` is the mode's voice: the mode
stack announces, the scene fans out, and no item ever reads which mode is current.

**The body is handed in, never assumed.** A card is whatever size the user made it, so
every helper measures from the ``body`` rect it is given and the only fixed numbers here
are paddings, radii and the reach of the decorations round the edge.
"""

from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
)

from dplanner.modules.project_editor.marks import Marks
from dplanner.theme.cards import (
    FILL_ALPHA,
    LIFT,
    LIFTED_SHADOW,
    LINE_GAP,
    PAD_Y,
    PADDING,
    RADIUS,
    RESTING_SHADOW,
    SECONDARY_ALPHA,
    SELECTED_BORDER_W,
    SELECTED_FILL_GAIN,
    over,
    paint_shadow,
    title_font,
    title_lines,
)
from dplanner.theme.icons import (
    paint_beaker_glyph,
    paint_layers_glyph,
    paint_shield_glyph,
    paint_spark_glyph,
    paint_tag_glyph,
)
from dplanner.theme.tones import (
    BADGE_BORDER,
    BADGE_TINT,
    BODY_TONES,
    CHIP_ATTENTION_BORDER,
    CHIP_ATTENTION_TINT,
    CHIP_INFO_BORDER,
    CHIP_INFO_TINT,
)

# The link handle: a dot on the node's right edge. Dragging from it means "then", so an
# edge always runs left to right and its direction cannot be read the wrong way round.
HANDLE_R = 5.0
# Connect mode's hovered handle grows a touch, so the one under the cursor is unmissable.
HANDLE_EMPHASIS = 1.5

# A marked socket: a disc a touch larger than the handle, in a hue the canvas already uses
# for something of the same feeling — the valid green for where the graph starts, the
# attention amber for where it ends — with a hairline of window colour so it reads on any
# body. An orphan wears a solid ring outside the body like the agent ring, since a node
# nothing touches is nearly always a mistake.
MARK_R = HANDLE_R + 1.0
START_MARK = QColor(120, 200, 140)
END_MARK = QColor(220, 170, 90)
# The orphan's ring is the refusal red at full strength and twice the agent ring's weight:
# it is the one mark that says *something is wrong here* rather than *this is where the
# graph ends*, and at the tint's alpha over a toned body it read as a shadow of the border
# rather than as a warning. It is on by default now, so it has to earn the glance it gets.
ORPHAN_RING = QColor(224, 82, 82)
ORPHAN_RING_W = 3.0

# Low-alpha semantic tints that read on every theme (DESIGN.md exception #2).
VALID_TINT = QColor(120, 200, 140, 180)
INVALID_TINT = QColor(220, 110, 110, 180)
BUSY_TINT = QColor(110, 160, 220, 180)
# A toned body colours the whole node, so its kind reads at any zoom. The tones live in
# ``theme/tones.py`` — the aspect bar's kind buttons wear the same ones, and a checked
# Feature button and a feature node are one identity.

# A muted node: the same colours, further faded. What "muted" means is the caller's business.
MUTED_TEXT_ALPHA = 110
MUTED_SECONDARY_ALPHA = 80
MUTED_FILL_ALPHA = 14
MUTED_BORDER_ALPHA = 50

# The spine: a strip down the node's left edge, clipped to the rounded body, carrying the
# step's key read bottom-to-top and shaded by status. The chrome font's height plus five
# or six pixels of air on either side of the key — at 18 it was two, and the number read
# as jammed against the strip's edges; a four-character key runs some 30 px along it,
# which the shortest card still has room for.
SPINE_W = 26.0
SPINE_FILL_ALPHA = 80  # A status tone's fill on the spine — a wash, not a swatch.
SPINE_QUIET_ALPHA = 14  # No status to show: the spine is a shade darker than the body.

BADGE_H = 14.0
BADGE_PAD = 6.0
BADGE_INSET = 10.0  # From the node's right edge, clear of the link handle's corner.
# Where the top-left medallions and the bottom-left chip start: past the spine, a gap on.
LEFT_INSET = SPINE_W + 4.0

# The chip on the bottom edge, left end — the badge's mirror, worn by a live agent run.
CHIP_H = 14.0

# The ring the same run wears: a dashed line marching round the body a few pixels out, in
# the chip's tone. Motion is what says "somebody is at work on this one right now" — a
# static outline would be one more border. The dash pattern is in pen widths (Qt's unit
# for it) and the phase advances by RING_STEP per scene tick; one full dash-and-gap per
# ~14 ticks reads as a steady crawl rather than a flicker.
RING_GAP = 3.0
RING_W = 1.5
RING_DASH = (4.0, 3.0)
RING_STEP = 0.5

# The icon medallions on the top edge, left end: one small circle per aspect kind a step
# carries, bound by the same boundingRect inequality the badge is. Twice grown by a fifth from
# the 14 they were first drawn at, and rounded to the pixel at the end of it.
ICON_D = 20.0
ICON_GAP = 4.0
# The glyph inside one, as the share of it these shapes were drawn at (8 in 14). Derived, so
# sizing a medallion sizes its glyph — every shape in theme/icons.py scales off the rect it is
# handed, and it was a literal 8.0 here that kept them from following.
ICON_GLYPH = ICON_D * 4 / 7

# The pill on the second line: a small status label (a PR, say) beside the subtitle.
PILL_H = 14.0
PILL_RADIUS = PILL_H / 2
PILL_PAD_X = 6.0
PILL_MARGIN = 6.0
PILL_FILL_ALPHA = 46
GLYPH_SIZE = 9.0
GLYPH_GAP = 5.0

# How far paint reaches outside the body, in every direction: the link handle (grown by
# connect mode's emphasis), a badge's or a medallion's rise, a chip's fall, the lift and the
# shadow. It is what ``StepNodeItem.boundingRect`` is made of, so a new decoration is
# measured here or it is clipped there.
PAINT_MARGIN = max(
    HANDLE_R + 4.0,
    MARK_R + 1.0,
    BADGE_H / 2 + 1.0 + LIFT,
    ICON_D / 2 + 1.0 + LIFT,
    CHIP_H / 2 + 1.0,
    RING_GAP + max(RING_W, ORPHAN_RING_W) + 1.0 + LIFT,
    LIFTED_SHADOW.drop + LIFTED_SHADOW.spread + 1.0,
)

SPINE_TONES = {"good": VALID_TINT, "busy": BUSY_TINT, "bad": INVALID_TINT}
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
    (a milestone label); a ``chip`` sits on the bottom edge (a live agent run — and the
    same run wears the marching ring, so one field says both); a ``pill``
    sits on the second line with a tone that is "good" or "bad", never "merged";
    ``branch`` and ``spark`` ask for the small glyphs beside it; ``key_text`` is what the
    spine down the left edge reads, and ``spine_tone`` how it is shaded.
    """

    muted: bool = False
    badge: str = ""
    pill_text: str = ""  # "" → no pill.
    pill_tone: str = ""  # "" neutral | "good" | "bad".
    branch: bool = False  # Paint the branch glyph.
    key_text: str = ""  # The step's key ("F7"), read up the spine; "" → a bare spine.
    spine_tone: str = ""  # "" quiet | "good" | "busy" | "bad": the status, as a shade.
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
    """The transient half of a node's look: selection, hover, link aim, mode hints, and
    what the marks have to say about its sockets."""

    selected: bool = False
    hovered: bool = False
    link_state: str = ""  # "" | "valid" | "invalid"
    hints: RenderHints = field(default_factory=RenderHints)
    ring_phase: float = 0.0  # Where the live ring's dashes are; the scene advances it.
    ports: tuple[bool, bool] = (False, False)  # (something arrives, something leaves).
    marks: Marks = field(default_factory=Marks)


def paint_node(
    painter: QPainter,
    palette: QPalette,
    body: QRectF,
    title: str,
    accent: NodeAccent,
    state: NodeState,
) -> None:
    """The default node: the spine with its key, the body, the title over a bottom line of
    stat, pill and glyph, the edge decorations, and the link handle.

    Every card rests on a shadow; a selected one is drawn :data:`LIFT` above its seat over
    a deeper shadow, so the whole composition — badge, chip, medallions, handle — travels
    together. The shadow is painted first and *unlifted*: it is the ground, not part of
    the card.
    """
    text_colour = QColor(palette.text().color())
    if accent.muted:
        text_colour.setAlpha(MUTED_TEXT_ALPHA)
    faded = QColor(palette.text().color())
    faded.setAlpha(MUTED_SECONDARY_ALPHA if accent.muted else SECONDARY_ALPHA)

    paint_shadow(painter, body, LIFTED_SHADOW if state.selected else RESTING_SHADOW)
    painter.save()
    if state.selected:
        painter.translate(0.0, -LIFT)

    paint_body(painter, palette, body, accent, state)
    paint_spine(painter, palette, body, accent, text_colour)
    paint_marks(painter, palette, body, state)
    if accent.chip_text:
        paint_ring(painter, body, accent.chip_tone, state.ring_phase)
    inner = body.adjusted(SPINE_W + PAD_Y, PAD_Y, -PADDING, -PAD_Y)
    detail = bool(accent.stat_text or accent.pill_text or accent.branch)
    reserved = painter.fontMetrics().height() + LINE_GAP if detail else 0.0
    paint_title(painter, inner, title, text_colour, accent.muted, reserved)
    if detail:
        paint_detail_line(painter, inner, accent, text_colour, faded)
    paint_icon_medallions(painter, palette, accent.icons)
    if accent.badge:
        paint_badge(painter, palette, body, accent.badge, medallion_end(accent.icons))
    if accent.chip_text:
        paint_chip(painter, palette, body, accent.chip_text, accent.chip_tone)
    paint_handle(painter, palette, body, state)
    painter.restore()


def paint_body(
    painter: QPainter, palette: QPalette, body: QRectF, accent: NodeAccent, state: NodeState
) -> None:
    """The rounded rect: fill, and the border (selection and link aim win).

    A body tone tints the whole node and strengthens its border — this node is a
    different kind of thing, legible at any zoom — but selection and a link drag's
    verdict still outrank it. Selection *deepens* whatever fill the node had rather than
    painting one of its own, so a picked milestone is still purple and a picked done step
    still green — and still recognisably fainter than the work around it.
    """
    muted = accent.muted
    toned = BODY_TONES.get(accent.body_tone)
    if toned is not None:
        tint = QColor(toned[0])
    else:
        tint = QColor(palette.text().color())
        tint.setAlpha(MUTED_FILL_ALPHA if muted else FILL_ALPHA)
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
        tint.setAlpha(min(255, round(tint.alpha() * SELECTED_FILL_GAIN)))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(over(palette.window().color(), tint))
    painter.drawRoundedRect(body, RADIUS, RADIUS)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(border, width))
    painter.drawRoundedRect(body, RADIUS, RADIUS)


def paint_marks(painter: QPainter, palette: QPalette, body: QRectF, state: NodeState) -> None:
    """The marks that are on, where this node has earned them.

    Painted before the handle, so a hovered handle still wins the right socket; in connect
    mode the faded handle sits over the end disc, which is accepted — the amber still shows
    round it, and connect mode is exactly when you are about to give the node an end.
    """
    incoming, outgoing = state.ports
    marks = state.marks
    if marks.orphans and not (incoming or outgoing):
        painter.setPen(QPen(ORPHAN_RING, ORPHAN_RING_W))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        ring = body.adjusted(-RING_GAP, -RING_GAP, RING_GAP, RING_GAP)
        painter.drawRoundedRect(ring, RADIUS + RING_GAP, RADIUS + RING_GAP)
    painter.setPen(QPen(QColor(palette.window().color()), 1.0))
    if marks.starts and not incoming:
        painter.setBrush(START_MARK)
        painter.drawEllipse(QPointF(body.left(), body.center().y()), MARK_R, MARK_R)
    if marks.ends and not outgoing:
        painter.setBrush(END_MARK)
        painter.drawEllipse(QPointF(body.right(), body.center().y()), MARK_R, MARK_R)


def spine_rect(body: QRectF) -> QRectF:
    return QRectF(body.left(), body.top(), SPINE_W, body.height())


def spine_fill(palette: QPalette, tone: str) -> QColor:
    """The spine's wash: the status tone at a wash's alpha, or a quiet shade of ink."""
    toned = SPINE_TONES.get(tone)
    fill = QColor(toned if toned is not None else palette.text().color())
    fill.setAlpha(SPINE_FILL_ALPHA if toned is not None else SPINE_QUIET_ALPHA)
    return fill


def paint_spine(
    painter: QPainter, palette: QPalette, body: QRectF, accent: NodeAccent, ink: QColor
) -> None:
    """The strip down the left edge: the status as a shade, the key read bottom-to-top.

    Clipped to the rounded body so the strip's outer corners follow the card's, painted
    after the body so the wash sits on the fill and under nothing. The key is set in the
    chrome font, bold — it is the one thing on the card meant to be found from across
    the graph — and rotated a quarter turn anticlockwise, the way a spine on a shelf
    reads.
    """
    strip = spine_rect(body)
    clip = QPainterPath()
    clip.addRoundedRect(body, RADIUS, RADIUS)
    painter.save()
    painter.setClipPath(clip)
    painter.fillRect(strip, spine_fill(palette, accent.spine_tone))
    if accent.key_text:
        font = QFont(painter.font())
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(ink)
        metrics = QFontMetricsF(font)
        length = metrics.horizontalAdvance(accent.key_text)
        painter.translate(strip.center())
        painter.rotate(-90.0)
        painter.drawText(
            QRectF(-length / 2, -metrics.height() / 2, length, metrics.height()),
            int(Qt.AlignmentFlag.AlignCenter),
            accent.key_text,
        )
    painter.restore()


def paint_title(
    painter: QPainter,
    inner: QRectF,
    title: str,
    text_colour: QColor,
    muted: bool,
    reserved: float,
) -> None:
    """The name, in the title face, on as many lines as fit above the ``reserved`` height
    the detail line keeps for itself — so a card dragged taller shows more of a long name,
    and most names read in full at the default size."""
    base = painter.font()
    painter.setFont(title_font(base))
    metrics = painter.fontMetrics()
    max_lines = max(1, int((inner.height() - reserved) // metrics.height()))
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
    for row, line in enumerate(title_lines(metrics, title, width, max_lines)):
        painter.drawText(
            QRectF(title_left, inner.top() + row * metrics.height(), width, metrics.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            line,
        )
    painter.setFont(base)


def paint_detail_line(
    painter: QPainter,
    inner: QRectF,
    accent: NodeAccent,
    text_colour: QColor,
    faded: QColor,
) -> None:
    """The bottom line, right-aligned: the stat, then the pill, then the branch glyph.

    Anchored to the node's bottom, so a short title just leaves air above it. The stat —
    the one number the step answers with — is the rightmost and the only full-ink text on
    the line; nothing on it is a sentence, since every aspect the card wears is a
    medallion, a badge, a bar or a pill already.
    """
    metrics = painter.fontMetrics()
    line_top = inner.bottom() - metrics.height()
    right = inner.right()
    if accent.stat_text:
        stat_font = QFont(painter.font())
        stat_font.setBold(accent.stat_strong)
        stat_w = QFontMetricsF(stat_font).horizontalAdvance(accent.stat_text)
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
    pill_font = QFont(painter.font())
    pill_font.setPointSizeF(max(6.0, pill_font.pointSizeF() - 1))
    pill_w = (
        QFontMetricsF(pill_font).horizontalAdvance(accent.pill_text) + 2 * PILL_PAD_X
        if accent.pill_text
        else 0.0
    )
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


def paint_badge(painter: QPainter, palette: QPalette, body: QRectF, text: str, room: float) -> None:
    """A pill on the top edge, right end: the milestone label, sitting on the border.

    It rises half its height above the node, which is why it must stay inside the item's
    ``PAINT_MARGIN`` — and the chip on the bottom edge owes the same inequality.

    ``room`` is where the medallion row on the other end of the edge leaves off. The label
    is elided to whichever is less, what is left of the edge or the fraction of the node a
    badge may claim: a step wearing every aspect and a long milestone name has to give way
    somewhere, and it is the name that can be read from the panel. A card too narrow to
    give the label any room at all wears no badge rather than an empty pill.
    """
    budget = int(min(body.width() * 0.6, body.width() - BADGE_INSET - room))
    if budget <= 0:
        return
    font = painter.font()
    small = painter.font()
    small.setPointSizeF(max(6.0, font.pointSizeF() - 2.0))
    painter.setFont(small)
    metrics = painter.fontMetrics()
    shown = metrics.elidedText(text, Qt.TextElideMode.ElideRight, budget)
    width = metrics.horizontalAdvance(shown) + 2 * BADGE_PAD
    pill = QRectF(body.right() - BADGE_INSET - width, -BADGE_H / 2, width, BADGE_H)
    painter.setBrush(BADGE_TINT)
    painter.setPen(QPen(BADGE_BORDER, 1.0))
    painter.drawRoundedRect(pill, BADGE_H / 2, BADGE_H / 2)
    painter.setPen(QColor(palette.text().color()))
    painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), shown)
    painter.setFont(font)


def paint_ring(painter: QPainter, body: QRectF, tone: str, phase: float) -> None:
    """The dashed ring round a node with a live agent run, its dashes at ``phase``.

    Drawn outside the body so it reads as something around the card rather than a second
    border, and never filled: what is inside is the node, unchanged.
    """
    _, border = CHIP_TONES.get(tone, CHIP_TONES["info"])
    pen = QPen(border, RING_W)
    pen.setDashPattern(list(RING_DASH))
    pen.setDashOffset(-phase)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    ring = body.adjusted(-RING_GAP, -RING_GAP, RING_GAP, RING_GAP)
    painter.drawRoundedRect(ring, RADIUS + RING_GAP, RADIUS + RING_GAP)


def paint_chip(painter: QPainter, palette: QPalette, body: QRectF, text: str, tone: str) -> None:
    """A pill on the bottom edge, left end: the badge's mirror, worn by a live agent run."""
    font = painter.font()
    small = painter.font()
    small.setPointSizeF(max(6.0, font.pointSizeF() - 2.0))
    painter.setFont(small)
    metrics = painter.fontMetrics()
    shown = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(body.width() * 0.5))
    width = metrics.horizontalAdvance(shown) + 2 * BADGE_PAD
    pill = QRectF(LEFT_INSET, body.bottom() - CHIP_H / 2, width, CHIP_H)
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


def medallion_end(icons: tuple[str, ...]) -> float:
    """Where the medallion row leaves off — the first x another top-edge decoration may use."""
    return LEFT_INSET + sum(ICON_D + ICON_GAP for _ in icons)


def paint_icon_medallions(painter: QPainter, palette: QPalette, icons: tuple[str, ...]) -> None:
    """One small circle per aspect kind, on the top edge's left end — the badge's opposite.

    A glance at a node's top-left corner answers "what is this step": a tag means a
    milestone, a spark means machine guidance, nothing means a plain step. The row starts
    past the spine, so the key under it stays clear.
    """
    ink = QColor(palette.text().color())
    faded = QColor(ink)
    faded.setAlpha(SECONDARY_ALPHA)
    x = LEFT_INSET
    for kind in icons:
        centre = QPointF(x + ICON_D / 2, 0.0)
        border = QColor(BADGE_BORDER) if kind == "tag" else faded
        fill = QColor(BADGE_TINT) if kind == "tag" else QColor(palette.window().color())
        painter.setBrush(fill)
        painter.setPen(QPen(border, 1.0))
        painter.drawEllipse(centre, ICON_D / 2, ICON_D / 2)
        glyph = QRectF(
            centre.x() - ICON_GLYPH / 2, centre.y() - ICON_GLYPH / 2, ICON_GLYPH, ICON_GLYPH
        )
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


def paint_handle(painter: QPainter, palette: QPalette, body: QRectF, state: NodeState) -> None:
    """The link dot on the right edge — what the hints say the mode wants of it.

    "hidden" paints none, whatever the cursor does. "hover" (idle) paints the hovered
    node's, full. "always" (connect) fades one onto every node and grows the hovered one:
    every handle is a target, and the one under the cursor is unmissable.
    """
    hints = state.hints
    if hints.handles == "hidden":
        return
    centre = QPointF(body.right(), body.center().y())
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
