"""The Settings dialog: a tree of module-contributed sections beside their pages.

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
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.settings_registry import SettingsSection, SettingsSectionRegistry

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

        self._tree = QTreeWidget(self)
        self._tree.setObjectName("SettingsTree")
        self._tree.setMinimumWidth(220)
        self._tree.setMaximumWidth(320)
        self._tree.setHeaderHidden(True)
        self._tree.currentItemChanged.connect(self._on_current_changed)

        body = QHBoxLayout()
        body.addWidget(self._tree)
        body.addWidget(self._pane, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addLayout(body)
        layout.addWidget(buttons)

        self._rebuild()

    def _rebuild(self) -> None:
        self._tree.clear()
        folder_items: dict[tuple[str, ...], QTreeWidgetItem] = {}

        def folder_item(path: tuple[str, ...]) -> QTreeWidget | QTreeWidgetItem:
            """The (non-clickable) tree node for the folders leading up to a section."""
            if not path:
                return self._tree
            if path in folder_items:
                return folder_items[path]
            parent = folder_item(path[:-1])
            item = QTreeWidgetItem(parent, [path[-1]])
            folder_items[path] = item
            return item

        for section in self._registry.sections():
            parent = folder_item(section.category[:-1])
            leaf = QTreeWidgetItem(parent, [section.category[-1]])
            leaf.setData(0, _SECTION_ROLE, section.id)

        self._tree.expandAll()
        self._select_first()

    def show_section(self, section_id: str) -> None:
        """Land on one section's page — a deep link from the surface it configures."""
        item = self._find_item(self._tree, lambda i: i.data(0, _SECTION_ROLE) == section_id)
        if item is not None:
            self._tree.setCurrentItem(item)

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
