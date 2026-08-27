"""The "Projects" folder in the index tree.

It owns one folder and everything under it: a row per project, and under each project a row
per contributed :class:`ProjectEntry`. Steps used to nest here, and moving them out is what
the graph editor is for — an index answers "what is in this workspace", and a step is a
position in a graph, which a list of rows cannot show. An entry is different: it is a door
into a project-scoped surface (its specs, say), not a copy of the project's content.

The segment publishes what is selected and opens what is activated. A project row is a
folder: double-clicking it folds and unfolds (Qt's own double-click behaviour — activation
adds nothing, so nothing here fights it). What *opens* is an entry row, through the
``entry.open`` callback the composition root supplied; the segment never learns what an
editor is.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QTreeWidget, QTreeWidgetItem, QWidget

from dplanner.domain.model import NodeId, Product
from dplanner.framework.action_menu import build_menu
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import ContextNode, ContextService, selection_uri
from dplanner.framework.index_panel import expansion_of, restore_expansion
from dplanner.framework.theme_service import ThemeService
from dplanner.theme.icons import project_icon

# The node kind for each row, so a right-click knows which menu it is looking at and the
# panel's selection scope names the right entity.
KIND_ROLE = int(Qt.ItemDataRole.UserRole) + 1
# On an entry row: which ProjectEntry it renders, and which project it belongs to. A row's
# UserRole stays its expansion key ("<project id>:<entry id>" — unique, where the bare
# project id would collide with the project row's own key).
ENTRY_ROLE = int(Qt.ItemDataRole.UserRole) + 2
PROJECT_ROLE = int(Qt.ItemDataRole.UserRole) + 3


@dataclass(frozen=True)
class ProjectEntry:
    """A row a module contributes under every project in the index.

    The same seam as ``open_project`` one level down: the contributing module hands the
    composition root a label, a glyph and an ``open`` callback, and this module renders the
    row without ever learning who owns it.
    """

    id: str  # Unique among entries; part of the row's expansion key.
    label: str
    # Show this entry's surface for a project. Activation calls it, nothing else does.
    open: Callable[[NodeId], None]
    icon: Callable[[str], QIcon] | None = None
    # The MENU_STRUCTURE menu the row's right-click renders; None means no menu.
    menu: str | None = None
    order: int = 50


class ProjectsSegment:
    """A row per project, an entry row under each. Rebuilt whenever the model changes shape."""

    def __init__(
        self,
        root: QTreeWidgetItem,
        product: Product,
        context: ContextService,
        actions: ActionRegistry,
        theme: ThemeService,
        entries: tuple[ProjectEntry, ...] = (),
    ) -> None:
        self._root = root
        self._product = product
        self._context = context
        self._actions = actions
        self._theme = theme
        self._entries = tuple(sorted(entries, key=lambda entry: (entry.order, entry.id)))
        self._unsubscribe = [
            product.structure_changed.connect(lambda *_args: self.rebuild()),
            product.field_changed.connect(lambda *_args: self.rebuild()),
            # Row icons are painted in the theme's ink, and only the segment knows which
            # rows carry one — the panel's re-tint hook covers folder roots alone.
            theme.changed.connect(lambda *_args: self.rebuild()),
        ]
        self.rebuild()

    # -- what the panel asks for ---------------------------------------------------------------

    def selection_nodes(self, items: Sequence[QTreeWidgetItem]) -> Sequence[ContextNode]:
        uris = []
        for item in items:
            kind, node_id = self._identity(item)
            if kind == "entry":
                # An entry row stands for its project: publishing the project's URI is what
                # keeps every Project verb and the project panel working from here.
                kind, node_id = "project", self._entry_project(item)
            if not (kind and node_id):
                continue
            uri = selection_uri(kind, node_id)
            # Dedupe: a project and its entry selected together are one project — a double
            # entry would make selected_entity() answer None and hide the project's panel.
            if uri not in uris:
                uris.append(uri)
        return [ContextNode(uri) for uri in uris]

    def activated(self, item: QTreeWidgetItem) -> None:
        kind, _node_id = self._identity(item)
        if kind == "entry":
            entry = self._entry_of(item)
            project_id = self._entry_project(item)
            if entry and project_id:
                entry.open(project_id)
        # A project row deliberately does nothing here: double-click already folds it, and
        # opening a surface is what its entry rows are for.

    def context_menu(self, item: QTreeWidgetItem) -> QMenu | None:
        kind, _node_id = self._identity(item)
        menu = "Project" if kind == "project" else None
        if kind == "entry" and (entry := self._entry_of(item)):
            menu = entry.menu
        parent = self._tree()
        if menu is None or parent is None:
            return None
        return build_menu(self._actions, self._context, menu, parent)

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()

    # -- building ------------------------------------------------------------------------------

    def rebuild(self) -> None:
        """Redraw the folder, keeping open what the user had open.

        A whole redraw rather than a diff: a product holds tens of projects, not thousands,
        and a diff is where tree bugs live. Expansion is still restored because a folder the
        user closed should stay closed — the entry rows nesting under each project are why.
        """
        ink = self._theme.current.text_secondary
        open_keys = expansion_of(self._root)
        self._root.takeChildren()
        for project in self._product.projects:
            row = QTreeWidgetItem([project.title or "Untitled project"])
            row.setData(0, Qt.ItemDataRole.UserRole, project.id)
            row.setData(0, KIND_ROLE, "project")
            row.setIcon(0, project_icon(ink))
            for entry in self._entries:
                child = QTreeWidgetItem([entry.label])
                child.setData(0, Qt.ItemDataRole.UserRole, f"{project.id}:{entry.id}")
                child.setData(0, KIND_ROLE, "entry")
                child.setData(0, ENTRY_ROLE, entry.id)
                child.setData(0, PROJECT_ROLE, project.id)
                if entry.icon is not None:
                    child.setIcon(0, entry.icon(ink))
                row.addChild(child)
            self._root.addChild(row)
        restore_expansion(self._root, open_keys)

    def _identity(self, item: QTreeWidgetItem) -> tuple[str, str]:
        kind = item.data(0, KIND_ROLE)
        node_id = item.data(0, Qt.ItemDataRole.UserRole)
        return (kind if isinstance(kind, str) else ""), (
            node_id if isinstance(node_id, str) else ""
        )

    def _entry_of(self, item: QTreeWidgetItem) -> ProjectEntry | None:
        entry_id = item.data(0, ENTRY_ROLE)
        return next((entry for entry in self._entries if entry.id == entry_id), None)

    def _entry_project(self, item: QTreeWidgetItem) -> str:
        project_id = item.data(0, PROJECT_ROLE)
        return project_id if isinstance(project_id, str) else ""

    def _tree(self) -> QWidget | None:
        tree = self._root.treeWidget()
        return tree if isinstance(tree, QTreeWidget) else None
