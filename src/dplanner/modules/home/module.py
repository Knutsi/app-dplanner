"""Home: where a window starts — the guide, the tabs kept lately, and the index row to both.

One page (``page.py``) and four ways to it:

- the tab host's **backdrop** — the page stands wherever the tabs would be while none is open,
  so a fresh window, and a window whose last tab closed, lands here rather than on an empty
  tab bar;
- the ``home`` tab, a singleton, for keeping Home open beside other tabs;
- the index's first row, a folder of its own whose segment answers its own row: a click
  previews Home, activation keeps it — and under it, whatever rows other modules hang
  there through ``HomeDeps.rows``;
- *Go ▸ Home*, because Go seats the index's rows.

What Home lists as recent is ``reopen_tabs``', handed over by the composition root: that
module does the reopening at startup, so it is the one that can tell a tab it brought back
from one the person chose.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu, QTreeWidgetItem

from dplanner.domain.model import Library
from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import ContextNode, ContextService
from dplanner.framework.index_panel import IndexSegment, IndexSegmentRegistry
from dplanner.framework.project_list_segment import LeadingRow
from dplanner.framework.tabs import KeptTab, TabHost
from dplanner.framework.theme_service import ThemeService
from dplanner.modules.home.page import HOME_KIND, HomeActivity, HomePage
from dplanner.theme.icons import home_icon

MODULE_ID = "home"
ROW_ROLE = int(Qt.ItemDataRole.UserRole) + 1  # Which of ``HomeDeps.rows`` a child item is.


@dataclass(frozen=True)
class HomeDeps:
    tabs: TabHost
    actions: ActionRegistry
    context: ContextService
    segments: IndexSegmentRegistry
    # Membership: a project that leaves the library takes its recent rows with it.
    library: Library
    # The tabs kept lately, newest first — and how to hear them change.
    recent: Callable[[], Sequence[KeptTab]]
    watch_recent: Callable[[Callable[[], None]], Callable[[], None]]
    theme: ThemeService  # The rows' glyphs are painted in its ink.
    # Rows other modules hang under Home in the index, each a surface that spans the library
    # — the Tests folder's All Projects row, one folder up. The flag ``open`` takes is preview.
    rows: tuple[LeadingRow, ...] = ()


class HomeSegment:
    """The index's Home row: a folder whose own row is the way in, with ``HomeDeps.rows``
    under it. Every row opens its surface — a click as a preview, activation to keep — and
    none stands for anything a verb could act on, so it offers no menu and no selection."""

    def __init__(
        self,
        root: QTreeWidgetItem,
        open_home: Callable[[bool], None],
        rows: tuple[LeadingRow, ...],
        theme: ThemeService,
    ) -> None:
        self._root = root
        self._open_home = open_home
        self._rows = rows
        self._theme = theme
        self._items: list[QTreeWidgetItem] = []
        for index, row in enumerate(rows):
            item = QTreeWidgetItem([row.label])
            item.setData(0, Qt.ItemDataRole.UserRole, f"{MODULE_ID}:{index}")
            item.setData(0, ROW_ROLE, index)
            root.addChild(item)
            self._items.append(item)
        self._paint()
        self._unsubscribe = theme.changed.connect(lambda *_args: self._paint())

    def _paint(self) -> None:
        ink = self._theme.current.text_secondary
        for row, item in zip(self._rows, self._items, strict=True):
            item.setIcon(0, row.icon(ink))

    def selection_nodes(self, items: Sequence[QTreeWidgetItem]) -> Sequence[ContextNode]:
        return []

    def clicked(self, item: QTreeWidgetItem) -> None:
        self._open(item, preview=True)

    def activated(self, item: QTreeWidgetItem) -> None:
        self._open(item, preview=False)

    def context_menu(self, item: QTreeWidgetItem) -> QMenu | None:
        return None

    def dispose(self) -> None:
        self._unsubscribe()

    def _open(self, item: QTreeWidgetItem, *, preview: bool) -> None:
        if item is self._root:
            self._open_home(preview)
            return
        index = item.data(0, ROW_ROLE)
        if isinstance(index, int) and 0 <= index < len(self._rows):
            self._rows[index].open(preview)


class HomeModule:
    id = MODULE_ID

    def __init__(self, deps: HomeDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.tabs.register_factory(HOME_KIND, lambda _target: HomeActivity(deps))
        deps.tabs.set_backdrop(HomePage(deps))
        deps.segments.register(
            IndexSegment(
                id=MODULE_ID,
                label="Home",
                factory=lambda root: HomeSegment(root, self.open, deps.rows, deps.theme),
                order=0,  # The top of the index: where a window starts.
                icon=home_icon,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="home.open",
                label="&Home",
                menu="Go",
                group="home",
                order=10,
                tip="The getting-started guide, and the tabs you kept open lately",
                icon=home_icon,
                run=lambda _context: self.open(),
            )
        )

    def open(self, preview: bool = False) -> None:
        self._deps.tabs.open(HOME_KIND, preview=preview)
