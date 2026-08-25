"""The Settings dialog: Project and Global scope as tabs, each with its own tree of
module-contributed sections.

Non-modal, like the task browser — settings changes shouldn't block the rest of the app.
Built once and reused (``.show()``/``.raise_()``), so leaving it open across an edit
doesn't lose the user's place in the tree.
"""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.settings_registry import (
    SettingsScope,
    SettingsSection,
    SettingsSectionRegistry,
)

_TAB_LABELS = {
    SettingsScope.PROJECT: "Project settings",
    SettingsScope.GLOBAL: "Global settings",
}
_SECTION_ROLE = Qt.ItemDataRole.UserRole


class SettingsDialog(QDialog):
    def __init__(self, registry: SettingsSectionRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SettingsDialog")
        self.setWindowTitle("Settings")
        self.resize(720, 480)
        self._registry = registry
        self._pages: dict[str, QWidget] = {}

        self._pane = QStackedWidget(self)
        self._pane.setObjectName("SettingsPane")
        self._empty_page = QLabel("Select a settings category.", self)
        self._empty_page.setObjectName("SettingsEmptyPage")
        self._empty_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pane.addWidget(self._empty_page)

        self._tabs = QTabWidget(self)
        self._tabs.setObjectName("SettingsTabs")
        self._tabs.setMinimumWidth(220)
        self._tabs.setMaximumWidth(320)
        self._trees: dict[SettingsScope, QTreeWidget] = {}
        for scope, label in _TAB_LABELS.items():
            tree = QTreeWidget(self)
            tree.setObjectName(f"SettingsTree_{scope.value}")
            tree.setHeaderHidden(True)
            tree.currentItemChanged.connect(self._on_current_changed)
            self._trees[scope] = tree
            self._tabs.addTab(tree, label)
        self._tabs.currentChanged.connect(self._on_tab_changed)

        body = QHBoxLayout()
        body.addWidget(self._tabs)
        body.addWidget(self._pane, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addLayout(body)
        layout.addWidget(buttons)

        self._rebuild()

    def _rebuild(self) -> None:
        for tree in self._trees.values():
            tree.clear()
        folder_items: dict[tuple[SettingsScope, tuple[str, ...]], QTreeWidgetItem] = {}

        def folder_item(
            scope: SettingsScope, path: tuple[str, ...]
        ) -> QTreeWidget | QTreeWidgetItem:
            """The (non-clickable) tree node for the folders leading up to a section."""
            if not path:
                return self._trees[scope]
            key = (scope, path)
            if key in folder_items:
                return folder_items[key]
            parent = folder_item(scope, path[:-1])
            item = QTreeWidgetItem(parent, [path[-1]])
            folder_items[key] = item
            return item

        for section in self._registry.sections():
            parent = folder_item(section.scope, section.category[:-1])
            leaf = QTreeWidgetItem(parent, [section.category[-1]])
            leaf.setData(0, _SECTION_ROLE, section.id)

        for tree in self._trees.values():
            tree.expandAll()
        for tree in self._trees.values():
            self._select_first_in(tree)
            if tree.currentItem() is not None:
                self._tabs.setCurrentWidget(tree)
                break

    def show_section(self, section_id: str) -> None:
        """Deeplink: select the given section's leaf and bring its tab to the front.
        An unknown id is a no-op — the dialog just opens wherever it was."""
        for tree in self._trees.values():
            item = self._find_item(tree, lambda i: i.data(0, _SECTION_ROLE) == section_id)
            if item is not None:
                # Item first, tab second: the tab-change handler re-applies the tree's
                # current item, so this order shows the target page exactly once.
                tree.setCurrentItem(item)
                self._tabs.setCurrentWidget(tree)
                return

    def _select_first_in(self, tree: QTreeWidget) -> None:
        """Select this tree's own first leaf — a no-op once it already has a selection,
        so revisiting a tab never disturbs where the user left it."""
        if tree.currentItem() is not None:
            return
        item = self._find_item(tree, lambda i: i.data(0, _SECTION_ROLE) is not None)
        if item is not None:
            tree.setCurrentItem(item)

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

    def _on_tab_changed(self, index: int) -> None:
        tree = self._tabs.widget(index)
        if isinstance(tree, QTreeWidget):
            self._select_first_in(tree)  # First visit to this tab: land on its own first leaf.
            self._on_current_changed(tree.currentItem(), None)

    def _on_current_changed(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        section_id = current.data(0, _SECTION_ROLE) if current is not None else None
        if section_id is None:
            self._pane.setCurrentWidget(self._empty_page)
            return
        self._pane.setCurrentWidget(self._page_for(section_id))

    def _page_for(self, section_id: str) -> QWidget:
        page = self._pages.get(section_id)
        if page is not None:
            return page
        section = self._section(section_id)
        page = section.factory(self._pane)
        self._pages[section_id] = page
        self._pane.addWidget(page)
        return page

    def _section(self, section_id: str) -> SettingsSection:
        return next(s for s in self._registry.sections() if s.id == section_id)
