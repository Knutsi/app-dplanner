"""Card metrics, and the rule that splits a card — or parts two groups of controls.

A card is a ``#ToolCard`` well on a ``#CardLane`` (a check's Covers tab); the box is the
stylesheet's, and what is here is the spacing it was designed at and the 1 px rule.
Metrics follow the Cards section of ``DESIGN.md``.
"""

from PySide6.QtWidgets import QFrame, QWidget

CARD_PADDING = 12  # Inside the card, all four sides.
STACK_SPACING = 12  # Between cards.


def card_rule(parent: QWidget | None = None, *, vertical: bool = False) -> QFrame:
    """A 1 px rule splitting a card's body into sections; inset by the card padding.
    ``vertical`` stands it up, to part two groups of controls in one row."""
    rule = QFrame(parent)
    rule.setObjectName("ToolCardRule")
    rule.setFrameShape(QFrame.Shape.NoFrame)
    if vertical:
        rule.setFixedWidth(1)
    else:
        rule.setFixedHeight(1)
    return rule
