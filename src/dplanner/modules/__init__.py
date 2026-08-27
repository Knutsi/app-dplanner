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
    from collections.abc import Container, Sequence

    from dplanner.cli import CliCommand
    from dplanner.domain.aspects import AspectSpec
    from dplanner.domain.model import Step
    from dplanner.domain.ordering import Placed
    from dplanner.domain.schedule import Scheduled
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
    from dplanner.domain.schedule import schedule
    from dplanner.domain.store import ProductStore
    from dplanner.modules.agent_skill.module import AgentSkillDeps, AgentSkillModule
    from dplanner.modules.appshell.module import AppShellDeps, AppShellModule
    from dplanner.modules.debug.module import DebugDeps, DebugModule
    from dplanner.modules.estimation.aspect import MODULE_ID as ESTIMATION_ID
    from dplanner.modules.estimation.aspect import read as estimated_days
    from dplanner.modules.estimation.module import EstimationDeps, EstimationModule
    from dplanner.modules.estimation.schedule import start_of
    from dplanner.modules.llm.module import LlmDeps, LlmModule
    from dplanner.modules.llm_anthropic.module import LlmAnthropicDeps, LlmAnthropicModule
    from dplanner.modules.llm_openai.module import LlmOpenAIDeps, LlmOpenAIModule
    from dplanner.modules.product.module import ProductDeps, ProductModule
    from dplanner.modules.project_editor.module import ProjectEditorDeps, ProjectEditorModule
    from dplanner.modules.projects.module import ProjectEntry, ProjectsDeps, ProjectsModule
    from dplanner.modules.settings.module import SettingsDeps, SettingsModule
    from dplanner.modules.spec.aspect import MODULE_ID as SPEC_ID
    from dplanner.modules.spec.module import SpecDeps, SpecModule
    from dplanner.modules.step_agent_instruction.module import (
        StepAgentInstructionDeps,
        StepAgentInstructionModule,
    )
    from dplanner.modules.step_description.aspect import read as description_read
    from dplanner.modules.step_description.aspect import summary as description_summary
    from dplanner.modules.step_description.module import (
        StepDescriptionDeps,
        StepDescriptionModule,
    )
    from dplanner.modules.step_order.module import StepOrderDeps, StepOrderModule
    from dplanner.modules.step_properties.module import (
        StepPropertiesDeps,
        StepPropertiesModule,
    )
    from dplanner.modules.step_ticket.module import StepTicketDeps, StepTicketModule
    from dplanner.modules.sync.module import SyncDeps, SyncModule
    from dplanner.modules.taskcenter.module import TaskCenterDeps, TaskCenterModule
    from dplanner.modules.workspace_watch.module import (
        WorkspaceWatchDeps,
        WorkspaceWatchModule,
    )
    from dplanner.modules.workspaces.module import WorkspacesDeps, WorkspacesModule
    from dplanner.theme.icons import spec_icon

    product: Product = services.document
    # The composition root knows the concrete store, exactly as it knows the concrete
    # document — modules reach a file area only through the typed callback on their Deps.
    store = services.repo
    assert isinstance(store, ProductStore)

    def skill_files() -> dict[str, str]:
        from dplanner.cli.command import CliRegistry
        from dplanner.cli.skill import generate

        registry = CliRegistry()
        registry.register_all(default_cli_commands())
        return generate(registry, aspect_specs())

    def step_aspects(step_id: str, skip: "Container[str]" = ()) -> list[str]:
        """One short phrase per aspect that has something to say about this step."""
        step = product.step(step_id)
        summaries = aspect_summaries(skip)
        return [phrase for phrase in (summary(step) for summary in summaries) if phrase]

    def step_schedule(project_id: str, order: "Sequence[Placed]") -> "list[Scheduled]":
        """The order carrying days and dates: the domain's walk, over one module's numbers.

        The domain never learns where an estimate is stored — it is handed a function that
        answers for a step — and the order view never learns that estimates exist.
        """
        return schedule(order, estimated_days, start_of(product.project(project_id)))

    # Three modules constructed before the list, because what each one hands the others
    # reads better as wiring than as ordering:
    #
    #   step_properties  anchors THE step detail panel in the window's right area
    #   project_editor   anchors the project form beside it, and opens projects into tabs
    #   projects         puts projects in the index and opens them through the editor
    #   estimation       owns the estimate, the start date and the bulk Estimates tab; the
    #                    order view hosts its bar, and its rows reveal steps on the canvas
    #
    # None of them imports any other, and the two panel modules do not even wire to each
    # other: each registers a panel and the dock decides what is on screen, so neither knows
    # the other is in the same area. Construction is side-effect-free, so ordering here is
    # about legibility; what matters at run time is that the aspect modules have registered
    # their sections before step_properties builds the panel, which is a position in the list
    # below.
    step_properties = StepPropertiesModule(
        StepPropertiesDeps(
            product=product,
            undo=services.undo,
            panels=services.panels,
            sections=services.inspector_sections,
            theme=services.theme,
        )
    )
    project_editor = ProjectEditorModule(
        ProjectEditorDeps(
            product=product,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            undo=services.undo,
            status=services.window,
            parent=services.window,
            panels=services.panels,
            theme=services.theme,
            # A node's second line: whatever the aspects have to say about that step.
            step_aspects=step_aspects,
        )
    )
    # Constructed before the list because the projects index opens Specs through it — the
    # same seam as open_project, one level down.
    spec = SpecModule(
        SpecDeps(
            product=product,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            undo=services.undo,
            parent=services.window,
            files=lambda node_id: store.files(node_id, SPEC_ID),
        )
    )
    estimation = EstimationModule(
        EstimationDeps(
            product=product,
            undo=services.undo,
            sections=services.inspector_sections,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            # A step's description, one line for the row and the prose for its tooltip.
            # Handed as answers, so the estimation module never learns where prose lives.
            step_summary=lambda step_id: description_summary(product.step(step_id)),
            describe_step=lambda step_id: description_read(product.step(step_id)),
            # An Estimates row reveals its step the same way an order row does.
            reveal_step=project_editor.reveal,
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
                # Registered before any panel exists, which is why it listens to the registry
                # rather than reading it: View ▸ Panels grows an entry as each one arrives.
                panels=services.panels,
                chrome=services.window,
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
                undo=services.undo,
                segments=services.index_segments,
                theme=services.theme,
                parent=services.window,
                # The index opens a project without knowing what an editor is.
                open_project=project_editor.open,
                # Rows under each project. The Specs entry renders the Project menu — the
                # row stands for its project, and spec.add / spec.open live there.
                entries=(
                    ProjectEntry(
                        id="spec",
                        label="Specs",
                        open=spec.open,
                        icon=spec_icon,
                        menu="Project",
                        order=10,
                    ),
                ),
            )
        ),
        spec,
        # -- the step aspects --------------------------------------------------------------
        # Each registers one tab into the step detail panel. They must come before
        # step_properties, which builds the panel from whatever has registered by then.
        estimation,
        StepTicketModule(
            StepTicketDeps(
                product=product, undo=services.undo, sections=services.inspector_sections
            )
        ),
        StepDescriptionModule(
            StepDescriptionDeps(
                product=product, undo=services.undo, sections=services.inspector_sections
            )
        ),
        StepAgentInstructionModule(
            StepAgentInstructionDeps(
                product=product, undo=services.undo, sections=services.inspector_sections
            )
        ),
        step_properties,
        project_editor,
        StepOrderModule(
            StepOrderDeps(
                product=product,
                actions=services.actions,
                context=services.context,
                tabs=services.tabs,
                parent=services.window,
                # Listing steps is one feature; showing one on a canvas is another. This is
                # the seam between them, and neither module knows the other's name.
                reveal_step=project_editor.reveal,
                # The estimate has a column of its own here, so it does not also belong in
                # the row's trailing summary. On the canvas, which has no columns, it does.
                step_aspects=lambda step_id: step_aspects(step_id, skip={ESTIMATION_ID}),
                # Days and dates, computed by the domain from what the estimation module
                # stores. Neither module knows the other's name.
                step_schedule=step_schedule,
                start_bar=estimation.create_start_bar,
            )
        ),
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
    from dplanner.modules.estimation import cli as estimation_cli
    from dplanner.modules.product import cli as product_cli
    from dplanner.modules.projects import cli as projects_cli
    from dplanner.modules.spec import cli as spec_cli
    from dplanner.modules.step_agent_instruction import cli as agent_cli
    from dplanner.modules.step_description import cli as description_cli
    from dplanner.modules.step_order import cli as order_cli
    from dplanner.modules.step_ticket import cli as ticket_cli

    specs = aspect_specs()
    commands = [
        *product_cli.commands(),
        *projects_cli.commands(),
        *spec_cli.commands(),
        *estimation_cli.commands(),
        *ticket_cli.commands(),
        *description_cli.commands(),
        *agent_cli.commands(),
        *order_cli.commands(),
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
    from dplanner.modules.estimation import aspect as estimation
    from dplanner.modules.spec import aspect as spec
    from dplanner.modules.step_agent_instruction import aspect as agent
    from dplanner.modules.step_description import aspect as description
    from dplanner.modules.step_ticket import aspect as ticket

    return [agent.SPEC, description.SPEC, estimation.SPEC, spec.SPEC, ticket.SPEC]


def aspect_summaries(skip: "Container[str]" = ()) -> list[Callable[["Step"], str]]:
    """Each aspect's one-phrase description of a step, for whoever renders a step row.

    ``skip`` is for a surface that already shows one of them in a column of its own — the
    order table and its Estimate column — so the phrase is not printed twice.
    """
    from dplanner.modules.estimation import aspect as estimation
    from dplanner.modules.spec import aspect as spec
    from dplanner.modules.step_agent_instruction import aspect as agent
    from dplanner.modules.step_description import aspect as description
    from dplanner.modules.step_ticket import aspect as ticket

    pairs = [
        (estimation.SPEC.id, estimation.summary),
        (ticket.SPEC.id, ticket.summary),
        (spec.SPEC.id, spec.summary),
        (description.SPEC.id, description.summary),
        (agent.SPEC.id, agent.summary),
    ]
    return [render for aspect_id, render in pairs if aspect_id not in skip]


def default_module_formats() -> list[ModuleDataFormat]:
    """Every module data format, for the CLI to migrate with.

    The GUI gets these from the module objects themselves (``AppBuilder`` reads
    ``data_format`` off anything that declares one). The CLI never builds those objects, so
    the same list has to be reachable without them — and it must stay complete, because a
    format missing here is data the CLI silently declines to bring forward.
    """
    from dplanner.modules.project_editor import positions

    # The aspects, plus the one module data that is not an aspect: the graph's node
    # positions. Deriving this list from aspect_specs() alone would silently omit it.
    # A project's start date needs no entry: it rides on the estimation aspect's format,
    # which is the same module writing under the same id on a different node.
    return [spec.data_format for spec in aspect_specs()] + [positions.DATA_FORMAT]


def choose_workspace() -> StorageLocation | None:
    """Ask the user which workspace to open.

    A thin wrapper so ``app.py`` reaches the workspaces module through the composition root
    rather than into its package, and so importing this file stays free of Qt.
    """
    from dplanner.modules.workspaces.module import choose_workspace as ask

    return ask()
