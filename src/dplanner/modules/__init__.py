"""Feature modules, and the composition root that wires them together.

``default_modules()`` **is** the application. Which features run, what each one may touch
(its typed ``Deps``), and how features cooperate — all of it is readable in this one file,
and nowhere else.

This is the only file allowed to import every module and :class:`AppServices`. Modules never
see the whole bundle and never import each other; when one needs something another provides,
it declares a typed callback on its own ``Deps`` and this file supplies one. So the answer to
"what is this application, and who depends on whom?" has exactly one place to look.

**Order matters.** The returned list is registration order, and it fixes status-bar widget
order, index segment order, and — the one that bites — that surfaces exist before whoever
renders them is built. Every constrained position below carries a comment saying why.

**The imports are inside the functions on purpose.** Importing this package must not load Qt,
because the CLI reaches a module's ``cli.py`` through it and has to start in milliseconds on
machines with no GUI libraries at all. The inventory is still in one place: it is the first
lines of each function instead of the first lines of the file, and
``tests/test_architecture.py`` reads them either way.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING

from dplanner.core.module_data import ModuleDataFormat
from dplanner.core.storage.locations import StorageLocation

if TYPE_CHECKING:
    from dplanner.cli import CliCommand
    from dplanner.domain.aspects import AspectSpec
    from dplanner.domain.model import Step
    from dplanner.framework.module import Module
    from dplanner.framework.services import AppServices

__all__ = [
    "StorageLocation",
    "aspect_specs",
    "choose_workspace",
    "default_cli_commands",
    "default_module_formats",
    "default_modules",
]


def default_modules(services: "AppServices") -> list["Module"]:
    from dplanner.domain.model import Product
    from dplanner.modules.agent_skill.module import AgentSkillDeps, AgentSkillModule
    from dplanner.modules.appshell.module import AppShellDeps, AppShellModule
    from dplanner.modules.debug.module import DebugDeps, DebugModule
    from dplanner.modules.llm.module import LlmDeps, LlmModule
    from dplanner.modules.llm_anthropic.module import LlmAnthropicDeps, LlmAnthropicModule
    from dplanner.modules.llm_openai.module import LlmOpenAIDeps, LlmOpenAIModule
    from dplanner.modules.product.module import ProductDeps, ProductModule
    from dplanner.modules.projects.module import ProjectsDeps, ProjectsModule
    from dplanner.modules.settings.module import SettingsDeps, SettingsModule
    from dplanner.modules.step_description.module import (
        StepDescriptionDeps,
        StepDescriptionModule,
    )
    from dplanner.modules.step_estimation.module import StepEstimationDeps, StepEstimationModule
    from dplanner.modules.step_ticket.module import StepTicketDeps, StepTicketModule
    from dplanner.modules.sync.module import SyncDeps, SyncModule
    from dplanner.modules.taskcenter.module import TaskCenterDeps, TaskCenterModule
    from dplanner.modules.workspace_watch.module import (
        WorkspaceWatchDeps,
        WorkspaceWatchModule,
    )
    from dplanner.modules.workspaces.module import WorkspacesDeps, WorkspacesModule

    product: Product = services.document

    def skill_files() -> dict[str, str]:
        from dplanner.cli.command import CliRegistry
        from dplanner.cli.skill import generate

        registry = CliRegistry()
        registry.register_all(default_cli_commands())
        return generate(registry, aspect_specs())

    def step_aspects(step_id: str) -> list[str]:
        """One short phrase per aspect that has something to say about this step."""
        step = product.step(step_id)
        return [phrase for phrase in (summary(step) for summary in aspect_summaries()) if phrase]

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
        # After sync, so a reload notice lands to the right of the workspace path.
        WorkspaceWatchModule(
            WorkspaceWatchDeps(
                repo=services.repo,
                autosave=services.autosave,
                actions=services.actions,
                switcher=services.switcher,
                status=services.window,
                parent=services.window,
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
        ProductModule(
            ProductDeps(
                product=product,
                actions=services.actions,
                context=services.context,
                tabs=services.tabs,
                undo=services.undo,
                window=services.window,
            )
        ),
        ProjectsModule(
            ProjectsDeps(
                product=product,
                actions=services.actions,
                context=services.context,
                tabs=services.tabs,
                undo=services.undo,
                segments=services.index_segments,
                parent=services.window,
                # The project tab shows what each aspect has to say about a step. It never
                # learns which aspects exist; they never learn a project tab renders them.
                step_aspects=step_aspects,
            )
        ),
        # -- the step aspects --------------------------------------------------------------
        # No surface yet: each declares data_format so the builder migrates its data when a
        # window opens an older workspace, and each contributes its verbs to the CLI.
        StepEstimationModule(StepEstimationDeps()),
        StepTicketModule(StepTicketDeps()),
        StepDescriptionModule(StepDescriptionDeps()),
        AgentSkillModule(
            AgentSkillDeps(
                actions=services.actions,
                status=services.window,
                parent=services.window,
                # The window writes exactly what `dplanner skill install` writes, from the
                # same generator over the same registry.
                skill_files=skill_files,
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


def default_cli_commands() -> list["CliCommand"]:
    """Every ``dplanner <noun> <verb>``, from the same modules the window is built from.

    The headless half of the composition root. It imports each module's ``cli.py`` and
    nothing else — no ``module.py``, no Qt — which is what lets ``dplanner project list``
    start in milliseconds and run where a graphics stack does not exist.
    """
    from dplanner.cli.aspects import commands as aspect_commands
    from dplanner.cli.command import CliRegistry
    from dplanner.cli.skill import commands as skill_commands
    from dplanner.modules.product import cli as product_cli
    from dplanner.modules.projects import cli as projects_cli
    from dplanner.modules.step_description import cli as description_cli
    from dplanner.modules.step_estimation import cli as estimation_cli
    from dplanner.modules.step_ticket import cli as ticket_cli

    specs = aspect_specs()
    commands = [
        *product_cli.commands(),
        *projects_cli.commands(),
        *estimation_cli.commands(),
        *ticket_cli.commands(),
        *description_cli.commands(),
        *aspect_commands(specs),
    ]
    # The skill describes the registry it is registered into, so the loop is closed here
    # rather than by anything going looking for a registry at run time.
    described = CliRegistry()
    described.register_all(commands)
    skill = skill_commands(specs, described)
    described.register_all(skill)
    return [*commands, *skill]


def aspect_specs() -> list["AspectSpec"]:
    """Every step aspect this build knows about.

    What ``dplanner aspect list`` prints and the generated skill describes — the entry point
    an agent uses to find out what a step can carry. Each package declares its own ``SPEC``;
    this is only the list of packages, in the order a person would read them.
    """
    from dplanner.modules.step_description import aspect as description
    from dplanner.modules.step_estimation import aspect as estimation
    from dplanner.modules.step_ticket import aspect as ticket

    return [description.SPEC, estimation.SPEC, ticket.SPEC]


def aspect_summaries() -> list[Callable[["Step"], str]]:
    """Each aspect's one-phrase description of a step, for whoever renders a step row."""
    from dplanner.modules.step_description import aspect as description
    from dplanner.modules.step_estimation import aspect as estimation
    from dplanner.modules.step_ticket import aspect as ticket

    return [estimation.summary, ticket.summary, description.summary]


def default_module_formats() -> list[ModuleDataFormat]:
    """Every module data format, for the CLI to migrate with.

    The GUI gets these from the module objects themselves (``AppBuilder`` reads
    ``data_format`` off anything that declares one). The CLI never builds those objects, so
    the same list has to be reachable without them — and it must stay complete, because a
    format missing here is data the CLI silently declines to bring forward.
    """
    return [spec.data_format for spec in aspect_specs()]


def choose_workspace() -> StorageLocation | None:
    """Ask the user which workspace to open.

    A thin wrapper so ``app.py`` reaches the workspaces module through the composition root
    rather than into its package, and so importing this file stays free of Qt.
    """
    from dplanner.modules.workspaces.module import choose_workspace as ask

    return ask()
