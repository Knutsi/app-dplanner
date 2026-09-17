"""Card chrome for panels that host independent features side by side.

A :class:`ToolCard` frames one module-owned feature — a caption (with an optional glyph)
over the feature's own widget — and a :class:`CardFlow` lays cards out in as many columns
as the width allows inside a vertical scroll area, so a panel keeps working at its
narrowest width and a wide page is not a column down its middle. The host decides what
goes in a card and when a card shows; the card never knows what it holds. Metrics follow
the Cards section of
``DESIGN.md``; the box itself is painted by the ``#ToolCard`` stylesheet rule.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
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
CARD_MIN_WIDTH = 360  # A panel's width: what every card was designed at.


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
        layout.addWidget(body, 1)  # Height a host gives the card goes to the feature.

    def set_glyph(self, icon: QIcon | None) -> None:
        """Colour-parameterised glyphs are repainted by the host on theme change."""
        if icon is None:
            self.glyph.hide()
            return
        self.glyph.setPixmap(icon.pixmap(ICON_SIZE, ICON_SIZE))
        self.glyph.show()


class CardFlow(QScrollArea):
    """Cards in as many equal columns as the width allows — one at a panel's width, three
    across a wide screen — scrolling vertically, never horizontally.

    The column count is read from this widget's own width, not the content's: a vertical
    scroll bar appearing takes a few pixels off the viewport, and a count taken from there
    could flip back and forth on the scroll bar it just caused. Cards keep their order,
    filling row by row. A card that ``grows`` takes the leftover height of the page — a
    prose editor wants it; a row holding one stretches, and the cards in it that do not
    grow stay at their own height, aligned to the top, so a list of three facts is never a
    tall empty box beside an editor.
    """

    def __init__(self, parent: QWidget | None = None, *, min_card_width: int = CARD_MIN_WIDTH):
        super().__init__(parent)
        self.setObjectName("CardFlow")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Tab goes straight to card controls.
        self._min_card_width = min_card_width
        # Our own list of what is in the grid: a layout is never read back (CLAUDE.md).
        self._cards: list[tuple[ToolCard, bool]] = []
        self._columns = 1

        content = QWidget()
        self._grid = QGridLayout(content)
        self._grid.setContentsMargins(STACK_MARGIN, STACK_MARGIN, STACK_MARGIN, STACK_MARGIN)
        self._grid.setHorizontalSpacing(STACK_SPACING)
        self._grid.setVerticalSpacing(STACK_SPACING)
        self.setWidget(content)
        # The hosting surface paints the background; a scroll area's viewport and widget
        # both default to filling with the palette's Base, which would hide it.
        self.viewport().setAutoFillBackground(False)
        content.setAutoFillBackground(False)

    def add_card(self, card: ToolCard, *, grows: bool = False) -> None:
        self._cards.append((card, grows))
        self._place()

    def columns(self) -> int:
        return self._columns

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        room = self.width() - 2 * STACK_MARGIN
        wanted = max(1, (room + STACK_SPACING) // (self._min_card_width + STACK_SPACING))
        if wanted != self._columns:
            self._columns = wanted
            self._place()

    def _place(self) -> None:
        """Lay every card out again for the current column count.

        ``takeAt`` in a loop that drops each wrapper is the sanctioned way to empty a layout;
        the cards themselves are ours and keep their parent.
        """
        while self._grid.takeAt(0) is not None:
            pass
        columns = self._columns
        rows = (len(self._cards) + columns - 1) // columns
        growing_rows = {
            index // columns for index, (_card, grows) in enumerate(self._cards) if grows
        }
        for index, (card, grows) in enumerate(self._cards):
            alignment = Qt.AlignmentFlag(0) if grows else Qt.AlignmentFlag.AlignTop
            self._grid.addWidget(card, index // columns, index % columns, alignment)
        # Equal columns. The leftover height goes to the rows that grow, or below the last
        # row when none does — never between rows. Stretches set for a wider layout are
        # taken back, or an empty column keeps its share.
        for column in range(max(columns, self._grid.columnCount())):
            self._grid.setColumnStretch(column, 1 if column < columns else 0)
        for row in range(max(rows + 1, self._grid.rowCount())):
            if growing_rows:
                self._grid.setRowStretch(row, 1 if row in growing_rows else 0)
            else:
                self._grid.setRowStretch(row, 1 if row == rows else 0)
