"""The "Projects" folder in the index tree.

It owns one folder and everything under it: a row per project, and under each project a row
per contributed :class:`ProjectEntry`. Steps used to nest here, and moving them out is what
the graph editor is for — an index answers "what is in this workspace", and a step is a
position in a graph, which a list of rows cannot show. An entry is different: it is a door
into a project-scoped surface (its specs, say), not a copy of the project's content.

The segment publishes what is selected and opens what is activated. A project row opens
the project's home — its Dashboard — through the ``open_dashboard`` callback the
composition root supplied, and an entry row opens its own surface through ``entry.open``;
the segment never learns what an editor is. A plain click opens the same surface as a
*preview* tab — the glance that VS Code's next glance replaces — and activation is what
keeps it. Double-clicking a project row also folds it (Qt's own double-click behaviour,
which nothing here fights): the tab is kept and the folder closes.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QTreeWidget, QTreeWidgetItem

from dplanner.core.signals import Signal as CoreSignal
from dplanner.domain.model import Library, NodeId, Project
from dplanner.domain.store import ProjectProblem
from dplanner.framework.action_menu import build_menu
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import ContextNode, ContextService, selection_uri
from dplanner.framework.debounce import Debounced, DebounceService
from dplanner.framework.index_panel import (
    expansion_of,
    restore_expansion,
    restore_selection,
    selection_of,
)
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
    # The same surface as a preview tab — what a single click opens. None is an entry
    # whose surface has no preview form; a click then only selects the row.
    open_preview: Callable[[NodeId], None] | None = None
    icon: Callable[[str], QIcon] | None = None
    # The MENU_STRUCTURE menu the row's right-click renders; None means no menu.
    menu: str | None = None
    order: int = 50
    # A mark after the label while this entry has something waiting for the person — the
    # Specs row while a source has updates. "" for nothing, which is the usual answer.
    badge: Callable[[NodeId], str] | None = None
    # What says to look again. The segment rebuilds on it, coalesced like every other
    # change; an entry with a badge and no signal would be right only by accident.
    changed: "CoreSignal[*tuple[Any, ...]] | None" = None


class ProjectsSegment:
    """A row per project, an entry row under each. Rebuilt whenever the model changes shape."""

    def __init__(
        self,
        root: QTreeWidgetItem,
        library: Library,
        context: ContextService,
        actions: ActionRegistry,
        theme: ThemeService,
        entries: tuple[ProjectEntry, ...] = (),
        problems: Callable[[], list[ProjectProblem]] = list,
        debounce: DebounceService | None = None,
        open_dashboard: Callable[[NodeId, bool], None] | None = None,
    ) -> None:
        self._root = root
        # (project id, preview) — the project row's own door; None is a build with no home
        # tab, where a click on the row only selects it.
        self._open_dashboard = open_dashboard
        # After a quiet spell, not per signal: the whole folder is redrawn. No Qt parent —
        # a segment is not a widget — so the service's cancel_all is what disarms it.
        self._rebuild_soon = Debounced(self.rebuild, parent=None, service=debounce)
        self._library = library
        self._problems = problems
        self._context = context
        self._actions = actions
        self._theme = theme
        self._entries = tuple(sorted(entries, key=lambda entry: (entry.order, entry.id)))
        self._unsubscribe = [
            # The tree lists projects, never steps: only the library's own membership and
            # a project's own fields can change what it shows.
            library.structure_changed.connect(self._on_structure),
            library.field_changed.connect(self._on_field),
            # Row icons are painted in the theme's ink, and only the segment knows which
            # rows carry one — the panel's re-tint hook covers folder roots alone.
            theme.changed.connect(lambda *_args: self.rebuild()),
            *(
                entry.changed.connect(lambda *_args: self._rebuild_soon.trigger())
                for entry in self._entries
                if entry.changed is not None
            ),
        ]
        self.rebuild()

    def _on_structure(self, parent_id: NodeId, *_rest: object) -> None:
        if parent_id == self._library.id:
            self._rebuild_soon.trigger()

    def _on_field(self, node_id: NodeId, *_rest: object) -> None:
        if self._library.has(node_id) and isinstance(self._library.node(node_id), Project):
            self._rebuild_soon.trigger()

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

    def clicked(self, item: QTreeWidgetItem) -> None:
        kind, node_id = self._identity(item)
        if kind == "entry":
            entry = self._entry_of(item)
            project_id = self._entry_project(item)
            if entry and project_id and entry.open_preview is not None:
                entry.open_preview(project_id)
        elif kind == "project" and node_id and self._open_dashboard is not None:
            self._open_dashboard(node_id, True)  # A glance at the project's home.

    def activated(self, item: QTreeWidgetItem) -> None:
        kind, node_id = self._identity(item)
        if kind == "entry":
            entry = self._entry_of(item)
            project_id = self._entry_project(item)
            if entry and project_id:
                entry.open(project_id)
        elif kind == "project" and node_id and self._open_dashboard is not None:
            self._open_dashboard(node_id, False)  # Kept; Qt folds the row as well.

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
        """Redraw the folder, keeping open — and selected — what the user had.

        A whole redraw rather than a diff: a library holds tens of projects, not thousands,
        and a diff is where tree bugs live. Expansion is still restored because a folder the
        user closed should stay closed — the entry rows nesting under each project are why.
        Selection is restored under blocked signals, because ``takeChildren`` deselecting
        everything would otherwise publish an empty selection scope on every rename — and
        the panels following the context would abandon what the user is looking at.
        """
        tree = self._tree()
        if tree is not None:
            tree.blockSignals(True)
        ink = self._theme.current.text_secondary
        open_keys = expansion_of(self._root)
        selected_keys = selection_of(self._root)
        self._root.takeChildren()
        for project in self._library.projects:
            row = QTreeWidgetItem([project.title or "Untitled project"])
            row.setData(0, Qt.ItemDataRole.UserRole, project.id)
            row.setData(0, KIND_ROLE, "project")
            row.setIcon(0, project_icon(ink))
            for entry in self._entries:
                child = QTreeWidgetItem([entry.label])
                child.setData(0, Qt.ItemDataRole.UserRole, f"{project.id}:{entry.id}")
                if entry.badge is not None:
                    child.setText(0, f"{entry.label}{entry.badge(project.id)}")
                child.setData(0, KIND_ROLE, "entry")
                child.setData(0, ENTRY_ROLE, entry.id)
                child.setData(0, PROJECT_ROLE, project.id)
                if entry.icon is not None:
                    child.setIcon(0, entry.icon(ink))
                row.addChild(child)
            self._root.addChild(row)
        for problem in self._problems():
            # A project this build could not open is still the user's project: a greyed,
            # non-activatable row that says why, instead of silently vanishing.
            row = QTreeWidgetItem([f"{problem.path.name} — unavailable"])
            row.setToolTip(0, f"{problem.path}\n{problem.reason}")
            row.setDisabled(True)
            row.setData(0, KIND_ROLE, "problem")
            self._root.addChild(row)
        restore_expansion(self._root, open_keys)
        restored = restore_selection(self._root, selected_keys)
        if tree is not None:
            tree.blockSignals(False)
            if restored != selected_keys:
                # A selected row is truly gone — that change must announce itself.
                tree.itemSelectionChanged.emit()

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

    def _tree(self) -> QTreeWidget | None:
        tree = self._root.treeWidget()
        return tree if isinstance(tree, QTreeWidget) else None
