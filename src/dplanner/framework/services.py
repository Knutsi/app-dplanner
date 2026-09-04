"""The one bundle of shared services, handed to the composition root and to tests.

A dataclass, not a service locator. There is no ``get("tabs")``, no registration by string,
no way to reach something that is not a field — so ``grep`` answers "who can reach what",
and adding a capability to the application is a visible edit to a named list.

**Modules never see this.** They receive a narrow, typed ``<Name>Deps`` object built in the
composition root, and ``tests/test_architecture.py`` fails the build if a module imports
this file. That restriction is what makes a module's blast radius readable: to know what a
feature can touch, you read its ``Deps``, not this bundle.

It exists so the composition root has one argument to work from — and so a test can build a
whole application and then reach into any part of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from dplanner.core.repository import Repository
from dplanner.core.telemetry import Telemetry
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.autosave import AutosaveService
from dplanner.framework.context import ContextService
from dplanner.framework.index_panel import IndexSegmentRegistry
from dplanner.framework.inspector import InspectorSectionRegistry
from dplanner.framework.llm import LLMProviderRegistry
from dplanner.framework.llm_service import LLMService
from dplanner.framework.module import Module
from dplanner.framework.panels import PanelRegistry
from dplanner.framework.settings_registry import SettingsSectionRegistry
from dplanner.framework.tabs import TabHost
from dplanner.framework.tasks import TaskService
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.framework.zoom import ZoomService

if TYPE_CHECKING:
    from dplanner.framework.main_window import AppWindow
    from dplanner.framework.session import SessionControl


@dataclass
class AppServices:
    # -- your data -----------------------------------------------------------------------------
    # ``repo`` is typed as the protocol so the framework compiles against any model; the
    # composition root knows the concrete type and hands modules whatever they need.
    repo: Repository[Any]
    # The loaded aggregate itself, whatever your domain calls it. Typed loosely here on
    # purpose — the framework never touches it, and the composition root re-types it the
    # moment it puts it on a module's Deps.
    document: Any
    # A key naming this build's source, under which the per-user store keeps what is true
    # of *this* document alone — which folders are open, which tabs were — as opposed to
    # the user's preferences, which follow them everywhere. See ``framework/user_config``.
    source_scope: str

    # -- what the user is doing ----------------------------------------------------------------
    context: ContextService
    actions: ActionRegistry
    tabs: TabHost
    window: AppWindow

    # -- editing -------------------------------------------------------------------------------
    undo: UndoService[Any]
    autosave: AutosaveService

    # -- surfaces modules contribute to --------------------------------------------------------
    index_segments: IndexSegmentRegistry
    panels: PanelRegistry
    inspector_sections: InspectorSectionRegistry
    detail_cards: InspectorSectionRegistry  # The same registry type, a different host.
    # Blocks composed into the step panel's first tab ("Details") — a third host of the
    # same contract, for the editors a step should show before any aspect tab is opened.
    step_details: InspectorSectionRegistry
    settings_sections: SettingsSectionRegistry

    # -- services ------------------------------------------------------------------------------
    theme: ThemeService
    zoom: ZoomService
    tasks: TaskService
    llm_providers: LLMProviderRegistry
    llm: LLMService
    switcher: SessionControl
    # The process's journal (``core/telemetry.py``): what ran and how long it took. One
    # per process rather than per build, because the signals that feed it belong to no
    # build — this is the handle a module or a test reads it through.
    telemetry: Telemetry

    # The feature modules themselves, in registration order. Not for modules — they never
    # see this bundle — but so a test can reach any part of the running application, which
    # is what this dataclass exists for.
    modules: list[Module] = field(default_factory=list)
