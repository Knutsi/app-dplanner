"""Home: where a window starts — the getting-started guide, and a garden that says what
DPlanner does.

Home is the ``home`` tab, a singleton like any library-wide tab, and there are three ways
to it:

- the program's start, when there were no tabs to reopen — the composition root's
  ``start_window``, called by ``app.open_at_startup`` and never by a reload, so a window
  whose last tab was closed stays blank;
- the index's first row, a folder of its own whose segment answers its own row: a click
  previews Home, activation keeps it — and under it, whatever rows other modules hang
  there through ``HomeDeps.rows``;
- *Go ▸ Home*, because Go seats the index's rows.

Its one preference — whether the garden shows — is *Settings ▸ Home*; ``garden_changed`` is
how an open Home tab hears it change.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu, QTreeWidgetItem

from dplanner.core.signals import Signal
from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import ContextNode, ContextService
from dplanner.framework.index_panel import IndexSegment, IndexSegmentRegistry
from dplanner.framework.project_list_segment import LeadingRow
from dplanner.framework.settings_registry import SettingsSection, SettingsSectionRegistry
from dplanner.framework.tabs import TabHost
from dplanner.framework.theme_service import ThemeService
from dplanner.modules.home.page import HOME_KIND, HomeActivity
from dplanner.modules.home.settings_page import MODULE_ID, build_page
from dplanner.theme.icons import home_icon

ROW_ROLE = int(Qt.ItemDataRole.UserRole) + 1  # Which of ``HomeDeps.rows`` a child item is.


@dataclass(frozen=True)
class HomeDeps:
    tabs: TabHost
    actions: ActionRegistry
    context: ContextService
    segments: IndexSegmentRegistry
    theme: ThemeService  # The rows' glyphs are painted in its ink.
    settings_sections: SettingsSectionRegistry
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
        # Whether the garden shows changed — from Settings ▸ Home or the garden's close.
        self.garden_changed: Signal[()] = Signal()

    def register(self) -> None:
        deps = self._deps
        changed = self.garden_changed
        deps.tabs.register_factory(HOME_KIND, lambda _target: HomeActivity(deps, changed))
        deps.settings_sections.register(
            SettingsSection(
                id=f"{MODULE_ID}.page",
                category=("Home",),
                factory=lambda parent: build_page(parent, changed),
            )
        )
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
                tip="The getting-started guide",
                icon=home_icon,
                run=lambda _context: self.open(),
            )
        )

    def open(self, preview: bool = False) -> None:
        self._deps.tabs.open(HOME_KIND, preview=preview)
