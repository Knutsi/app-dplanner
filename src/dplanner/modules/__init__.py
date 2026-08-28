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
    from dplanner.domain.model import Product, Step
    from dplanner.domain.ordering import Placed
    from dplanner.domain.schedule import Scheduled
    from dplanner.domain.store import ModuleFileArea
    from dplanner.framework.module import Module
    from dplanner.framework.services import AppServices
    from dplanner.modules.step_agent_instruction.prompt import PromptPart

__all__ = [
    "StorageLocation",
    "aspect_specs",
    "choose_workspace",
    "default_cli_commands",
    "default_module_formats",
    "default_modules",
]


def default_modules(services: "AppServices") -> list["Module"]:
    from dplanner.core.storage.git import find_repo_root
    from dplanner.core.storage.github import gh_authenticated, gh_path, repository_url
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
    from dplanner.modules.github.aspect import MODULE_ID as GITHUB_ID
    from dplanner.modules.github.aspect import read as github_read
    from dplanner.modules.github.module import GithubDeps, GithubModule
    from dplanner.modules.llm.module import LlmDeps, LlmModule
    from dplanner.modules.llm_anthropic.module import LlmAnthropicDeps, LlmAnthropicModule
    from dplanner.modules.llm_openai.module import LlmOpenAIDeps, LlmOpenAIModule
    from dplanner.modules.product.module import ProductDeps, ProductModule
    from dplanner.modules.progression.module import ProgressionDeps, ProgressionModule
    from dplanner.modules.project_editor.items import NodeAccent
    from dplanner.modules.project_editor.module import ProjectEditorDeps, ProjectEditorModule
    from dplanner.modules.project_repo.module import ProjectRepoDeps, ProjectRepoModule
    from dplanner.modules.project_repo.repo import checkout_for as repo_checkout_for
    from dplanner.modules.project_repo.repo import repository_for as repo_repository_for
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
    from dplanner.modules.step_handoff.module import StepHandoffDeps, StepHandoffModule
    from dplanner.modules.step_order.module import StepOrderDeps, StepOrderModule
    from dplanner.modules.step_properties.module import (
        StepPropertiesDeps,
        StepPropertiesModule,
    )
    from dplanner.modules.step_release.aspect import MODULE_ID as RELEASE_ID
    from dplanner.modules.step_release.aspect import read as release_label
    from dplanner.modules.step_release.module import StepReleaseDeps, StepReleaseModule
    from dplanner.modules.step_status.aspect import read as step_status
    from dplanner.modules.step_status.module import StepStatusDeps, StepStatusModule
    from dplanner.modules.step_ticket.module import StepTicketDeps, StepTicketModule
    from dplanner.modules.sync.module import SyncDeps, SyncModule
    from dplanner.modules.taskcenter.module import TaskCenterDeps, TaskCenterModule
    from dplanner.modules.workspace_watch.module import (
        WorkspaceWatchDeps,
        WorkspaceWatchModule,
    )
    from dplanner.modules.workspaces.module import WorkspacesDeps, WorkspacesModule
    from dplanner.theme.icons import gauge_icon, graph_icon, spec_icon

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

    def step_accent(step_id: str) -> "NodeAccent":
        """How a step looks on the canvas, translated from aspects the canvas never learns.

        A done step is muted; a release wears its label as a badge; a PR is a pill on the
        second line with its state as a tone, and a branch the small fork glyph — which is
        why the canvas subtitle skips the release and GitHub phrases below.
        """
        step = product.step(step_id)
        refs = github_read(step)
        pill = ""
        if refs is not None and refs.has_pr():
            pill = f"PR #{refs.pr_number}" if refs.pr_number is not None else "PR"
        return NodeAccent(
            muted=step_status(step) == "done",
            badge=release_label(step),
            pill_text=pill,
            pill_tone={"merged": "good", "closed": "bad"}.get(refs.pr_state, "") if refs else "",
            branch=bool(refs is not None and refs.branch),
        )

    def step_schedule(project_id: str, order: "Sequence[Placed]") -> "list[Scheduled]":
        """The order carrying days and dates: the domain's walk, over one module's numbers.

        The domain never learns where an estimate is stored — it is handed a function that
        answers for a step — and the order view never learns that estimates exist.
        """
        return schedule(order, estimated_days, start_of(product.project(project_id)))

    # The briefing's blocks come from the shared builders below the list — the same two
    # functions the CLI wires in — closed over the window's product and store here.
    def agent_prompt_parts(step_id: str) -> list["PromptPart"]:
        return _handoff_parts(product, product.step(step_id), store.files)

    def agent_prompt_sections(step_id: str) -> list["PromptPart"]:
        return _briefing_sections(product, product.step(step_id), store.files)

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
    # The probes are advisory status only; the github module makes its own checks.
    project_repo = ProjectRepoModule(
        ProjectRepoDeps(
            product=product,
            undo=services.undo,
            cards=services.detail_cards,
            is_git_repo=lambda path: find_repo_root(path) is not None,
            gh_installed=lambda: gh_path() is not None,
            gh_signed_in=gh_authenticated,
            repository_url_for=repository_url,
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
            # A node's second line: whatever the aspects have to say about that step. The
            # release and GitHub phrases are skipped because the accent already wears them
            # — the badge the label, the pill and glyph the PR and branch.
            step_aspects=lambda step_id: step_aspects(step_id, skip={RELEASE_ID, GITHUB_ID}),
            step_accent=step_accent,
            # The timeline sort reads a step's length through this seam; estimation owns it.
            days_for=estimated_days,
            # The project panel renders whatever registered a card here — the project-level
            # counterpart of the step panel's inspector_sections.
            cards=services.detail_cards,
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
            theme=services.theme,
            parent=services.window,
            files=lambda node_id: store.files(node_id, SPEC_ID),
        )
    )
    # Constructed before the list because the projects index opens the board through it.
    # Run Agent arrives as the real action's state and verb, resolved lazily so the agent
    # module's registration order does not matter; neither module knows the other's name.
    progression = ProgressionModule(
        ProgressionDeps(
            product=product,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            # Statuses and estimates through the aspects' Qt-free readers — the board
            # never learns what either is stored as.
            status_for=step_status,
            days_for=estimated_days,
            # A card reveals its step the same way an order row does.
            reveal_step=project_editor.reveal,
            agent_state=lambda ctx: services.actions.spec("agent.run").state(ctx),
            agent_run=lambda ctx: services.actions.run("agent.run", ctx),
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
                # Rows under each project — a project row itself only folds; these are
                # what opens. Each renders the Project menu: the row stands for its
                # project, and the project's verbs all live there.
                entries=(
                    ProjectEntry(
                        id="steps",
                        label="Steps",
                        open=project_editor.open,
                        icon=graph_icon,
                        menu="Project",
                        order=10,
                    ),
                    ProjectEntry(
                        id="spec",
                        label="Specs",
                        open=spec.open,
                        icon=spec_icon,
                        menu="Project",
                        order=20,
                    ),
                    ProjectEntry(
                        id="progression",
                        label="Progression",
                        open=progression.open,
                        icon=gauge_icon,
                        menu="Project",
                        order=30,
                    ),
                ),
            )
        ),
        spec,
        # Before project_editor: its Repository card must be registered when the project
        # panel is built. The builder also reads its data_format from the list.
        project_repo,
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
                product=product,
                undo=services.undo,
                sections=services.inspector_sections,
                files=store.files,
            )
        ),
        StepAgentInstructionModule(
            StepAgentInstructionDeps(
                product=product,
                undo=services.undo,
                sections=services.inspector_sections,
                actions=services.actions,
                context=services.context,
                settings_sections=services.settings_sections,
                status=services.window,
                parent=services.window,
                # Its project-level card: the standing instruction every briefing opens with.
                cards=services.detail_cards,
                files=store.files,
                # How staged assets are read at launch — bytes by workspace-relative path.
                read_asset=store.storage.read_bytes,
                prompt_parts=agent_prompt_parts,
                prompt_sections=agent_prompt_sections,
                epilogue=lambda step_id: _agent_epilogue(product.step(step_id).title),
                preamble=_agent_preamble(),
                # Where the agent runs: the project's checkout over the product's — the
                # one resolution rule, closed over step → project here.
                checkout_for=lambda step_id: repo_checkout_for(
                    product, product.project_of(step_id)
                ),
            )
        ),
        StepHandoffModule(
            StepHandoffDeps(
                product=product,
                undo=services.undo,
                sections=services.inspector_sections,
                files=store.files,
            )
        ),
        StepReleaseModule(
            StepReleaseDeps(
                product=product, undo=services.undo, sections=services.inspector_sections
            )
        ),
        # No tab: the status vocabulary is a Status submenu of checkable Step verbs.
        StepStatusModule(
            StepStatusDeps(product=product, undo=services.undo, actions=services.actions)
        ),
        GithubModule(
            GithubDeps(
                product=product,
                undo=services.undo,
                sections=services.inspector_sections,
                tasks=services.tasks,
                parent=services.window,
                # Which repository a step's refs belong to: the project's own over the
                # product's — the one resolution rule, closed over step → project here.
                repository_for=lambda step_id: repo_repository_for(
                    product, product.project_of(step_id)
                ),
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
        progression,
        AgentSkillModule(
            AgentSkillDeps(
                actions=services.actions,
                tasks=services.tasks,
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


def _module_asset_paths(
    files: "Callable[[str, str], ModuleFileArea]", node_id: str, module_id: str
) -> tuple[str, ...]:
    """A node's module files as workspace-relative paths; a never-flushed node has none."""
    from dplanner.domain.assets import assets

    try:
        area = files(node_id, module_id)
    except KeyError:
        return ()
    return tuple(f"{area.directory}/{name}" for name in assets(area))


def _handoff_parts(
    product: "Product", step: "Step", files: "Callable[[str, str], ModuleFileArea]"
) -> "list[PromptPart]":
    """The briefing's inherited blocks: handoffs become prompt parts here, and neither the
    agent module nor the handoff module learns the other's name. Both surfaces call this
    one function, so the window and the CLI cannot brief a step two ways."""
    from dplanner.modules.step_agent_instruction.prompt import PromptPart
    from dplanner.modules.step_handoff.handoff import inherited

    return [
        PromptPart(heading=h.title, body=h.note, files=h.assets)
        for h in inherited(product, step, files)
    ]


def _briefing_sections(
    product: "Product", step: "Step", files: "Callable[[str, str], ModuleFileArea]"
) -> "list[PromptPart]":
    """The step's own facts as briefing sections: what it is, why it exists, where the
    work lands. Cross-module prose, so it is worded here in the one file allowed to know
    every module's vocabulary — the agent module renders the blocks without learning what
    a description, a requirement or a PR is. An empty fact contributes no section.
    """
    from dplanner.modules.github.aspect import read as github_read
    from dplanner.modules.spec.aspect import attachment_paths, read_links
    from dplanner.modules.spec.documents import read_index
    from dplanner.modules.step_agent_instruction.prompt import PromptPart
    from dplanner.modules.step_description.aspect import MODULE_ID as DESCRIPTION_ID
    from dplanner.modules.step_description.aspect import read as description_read

    sections: list[PromptPart] = []
    description = description_read(step)
    description_files = _module_asset_paths(files, step.id, DESCRIPTION_ID)
    if description or description_files:
        sections.append(
            PromptPart(heading="Description", body=description, files=description_files)
        )
    links = read_links(step)
    if links:
        requirements = read_index(product.project_of(step.id)).requirements
        by_id = {requirement.id: requirement for requirement in requirements}
        lines: list[str] = []
        for link in links:
            requirement = by_id.get(link)
            if requirement is None:
                # Links dangle by design (unmark warns, it does not rewrite steps);
                # the briefing says so instead of pretending the link never existed.
                lines.append(f"- {link} (no longer in the spec index)")
                continue
            where = f", in {requirement.document}" if requirement.document else ""
            lines.append(f"- **{requirement.title}** ({requirement.id}{where})")
            lines += [f"  > {quoted}" for quoted in requirement.quote.splitlines()]
        sections.append(
            PromptPart(heading="Requirements this step implements", body="\n".join(lines))
        )
    figures = attachment_paths(files, step.id)
    if figures:
        sections.append(
            PromptPart(
                heading="Figures from the spec",
                body="Rendered from the specification for this step — look at them.",
                files=figures,
            )
        )
    refs = github_read(step)
    if refs is not None:
        lines = []
        if refs.branch:
            lines.append(f"Branch: {refs.branch}")
        if refs.has_pr():
            pr = f"PR #{refs.pr_number}" if refs.pr_number is not None else "PR"
            if refs.pr_title:
                pr += f" — {refs.pr_title}"
            if refs.pr_state:
                pr += f" ({refs.pr_state})"
            if refs.pr_url:
                pr += f" {refs.pr_url}"
            lines.append(pr)
        if lines:
            sections.append(PromptPart(heading="Where the work lands", body="\n".join(lines)))
    return sections


def _agent_preamble() -> str:
    """The briefing's preflight: the agent proves it can report back before it starts.

    An agent without the DPlanner skill would do the work and leave the plan blind — no
    status, no handoff — so the briefing makes the check the first move and stopping the
    honest fallback. Root prose for the same reason as the epilogue: it names another
    module's verbs.
    """
    return (
        "First, confirm you can drive DPlanner: run `dplanner skill status`. If the"
        " command is missing or the skill is not installed, STOP — do not carry out the"
        " step — and tell the developer this step needs the DPlanner skill"
        " (`dplanner skill install`)."
    )


def _agent_epilogue(step_title: str) -> str:
    """The briefing's closing words: how the agent reports back through the CLI.

    Cross-module prose — it names the status and handoff verbs — so it is written here, in
    the one file allowed to know every module's vocabulary, and handed to the agent module
    as a callback on both surfaces.
    """
    title = step_title or "Untitled step"
    return (
        "When the work is finished, record it in DPlanner:\n"
        f"- `dplanner status set '{title}' done`\n"
        f"- `dplanner handoff set '{title}' --file -` with anything later steps should"
        " know (add `--scope project` to reach the whole project;"
        f" `dplanner handoff attach '{title}' <file>` for files).\n"
        f"If you cannot finish, `dplanner status set '{title}' blocked` and say why in the"
        " handoff."
    )


def default_cli_commands() -> list["CliCommand"]:
    """Every ``dplanner <noun> <verb>``, from the same modules the window is built from.

    The headless half of the composition root. It imports each module's ``cli.py`` and
    nothing else — no ``module.py``, no Qt — which is what lets ``dplanner project list``
    start in milliseconds and run where a graphics stack does not exist.
    """
    from dplanner.cli.aspects import commands as aspect_commands
    from dplanner.cli.command import CliRegistry
    from dplanner.cli.lint import commands as lint_commands
    from dplanner.cli.skill import commands as skill_commands
    from dplanner.modules.estimation import cli as estimation_cli
    from dplanner.modules.estimation.aspect import read as estimated_days
    from dplanner.modules.github import cli as github_cli
    from dplanner.modules.product import cli as product_cli
    from dplanner.modules.progression import cli as progression_cli
    from dplanner.modules.project_editor import cli as layout_cli
    from dplanner.modules.project_repo import cli as repo_cli
    from dplanner.modules.project_repo.repo import repository_for as repo_repository_for
    from dplanner.modules.projects import cli as projects_cli
    from dplanner.modules.spec import cli as spec_cli
    from dplanner.modules.step_agent_instruction import cli as agent_cli
    from dplanner.modules.step_description import cli as description_cli
    from dplanner.modules.step_handoff import cli as handoff_cli
    from dplanner.modules.step_order import cli as order_cli
    from dplanner.modules.step_release import cli as release_cli
    from dplanner.modules.step_status import cli as status_cli
    from dplanner.modules.step_status.aspect import read as step_status
    from dplanner.modules.step_ticket import cli as ticket_cli

    specs = aspect_specs()
    commands = [
        *product_cli.commands(),
        # The step authors let `step add` author the step in the same call; the list
        # order is the report order — the same order the skill teaches authoring in.
        *projects_cli.commands(
            step_authors=[
                description_cli.step_author(),
                agent_cli.step_author(),
                estimation_cli.step_author(),
                spec_cli.step_author(),
            ]
        ),
        *repo_cli.commands(),
        *spec_cli.commands(),
        *estimation_cli.commands(),
        *ticket_cli.commands(),
        *description_cli.commands(),
        *agent_cli.commands(
            prompt_parts=_handoff_parts,
            prompt_sections=_briefing_sections,
            epilogue=lambda step: _agent_epilogue(step.title),
            preamble=_agent_preamble(),
        ),
        *status_cli.commands(),
        *release_cli.commands(),
        *handoff_cli.commands(),
        *order_cli.commands(),
        # Progression reads statuses and estimates through the aspects' Qt-free readers —
        # handed over here so no cli.py imports another module's.
        *progression_cli.commands(status_for=step_status, days_for=estimated_days),
        # The timeline sort reads a step's length through estimation's Qt-free reader —
        # handed over here so neither cli.py imports the other.
        *layout_cli.commands(days_for=estimated_days),
        # Which repository a step's refs belong to is project_repo's rule — the project's
        # own over the product's — handed over here so neither cli.py imports the other.
        *github_cli.commands(repository_for=repo_repository_for),
        *aspect_commands(specs),
        # Each module exports what "missing" means for its own aspect; the list order is
        # the report order — the graph's integrity first, then authoring, then the spec.
        *lint_commands(
            checks=[
                *projects_cli.lint_checks(),
                *description_cli.lint_checks(),
                *agent_cli.lint_checks(),
                *estimation_cli.lint_checks(),
                *spec_cli.lint_checks(),
            ]
        ),
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
    from dplanner.modules.github import aspect as github
    from dplanner.modules.spec import aspect as spec
    from dplanner.modules.step_agent_instruction import aspect as agent
    from dplanner.modules.step_description import aspect as description
    from dplanner.modules.step_handoff import aspect as handoff
    from dplanner.modules.step_release import aspect as release
    from dplanner.modules.step_status import aspect as status
    from dplanner.modules.step_ticket import aspect as ticket

    return [
        agent.SPEC,
        description.SPEC,
        estimation.SPEC,
        github.SPEC,
        handoff.SPEC,
        release.SPEC,
        spec.SPEC,
        status.SPEC,
        ticket.SPEC,
    ]


def aspect_summaries(skip: "Container[str]" = ()) -> list[Callable[["Step"], str]]:
    """Each aspect's one-phrase description of a step, for whoever renders a step row.

    ``skip`` is for a surface that already shows one of them in a column of its own — the
    order table and its Estimate column — so the phrase is not printed twice.
    """
    from dplanner.modules.estimation import aspect as estimation
    from dplanner.modules.github import aspect as github
    from dplanner.modules.spec import aspect as spec
    from dplanner.modules.step_agent_instruction import aspect as agent
    from dplanner.modules.step_description import aspect as description
    from dplanner.modules.step_handoff import aspect as handoff
    from dplanner.modules.step_release import aspect as release
    from dplanner.modules.step_status import aspect as status
    from dplanner.modules.step_ticket import aspect as ticket

    pairs = [
        (status.SPEC.id, status.summary),
        (release.SPEC.id, release.summary),
        (estimation.SPEC.id, estimation.summary),
        (ticket.SPEC.id, ticket.summary),
        (github.SPEC.id, github.summary),
        (spec.SPEC.id, spec.summary),
        (description.SPEC.id, description.summary),
        (agent.SPEC.id, agent.summary),
        (handoff.SPEC.id, handoff.summary),
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
    from dplanner.modules.project_repo import repo

    # The aspects, plus the module data that is not an aspect: the graph's node positions
    # and a project's repo association. Deriving this list from aspect_specs() alone would
    # silently omit them. A project's start date needs no entry: it rides on the estimation
    # aspect's format, which is the same module writing under the same id on another node.
    return [spec.data_format for spec in aspect_specs()] + [
        positions.DATA_FORMAT,
        repo.DATA_FORMAT,
    ]


def choose_workspace() -> StorageLocation | None:
    """Ask the user which workspace to open.

    A thin wrapper so ``app.py`` reaches the workspaces module through the composition root
    rather than into its package, and so importing this file stays free of Qt.
    """
    from dplanner.modules.workspaces.module import choose_workspace as ask

    return ask()
