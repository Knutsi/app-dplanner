"""The semantic tones a step wears: low-alpha constant colours that read on every theme.

One home for the colours the canvas paints a node's body in, so the aspect bar's kind
buttons can wear the same ones — a checked *Feature* button and a feature node are one
identity, and a table of two copies is how they would drift. DESIGN.md's exception #2: a
semantic tint is a constant ``QColor`` with a low alpha, never an opaque theme colour.

"highlight" is the badge's purple family — a milestone node, its badge and the order
table's milestone row are one identity; "good" is the green family — finished work recedes
into a calm green column the eye can skip; "feature" is teal — the other collector, one
rank down; "info" is the agent-run chip's blue, which the bar lends to the Agent kind.

Teal because of where the hues already are: it sits 76° from the milestone's violet, so
the two collectors never read as one, and 42° from the done green — which additionally
*mutes* its node, so the pair is told apart by weight as well as by hue, and a feature
still wears its layer medallion. Fill low-alpha, border full-strength.
"""

from PySide6.QtGui import QColor

BADGE_TINT = QColor(150, 130, 220, 70)
BADGE_BORDER = QColor(150, 130, 220, 160)
HIGHLIGHT_FILL = QColor(150, 130, 220, 36)
GOOD_FILL = QColor(120, 200, 140, 36)
GOOD_BORDER = QColor(120, 200, 140, 160)
FEATURE_FILL = QColor(80, 180, 175, 36)
FEATURE_BORDER = QColor(80, 180, 175, 160)
CHIP_INFO_TINT = QColor(90, 170, 200, 70)
CHIP_INFO_BORDER = QColor(90, 170, 200, 160)
CHIP_ATTENTION_TINT = QColor(220, 170, 90, 70)
CHIP_ATTENTION_BORDER = QColor(220, 170, 90, 160)

# name → (fill, border). A node body takes the fill; a checked button takes the border's
# hue at the chip's alpha, which is what a small control needs to read as coloured at all.
BODY_TONES: dict[str, tuple[QColor, QColor]] = {
    "highlight": (HIGHLIGHT_FILL, BADGE_BORDER),
    "good": (GOOD_FILL, GOOD_BORDER),
    "feature": (FEATURE_FILL, FEATURE_BORDER),
    "info": (CHIP_INFO_TINT, CHIP_INFO_BORDER),
}

BUTTON_FILL_ALPHA = 70


def button_tone(name: str) -> tuple[QColor, QColor] | None:
    """``(fill, border)`` for a checked control wearing this tone, or None for no such tone."""
    tone = BODY_TONES.get(name)
    if tone is None:
        return None
    fill = QColor(tone[1])
    fill.setAlpha(BUTTON_FILL_ALPHA)
    return fill, tone[1]
