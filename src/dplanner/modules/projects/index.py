"""The "Projects" folder in the index tree.

It owns one folder and everything under it: a row per project, and nothing below. Steps used
to nest here, and moving them out is what the graph editor is for — an index answers "what is
in this workspace", and a step is a position in a graph, which a list of rows cannot show.

The segment publishes what is selected and opens what is activated. It does not know what an
editor is: opening goes through a callback the composition root supplied.
"""

from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu, QTreeWidget, QTreeWidgetItem, QWidget

from dplanner.domain.model import NodeId, Product
from dplanner.framework.action_menu import build_menu
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import ContextNode, ContextService, selection_uri
from dplanner.framework.index_panel import expansion_of, restore_expansion

# The node kind for each row, so a right-click knows which menu it is looking at and the
# panel's selection scope names the right entity.
KIND_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class ProjectsSegment:
    """A row per project. Rebuilt whenever the model changes shape."""

    def __init__(
        self,
        root: QTreeWidgetItem,
        product: Product,
        context: ContextService,
        actions: ActionRegistry,
        open_project: Callable[[NodeId], None],
    ) -> None:
        self._root = root
        self._product = product
        self._context = context
        self._actions = actions
        self._open_project = open_project
        self._unsubscribe = [
            product.structure_changed.connect(lambda *_args: self.rebuild()),
            product.field_changed.connect(lambda *_args: self.rebuild()),
        ]
        self.rebuild()

    # -- what the panel asks for ---------------------------------------------------------------

    def selection_nodes(self, items: Sequence[QTreeWidgetItem]) -> Sequence[ContextNode]:
        nodes = []
        for item in items:
            kind, node_id = self._identity(item)
            if kind and node_id:
                nodes.append(ContextNode(selection_uri(kind, node_id)))
        return nodes

    def activated(self, item: QTreeWidgetItem) -> None:
        kind, node_id = self._identity(item)
        if kind == "project" and node_id:
            self._open_project(node_id)

    def context_menu(self, item: QTreeWidgetItem) -> QMenu | None:
        kind, _node_id = self._identity(item)
        if kind != "project":
            return None
        parent = self._tree()
        return build_menu(self._actions, self._context, "Project", parent) if parent else None

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()

    # -- building ------------------------------------------------------------------------------

    def rebuild(self) -> None:
        """Redraw the folder, keeping open what the user had open.

        A whole redraw rather than a diff: a product holds tens of projects, not thousands,
        and a diff is where tree bugs live. Expansion is still restored because a folder the
        user closed should stay closed — and because segments below this one may nest.
        """
        open_keys = expansion_of(self._root)
        self._root.takeChildren()
        for project in self._product.projects:
            row = QTreeWidgetItem([project.title or "Untitled project"])
            row.setData(0, Qt.ItemDataRole.UserRole, project.id)
            row.setData(0, KIND_ROLE, "project")
            self._root.addChild(row)
        restore_expansion(self._root, open_keys)

    def _identity(self, item: QTreeWidgetItem) -> tuple[str, str]:
        kind = item.data(0, KIND_ROLE)
        node_id = item.data(0, Qt.ItemDataRole.UserRole)
        return (kind if isinstance(kind, str) else ""), (
            node_id if isinstance(node_id, str) else ""
        )

    def _tree(self) -> QWidget | None:
        tree = self._root.treeWidget()
        return tree if isinstance(tree, QTreeWidget) else None
