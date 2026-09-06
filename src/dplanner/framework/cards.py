"""Card chrome for panels that host independent features side by side.

A :class:`ToolCard` frames one module-owned feature — a caption (with an optional glyph)
over the feature's own widget — and a :class:`CardStack` lays cards out top to bottom
inside a vertical scroll area, so a panel keeps working at its narrowest width and on
short screens as features accumulate. The host decides what goes in a card and when a
card shows; the card never knows what it holds. Metrics follow the Cards section of
``DESIGN.md``; the box itself is painted by the ``#ToolCard`` stylesheet rule.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from dplanner.theme.icons import ICON_SIZE

CARD_PADDING = 12  # Inside the card, all four sides.
CARD_HEADER_GAP = 8  # Caption to body.
STACK_MARGIN = 16  # Panel metrics per DESIGN.md.
STACK_SPACING = 12  # Between cards.
SECTION_GAP = 12  # Between the sections of a split card (above and below its rule).


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


class ToolCard(QFrame):
    """One feature's card: glyph + caption header, then the feature's own widget."""

    def __init__(self, title: str, body: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # The box is the stylesheet's: QSS auto-enables styled backgrounds for QFrame
        # subclasses, so no frame shape and no WA_StyledBackground dance is needed here.
        self.setObjectName("ToolCard")
        self.setFrameShape(QFrame.Shape.NoFrame)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        layout.setSpacing(CARD_HEADER_GAP)

        header = QHBoxLayout()
        header.setSpacing(6)
        self.glyph = QLabel(self)
        self.glyph.setFixedSize(ICON_SIZE, ICON_SIZE)
        self.glyph.hide()  # Until a glyph is set; the caption then sits flush left.
        header.addWidget(self.glyph)
        self.title = QLabel(title, self)
        self.title.setObjectName("InspectorCaption")  # The one caption per block.
        header.addWidget(self.title)
        header.addStretch(1)
        layout.addLayout(header)

        self.body = body
        layout.addWidget(body)

    def set_glyph(self, icon: QIcon | None) -> None:
        """Colour-parameterised glyphs are repainted by the host on theme change."""
        if icon is None:
            self.glyph.hide()
            return
        self.glyph.setPixmap(icon.pixmap(ICON_SIZE, ICON_SIZE))
        self.glyph.show()


class CardStack(QScrollArea):
    """Cards top to bottom; scrolls vertically, never horizontally."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CardStack")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Tab goes straight to card controls.

        content = QWidget()
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(STACK_MARGIN, STACK_MARGIN, STACK_MARGIN, STACK_MARGIN)
        self._layout.setSpacing(STACK_SPACING)
        self._layout.addStretch(1)
        self.setWidget(content)
        # The hosting panel paints the background; a scroll area's viewport and widget
        # both default to filling with the palette's Base, which would hide it.
        self.viewport().setAutoFillBackground(False)
        content.setAutoFillBackground(False)

    def add_card(self, card: ToolCard) -> None:
        # The trailing stretch stays last because every insert lands before it.
        self._layout.insertWidget(self._layout.count() - 1, card)
