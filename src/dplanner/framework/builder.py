"""One build: everything needed to run the application against exactly one workspace.

``AppBuilder.build()`` assembles a window and its services, in a strict order, and then
never tears any of it down. Opening a different workspace is a *new build* — see
:mod:`dplanner.framework.session` for why that is the cheap option rather than the expensive
one.

**The order is the interesting part.** Stages 3 and 5 exist purely so that stage 7 can be
unconditional: by the time a module registers, the menus, the sidebar and the context
already exist, so a module may do anything — including opening its own tab — without
checking whether the world is ready.

1. open the storage provider and load (or seed) the workspace
2. construct the framework services
3. install the window shell: menu bar, sidebar, status bar
4. bundle everything into :class:`AppServices`
5. set the application context scope
6. build the modules through the composition root
7. migrate older module data, then let every module register itself

Nothing above this file is imported. The window class, the repository and the module list
all arrive as arguments, which is what keeps the framework independent of the application
built on it — and is enforced by ``tests/test_architecture.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Self

from PySide6.QtWidgets import QApplication

from dplanner.core.module_data import migrate_module_data
from dplanner.core.repository import RepositoryFactory
from dplanner.core.storage.provider import StorageProvider
from dplanner.framework.action_registry import ActionRegistry, MenuStructure
from dplanner.framework.autosave import AutosaveService
from dplanner.framework.context import (
    SCOPE_APP,
    WORKSPACE_URI,
    ContextNode,
    ContextService,
)
from dplanner.framework.exports import ExportRegistry
from dplanner.framework.index_panel import IndexPanel, IndexSegmentRegistry
from dplanner.framework.inspector import InspectorSectionRegistry
from dplanner.framework.llm import LLMProviderRegistry
from dplanner.framework.llm_service import LLMService
from dplanner.framework.main_window import AppWindow
from dplanner.framework.menubar import DynamicMenuBar
from dplanner.framework.module import Module, PersistsModuleData
from dplanner.framework.services import AppServices
from dplanner.framework.settings_registry import SettingsSectionRegistry
from dplanner.framework.tabs import TabHost
from dplanner.framework.tasks import TaskService
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.framework.zoom import ZoomService

if TYPE_CHECKING:
    # Type-only: the session module imports this builder at runtime.
    from dplanner.framework.session import WorkspaceSwitcher

type ModuleFactory = Callable[[AppServices], Sequence[Module]]
# Write a starter workspace into empty storage. Called only when nothing is there yet, and
# the repository loads it afterwards like any other — so there is exactly one load path.
type SeedFactory = Callable[[StorageProvider], None]
type WindowFactory = Callable[[TabHost], AppWindow]


class AppBuilder:
    """A small fluent object. Everything is set before ``build()``, which raises rather
    than guessing when something is missing."""

    def __init__(self) -> None:
        self._storage: StorageProvider | None = None
        self._repository: RepositoryFactory[Any] | None = None
        self._menus: MenuStructure | None = None
        self._switcher: WorkspaceSwitcher | None = None
        self._module_factory: ModuleFactory = lambda _services: ()
        self._window_factory: WindowFactory = AppWindow
        self._seed: SeedFactory | None = None
        self._progress: Callable[[str], None] | None = None

    def with_storage(self, storage: StorageProvider) -> Self:
        self._storage = storage
        return self

    def with_repository(self, factory: RepositoryFactory[Any]) -> Self:
        """How to build your repository over a storage provider."""
        self._repository = factory
        return self

    def with_seed(self, seed: SeedFactory) -> Self:
        """What to write into empty storage. Without one, an empty workspace stays empty."""
        self._seed = seed
        return self

    def with_menus(self, menus: MenuStructure) -> Self:
        self._menus = menus
        return self

    def with_switcher(self, switcher: WorkspaceSwitcher) -> Self:
        self._switcher = switcher
        return self

    def with_modules(self, factory: ModuleFactory) -> Self:
        """The composition root: builds each module with exactly the deps it needs."""
        self._module_factory = factory
        return self

    def with_window(self, factory: WindowFactory) -> Self:
        """A window class of your own. Defaults to :class:`AppWindow`."""
        self._window_factory = factory
        return self

    def with_progress(self, progress: Callable[[str], None] | None) -> Self:
        """Stage-boundary reporting for the startup splash; None stays silent."""
        self._progress = progress
        return self

    def build(self) -> tuple[AppWindow, AppServices]:
        """Assemble the application. Requires a live ``QApplication``."""
        storage, repo_factory, menus, switcher = self._require()
        qt_app = QApplication.instance()
        if not isinstance(qt_app, QApplication):
            raise RuntimeError("build() requires a live QApplication")

        # 1 — data ------------------------------------------------------------------------
        self._report("Opening workspace…")
        repo = repo_factory(storage)
        # A workspace that does not exist yet is seeded rather than opened empty: an
        # application whose first screen is blank teaches the user nothing.
        # A workspace that does not exist yet is seeded rather than opened empty: an
        # application whose first screen is blank teaches its user nothing. It is then
        # loaded through the same path as any other, so the repository is never left
        # holding a document it did not read.
        if self._seed is not None and not repo.exists():
            self._seed(storage)
        document = repo.load()

        # 2 — services --------------------------------------------------------------------
        context = ContextService()
        actions = ActionRegistry(menus)
        undo: UndoService[Any] = UndoService(document)
        autosave = AutosaveService(repo.dirty, repo)
        tabs = TabHost(context)

        # 3 — the shell -------------------------------------------------------------------
        window = self._window_factory(tabs)
        # A tab switch is a natural save point and the end of any typing burst.
        tabs.activity_changed.connect(lambda _activity: undo.break_coalescing())
        tabs.activity_changed.connect(lambda _activity: autosave.flush_now())
        window.close_hooks.append(autosave.flush_now)
        # The menu bar subscribes to the registry, so it may exist before any action does;
        # stored on the window because its QMenus must outlive this function (PySide
        # invalidates menu wrappers whose last Python reference is dropped).
        window.dynamic_menubar = DynamicMenuBar(window, actions, context)
        # The sidebar is one index tree, installed empty. Nothing is pre-registered:
        # every folder in it belongs to a module, and the framework never learns which.
        index_segments = IndexSegmentRegistry()
        index_panel = IndexPanel(index_segments, context)
        window.set_sidebar(index_panel)
        window.close_hooks.append(index_panel.dispose)

        # 4 — the bundle ------------------------------------------------------------------
        llm_providers = LLMProviderRegistry()
        theme = ThemeService(qt_app)
        services = AppServices(
            repo=repo,
            storage=storage,
            document=document,
            context=context,
            actions=actions,
            tabs=tabs,
            window=window,
            undo=undo,
            autosave=autosave,
            index_segments=index_segments,
            inspector_sections=InspectorSectionRegistry(),
            detail_cards=InspectorSectionRegistry(),
            settings_sections=SettingsSectionRegistry(),
            exports=ExportRegistry(),
            theme=theme,
            zoom=ZoomService(),
            tasks=TaskService(),
            llm_providers=llm_providers,
            llm=LLMService(llm_providers),
            switcher=switcher,
        )

        # Index folder glyphs follow the theme's secondary text colour.
        theme.changed.connect(lambda t: index_panel.set_icon_color(t.text_secondary))
        index_panel.set_icon_color(theme.current.text_secondary)

        # 5 — the app scope, before any module registers, so a module that opens a tab
        # during registration acts against a valid context.
        context.set_scope(SCOPE_APP, (ContextNode(WORKSPACE_URI),))

        # 6 and 7 — the composition root, then migrate, then register -----------------------
        self._report("Preparing workspace…")
        modules = self._module_factory(services)
        services.modules = list(modules)
        # Module data written by an older build is migrated before any module reads it
        # (they do so in register()), and persisted straight away — per owner, so a
        # takeover's remove-and-write lands in one save.
        formats = [m.data_format for m in modules if isinstance(m, PersistsModuleData)]
        changed = migrate_module_data(repo, formats)
        if changed:
            repo.flush({(owner_id, "module_data") for owner_id in changed})
        for module in modules:
            module.register()

        return window, services

    # -- helpers -----------------------------------------------------------------------------

    def _require(
        self,
    ) -> tuple[StorageProvider, RepositoryFactory[Any], MenuStructure, WorkspaceSwitcher]:
        if self._storage is None:
            raise ValueError("with_storage() must be called before build()")
        if self._repository is None:
            raise ValueError("with_repository() must be called before build()")
        if self._menus is None:
            raise ValueError("with_menus() must be called before build()")
        if self._switcher is None:
            raise ValueError("with_switcher() must be called before build()")
        return self._storage, self._repository, self._menus, self._switcher

    def _report(self, message: str) -> None:
        if self._progress is not None:
            self._progress(message)
