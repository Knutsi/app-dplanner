"""The window's sidebar: one tree, whose folders come from whoever registered them.

There is exactly one sidebar and it is an index of what the workspace holds. A module that
wants a place in it registers an :class:`IndexSegment` and owns one folder and everything
under it — its rows, its icons, its double-click, its right-click menu.

**Why a tree rather than a set of pages.** A tab bar over a stack makes every feature a
peer of every other and shows one at a time; an index shows a workspace's shape at a glance
and grows by one folder rather than by one more tab. Anything a page could have held is a
folder here, so the tree subsumes the older arrangement rather than sitting beside it.

Three things live in the panel rather than in each segment, because a *shared* tree is not
the same problem as a stack of independent widgets:

**Selection is published once.** Qt selection is per-tree, not per-subtree, and
``ContextService`` has a single selection scope. The panel groups the selected items by
owning segment, asks each for its context nodes, and sets the scope once — so two segments
can never fight over it.

**A segment supplies its own menu.** The spec does not name a menu from ``MENU_STRUCTURE``:
a menu name is application vocabulary and has no business in a framework spec. A segment has
its own ``Deps`` and builds its menu with :func:`~dplanner.framework.action_menu.build_menu`.

**Expansion survives a rebuild.** Rebuilding a subtree when the model changes is the normal
case, and remembering what was open is the bookkeeping every segment would otherwise copy.
:func:`expansion_of` and :func:`restore_expansion` do it once — plain functions over the
items, so a segment needs no reference to the panel that hosts it.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from dplanner.core.signals import Signal
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, ContextService

# Set on every item so the panel can find the segment that owns it without walking the
# tree's shape, and so a segment can recognise its own rows in a signal.
SEGMENT_ROLE = int(Qt.ItemDataRole.UserRole) + 1000


@runtime_checkable
class IndexSegmentView(Protocol):
    """One folder in the index, and everything under it.

    The panel creates the folder item and hands it over; from then on the segment owns its
    contents. Every hook is optional in spirit — a segment with nothing to say returns
    nothing — but all four exist so the panel never has to guess.
    """

    def selection_nodes(self, items: Sequence[QTreeWidgetItem]) -> Sequence[ContextNode]:
        """The context nodes for whichever of this segment's rows are selected."""
        ...

    def activated(self, item: QTreeWidgetItem) -> None:
        """The user double-clicked or pressed Return on one of this segment's rows."""
        ...

    def context_menu(self, item: QTreeWidgetItem) -> QMenu | None:
        """The right-click menu for one of this segment's rows, or None for no menu."""
        ...

    def dispose(self) -> None:
        """Disconnect from the model. Called when the panel goes away."""
        ...


@dataclass(frozen=True)
class IndexSegment:
    id: str  # "projects" — module-prefixed where it could collide, globally unique.
    label: str  # The folder's text.
    factory: Callable[[QTreeWidgetItem], IndexSegmentView]
    order: int = 50  # Folder position; lowest first.
    # Folder glyph, colour-parameterized like everything in dplanner.theme.icons; the
    # panel's owner feeds it the theme's secondary text colour and re-feeds on theme change.
    icon: Callable[[str], QIcon] | None = None


class IndexSegmentRegistry:
    def __init__(self) -> None:
        self._segments: dict[str, IndexSegment] = {}
        self.registered: Signal[IndexSegment] = Signal()

    def register(self, segment: IndexSegment) -> None:
        if segment.id in self._segments:
            raise ValueError(f"index segment {segment.id!r} already registered")
        self._segments[segment.id] = segment
        self.registered.emit(segment)

    def segments(self) -> list[IndexSegment]:
        return sorted(self._segments.values(), key=lambda s: (s.order, s.id))


