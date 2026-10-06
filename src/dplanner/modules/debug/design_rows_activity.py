"""Debug ▸ Design Examples ▸ Rows: what a picked row wears, and the block it replaced.

A roster's picked row is one ground across the whole row — the indent, the disclosure
chevron, the glyph and the words — with the accent on its left edge where the primitive
draws one. A list and a tree are shown picked, and under them the defect this page exists
for: Qt draws its focus frame round an item's **text** sub-rect, which begins where the
*style* would have put the text, not where these delegates do — past a glyph slot of their
own — so a frame left on starts part-way across the glyph and reads as a cell picked
inside the row rather than a row picked in the list. It showed in every list on
``TwoLineDelegate`` at once (the Specs tree, Problems, Open Project, the command palette),
which is why the answer is in the delegate and not in any of them.

``framework/list_rows.py`` and ``framework/table.py`` strip the frame; this page is what
that looks like, and what it looked like before. A table's picked row wears the same mark
and is on the Table page already, so it is not repeated here. Nothing reads the model.
"""

from PySide6.QtCore import QModelIndex, QPersistentModelIndex
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QListWidgetItem,
    QStyle,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.activity import ActivityBase
from dplanner.framework.context import SCOPE_ACTIVITY, ContextNode, ContextService, activity_uri
from dplanner.framework.list_rows import (
    DETAIL_ROLE,
    RichList,
    TwoLineDelegate,
    rich_row_height,
)
from dplanner.framework.widgets import caption, ink_of, note
from dplanner.theme.icons import folder_icon, spec_icon
from dplanner.theme.tokens import CAPTION_GAP, PANEL_MARGIN, SECTION_GAP

DESIGN_ROWS_KIND = "design_rows"

TREE_INDENT = 16  # The Specs tab's, so the tree here is laid out as the real one is.

# One roster's worth of sample rows, shown by each primitive in turn: three renderings of
# the same list, so what differs between them is the mark and not the content.
SAMPLE_ROWS: tuple[tuple[str, str], ...] = (
    ("Authentication", "markdown · imported today"),
    ("Product specs", "Folder · 3 documents"),
    ("Glossary", "markdown · fetched today"),
    ("Rollout", "markdown · fetched today"),
)
PICKED = 1  # *Product specs*: the row with children, where the two rects differ most.


class _FocusFramedRow(TwoLineDelegate):
    """The two-line row with Qt's focus frame put back on — the defect, kept to be seen.

    Deliberately wrong, and the only place in the application that is. An agent sent at a
    report of "a weird block that crosses the icon" has something to compare against
    without having to reproduce it.
    """

    def __init__(self, view: QAbstractItemView) -> None:
        super().__init__(view)
        self._view = view

    def initStyleOption(  # noqa: N802 - Qt override
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        super().initStyleOption(option, index)
        if index == self._view.currentIndex():
            option.state |= QStyle.StateFlag.State_HasFocus


class DesignExampleRows(ActivityBase):
    """The tab: a picked row in each roster primitive, and the block that is not one."""

    def __init__(self, context: ContextService) -> None:
        self._context = context
        self.uri = activity_uri(DESIGN_ROWS_KIND)
        self.title = "Design Example Rows"

        self.widget = QWidget()
        column = QVBoxLayout(self.widget)
        column.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        column.setSpacing(SECTION_GAP)

        ink = ink_of(self.widget)
        self.list = self._list(ink)
        self._block(
            column,
            "A list of rich items",
            self.list,
            "The picked row gains the quiet overlay ground and wears the 2 px accent "
            "inside its left edge. The ground is the row's whole width, so the glyph sits "
            "inside it rather than astride its border.",
        )

        self.tree = self._tree(ink, TwoLineDelegate)
        self._block(
            column,
            "…and a tree of them",
            self.tree,
            "A nested row is picked the same way, and the ground covers the indent and the "
            "disclosure chevron too: what is picked is the row, and the row starts at the "
            "list's edge however deep it sits. A table's row wears the same mark — the "
            "Table example is where that one is.",
        )

        self.defect = self._tree(ink, _FocusFramedRow)
        self._block(
            column,
            "The block this replaced — not a thing to build",
            self.defect,
            "Qt's focus frame, drawn round the item's text sub-rect. That rect starts where "
            "the style would have put the text, not where the delegate draws it past its "
            "own glyph slot, so the frame begins part-way across the glyph and stops at the "
            "row's indent: the eye reads a cell picked inside the row. Stripping "
            "State_HasFocus in the delegate is what removes it, for every list at once.",
        )
        column.addStretch(1)

    def on_activated(self) -> None:
        self._context.set_scope(SCOPE_ACTIVITY, (ContextNode(self.uri),))

    def _block(self, column: QVBoxLayout, title: str, roster: QWidget, remark: str) -> None:
        column.addWidget(caption(title, self.widget))
        row = QHBoxLayout()
        column.addLayout(row)  # Before it is filled: a parentless layout leaks its items.
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(CAPTION_GAP)
        row.addWidget(roster, 1)
        column.addWidget(note(remark, self.widget))

    def _glyph(self, place: int, ink: QColor) -> QIcon:
        return (folder_icon if place == PICKED else spec_icon)(ink)

    @staticmethod
    def _fit_rows(view: QAbstractItemView) -> None:
        """Exactly its rows tall, so no roster here scrolls a row half out of sight — from
        the font through the formula the rows themselves take their height from, never a
        pixel (DESIGN.md's *Row height comes from the font*)."""
        rows = len(SAMPLE_ROWS) * rich_row_height(view.font())
        view.setFixedHeight(rows + 2 * view.frameWidth())

    def _list(self, ink: QColor) -> RichList:
        made = RichList(self.widget)
        for place, (title, detail) in enumerate(SAMPLE_ROWS):
            item = QListWidgetItem(title)
            item.setData(DETAIL_ROLE, detail)
            item.setIcon(self._glyph(place, ink))
            made.addItem(item)
        made.setCurrentRow(PICKED)
        self._fit_rows(made)
        return made

    def _tree(self, ink: QColor, delegate: type[TwoLineDelegate]) -> QTreeWidget:
        """The Specs tab's tree, over the same rows: the folder holds the two under it."""
        made = QTreeWidget(self.widget)
        made.setObjectName("SpecTree")
        made.setHeaderHidden(True)
        made.setUniformRowHeights(False)
        made.setIndentation(TREE_INDENT)
        made.setItemDelegate(delegate(made))
        items = []
        for place, (title, detail) in enumerate(SAMPLE_ROWS):
            item = QTreeWidgetItem([title])
            item.setData(0, DETAIL_ROLE, detail)
            item.setIcon(0, self._glyph(place, ink))
            items.append(item)
        folder = items[PICKED]
        for nested in items[PICKED + 1 :]:
            folder.addChild(nested)
        made.addTopLevelItem(items[0])
        made.addTopLevelItem(folder)
        folder.setExpanded(True)
        made.setCurrentItem(folder)
        self._fit_rows(made)
        return made


__all__ = ["DESIGN_ROWS_KIND", "DesignExampleRows"]
