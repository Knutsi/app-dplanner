"""The "Archive" folder in the index tree: a row per project archived out of this library.

The Projects folder's quieter sibling. An archived project is not in the model, so a row
here stands for a *directory* — published as ``archived_project`` — and every verb it
offers is the Project menu's *membership* band, the band the Archive tab's strip and
right-click render too. A click glances at the Archive tab with the row picked, and
activation keeps the tab. It rebuilds on the store's ``archive_changed`` and on a theme
change, whole, as the Projects folder does: an archive holds tens of rows.
"""

from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QMenu, QTreeWidget, QTreeWidgetItem

from dplanner.core.signals import Signal
from dplanner.domain.plan_repo import summary
from dplanner.framework.action_menu import build_menu
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import ContextNode, ContextService, selection_uri
from dplanner.framework.index_panel import restore_selection, selection_of
from dplanner.framework.theme_service import ThemeService
from dplanner.modules.projects.archive_tab import archived_label
from dplanner.modules.projects.verbs import ARCHIVED_KIND
from dplanner.theme.icons import project_icon


class ArchiveSegment:
    def __init__(
        self,
        root: QTreeWidgetItem,
        *,
        archived: Callable[[], list[Path]],
        changed: Signal[()],
        open_archive: Callable[[Path, bool], None],  # The directory, and `preview`.
        context: ContextService,
        actions: ActionRegistry,
        theme: ThemeService,
    ) -> None:
        self._root = root
        self._archived = archived
        self._open_archive = open_archive
        self._context = context
        self._actions = actions
        self._theme = theme
        self._unsubscribe = [
            changed.connect(self.rebuild),
            # Row icons and the missing-folder tone are painted in the theme's ink.
            theme.changed.connect(lambda *_args: self.rebuild()),
        ]
        self.rebuild()

    # -- what the panel asks for ---------------------------------------------------------------

    def selection_nodes(self, items: Sequence[QTreeWidgetItem]) -> Sequence[ContextNode]:
        return [
            ContextNode(selection_uri(ARCHIVED_KIND, directory))
            for item in items
            if (directory := self._directory(item))
        ]

    def clicked(self, item: QTreeWidgetItem) -> None:
        if directory := self._directory(item):
            self._open_archive(Path(directory), True)

    def activated(self, item: QTreeWidgetItem) -> None:
        if directory := self._directory(item):
            self._open_archive(Path(directory), False)

    def context_menu(self, item: QTreeWidgetItem) -> QMenu | None:
        tree = self._tree()
        if not self._directory(item) or tree is None:
            return None
        return build_menu(self._actions, self._context, "Project", tree, group="membership")

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()

    # -- building ------------------------------------------------------------------------------

    def rebuild(self) -> None:
        """Redraw the folder, keeping the selection under blocked signals — the Projects
        folder's reason: a rebuild must not publish an empty selection on its way."""
        tree = self._tree()
        if tree is not None:
            tree.blockSignals(True)
        ink = self._theme.current.text_secondary
        selected_keys = selection_of(self._root)
        self._root.takeChildren()
        for directory in self._archived():
            found = summary(directory)
            row = QTreeWidgetItem([archived_label(directory, found)])
            row.setData(0, Qt.ItemDataRole.UserRole, str(directory))
            row.setToolTip(0, str(directory))
            row.setIcon(0, project_icon(ink))
            if not found.present:
                # Greyed by tone, not disabled: Remove from Library still has to reach it.
                row.setForeground(0, QColor(ink))
            self._root.addChild(row)
        restored = restore_selection(self._root, selected_keys)
        if tree is not None:
            tree.blockSignals(False)
            if restored != selected_keys:
                tree.itemSelectionChanged.emit()  # A selected row went: announce it.

    def _directory(self, item: QTreeWidgetItem) -> str:
        if item is self._root:
            return ""
        directory = item.data(0, Qt.ItemDataRole.UserRole)
        return directory if isinstance(directory, str) else ""

    def _tree(self) -> QTreeWidget | None:
        tree = self._root.treeWidget()
        return tree if isinstance(tree, QTreeWidget) else None
