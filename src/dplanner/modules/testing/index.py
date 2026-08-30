"""The "Tests" folder in the index tree, below Projects.

Two kinds of row and nothing else: **All Projects**, which opens the library-wide roll
call, and one row per project, which opens that project's Tests tab. Tests get a folder of
their own rather than an entry under each project because they are the one surface that is
also *cross*-project — the roll call has no project to sit under.

It is a deliberately simpler cousin of ``projects/index.py``: a flat list, no nesting, no
unavailable rows (a project that will not open has no tests to show either). If a third
segment ever wants this shape, that is the moment to extract it — not before.
"""

from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu, QTreeWidget, QTreeWidgetItem

from dplanner.domain.model import Library, NodeId
from dplanner.framework.action_menu import build_menu
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import ContextNode, ContextService, selection_uri
from dplanner.framework.index_panel import expansion_of, restore_expansion
from dplanner.framework.theme_service import ThemeService
from dplanner.theme.icons import list_icon, project_icon

KIND_ROLE = int(Qt.ItemDataRole.UserRole) + 1
_PROJECT_ROLE = int(Qt.ItemDataRole.UserRole) + 2

ALL_KEY = "tests:all"
ALL_LABEL = "All Projects"


class TestsSegment:
    """A row for every project's tests, and one for all of them at once."""

    def __init__(
        self,
        root: QTreeWidgetItem,
        library: Library,
        context: ContextService,
        actions: ActionRegistry,
        theme: ThemeService,
        open_project: Callable[[NodeId, bool], None],
        open_all: Callable[[bool], None],
    ) -> None:
        self._root = root
        self._library = library
        self._context = context
        self._actions = actions
        self._theme = theme
        self._open_project = open_project
        self._open_all = open_all
        self._unsubscribe = [
            library.structure_changed.connect(lambda *_args: self.rebuild()),
            library.field_changed.connect(lambda *_args: self.rebuild()),
            theme.changed.connect(lambda *_args: self.rebuild()),
        ]
        self.rebuild()

    # -- what the panel asks for ---------------------------------------------------------

    def selection_nodes(self, items: Sequence[QTreeWidgetItem]) -> Sequence[ContextNode]:
        """A project row stands for its project, so every Project verb works from here."""
        uris: list[str] = []
        for item in items:
            kind, node_id = self._identity(item)
            if kind != "project" or not node_id:
                continue
            uri = selection_uri("project", node_id)
            if uri not in uris:
                uris.append(uri)
        return [ContextNode(uri) for uri in uris]

    def clicked(self, item: QTreeWidgetItem) -> None:
        """A single click is a glance: the same surface, as a preview tab."""
        self._open(item, preview=True)

    def activated(self, item: QTreeWidgetItem) -> None:
        self._open(item, preview=False)

    def context_menu(self, item: QTreeWidgetItem) -> QMenu | None:
        kind, _node_id = self._identity(item)
        parent = self._tree()
        if kind != "project" or parent is None:
            return None
        return build_menu(self._actions, self._context, "Project", parent)

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()

    # -- building ------------------------------------------------------------------------

    def rebuild(self) -> None:
        tree = self._tree()
        if tree is not None:
            tree.blockSignals(True)
        ink = self._theme.current.text_secondary
        open_keys = expansion_of(self._root)
        self._root.takeChildren()

        everything = QTreeWidgetItem([ALL_LABEL])
        everything.setData(0, Qt.ItemDataRole.UserRole, ALL_KEY)
        everything.setData(0, KIND_ROLE, "all")
        everything.setIcon(0, list_icon(ink))
        self._root.addChild(everything)

        for project in self._library.projects:
            row = QTreeWidgetItem([project.title or "Untitled project"])
            row.setData(0, Qt.ItemDataRole.UserRole, f"tests:{project.id}")
            row.setData(0, KIND_ROLE, "project")
            row.setData(0, _PROJECT_ROLE, project.id)
            row.setIcon(0, project_icon(ink))
            self._root.addChild(row)

        restore_expansion(self._root, open_keys)
        if tree is not None:
            tree.blockSignals(False)

    def _open(self, item: QTreeWidgetItem, *, preview: bool) -> None:
        kind, _node_id = self._identity(item)
        if kind == "all":
            self._open_all(preview)
            return
        project_id = item.data(0, _PROJECT_ROLE)
        if kind == "project" and isinstance(project_id, str):
            self._open_project(project_id, preview)

    def _identity(self, item: QTreeWidgetItem) -> tuple[str, str]:
        kind = item.data(0, KIND_ROLE)
        node_id = item.data(0, _PROJECT_ROLE)
        return (kind if isinstance(kind, str) else ""), (
            node_id if isinstance(node_id, str) else ""
        )

    def _tree(self) -> QTreeWidget | None:
        tree = self._root.treeWidget()
        return tree if isinstance(tree, QTreeWidget) else None
