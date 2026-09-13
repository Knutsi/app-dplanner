"""The Settings dialog: a tree of module-contributed sections beside their pages.

Non-modal, like the task browser — settings changes shouldn't block the rest of the app.
Built once and reused (``.show()``/``.raise_()``), so leaving it open across an edit
doesn't lose the user's place in the tree.

On the frame (DESIGN.md's *Dialogs*): a framed dialog with Close and nothing else, since
every edit on every page is live; the tree and the page parted by a splitter, whose seam
is the one every two surfaces meet at; each page in a scroll area of its own, inset from
the seam by the dialog — a page owns no outer margin (``settings_registry.settings_page``).
A folder in the tree is a heading, never a page: a click on it lands on its first page,
and the arrow keys step over it, so Up and Down move page to page.
"""

from collections.abc import Callable

from PySide6.QtCore import QEvent, QModelIndex, QPersistentModelIndex, QSize, Qt
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.dialog import DialogFrame
from dplanner.framework.settings_registry import SettingsSection, SettingsSectionRegistry
from dplanner.framework.table import row_height
from dplanner.framework.widgets import ink_of
from dplanner.theme.tokens import SECONDARY_ALPHA, SECTION_GAP

_SECTION_ROLE = Qt.ItemDataRole.UserRole
# Room for the busiest page — profiles beside their editor — before it has to scroll; a
# framed dialog, so the screen's share still caps it.
DIALOG_SIZE = (880, 620)
TREE_MIN_W, TREE_MAX_W = 220, 320  # Room for the longest leaf; never half the dialog.