class IndexPanel(QWidget):
    """The one widget installed via ``SidebarHost.set_sidebar``: a tree of folders."""

    def __init__(
        self,
        segments: IndexSegmentRegistry,
        context: ContextService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("IndexPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._views: dict[str, IndexSegmentView] = {}
        self._roots: dict[str, QTreeWidgetItem] = {}
        self._specs: list[IndexSegment] = []
        self._icon_color = ""

        self._tree = QTreeWidget()
        self._tree.setObjectName("IndexTree")
        self._tree.setHeaderHidden(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._tree)

        self._tree.itemActivated.connect(self._on_activated)
        self._tree.itemSelectionChanged.connect(self._on_selection)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)

        self._context = context
        for segment in segments.segments():
            self._add_segment(segment)
        segments.registered.connect(self._add_segment)

    @property
    def tree(self) -> QTreeWidget:
        return self._tree

    def set_icon_color(self, color: str) -> None:
        """Repaint every folder glyph — called on install and on each theme change."""
        self._icon_color = color
        for segment in self._specs:
            if segment.icon is not None:
                self._roots[segment.id].setIcon(0, segment.icon(color))

    def dispose(self) -> None:
        for view in self._views.values():
            view.dispose()
        self._views.clear()

    # -- routing ---------------------------------------------------------------------------------

    def _add_segment(self, segment: IndexSegment) -> None:
        key = (segment.order, segment.id)
        index = len([s for s in self._specs if (s.order, s.id) <= key])
        root = QTreeWidgetItem([segment.label])
        root.setData(0, SEGMENT_ROLE, segment.id)
        root.setFlags(root.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self._tree.insertTopLevelItem(index, root)
        self._specs.insert(index, segment)
        self._roots[segment.id] = root
        if segment.icon is not None and self._icon_color:
            root.setIcon(0, segment.icon(self._icon_color))
        self._views[segment.id] = segment.factory(root)
        root.setExpanded(True)

    def _owner_of(self, item: QTreeWidgetItem | None) -> str | None:
        while item is not None:
            owner = item.data(0, SEGMENT_ROLE)
            if isinstance(owner, str):
                return owner
            item = item.parent()
        return None

    def _on_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        owner = self._owner_of(item)
        if owner is not None and item is not self._roots[owner]:
            self._views[owner].activated(item)

    def _on_selection(self) -> None:
        """Collect every segment's nodes and publish the selection scope exactly once."""
        by_owner: dict[str, list[QTreeWidgetItem]] = {}
        for item in self._tree.selectedItems():
            owner = self._owner_of(item)
            if owner is not None and item is not self._roots[owner]:
                by_owner.setdefault(owner, []).append(item)
        nodes: list[ContextNode] = []
        for owner, items in by_owner.items():
            nodes.extend(self._views[owner].selection_nodes(items))
        self._context.set_scope(SCOPE_SELECTION, tuple(nodes))

    def _on_context_menu(self, position: object) -> None:
        from PySide6.QtCore import QPoint

        assert isinstance(position, QPoint)
        item = self._tree.itemAt(position)
        owner = self._owner_of(item)
        if item is None or owner is None or item is self._roots[owner]:
            return
        menu = self._views[owner].context_menu(item)
        if menu is not None:
            menu.exec(self._tree.viewport().mapToGlobal(position))


def expansion_of(item: QTreeWidgetItem) -> set[str]:
    """Which rows under ``item`` are open, keyed by the id the segment stored on each.

    A segment puts a node id in ``Qt.ItemDataRole.UserRole`` on every row it creates; this
    reads them back so a rebuild can restore exactly what the user had open rather than
    collapsing everything under them.
    """
    open_keys: set[str] = set()
    for row in _walk(item):
        key = row.data(0, Qt.ItemDataRole.UserRole)
        if row.isExpanded() and isinstance(key, str):
            open_keys.add(key)
    return open_keys


def restore_expansion(item: QTreeWidgetItem, open_keys: set[str]) -> None:
    for row in _walk(item):
        key = row.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(key, str) and key in open_keys:
            row.setExpanded(True)


def _walk(item: QTreeWidgetItem) -> list[QTreeWidgetItem]:
    rows = [item]
    for index in range(item.childCount()):
        child = item.child(index)
        if child is not None:
            rows.extend(_walk(child))
    return rows
