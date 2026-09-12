"""The primitives every painted card is made of: its radius and paddings, the shadow it
rests on, the opaque fill a tint lands as, and the title face and wrap.

Two surfaces paint cards — the graph canvas (``modules/project_editor/renderers.py``) and
the coverage view — and modules never import each other, so what they share lives here
beside the tones and glyphs they also share. Everything is a pure function over a
``QPainter``, a rect and a colour: nothing here knows what a card *is*.
"""

from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QFontMetricsF, QPainter

RADIUS = 8.0  # = theme.tokens.RADIUS_MD, matched by eye rather than import: this is a painter.
# DESIGN.md's row of rich content: 12 across, 8 down. The vertical 8 is what lets two lines of
# the larger title sit over the bottom line inside the default height.
PADDING = 12.0
PAD_Y = 8.0
LINE_GAP = 4.0

# The title is the card's reason to exist, so it is set larger than the chrome around it —
# this many points over the application font — and wraps onto as many lines as the card
# has room for above its detail line; only the last one elides.
TITLE_POINTS = 2.0
# A secondary line is one point down from the text it is about — the same step the empty
# state takes, so there are two sizes below the title and not three.
DETAIL_POINTS = 1.0

# A selected card is *lifted*: it draws this far up from where it sits, over a deeper shadow
# left behind at the seat. Two pixels is the whole effect — enough that the eye reads a card
# picked up off the table, small enough that nothing appears to have moved. The edges still
# meet the seat, which is what keeps a surface from twitching as the selection travels.
LIFT = 2.0

# Secondary text as opacity rather than a theme colour: a painter has only the palette, and
# an alpha-derived secondary is theme-independent by construction (DESIGN.md exception #1).
FILL_ALPHA = 28

# What a surface that lights part of itself fades the rest to. Two of them do — the coverage
# trace lights a path through its lanes, the canvas spotlights what the selection is linked
# to — and both fade by *item opacity* rather than by a colour, so a card recedes whole: fill,
# border, title, glyphs and the shadow under it together, on any theme. Low enough that the
# lit part is unmistakable, high enough that the rest is still a graph and not a rumour.
DIM_OPACITY = 0.35

# Selection: a thicker outline in the accent, and half again the fill the card already had.
# A *gain* rather than a colour of its own is what lets a picked milestone stay purple and a
# picked done step stay green — the accent is already saying "this one" at the border.
SELECTED_BORDER_W = 2.5
SELECTED_FILL_GAIN = 1.6


@dataclass(frozen=True)
class Shadow:
    """A soft shadow: concentric rounded rects, each fainter and wider than the last, since
    a QPainter has no blur. Constant black at low alpha, like every other semantic tint
    here (DESIGN.md exception #2) — it darkens the ground under the card on any theme.

    ``alpha`` is the innermost ring's; the outer ones fade from it, and the rings
    composite, so what lands at the card's edge is roughly twice this."""

    drop: float  # How far below the seat the shadow falls.
    spread: float  # How far the softest ring reaches past the body.
    alpha: int


SHADOW_LAYERS = 4
# Every card rests on a faint shadow, so a surface reads as cards on a table rather than
# outlines on a plane; a selected card's is deeper and wider, which with the lift is what
# says "this one is up". Both kept faint on purpose: the border and the fill are what
# identify a card, and the shadow only has to seat it. At 30 the lifted one read as a hole
# punched in a light theme's paper.
RESTING_SHADOW = Shadow(drop=2.0, spread=3.0, alpha=6)
LIFTED_SHADOW = Shadow(drop=4.0, spread=5.0, alpha=12)


def paint_shadow(painter: QPainter, body: QRectF, shadow: Shadow) -> None:
    """The soft dark ground a card casts: rings of black, each wider and fainter.

    Widest first so the tight, darkest ring lands on top; at the sizes a card is drawn,
    four rings at these alphas are indistinguishable from one blurred one. The body's fill
    is opaque (see :func:`over`), so nothing painted here shows through the card.
    """
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    for layer in range(SHADOW_LAYERS, 0, -1):
        spread = shadow.spread * layer / SHADOW_LAYERS
        painter.setBrush(QColor(0, 0, 0, round(shadow.alpha / layer)))
        painter.drawRoundedRect(
            body.adjusted(-spread, -spread + shadow.drop, spread, spread + shadow.drop),
            RADIUS + spread,
            RADIUS + spread,
        )
    painter.restore()


def over(ground: QColor, ink: QColor) -> QColor:
    """``ink`` composited over ``ground`` — the opaque colour a translucent tint lands as.

    A card's fill is *designed* as ink over the ground (``FILL_ALPHA``, a kind's tone), but
    it is painted opaque: the ground under a card is a grid, a region's wash or a
    neighbour's shadow, and a card that lets any of those show through reads as a stain
    rather than a card. Blending here gives exactly the colour the tint would have had
    over bare ground, on any theme, with nothing underneath able to change it.
    """
    share = ink.alphaF()
    return QColor(
        round(ground.red() * (1 - share) + ink.red() * share),
        round(ground.green() * (1 - share) + ink.green() * share),
        round(ground.blue() * (1 - share) + ink.blue() * share),
    )


def detail_font(base: QFont) -> QFont:
    """A secondary line's face — a row's second line, an empty state's one line — a point
    smaller than the base: the step down that says *about* rather than *is*."""
    font = QFont(base)
    if font.pointSizeF() > 0:
        font.setPointSizeF(max(1.0, font.pointSizeF() - DETAIL_POINTS))
    else:
        font.setPixelSize(max(1, font.pixelSize() - round(DETAIL_POINTS * 4 / 3)))
    return font


def title_font(base: QFont) -> QFont:
    """The card's title face: the painter's font, :data:`TITLE_POINTS` larger."""
    font = QFont(base)
    if font.pointSizeF() > 0:
        font.setPointSizeF(font.pointSizeF() + TITLE_POINTS)
    else:  # A pixel-sized font has no point size to grow; a point is about 1.33 px.
        font.setPixelSize(font.pixelSize() + round(TITLE_POINTS * 4 / 3))
    return font


def title_lines(
    metrics: QFontMetrics | QFontMetricsF, title: str, width: float, max_lines: int = 2
) -> list[str]:
    """The title wrapped onto at most ``max_lines`` lines, the last one elided.

    Word-accumulation, so a name breaks where a person would break it; a single word too
    wide for a line is left to the elision. Pure, so it can be tested without a painter.
    """
    if metrics.horizontalAdvance(title) <= width:
        return [title]
    lines: list[str] = []
    line = ""
    words = title.split()
    for index, word in enumerate(words):
        attempt = f"{line} {word}".strip()
        if line and metrics.horizontalAdvance(attempt) > width:
            if len(lines) == max_lines - 1:
                rest = " ".join([line, *words[index:]])
                return [*lines, metrics.elidedText(rest, Qt.TextElideMode.ElideRight, int(width))]
            lines.append(line)
            line = word
        else:
            line = attempt
    return [*lines, metrics.elidedText(line, Qt.TextElideMode.ElideRight, int(width))]
