"""One build: everything needed to run the application against exactly one library.

``AppBuilder.build()`` assembles a window and its services, in a strict order, and then
never tears any of it down. Reloading the library is a *new build* — see
:mod:`dplanner.framework.session` for why that is the cheap option rather than the expensive
one.

**The order is the interesting part.** Stages 3 and 5 exist purely so that stage 7 can be
unconditional: by the time a module registers, the menus, the panel areas and the context
already exist, so a module may do anything — including opening its own tab — without
checking whether the world is ready.

1. build the repository over its source path and load (or seed) it
2. construct the framework services
3. install the window shell: menu bar, panel dock, index panel, status bar
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
from dplanner.core.telemetry import current as current_telemetry
from dplanner.domain.shelf import DATA_FORMAT as SHELF_FORMAT
from dplanner.domain.shelf import migrate_shelved
from dplanner.framework.action_registry import ActionRegistry, MenuStructure
from dplanner.framework.autosave import AutosaveService
from dplanner.framework.context import (
    SCOPE_APP,
    WORKSPACE_URI,
    ContextNode,
    ContextService,
)
from dplanner.framework.debounce import Debounced, DebounceService
from dplanner.framework.index_panel import IndexPanel, IndexSegmentRegistry
from dplanner.framework.inspector import InspectorSectionRegistry
from dplanner.framework.llm import LLMProviderRegistry
from dplanner.framework.llm_service import LLMService
from dplanner.framework.main_window import AppWindow
from dplanner.framework.menubar import DynamicMenuBar
from dplanner.framework.module import Module, PersistsModuleData
from dplanner.framework.panels import PanelArea, PanelDock, PanelRegistry, PanelSpec
from dplanner.framework.services import AppServices
from dplanner.framework.settings_registry import SettingsSectionRegistry
from dplanner.framework.tabs import TabHost
from dplanner.framework.tasks import TaskService
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.framework.user_config import library_scope
from dplanner.framework.zoom import ZoomService

if TYPE_CHECKING:
    from pathlib import Path

    # Type-only: the session module imports this builder at runtime.
    from dplanner.framework.session import SessionControl

type ModuleFactory = Callable[[AppServices], Sequence[Module]]
# Write starter data at an empty source. Called only when nothing is there yet, and the
# repository loads it afterwards like any other — so there is exactly one load path.
type SeedFactory = Callable[[Path], None]
type WindowFactory = Callable[[TabHost, PanelDock], AppWindow]

# The framework's own panel: the index tree, anchored left. Named so a test — and the
# builder's own wiring below — can ask the window for it.
INDEX_PANEL_ID = "index"


class AppBuilder:
    """A small fluent object. Everything is set before ``build()``, which raises rather
    than guessing when something is missing."""

    def __init__(self) -> None:
        self._source: Path | None = None
        self._repository: RepositoryFactory[Any] | None = None
        self._menus: MenuStructure | None = None
        self._session: SessionControl | None = None
        self._module_factory: ModuleFactory = lambda _services: ()
        self._window_factory: WindowFactory = AppWindow
        self._seed: SeedFactory | None = None
        self._progress: Callable[[str], None] | None = None

    def with_source(self, source: Path) -> Self:
        """The path the repository is built over — for DPlanner, the library file."""
        self._source = source
        return self

    def with_repository(self, factory: RepositoryFactory[Any]) -> Self:
        """How to build your repository over its source path."""
        self._repository = factory
        return self

    def with_seed(self, seed: SeedFactory) -> Self:
        """What to write at an empty source. Without one, an empty source stays empty."""
        self._seed = seed
        return self

    def with_menus(self, menus: MenuStructure) -> Self:
        self._menus = menus
        return self

    def with_session(self, session: SessionControl) -> Self:
        self._session = session
        return self

    def with_modules(self, factory: ModuleFactory) -> Self:
        """The composition root: builds each module with exactly the deps it needs."""
        self._module_factory = factory
        return self

    def with_progress(self, progress: Callable[[str], None] | None) -> Self:
        """Stage-boundary reporting for the startup splash; None stays silent."""
        self._progress = progress
        return self

    def build(self) -> tuple[AppWindow, AppServices]:
        """Assemble the application. Requires a live ``QApplication``."""
        source, repo_factory, menus, session = self._require()
        qt_app = QApplication.instance()
        if not isinstance(qt_app, QApplication):
            raise RuntimeError("build() requires a live QApplication")

        # 1 — data ------------------------------------------------------------------------
        self._report("Opening library…")
        repo = repo_factory(source)
        # A source that does not exist yet is seeded rather than opened empty: an
        # application whose first screen is blank teaches its user nothing. It is then
        # loaded through the same path as any other, so the repository is never left
        # holding a document it did not read.
        if self._seed is not None and not repo.exists():
            self._seed(source)
        document = repo.load()

        # 2 — services --------------------------------------------------------------------
        context = ContextService()
        actions = ActionRegistry(menus)
        undo: UndoService[Any] = UndoService(document)
        autosave = AutosaveService(repo.dirty, repo)
        debounce = DebounceService()

        tabs = TabHost(context)

        # 3 — the shell -------------------------------------------------------------------
        # Every surface anchored beside the tabs is a registered panel; the dock is what the
        # window shows, and the registry is what modules contribute to.
        panels = PanelRegistry()
        dock = PanelDock(panels, context, tabs)
        window = self._window_factory(tabs, dock)
        # The context is announced once per event-loop turn: a gesture that publishes the
        # selection several times — a re-selection clears before it selects — costs one
        # re-evaluation of every action state, toolbar and panel, over the final state.
        context.announce = Debounced(
            context.announce_now, 0, parent=window, service=debounce
        ).trigger
        # A tab switch is a natural save point and the end of any typing burst.
        tabs.activity_changed.connect(lambda _activity: undo.break_coalescing())
        tabs.activity_changed.connect(lambda _activity: autosave.flush_now())
        window.close_hooks.append(autosave.flush_now)
        # The menu bar subscribes to the registry, so it may exist before any action does;
        # stored on the window because its QMenus must outlive this function (PySide
        # invalidates menu wrappers whose last Python reference is dropped).
        window.dynamic_menubar = DynamicMenuBar(window, actions, context)
        # The index is one tree, installed empty. Nothing is pre-registered: every folder in
        # it belongs to a module, and the framework never learns which. It is built here
        # rather than in its spec's factory because its glyph colour and its disposal are
        # wired here too — it is the framework's own panel, not a module's.
        index_segments = IndexSegmentRegistry()
        # Derived once and shared through AppServices: which folders are open, and which
        # tabs, is true of this source alone, so opening a second library never restores
        # the first one's tree.
        scope = library_scope(source)
        index_panel = IndexPanel(index_segments, context, scope=scope)
        panels.register(
            PanelSpec(
                id=INDEX_PANEL_ID,
                title="Index",
                factory=lambda: index_panel,
                area=PanelArea.LEFT,
                order=10,
            )
        )
        window.close_hooks.append(index_panel.dispose)
        window.close_hooks.append(dock.dispose)
        # The host watches the application to know which pane the user is in. A workspace
        # switch builds a new one before the old window has finished going, so the old
        # watcher has to be told to stop rather than left answering for a dead window.
        window.close_hooks.append(tabs.dispose)

        # 4 — the bundle ------------------------------------------------------------------
        llm_providers = LLMProviderRegistry()
        theme = ThemeService(qt_app)
        services = AppServices(
            repo=repo,
            document=document,
            source_scope=scope,
            context=context,
            actions=actions,
            tabs=tabs,
            window=window,
            undo=undo,
            autosave=autosave,
            debounce=debounce,
            index_segments=index_segments,
            panels=panels,
            inspector_sections=InspectorSectionRegistry(),
            detail_cards=InspectorSectionRegistry(),
            step_details=InspectorSectionRegistry(),
            settings_sections=SettingsSectionRegistry(),
            theme=theme,
            zoom=ZoomService(),
            tasks=TaskService(),
            llm_providers=llm_providers,
            llm=LLMService(llm_providers),
            switcher=session,
            telemetry=current_telemetry(),
        )

        # Index folder glyphs follow the theme's secondary text colour.
        theme.changed.connect(lambda t: index_panel.set_icon_color(t.text_secondary))
        index_panel.set_icon_color(theme.current.text_secondary)

        # 5 — the app scope, before any module registers, so a module that opens a tab
        # during registration acts against a valid context.
        context.set_scope(SCOPE_APP, (ContextNode(WORKSPACE_URI),))

        # 6 and 7 — the composition root, then migrate, then register -----------------------
        self._report("Preparing projects…")
        modules = self._module_factory(services)
        services.modules = list(modules)
        # Module data written by an older build is migrated before any module reads it
        # (they do so in register()), and persisted straight away — per owner, so a
        # takeover's remove-and-write lands in one save.
        formats = [m.data_format for m in modules if isinstance(m, PersistsModuleData)]
        # The shelf is the domain's, not a module's; what it holds is theirs.
        changed = migrate_module_data(repo, [*formats, SHELF_FORMAT], document)
        changed += migrate_shelved(repo, formats)
        if changed:
            # Prose too: an absorption may have moved an owner's text, not only its data.
            aspects = ("module_data", "module_text")
            repo.flush({(owner_id, aspect) for owner_id in changed for aspect in aspects})
        for module in modules:
            module.register()

        return window, services

    # -- helpers -----------------------------------------------------------------------------

    def _require(
        self,
    ) -> tuple[Path, RepositoryFactory[Any], MenuStructure, SessionControl]:
        if self._source is None:
            raise ValueError("with_source() must be called before build()")
        if self._repository is None:
            raise ValueError("with_repository() must be called before build()")
        if self._menus is None:
            raise ValueError("with_menus() must be called before build()")
        if self._session is None:
            raise ValueError("with_session() must be called before build()")
        return self._source, self._repository, self._menus, self._session

    def _report(self, message: str) -> None:
        if self._progress is not None:
            self._progress(message)
