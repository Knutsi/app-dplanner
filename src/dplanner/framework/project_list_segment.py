"""A flat index folder: one row per project, opening that project's surface.

The shape ``modules/testing/index.py`` wrote first and asked to have extracted at the third
user — *"If a third segment ever wants this shape, that is the moment to extract it, not
before"* — which the Docs folder is. What it holds is the half that is genuinely the same:
rebuilding on the model's and the theme's signals, restoring which rows were open, and
answering the panel's five hooks so a project row stands for its project and every Project
verb works from the folder.

**The menu name arrives as an argument.** ``"Project"`` is application vocabulary and has no
business in a framework file — the same reason ``IndexSegment`` names a factory rather than a
menu (see ``ARCHITECTURE.md``'s *The index tree*). The framework builds the menu; the module
says which one.

The richer ``projects/index.py`` — nested contributed entries, greyed unavailable rows,
selection restored across a rebuild — is deliberately not folded in. It is a different
problem that happens to draw rows too.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QTreeWidget, QTreeWidgetItem

from dplanner.domain.model import Library, NodeId, Project
from dplanner.framework.action_menu import build_menu
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import ContextNode, ContextService, selection_uri
from dplanner.framework.index_panel import expansion_of, restore_expansion
from dplanner.framework.theme_service import ThemeService

KIND_ROLE = int(Qt.ItemDataRole.UserRole) + 1
PROJECT_ROLE = int(Qt.ItemDataRole.UserRole) + 2

IconFor = Callable[[str], QIcon]


@dataclass(frozen=True)
class LeadingRow:
    """A row above the projects, for a surface that spans them all.

    The Tests folder has one — the library-wide roll call has no project to sit under — and
    the Docs folder has none, which is the only way the two segments differ.
    """

    label: str
    icon: IconFor
    open: Callable[[bool], None]  # The flag is `preview`.


class ProjectListSegment:
    """One row per project in the library, plus an optional row above them."""

    def __init__(
        self,
        root: QTreeWidgetItem,
        library: Library,
        context: ContextService,
        actions: ActionRegistry,
        theme: ThemeService,
        *,
        key_prefix: str,
        menu: str,
        project_icon: IconFor,
        open_project: Callable[[NodeId, bool], None],
        leading: LeadingRow | None = None,
    ) -> None:
        self._root = root
        self._library = library
        self._context = context
        self._actions = actions
        self._theme = theme
        self._key_prefix = key_prefix
        self._menu = menu
        self._project_icon = project_icon
        self._open_project = open_project
        self._leading = leading
        self._unsubscribe = [
            # The rows are projects, never steps: only the library's own membership and a
            # project's own fields can change them.
            library.structure_changed.connect(self._on_structure),
            library.field_changed.connect(self._on_field),
            # The rows carry ink-coloured icons, which a copied colour would leave stale.
            theme.changed.connect(lambda *_args: self.rebuild()),
        ]
        self.rebuild()

    def _on_structure(self, parent_id: NodeId, *_rest: object) -> None:
        if parent_id == self._library.id:
            self.rebuild()

    def _on_field(self, node_id: NodeId, *_rest: object) -> None:
        if self._library.has(node_id) and isinstance(self._library.node(node_id), Project):
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
        return build_menu(self._actions, self._context, self._menu, parent)

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

        if self._leading is not None:
            row = QTreeWidgetItem([self._leading.label])
            row.setData(0, Qt.ItemDataRole.UserRole, f"{self._key_prefix}:all")
            row.setData(0, KIND_ROLE, "all")
            row.setIcon(0, self._leading.icon(ink))
            self._root.addChild(row)

        for project in self._library.projects:
            row = QTreeWidgetItem([project.title or "Untitled project"])
            row.setData(0, Qt.ItemDataRole.UserRole, f"{self._key_prefix}:{project.id}")
            row.setData(0, KIND_ROLE, "project")
            row.setData(0, PROJECT_ROLE, project.id)
            row.setIcon(0, self._project_icon(ink))
            self._root.addChild(row)

        restore_expansion(self._root, open_keys)
        if tree is not None:
            tree.blockSignals(False)

    def _open(self, item: QTreeWidgetItem, *, preview: bool) -> None:
        kind, _node_id = self._identity(item)
        if kind == "all" and self._leading is not None:
            self._leading.open(preview)
            return
        project_id = item.data(0, PROJECT_ROLE)
        if kind == "project" and isinstance(project_id, str):
            self._open_project(project_id, preview)

    def _identity(self, item: QTreeWidgetItem) -> tuple[str, str]:
        kind = item.data(0, KIND_ROLE)
        node_id = item.data(0, PROJECT_ROLE)
        return (kind if isinstance(kind, str) else ""), (
            node_id if isinstance(node_id, str) else ""
        )

    def _tree(self) -> QTreeWidget | None:
        tree = self._root.treeWidget()
        return tree if isinstance(tree, QTreeWidget) else None
