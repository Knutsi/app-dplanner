"""Feature modules, and the composition root that wires them together.

``default_modules()`` **is** the application. Which features run, what each one may touch
(its typed ``Deps``), and how features cooperate — all of it is readable in this one file,
and nowhere else.

This is the only file allowed to import every module and :class:`AppServices`. Modules never
see the whole bundle and never import each other; when one needs something another provides,
it declares a typed callback on its own ``Deps`` and this file supplies one. So the answer to
"what is this application, and who depends on whom?" has exactly one place to look.

**Order matters.** The returned list is registration order, and it fixes status-bar widget
order, sidebar page order, and — the one that bites — that surfaces exist before whoever
renders them is built. Every constrained position below carries a comment saying why.
"""

from dplanner.core.storage.locations import StorageLocation
from dplanner.domain.model import Plan
from dplanner.framework.module import Module
from dplanner.framework.services import AppServices
from dplanner.modules.appshell import AppShellDeps, AppShellModule
from dplanner.modules.debug import DebugDeps, DebugModule
from dplanner.modules.llm import LlmDeps, LlmModule
from dplanner.modules.llm_anthropic import LlmAnthropicDeps, LlmAnthropicModule
from dplanner.modules.llm_openai import LlmOpenAIDeps, LlmOpenAIModule
from dplanner.modules.plan_tree import PlanTreeDeps, PlanTreeModule
from dplanner.modules.settings import SettingsDeps, SettingsModule
from dplanner.modules.sync import SyncDeps, SyncModule
from dplanner.modules.task_editor import TaskEditorDeps, TaskEditorModule
from dplanner.modules.task_properties import TaskPropertiesDeps, TaskPropertiesModule
from dplanner.modules.taskcenter import TaskCenterDeps, TaskCenterModule
from dplanner.modules.workspaces import WorkspacesDeps, WorkspacesModule, choose_workspace

__all__ = ["StorageLocation", "choose_workspace", "default_modules"]


def default_modules(services: AppServices) -> list[Module]:
    plan: Plan = services.document

    # The editor is constructed first so the browser can be handed its open() as a plain
    # function. Construction is side-effect-free — nothing is registered until register()
    # — which is exactly what lets the composition root order construction by the wiring
    # rather than by the runtime dependencies.
    editor = TaskEditorModule(
        TaskEditorDeps(
            plan=plan,
            context=services.context,
            actions=services.actions,
            tabs=services.tabs,
            undo=services.undo,
            zoom=services.zoom,
            sections=services.inspector_sections,
        )
    )

    return [
        # -- the shell -------------------------------------------------------------------
        AppShellModule(
            AppShellDeps(
                actions=services.actions,
                context=services.context,
                tabs=services.tabs,
                theme=services.theme,
                undo=services.undo,
                zoom=services.zoom,
                window=services.window,
            )
        ),
        WorkspacesModule(
            WorkspacesDeps(
                actions=services.actions,
                tasks=services.tasks,
                parent=services.window,
                switcher=services.switcher,
            )
        ),
        # Before the task centre, so the workspace path and branch sit left of the task
        # button in the status bar.
        SyncModule(
            SyncDeps(
                actions=services.actions,
                autosave=services.autosave,
                context=services.context,
                storage=services.storage,
                status=services.window,
                tasks=services.tasks,
                chrome=services.window,
                theme=services.theme,
                parent=services.window,
                switcher=services.switcher,
            )
        ),
        TaskCenterModule(
            TaskCenterDeps(
                tasks=services.tasks,
                actions=services.actions,
                status=services.window,
                parent=services.window,
            )
        ),
        # -- AI --------------------------------------------------------------------------
        # Providers before the llm module: its settings page lists whatever has registered.
        LlmOpenAIModule(
            LlmOpenAIDeps(
                llm_providers=services.llm_providers,
                llm=services.llm,
                settings_sections=services.settings_sections,
            )
        ),
        LlmAnthropicModule(
            LlmAnthropicDeps(
                llm_providers=services.llm_providers,
                llm=services.llm,
                settings_sections=services.settings_sections,
            )
        ),
        LlmModule(
            LlmDeps(
                llm_providers=services.llm_providers,
                llm=services.llm,
                settings_sections=services.settings_sections,
            )
        ),
        DebugModule(
            DebugDeps(
                llm=services.llm,
                actions=services.actions,
                tabs=services.tabs,
                context=services.context,
            )
        ),
        # -- the planner ------------------------------------------------------------------
        # The properties card registers into the detail panel, so it must come before the
        # editor builds its first one.
        TaskPropertiesModule(
            TaskPropertiesDeps(plan=plan, undo=services.undo, sections=services.inspector_sections)
        ),
        editor,
        PlanTreeModule(
            PlanTreeDeps(
                plan=plan,
                context=services.context,
                actions=services.actions,
                undo=services.undo,
                panels=services.sidebar_panels,
                parent=services.window,
                # The tree opens tasks without knowing what an editor is.
                open_task=editor.open,
            )
        ),
        # Last: its dialog is built during register() and must see every other module's
        # settings sections.
        SettingsModule(
            SettingsDeps(
                actions=services.actions,
                settings_sections=services.settings_sections,
                parent=services.window,
            )
        ),
    ]