class _RowHeight(QStyledItemDelegate):
    """A plain table row's height — the line and its padding, from the font, never a
    pixel (DESIGN.md's *Tables*): the stylesheet's padding is not in an item's size hint."""

    def sizeHint(  # noqa: N802 - Qt override
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        return QSize(super().sizeHint(option, index).width(), row_height(option.font, rich=False))


class _SectionTree(QTreeWidget):
    """A tree whose folders are headings: the keyboard steps over them."""

    def moveCursor(  # noqa: N802 - Qt override
        self,
        action: QAbstractItemView.CursorAction,
        modifiers: Qt.KeyboardModifier,
    ) -> QModelIndex:
        index = super().moveCursor(action, modifiers)
        item = self.itemFromIndex(index)
        if item is not None and item.data(0, _SECTION_ROLE) is None:
            upwards = action in (
                QAbstractItemView.CursorAction.MoveUp,
                QAbstractItemView.CursorAction.MovePrevious,
            )
            beyond = self.itemAbove(item) if upwards else self.itemBelow(item)
            if beyond is not None:
                return self.indexFromItem(beyond)
        return index


class SettingsDialog(DialogFrame):
    def __init__(self, registry: SettingsSectionRegistry, parent: QWidget | None = None) -> None:
        super().__init__("Settings", parent, size=DIALOG_SIZE)
        self.setObjectName("SettingsDialog")
        self._registry = registry
        # Section id → the scroller the stack shows, holding the page the factory built.
        self._pages: dict[str, QScrollArea] = {}
        self._folders: list[QTreeWidgetItem] = []  # Kept here: never read back for their ink.

        splitter = QSplitter(Qt.Orientation.Horizontal, self.body)
        splitter.setChildrenCollapsible(False)
        # Built into the splitter, the tree before the page: the frame focuses the first
        # field it finds, and the tree is where the keyboard starts here.
        self._tree = _SectionTree(splitter)
        self._tree.setObjectName("SettingsTree")
        self._tree.setHeaderHidden(True)
        self._tree.setItemDelegate(_RowHeight(self._tree))
        self._tree.setUniformRowHeights(True)  # One line a row: the first row's is every row's.
        # Always open, no arrows: a control that folds a handful of pages teaches nothing.
        self._tree.setRootIsDecorated(False)
        self._tree.setItemsExpandable(False)
        self._tree.setMinimumWidth(TREE_MIN_W)
        self._tree.setMaximumWidth(TREE_MAX_W)
        self._tree.currentItemChanged.connect(self._on_current_changed)

        # The inset from the seam is the dialog's, so no page carries a margin of its own.
        pane_host = QWidget(splitter)
        host_layout = QVBoxLayout(pane_host)
        host_layout.setContentsMargins(SECTION_GAP, 0, 0, 0)
        self._pane = QStackedWidget(pane_host)
        self._pane.setObjectName("SettingsPane")
        host_layout.addWidget(self._pane)

        splitter.addWidget(self._tree)
        splitter.addWidget(pane_host)
        splitter.setStretchFactor(1, 1)
        self.body_layout.addWidget(splitter, 1)

        self.add_dismiss("Close")  # Every edit is live: Close, and nothing else.
        self._rebuild()

    def _rebuild(self) -> None:
        self._tree.clear()
        self._folders.clear()
        folder_items: dict[tuple[str, ...], QTreeWidgetItem] = {}

        def folder_item(path: tuple[str, ...]) -> QTreeWidget | QTreeWidgetItem:
            """The heading for the folders leading up to a section — enabled so its
            children are, never selectable, bold in the secondary ink."""
            if not path:
                return self._tree
            if path in folder_items:
                return folder_items[path]
            parent = folder_item(path[:-1])
            item = QTreeWidgetItem(parent, [path[-1]])
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
            folder_items[path] = item
            self._folders.append(item)
            return item

        for section in self._registry.sections():
            parent = folder_item(section.category[:-1])
            leaf = QTreeWidgetItem(parent, [section.category[-1]])
            leaf.setData(0, _SECTION_ROLE, section.id)

        self._tree.expandAll()
        self._retint()
        self._select_first()

    def _retint(self) -> None:
        """A heading's ink is stored on its item, so it is re-read on a theme change."""
        ink = ink_of(self._tree)
        ink.setAlpha(SECONDARY_ALPHA)
        for folder in self._folders:
            folder.setForeground(0, QBrush(ink))

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.PaletteChange:
            self._retint()
        super().changeEvent(event)

    def show_section(self, section_id: str) -> None:
        """Land on one section's page — a deep link from the surface it configures."""
        item = self._find_item(self._tree, lambda i: i.data(0, _SECTION_ROLE) == section_id)
        if item is not None:
            self._tree.setCurrentItem(item)

    def current_page(self) -> QWidget | None:
        """The page on show — what a factory built, inside its scroller."""
        shown = self._pane.currentWidget()
        return shown.widget() if isinstance(shown, QScrollArea) else None

    def _select_first(self) -> None:
        """Select the first leaf — a no-op once there already is a selection, so a rebuild
        never disturbs where the user left off."""
        if self._tree.currentItem() is not None:
            return
        item = self._find_item(self._tree, lambda i: i.data(0, _SECTION_ROLE) is not None)
        if item is not None:
            self._tree.setCurrentItem(item)

    @staticmethod
    def _find_item(
        tree: QTreeWidget, matches: Callable[[QTreeWidgetItem], bool]
    ) -> QTreeWidgetItem | None:
        it = QTreeWidgetItemIterator(tree)
        while it.value() is not None:
            item = it.value()
            if matches(item):
                return item
            it += 1
        return None

    def _on_current_changed(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        if current is None:
            return
        section_id = current.data(0, _SECTION_ROLE)
        if section_id is None:
            # A heading was clicked: it has no page, so its first page answers.
            first = current.child(0)
            if first is not None:
                self._tree.setCurrentItem(first)
            return
        self._pane.setCurrentWidget(self._page_for(section_id))

    def _page_for(self, section_id: str) -> QScrollArea:
        shown = self._pages.get(section_id)
        if shown is not None:
            return shown
        section = self._section(section_id)
        shown = self._scrolling(section.factory(self._pane))
        self._pages[section_id] = shown
        self._pane.addWidget(shown)
        return shown

    def _scrolling(self, page: QWidget) -> QScrollArea:
        """A page taller than the dialog scrolls rather than squeezing; the scroller is
        frameless and transparent, so the page sits on the dialog's own ground."""
        area = QScrollArea(self._pane)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidgetResizable(True)
        area.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # The page's fields are the stops, not it.
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.viewport().setAutoFillBackground(False)
        page.setAutoFillBackground(False)
        area.setWidget(page)
        return area

    def _section(self, section_id: str) -> SettingsSection:
        return next(s for s in self._registry.sections() if s.id == section_id)
