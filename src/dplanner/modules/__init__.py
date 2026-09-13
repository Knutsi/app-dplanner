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
from typing import TYPE_CHECKING, Any

from dplanner.core.module_data import ModuleDataFormat

if TYPE_CHECKING:
    from collections.abc import Callable, Container, Sequence

    from PySide6.QtGui import QIcon

    from dplanner.cli import CliCommand
    from dplanner.cli.checklist import MachineCheck
    from dplanner.cli.gate import TopologyGate
    from dplanner.cli.lint import LintCheck
    from dplanner.cli.report.parts import ReportSource
    from dplanner.domain.agents import AgentHarness
    from dplanner.domain.aspects import AspectSpec
    from dplanner.domain.assets import AssetSource
    from dplanner.domain.commands import Command
    from dplanner.domain.dictation import DictationProvider
    from dplanner.domain.model import Library, Project, Step
    from dplanner.domain.ordering import Placed
    from dplanner.domain.repositories import RepositoryFacts
    from dplanner.domain.schedule import Scheduled
    from dplanner.domain.scope import ScopeKind
    from dplanner.domain.store import FilesFor, ModuleFileArea
    from dplanner.framework.mime_files import Payload
    from dplanner.framework.module import Module
    from dplanner.framework.services import AppServices
    from dplanner.modules.coverage.trace import Trace
    from dplanner.modules.feature.aspect import FeatureSource
    from dplanner.modules.project_editor.clipboard import PastePolicy
    from dplanner.modules.spec.source_kind import DocumentSourceKind
    from dplanner.modules.spec_confluence.module import SecretStore
    from dplanner.modules.step_agent_instruction.prompt import Briefing, PromptPart
    from dplanner.modules.sync.service import Publication
    from dplanner.theme.providers import ThemeProvider

__all__ = [
    "agent_harnesses",
    "aspect_specs",
    "default_cli_commands",
    "default_module_formats",
    "default_modules",
    "dictation_providers",
    "theme_providers",
]


def default_modules(services: "AppServices") -> list["Module"]:
    from pathlib import Path

    from dplanner.core.config_dir import config_dir
    from dplanner.core.storage.git import GitStorage
    from dplanner.core.storage.github import GitHubStorage
    from dplanner.core.storage.locations import find_repo_root, origin_url, repo_storage
    from dplanner.core.storage.provider import StorageError, VersionedStorage
    from dplanner.domain.commands import (
        Command,
        CompositeCommand,
        EditTextCommand,
        SetModuleDataCommand,
    )
    from dplanner.domain.model import Library, Project, TextEdit
    from dplanner.domain.relocate import move_project
    from dplanner.domain.repositories import RepositoryFacts, repository_facts
    from dplanner.domain.schedule import format_days, schedule
    from dplanner.domain.scope import gatherers
    from dplanner.domain.store import LibraryStore
    from dplanner.framework.aspect_bar import AspectTemplate
    from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri
    from dplanner.modules.appearance.module import AppearanceDeps, AppearanceModule
    from dplanner.modules.appshell.module import AppShellDeps, AppShellModule
    from dplanner.modules.checklist.module import ChecklistDeps, ChecklistModule
    from dplanner.modules.coverage.activity import CoverageDeps
    from dplanner.modules.coverage.module import CoverageModule
    from dplanner.modules.debug.module import DebugDeps, DebugModule
    from dplanner.modules.dictation.module import DictationDeps, DictationModule
    from dplanner.modules.docs.module import DocsCompiledModule, DocsDeps, DocsModule
    from dplanner.modules.estimation.aspect import MODULE_ID as ESTIMATION_ID
    from dplanner.modules.estimation.aspect import read as estimated_days
    from dplanner.modules.estimation.aspect import read_history as estimate_history
    from dplanner.modules.estimation.aspect import write as estimate_write
    from dplanner.modules.estimation.module import EstimationDeps, EstimationModule
    from dplanner.modules.estimation.schedule import start_of, write_start
    from dplanner.modules.feature.aspect import MODULE_ID as FEATURE_ID
    from dplanner.modules.feature.aspect import is_feature
    from dplanner.modules.feature.aspect import read as feature_read
    from dplanner.modules.feature.module import FeatureDeps, FeatureModule
    from dplanner.modules.github.aspect import pr_label
    from dplanner.modules.github.aspect import read as github_read
    from dplanner.modules.github.module import GithubDeps, GithubModule
    from dplanner.modules.install.module import InstallDeps, InstallModule
    from dplanner.modules.library.module import LibraryDeps, LibraryModule
    from dplanner.modules.library_watch.module import LibraryWatchDeps, LibraryWatchModule
    from dplanner.modules.llm.module import LlmDeps, LlmModule
    from dplanner.modules.llm_anthropic.module import LlmAnthropicDeps, LlmAnthropicModule
    from dplanner.modules.llm_openai.module import LlmOpenAIDeps, LlmOpenAIModule
    from dplanner.modules.notes.module import NotesDeps, NotesModule
    from dplanner.modules.problems.module import ProblemsDeps, ProblemsModule
    from dplanner.modules.progression.module import ProgressionDeps, ProgressionModule
    from dplanner.modules.project_assets.module import (
        ProjectAssetsDeps,
        ProjectAssetsModule,
    )
    from dplanner.modules.project_editor.module import ProjectEditorDeps, ProjectEditorModule
    from dplanner.modules.project_editor.renderers import NodeAccent
    from dplanner.modules.project_editor.side_panel import SidePanel
    from dplanner.modules.projects.module import ProjectEntry, ProjectsDeps, ProjectsModule
    from dplanner.modules.projects.repos import (
        LogEntry,
        PullRequest,
        RepoLog,
        RepositoryServices,
    )
    from dplanner.modules.reopen_tabs.module import ReopenTabsDeps, ReopenTabsModule
    from dplanner.modules.reporting.module import ReportingDeps, ReportingModule
    from dplanner.modules.settings.module import SettingsDeps, SettingsModule
    from dplanner.modules.spec.aspect import MODULE_ID as SPEC_ID
    from dplanner.modules.spec.cli import digest_of as spec_digest_of
    from dplanner.modules.spec.cli import document_names as spec_document_names
    from dplanner.modules.spec.module import SpecDeps, SpecModule
    from dplanner.modules.spec.module import open_url as open_in_browser
    from dplanner.modules.spec_confluence.module import SpecConfluenceDeps, SpecConfluenceModule
    from dplanner.modules.spec_folder.module import SpecFolderKind
    from dplanner.modules.spec_git.module import SPEC_GIT_CACHE, SpecGitDeps, SpecGitKind
    from dplanner.modules.step_agent_instruction.aspect import MODULE_ID as AGENT_INSTRUCTION_ID
    from dplanner.modules.step_agent_instruction.aspect import enabled as agent_enabled
    from dplanner.modules.step_agent_instruction.aspect import read as agent_instruction_read
    from dplanner.modules.step_agent_instruction.aspect import (
        separate_instruction as agent_separate,
    )
    from dplanner.modules.step_agent_instruction.aspect import write_state as agent_write_state
    from dplanner.modules.step_agent_instruction.module import (
        RUN_MENU_ID,
        StepAgentInstructionDeps,
        StepAgentInstructionModule,
    )
    from dplanner.modules.step_agent_run.aspect import read as agent_run_state
    from dplanner.modules.step_agent_run.module import StepAgentRunDeps, StepAgentRunModule
    from dplanner.modules.step_agent_run.usage import summary as usage_words
    from dplanner.modules.step_check.aspect import read as check_read
    from dplanner.modules.step_check.module import StepCheckDeps, StepCheckModule
    from dplanner.modules.step_description.aspect import read as description_read
    from dplanner.modules.step_description.aspect import summary as description_summary
    from dplanner.modules.step_description.module import (
        StepDescriptionDeps,
        StepDescriptionModule,
    )
    from dplanner.modules.step_description.section import SeparateInstructionLink
    from dplanner.modules.step_milestone.aspect import read as milestone_read
    from dplanner.modules.step_milestone.module import StepMilestoneDeps, StepMilestoneModule
    from dplanner.modules.step_order.module import StepOrderDeps, StepOrderModule
    from dplanner.modules.step_properties.module import (
        StepPropertiesDeps,
        StepPropertiesModule,
    )
    from dplanner.modules.step_status.aspect import read as step_status
    from dplanner.modules.step_status.aspect import record_started
    from dplanner.modules.step_status.module import StepStatusDeps, StepStatusModule
    from dplanner.modules.step_ticket.module import StepTicketDeps, StepTicketModule
    from dplanner.modules.sync.module import SyncDeps, SyncModule
    from dplanner.modules.taskcenter.module import TaskCenterDeps, TaskCenterModule
    from dplanner.modules.testing.aspect import read as tests_read
    from dplanner.modules.testing.module import TestsDeps, TestsModule
    from dplanner.modules.time_estimates.module import (
        ProgressHistoryModule,
        TimeEstimatesDeps,
        TimeEstimatesModule,
    )
    from dplanner.theme.icons import (
        clock_icon,
        coverage_icon,
        gauge_icon,
        graph_icon,
        image_icon,
        list_icon,
        problem_icon,
        spec_icon,
    )

    library: Library = services.document
    # The composition root knows the concrete store, exactly as it knows the concrete
    # document — modules reach a file area only through the typed callback on their Deps.
    store = services.repo
    assert isinstance(store, LibraryStore)

    def project_dir_of(step_id: str) -> "Path":
        return store.project_dir(library.project_of(step_id).id)

    def facts_of(project_id: str) -> RepositoryFacts:
        """Both repositories of a project — where the plan lives, which code it plans,
        where that code is here — the one derivation every seam below reads."""
        return repository_facts(
            library.project(project_id),
            store.project_dir(project_id),
            store.checkout_of(project_id),
        )

    def facts_for(node_id: str) -> RepositoryFacts:
        """The facts for a step — or for a project named directly, which is what a run
        with no step (the Problems panel's) has to ask about."""
        node = library.node(node_id)
        return facts_of(node.id if isinstance(node, Project) else library.project_of(node_id).id)

    def repository_for(step_id: str) -> str:
        """Which repository a step's GitHub refs belong to: the code repository the
        project records, else — the older shape, a plan kept beside its code — the plan's
        own origin. Git's answer either way; nothing stored can disagree with it."""
        facts = facts_for(step_id)
        return facts.repository or facts.plan_remote

    # A checkout recorded for a project — by the Project dialog, or by an agent's first
    # `dplanner` call from the code and adopted through the library file — is what turns
    # Run Agent from greyed to runnable, and nothing in the context graph changed.
    store.checkout_changed.connect(lambda _project_id: services.context.refresh())

    # -- git and GitHub for the project surfaces ----------------------------------------
    # The Project dialog, the Repositories card, Open Projects and Move Plan reach both
    # repositories through this one bundle; the root names the providers (rule 8) and
    # the github module's gh door (rule 5) so the projects module names neither.

    def plan_roots() -> list[Path]:
        roots: list[Path] = []
        for project in library.projects:
            root = find_repo_root(store.project_dir(project.id))
            if root is not None and root not in roots:
                roots.append(root)
        return roots

    def pr_steps(project_id: str) -> dict[int, str]:
        from dplanner.modules.github.aspect import read as github_read

        named: dict[int, str] = {}
        for step in library.project(project_id).steps:
            refs = github_read(step)
            if refs is not None and refs.pr_number is not None:
                named[refs.pr_number] = f"{_step_key(step)} {step.title}".strip()
        return named

    def history_for(root: Path, scope: str, limit: int) -> RepoLog:
        storage = repo_storage(root, (scope,) if scope else ())
        if not isinstance(storage, VersionedStorage):
            raise StorageError(f"{root} has no history")
        return RepoLog(
            branch=storage.current_branch(),
            entries=tuple(
                LogEntry(id=rev.id, subject=rev.message, author=rev.author, when=rev.when)
                for rev in storage.history(limit)
            ),
        )

    def gh_refusal() -> str | None:
        from dplanner.modules.github.gh import gh_refusal as refusal

        return refusal(check_auth=True)

    def open_prs(remote: str) -> list[PullRequest]:
        from dplanner.modules.github.gh import GhError, list_prs, parse_repo

        repo = parse_repo(remote)
        if repo is None:
            return []
        try:
            rows = list_prs(repo)
        except GhError as error:
            raise StorageError(str(error)) from error
        return [
            PullRequest(number=row.number, title=row.title, head_ref=row.head_ref, url=row.url)
            for row in rows
            if row.state == "open"
        ]

    def publish(root: Path, name: str) -> str:
        storage = repo_storage(root)
        assert isinstance(storage, GitStorage)
        storage.commit("Start the plan repository")  # gh needs a commit to push.
        GitHubStorage.publish(storage, name)
        return origin_url(root)

    def create_repository(name: str, dest: Path) -> str:
        GitHubStorage.create(name, dest)
        return origin_url(dest)

    def connect_project(directory: Path, checkout: Path | None) -> Project:
        from dplanner.modules.library.membership import LIBRARY_ORIGIN

        project = store.attach(directory, checkout)
        library.add_child(library.id, project, origin=LIBRARY_ORIGIN)
        return project

    repos = RepositoryServices(
        facts_of=facts_of,
        project_dir=store.project_dir,
        set_checkout=store.set_checkout,
        checkout_changed=store.checkout_changed,
        plan_roots=plan_roots,
        pr_steps=pr_steps,
        history_for=history_for,
        gh_refusal=gh_refusal,
        list_repositories=GitHubStorage.list_repositories,
        clone=lambda repo, dest: (GitHubStorage.clone(repo, dest), None)[1],
        publish=publish,
        create_repository=create_repository,
        open_prs=open_prs,
        move_project=lambda project_id, target, init: move_project(
            store, project_id, target, init_repo=init
        ),
    )

    def read_absolute(path: str) -> bytes | None:
        """Asset bytes by absolute path — module file areas hand those out now."""
        file = Path(path)
        return file.read_bytes() if file.is_file() else None

    def focused_project(context: object) -> str | None:
        """The project the user is in: the focused project, else the focused step's."""
        from dplanner.framework.context import Context

        assert isinstance(context, Context)
        project_id = context.focus_entity("project")
        if project_id is not None and library.has(project_id):
            return project_id
        step_id = context.focus_entity("step")
        if step_id is not None and library.has(step_id):
            return library.project_of(step_id).id
        return None

    def projects_in(group: object) -> list[str]:
        """The titles a repository group covers — for the diff picker and quit dialog."""
        return [
            project.title or project.folder_name
            for project in library.projects
            if store.repo_for(project.id) is group
        ]

    def skill_files() -> dict[str, str]:
        from dplanner.cli.command import CliRegistry
        from dplanner.cli.skill import generate

        registry = CliRegistry()
        registry.register_all(default_cli_commands())
        return generate(registry, aspect_specs())

    def step_aspects(step_id: str, skip: "Container[str]" = ()) -> list[str]:
        """One short phrase per aspect that has something to say about this step."""
        step = library.step(step_id)
        summaries = aspect_summaries(skip)
        return [phrase for phrase in (summary(step) for summary in summaries) if phrase]

    def milestone_stats(project: "Project") -> dict[str, str]:
        return _milestone_stats(library, project)

    def milestone_colors(project: "Project") -> dict[str, str]:
        return _milestone_colors(library, project)

    def milestone_color(step_id: str) -> str:
        """One milestone's shade, for a surface that draws a row at a time. A surface that
        draws many at once takes the whole dict instead — this deals the project each call."""
        if not library.has(step_id):
            return ""
        return milestone_colors(library.project_of(step_id)).get(step_id, "")

    def milestone_badge(step_id: str) -> "QIcon | None":
        """A milestone's key as a badge in its own shade, or None for a step that is not one.

        The one place a milestone's key and its colour are painted together for a surface
        that is not a table; the order table builds the same badge from the same two facts.
        """
        from dplanner.theme.icons import key_badge_icon

        if not library.has(step_id):
            return None
        step = library.step(step_id)
        if not milestone_read(step):
            return None
        return key_badge_icon(_step_key(step), milestone_color(step_id))

    def milestone_palette(project_id: str) -> str:
        """Which colour map a project's milestones are shaded from."""
        from dplanner.modules.time_estimates.schedule import read_palette

        if not library.has(project_id):
            return ""
        return read_palette(library.project(project_id)).id

    def set_milestone_palette(project_id: str, palette_id: str) -> None:
        """The same undoable write the Time tab's picker and ``schedule palette`` make —
        one choice, three ways in, so the window and the published report cannot disagree."""
        from dplanner.modules.time_estimates.schedule import MODULE_ID as TIME_ID
        from dplanner.modules.time_estimates.schedule import write_project

        if not library.has(project_id):
            return
        project = library.project(project_id)
        services.undo.push(
            SetModuleDataCommand(
                project_id,
                TIME_ID,
                write_project(project, palette_id=palette_id),
                label="Milestone Palette",
            )
        )

    def watch_milestone_palette(restate: "Callable[[], None]") -> None:
        """Restate the menu's ticks when a project's stored map changes underneath — the
        Time tab's picker, an undo, or a terminal's ``dplanner schedule palette`` adopted
        from disk. One entry of one node, so the guard is the module id."""
        from dplanner.modules.time_estimates.schedule import MODULE_ID as TIME_ID

        library.module_data_changed.connect(
            lambda _node_id, module_id, _origin: restate() if module_id == TIME_ID else None
        )

    def milestone_shade(step_id: str) -> tuple[str, str]:
        """A milestone's shade and the sentence for it: *2nd of 4 · Viridis*.

        The words are what make a swatch teach rather than decorate — a colour means "this
        far along the roadmap", and the tooltip is where that is said once (DESIGN.md's
        *Words*) instead of as a line under every field.
        """
        from dplanner.modules.time_estimates.schedule import read_palette

        if not library.has(step_id):
            return "", ""
        project = library.project_of(step_id)
        colors = milestone_colors(project)
        color = colors.get(step_id, "")
        if not color:
            return "", ""
        place = list(colors).index(step_id) + 1
        return color, f"{_ordinal(place)} of {len(colors)} · {read_palette(project).name}"

    def step_type_icons(step: "Step") -> tuple[str, ...]:
        return _step_type_icons(step)

    def set_separate_instruction(step_id: str, separate: bool) -> None:
        """The Description block's checkbox, translated into the agent aspect's writes.

        Unchecking merges back into the description — the separate text is dropped and
        the mark stays — as one undo step, so Ctrl+Z restores text and flag together.
        """
        if separate:
            services.undo.push(
                SetModuleDataCommand(
                    step_id,
                    AGENT_INSTRUCTION_ID,
                    agent_write_state(True, separate=True),
                    label="Separate Agent Instruction",
                )
            )
            return
        current = agent_instruction_read(library.step(step_id))
        mark: Command = SetModuleDataCommand(
            step_id,
            AGENT_INSTRUCTION_ID,
            agent_write_state(True),
            label="Use Description as Instructions",
        )
        if not current:
            services.undo.push(mark)
            return
        services.undo.push(
            CompositeCommand(
                "Use Description as Instructions",
                [
                    EditTextCommand(
                        TextEdit(step_id, AGENT_INSTRUCTION_ID, 0, current, ""),
                        label="Set Agent Instruction",
                    ),
                    mark,
                ],
            )
        )

    def step_accents(project_id: str) -> "dict[str, NodeAccent]":
        """How every step of a project looks on the canvas — one call per canvas sync, so
        the schedule behind the milestone stats and the project's colour deal are each
        walked once for all of them."""
        project = library.project(project_id)
        stats = milestone_stats(project)
        colors = milestone_colors(project)
        # The settled reading, never a fresh lint pass: the checks are super-linear in the
        # size of a plan (66 ms at 300 steps) and this runs on every canvas sync.
        flagged = problems.flagged(project_id)
        return {
            step.id: step_accent(
                step,
                stats.get(step.id, ""),
                colors.get(step.id, ""),
                flagged=step.id in flagged,
            )
            for step in project.steps
        }

    def step_accent(
        step: "Step",
        milestone_stat: str,
        milestone_color: str = "",
        *,
        flagged: bool = False,
    ) -> "NodeAccent":
        """How a step looks on the canvas, translated from aspects the canvas never learns.


        A done step is muted with a green body — finished work recedes into a colour the
        eye can skip; the spine down the card's left carries the step's key and is shaded
        by status — busy for in-progress, bad for blocked, good for done, quiet otherwise;
        a milestone is a purple-highlighted node wearing its label as a badge, a tag
        medallion and the schedule's accumulated days and date as its stat (done outranks
        it on the body — a shipped milestone reads finished, and the tag still says what
        it was); an agent instruction is the spark medallion; a PR is a pill with its
        state as a tone and a branch the fork glyph; a live agent run is the chip on the
        bottom edge; a plain step's stat is its own estimate. The card says nothing in
        words beyond its title and its key: every aspect it wears is one of these, never
        a phrase.
        """
        refs = github_read(step)

        pill = ""
        if refs is not None and refs.has_pr():
            pill = pr_label(refs)
        chip_text, chip_tone = {
            "launched": ("launched", "info"),
            "working": ("working", "info"),
            "plan-for-review": ("plan ready", "attention"),
            "pending-approval": ("needs approval", "attention"),
            "needs-input": ("needs input", "attention"),
        }.get(agent_run_state(step), ("", ""))
        status = step_status(step)
        milestone = milestone_read(step)
        if milestone:
            stat = milestone_stat
        else:
            days = estimated_days(step)
            stat = format_days(days) if days is not None else ""
        return NodeAccent(
            muted=status == "done",
            badge=milestone,
            pill_text=pill,
            pill_tone={"merged": "good", "closed": "bad"}.get(refs.pr_state, "") if refs else "",
            branch=bool(refs is not None and refs.branch),
            key_text=_step_key(step),
            spine_tone={"in-progress": "busy", "blocked": "bad", "done": "good"}.get(status, ""),
            chip_text=chip_text,
            chip_tone=chip_tone,
            # Done outranks a kind, and a milestone outranks a feature: the coarser claim
            # wins the body, and the medallion still says what the node also is.
            body_tone=(
                "good"
                if status == "done"
                else "highlight"
                if milestone
                else "feature"
                if is_feature(step)
                else ""
            ),
            # A milestone recolours the kind it is rather than gaining a second mark: the
            # body, the badge and the tag medallion all take its shade of the project's map.
            tone_color=milestone_color if milestone else "",
            icons=step_type_icons(step),
            # Something in the plan is wrong about this step. The canvas draws the
            # squiggle; what is wrong is the Problems panel's to say.
            flagged=flagged,
            stat_text=stat,
            stat_strong=bool(milestone),
        )

    def step_schedule(project_id: str, order: "Sequence[Placed]") -> "list[Scheduled]":
        """The order carrying days and dates: the domain's walk, over one module's numbers.

        The domain never learns where an estimate is stored — it is handed a function that
        answers for a step — and the order view never learns that estimates exist.
        """
        return schedule(order, estimated_days, start_of(library.project(project_id)))

    # The one briefing both the window and the CLI assemble from — see _default_briefing.
    briefing = _default_briefing()

    # Three modules constructed before the list, because what each one hands the others
    # reads better as wiring than as ordering:
    #
    #   step_properties  anchors THE step detail panel in the window's right area
    #   project_editor   anchors the project form beside it, and opens projects into tabs
    #   projects         puts projects in the index and opens them through the editor
    #   estimation       owns the estimate, the start date and the bulk Estimates tab; the
    #                    order view hosts its bar
    #
    # None of them imports any other, and the two panel modules do not even wire to each
    # other: each registers a panel and the dock decides what is on screen, so neither knows
    # the other is in the same area. Construction is side-effect-free, so ordering here is
    # about legibility; what matters at run time is that the aspect modules have registered
    # their sections before step_properties builds the panel, which is a position in the list
    # below.
    step_properties = StepPropertiesModule(
        StepPropertiesDeps(
            # The templates the bar's dropdown offers: what a step *amounts to*, as the set
            # of Type toggles that are on — picking one moves every toggle to match, and a
            # step carrying exactly that set wears its name. Step is the catch-all: any
            # combination no other template names is still a step. Collectors carry no
            # estimate of their own; an agent step gets what an agent reports back
            # through. The selected one's glyph wears its body tone: violet the milestone,
            # teal the feature, the agent-run chip's blue for an agent step; Step and Check
            # keep the plain ink. Wired, never inferred, like the scope kinds.
            templates=(
                AspectTemplate(
                    "Step",
                    frozenset({"estimate.toggle", "description.toggle"}),
                    # A glyph like every other, so the face's icon slot is never empty:
                    # one that appeared only for the named kinds would resize the face as
                    # the step changed, and a face that reports what is on keeps its size.
                    glyph="step",
                    catch_all=True,
                ),
                AspectTemplate(
                    "Milestone",
                    frozenset({"milestone.toggle", "description.toggle"}),
                    tone="highlight",
                    glyph="tag",
                ),
                AspectTemplate(
                    "Feature",
                    frozenset({"feature.toggle", "description.toggle"}),
                    tone="feature",
                    glyph="layers",
                ),
                AspectTemplate(
                    "Agent",
                    frozenset({"agent.toggle", "description.toggle", "estimate.toggle"}),
                    tone="info",
                    glyph="spark",
                ),
                AspectTemplate(
                    "Check", frozenset({"check.toggle", "description.toggle"}), glyph="shield"
                ),
            ),
            library=library,
            undo=services.undo,
            panels=services.panels,
            actions=services.actions,
            parent=services.window,
            sections=services.inspector_sections,
            details=services.step_details,
            theme=services.theme,
        )
    )

    def place_feature_step(project_id: str, title: str, marker: dict[str, Any]) -> str:
        """A feature step born where nobody pointed — the Specs tab's *New feature step…*.

        It arrives as the *Feature* template: the marker, and the estimate opted out, since
        a collector carries no estimate of its own — the set written here and the template's
        set are the same fact; change one, change the other. Where it lands is the graph
        editor's answer (``placement.free_spot``), so nothing is born on top of a card
        somebody placed, and it is one undo entry like every other placed step.
        """
        from dplanner.modules.project_editor.placement import free_spot

        return project_editor.create_step(
            project_id,
            title,
            at=free_spot(library, library.project(project_id)),
            carrying=lambda step: [
                SetModuleDataCommand(step.id, FEATURE_ID, marker),
                SetModuleDataCommand(step.id, ESTIMATION_ID, estimate_write(None, on=False)),
            ],
            label="New Feature",
        ).id

    # Constructed before the list because the Specs tab cites a selection into it — the
    # feature side of one seam.
    feature = FeatureModule(
        FeatureDeps(
            library=library,
            undo=services.undo,
            actions=services.actions,
            sections=services.inspector_sections,
            parent=services.window,
            documents_of=lambda project_id: spec_document_names(library.project(project_id)),
            digest_of=lambda project_id, name: spec_digest_of(library.project(project_id), name),
            # Births a feature step somewhere free on the graph; the editor is constructed
            # below, so the call is what resolves it, not the reference.
            place_step=lambda project_id, title, marker: place_feature_step(
                project_id, title, marker
            ),
        )
    )

    # Constructed before the graph editor because the editor stands its panel beside the
    # canvas. What it shows is the lint registry — the very list `dplanner project lint`
    # runs — so the window and the terminal cannot disagree about what is wrong with a plan.
    problems = ProblemsModule(
        ProblemsDeps(
            library=library,
            actions=services.actions,
            files=store.files,
            checks=_lint_checks,
            debounce=services.debounce,
            parent=services.window,
            facts_of=facts_of,
            key_of=_step_key,
            # Handing the problems to an agent is the agent module's — resolved lazily,
            # since it is constructed further down and neither knows the other's name.
            fix_profiles=lambda: agent_instruction.problem_profiles(),
            fix=lambda project_id, findings, profile: agent_instruction.fix_problems(
                project_id,
                [(row.check, row.subject, row.message) for row in findings],
                profile,
            ),
        )
    )

    project_editor = ProjectEditorModule(
        ProjectEditorDeps(
            library=library,
            debounce=services.debounce,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            undo=services.undo,
            status=services.window,
            parent=services.window,
            panels=services.panels,
            theme=services.theme,
            files=store.files,
            file_modules=tuple(source.id for source in _asset_sources()),
            paste_policies=_paste_policies(),
            step_accents=step_accents,
            accents_changed=problems.findings.flagged_changed,
            # The timeline sort reads a step's length through this seam; estimation owns it.
            days_for=estimated_days,
            # The project panel renders whatever registered a card here — the project-level
            # counterpart of the step panel's inspector_sections.
            cards=services.detail_cards,
            # What stands beside the canvas: what is wrong with this plan, where it is
            # fixed. The editor never learns whose widget it is — only that it may carry
            # a reading for the button that opens it.
            side_panel=SidePanel("Problems", problem_icon, problems.create_panel),
        )
    )

    # Constructed before the list because the projects index opens it and the Specs tab
    # jumps into it. Its picture is every module's Qt-free half read once (_coverage_trace);
    # the surfaces a double-click reaches arrive as callables, and the Specs tab's is
    # resolved lazily because the two modules point at each other.
    def _step_passages(step_id: str) -> list[tuple[str, str]]:
        """The passages a step reaches: its own, or its gathering features'."""
        if not library.has(step_id):
            return []
        step = library.step(step_id)
        project = library.project_of(step_id)
        holders = [step] if is_feature(step) else []
        if not holders:
            owners = gatherers(
                library,
                project,
                carried_by=is_feature,
                stops_at=lambda other: is_feature(other) or bool(milestone_read(other)),
            ).get(step_id, ())
            holders = [owned for owner in owners if (owned := project.step(owner)) is not None]
        return [
            (source.document, source.quote)
            for holder in holders
            for source in feature_read(holder) or ()
            if source.quote
        ]

    coverage = CoverageModule(
        CoverageDeps(
            library=library,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            debounce=services.debounce,
            files=store.files,
            trace_of=_coverage_trace,
            parent=services.window,
            show_passages=lambda *args: spec.show_passages(*args),
            open_docs=lambda _project_id, step_id: services.actions.run(
                "docs.open_step",
                Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step_id)),)}),
            ),
            feature_of=lambda step_id: (
                step_id if library.has(step_id) and is_feature(library.step(step_id)) else None
            ),
            is_milestone=lambda step_id: (
                bool(milestone_read(library.step(step_id))) if library.has(step_id) else False
            ),
            tests_of=lambda step_id: (
                [test.id for test in tests_read(library.step(step_id))]
                if library.has(step_id)
                else []
            ),
            passages_of=_step_passages,
        )
    )

    # Constructed before spec: it owns the two Confluence document source kinds the Specs
    # tab runs, and the credential's four doors are the keychain's, handed over as
    # callables so a test can hand in a dict instead.
    confluence = SpecConfluenceModule(
        SpecConfluenceDeps(
            parent=services.window,
            tasks=services.tasks,
            settings_sections=services.settings_sections,
            secrets=_keychain(),
            open_url=open_in_browser,
        )
    )
    # Constructed before the list because the projects index opens Specs through it — the
    # same seam as open_project, one level down. The document source kinds it runs are
    # named here — ``_source_kinds`` — and nowhere else; a test hands in a fake through
    # the same function.
    # Kinds, not modules: they register nothing (the spec module mints the + menu's
    # entries from the kinds it is handed), so there is no `register()` for the list to
    # call. The git cache is named here and nowhere deeper — no feature module reaches
    # `config_dir`, the same rule the topology gate's record path follows.
    spec_folder = SpecFolderKind()
    spec_git = SpecGitKind(
        SpecGitDeps(tasks=services.tasks, cache_root=config_dir() / SPEC_GIT_CACHE)
    )
    spec = SpecModule(
        SpecDeps(
            dictation=services.dictation,
            library=library,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            undo=services.undo,
            theme=services.theme,
            parent=services.window,
            files=lambda node_id: store.files(node_id, SPEC_ID),
            details=services.step_details,
            tasks=services.tasks,
            debounce=services.debounce,
            rename_references=_rename_spec_references,
            kinds=_source_kinds(spec_folder, spec_git, confluence.page, confluence.folder),
            passages_of=lambda project_id, document: [
                source.quote
                for step in library.project(project_id).steps
                for source in feature_read(step) or ()
                if source.document == document and source.quote
            ],
            cite=feature.cite_passage,
            open_coverage=coverage.show_passage,
        )
    )
    # Constructed before the list because the projects index opens the board through it.
    # Run Agent arrives as the real action's state and verb, resolved lazily so the agent
    # module's registration order does not matter; neither module knows the other's name.
    progression = ProgressionModule(
        ProgressionDeps(
            library=library,
            debounce=services.debounce,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            # The statuses through the status aspect's Qt-free reader — the board never
            # learns what one is stored as.
            status_for=step_status,
            agent_state=lambda ctx: services.actions.spec("agent.run").state(ctx),
            # The Run Agents button drops the Step menu's own Run Agent child down — the
            # profiles, then Manage Agent Profiles… — filled as it opens, never a copy.
            agent_menu=lambda menu: services.actions.data_menu(RUN_MENU_ID).fill(menu),
            # A milestone on the board leads with its key in its own shade: a lane already
            # says where the work stands, so the one colour that is not a status says what
            # the work is leading to.
            milestone_badge=milestone_badge,
        )
    )
    estimation = EstimationModule(
        EstimationDeps(
            library=library,
            undo=services.undo,
            details=services.step_details,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            # A step's description, one line for the row and the prose for its tooltip.
            # Handed as answers, so the estimation module never learns where prose lives.
            step_summary=lambda step_id: description_summary(library.step(step_id)),
            describe_step=lambda step_id: description_read(library.step(step_id)),
        )
    )
    # Constructed before the list because the Docs folder carries its Implementation notes
    # row; the key rule is the root's, handed over like every row's.
    notes = NotesModule(
        NotesDeps(
            dictation=services.dictation,
            library=library,
            undo=services.undo,
            debounce=services.debounce,
            context=services.context,
            tabs=services.tabs,
            step_key=_step_key,
        )
    )
    # Constructed before the list because the projects index opens the matrix through it.
    time_estimates = TimeEstimatesModule(
        TimeEstimatesDeps(
            library=library,
            debounce=services.debounce,
            undo=services.undo,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            # Estimates, agent-ness and the start date through the owners' Qt-free
            # readers — the matrix never learns what any of them is stored as.
            days_for=estimated_days,
            is_agent=agent_enabled,
            milestone_label=milestone_read,
            # What "landed" means: the status aspect's word, the progression board's seam.
            status_for=step_status,
            # What each estimate was before, and the key a row prints: the change report
            # behind the chart's delta.
            estimate_history=estimate_history,
            step_key=_step_key,
            start_of=lambda project_id: start_of(library.project(project_id)),
            # Clicking the calendar re-dates the plan: one undoable write of the
            # estimation module's own entry, composed here so neither module imports
            # the other.
            set_start=lambda project_id, when: services.undo.push(
                SetModuleDataCommand(
                    project_id, ESTIMATION_ID, write_start(when), label="Set Start Date"
                )
            ),
            # The banner's *Estimate missing*: the Estimates tab, on the unsized rows.
            estimate_missing=lambda project_id: estimation.open_for_steps(
                project_id, unestimated=True
            ),
            parent=services.window,
        )
    )
    # Constructed before the list for the same reason — its index row opens the tab. The
    # sources tuple is the same one the CLI reports read (`_asset_sources`), so the tab,
    # the picker and `dplanner asset list` can never disagree about what a project holds.
    asset_sources = _asset_sources()
    project_assets = ProjectAssetsModule(
        ProjectAssetsDeps(
            library=library,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            undo=services.undo,
            parent=services.window,
            debounce=services.debounce,
            files=store.files,
            sources=asset_sources,
        )
    )

    # Constructed before the list because Save publishes through it: the sync module is
    # handed `publication_for` and never learns this module's name. The sources are the
    # tuple `dplanner report` reads (`_report_sources`), so the page a Save writes and the
    # page the terminal writes are one page.
    reporting = ReportingModule(
        ReportingDeps(
            library=library,
            actions=services.actions,
            context=services.context,
            tasks=services.tasks,
            status=services.window,
            settings_sections=services.settings_sections,
            parent=services.window,
            files=store.files,
            project_dir=store.project_dir,
            repo_root=lambda project_id: find_repo_root(store.project_dir(project_id)),
            plan_remote=lambda project_id: origin_url(store.project_dir(project_id)),
            sources=_report_sources(),
            key_of=_step_key,
            kind_of=_step_kind,
            status_for=step_status,
        )
    )

    def publication_for(group: object) -> "Publication | None":
        """Save's hook: the reports of every project a repository group covers, written
        beside the plan in the same commit — or nothing, when the switch is off."""
        members = [
            project.id for project in library.projects if store.repo_for(project.id) is group
        ]
        root = find_repo_root(store.project_dir(members[0])) if members else None
        if root is None:
            return None
        return reporting.prepare_publication(root, members)

    def pick_assets(node_id: str) -> "list[Payload]":
        """Insert from Assets…: the picker over the node's project's whole catalog.

        Composed here because it is cross-module three ways — the catalog is every
        module's areas, the titles are the asset browser's data, and the host knows only
        its own node. The picked bytes go back to the host, which attaches them into its
        *own* area: reuse is a copy, so a link never points into another module's
        directory.
        """
        from pathlib import PurePosixPath

        from dplanner.domain.assets import AssetEntry, catalog
        from dplanner.framework.asset_picker import AssetPickerDialog, PickerEntry
        from dplanner.modules.project_assets.cli import read_titles

        node = library.node(node_id)
        project = (
            library.project(node_id) if node.kind == "project" else library.project_of(node_id)
        )
        titles = read_titles(project)

        def reader(entry: "AssetEntry") -> "Callable[[], bytes | None]":
            def read() -> bytes | None:
                for _source, location in entry.locations:
                    try:
                        area = store.files(location.node_id, location.module_id)
                    except KeyError:
                        continue
                    data = area.read_bytes(location.name)
                    if data is not None:
                        return data
                return None

            return read

        choices = []
        for entry in catalog(library, project, store.files, asset_sources):
            basename = PurePosixPath(entry.name).name
            title = titles.get(entry.name, "")
            choices.append(
                PickerEntry(
                    key=entry.name,
                    title=title or basename,
                    detail=", ".join(dict.fromkeys(source.label for source, _l in entry.locations)),
                    # The display name becomes the typed link's alt text; the suffix
                    # stays the content's own.
                    filename=f"{title}{PurePosixPath(entry.name).suffix}" if title else basename,
                    read=reader(entry),
                )
            )
        dialog = AssetPickerDialog(choices, services.window)
        picked = dialog.chosen() if dialog.exec() == AssetPickerDialog.DialogCode.Accepted else []
        dialog.deleteLater()
        return picked

    # Constructed before the list for the same reason — its index row opens the table.
    step_order = StepOrderModule(
        StepOrderDeps(
            library=library,
            debounce=services.debounce,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            parent=services.window,
            # The estimate has a column of its own here, so it does not also belong in
            # the row's trailing summary. On the canvas, which has no columns, it does.
            step_aspects=lambda step_id: step_aspects(step_id, skip={ESTIMATION_ID}),
            # Days and dates, computed by the domain from what the estimation module
            # stores. Neither module knows the other's name.
            step_schedule=step_schedule,
            # A milestone row wears a rule and a tint; the name itself stays in the
            # trailing aspects column, which is why the milestone is not skipped here.
            milestone_label=lambda step_id: milestone_read(library.step(step_id)),
            # The same kind vocabulary the canvas medallions wear, one translation.
            step_icons=lambda step_id: step_type_icons(library.step(step_id)),
            # The rule, the tint and the key badge all take the milestone's own shade —
            # the same one its card wears on the canvas and its band in the calendar.
            milestone_color=milestone_color,
            step_key=lambda step_id: _step_key(library.step(step_id)),
        )
    )

    def reveal_step(step_id: str) -> None:
        """Select a step in its project: ``steps.reveal`` against a context naming it."""
        from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri

        services.actions.run(
            "steps.reveal",
            Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step_id)),)}),
        )

    # Built ahead of the list because Run Agent's module closes over it: every launch is
    # handed here, and this is the one place that keeps an eye on the shell afterwards.
    agent_runs = StepAgentRunModule(
        StepAgentRunDeps(
            library=library,
            undo=services.undo,
            actions=services.actions,
            context=services.context,
            status=services.window,
            parent=services.window,
            # An exit is never written over a plan that changed underneath — the same
            # narrowed store the library watcher reads.
            repo=store,
            reveal=reveal_step,
            # Which CLI ran a step, and how to read its record back when the shell ends.
            harnesses=agent_harnesses(),
        )
    )

    # Built ahead of the list: the agent module deep-links to its own settings page
    # through it. Registered last, since its dialog must see every other module's
    # settings sections.
    settings = SettingsModule(
        SettingsDeps(
            actions=services.actions,
            settings_sections=services.settings_sections,
            parent=services.window,
        )
    )

    # Built ahead of the list too: the library watcher hands an entry two writers changed
    # at once to this module's launcher, and it is listed before this module.
    agent_instruction = StepAgentInstructionModule(
        StepAgentInstructionDeps(
            dictation=services.dictation,
            library=library,
            debounce=services.debounce,
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
            # How staged assets are read at launch — bytes by absolute path.
            read_asset=read_absolute,
            # Where the agent runs is the module's reading of these: the code checkout
            # for a project that records its code repository, the plan's own repository
            # for one that does not.
            facts_for=facts_for,
            briefing=briefing,
            # The spawned shell goes to the run tracker: it stamps the launch — directly,
            # off the undo stack, since Ctrl+Z cannot un-launch a shell — and watches
            # the run's files for the shell's end.
            record_launch=lambda step_id, files, harness: agent_runs.track(
                step_id,
                str(files.shell_file),
                str(files.exit_file),
                harness,
                # The session the command named, for a harness that names one; a harness
                # that mints its own is found by its record once the run ends.
                files.session if _names_session(harness) else "",
                # What the briefing came to: measured where prompt.md was written.
                files.prompt_chars,
            ),
            harnesses=agent_harnesses(),
            # The Agent tab's "tokens so far" line: the run tracker's ledger, worded.
            usage_words=lambda step_id: usage_words(library.step(step_id)),
            pick_assets=pick_assets,
            # Run Agent asks before launching on a step whose prerequisites are not
            # done — the same status reader the progression board's frontier uses.
            status_for=step_status,
            # And says so on the step when the shell opens: the status aspect's own
            # writer, applied off the undo stack the way the launch stamp is. The
            # agent module holds the preference; the word is the status module's.
            mark_started=lambda step_id: record_started(library, step_id),
            # What names the run — its worktree, its branch, its window: the key and
            # the ticket, composed here from aspects the agent module never reads.
            step_key=_step_key,
            ticket_key=_ticket_key,
            # Manage Agent Profiles… lands on the module's own settings page.
            open_settings=settings.open,
        )
    )

    return [
        # -- the shell -------------------------------------------------------------------
        AppShellModule(
            AppShellDeps(
                actions=services.actions,
                context=services.context,
                tabs=services.tabs,
                undo=services.undo,
                zoom=services.zoom,
                window=services.window,
                # Registered before any panel exists, which is why it listens to the registry
                # rather than reading it: View ▸ Panels grows an entry as each one arrives.
                panels=services.panels,
                chrome=services.window,
            )
        ),
        AppearanceModule(
            AppearanceDeps(
                actions=services.actions,
                context=services.context,
                theme=services.theme,
                settings_sections=services.settings_sections,
                # View ▸ Milestone Colours writes the *project's* stored map — the same
                # entry the Time tab's picker and `dplanner schedule palette` write. The
                # appearance module never learns where a palette lives.
                milestone_palette=milestone_palette,
                set_milestone_palette=set_milestone_palette,
                watch_palette=watch_milestone_palette,
            )
        ),
        LibraryModule(
            LibraryDeps(
                library=library,
                actions=services.actions,
                parent=services.window,
                status=services.window,
                window=services.window,
                library_path=store.library_path,
                problems=store.problems,
            )
        ),
        # Before the task centre, so the library path and branch sit left of the task
        # button in the status bar.
        SyncModule(
            SyncDeps(
                actions=services.actions,
                autosave=services.autosave,
                context=services.context,
                status=services.window,
                tasks=services.tasks,
                chrome=services.window,
                theme=services.theme,
                parent=services.window,
                switcher=services.switcher,
                library=library,
                library_path=store.library_path,
                # One provider per distinct git repository, scoped to its projects'
                # directories — the store owns the grouping, sync only operates on it.
                repos=store.repo_groups,
                repo_for=store.repo_for,
                focused_project=focused_project,
                projects_in=projects_in,
                publisher=publication_for,
            )
        ),
        # After sync, so the conflict button lands to the right of the library path.
        LibraryWatchModule(
            LibraryWatchDeps(
                # The narrowed store from above: the watcher needs changed_underneath()
                # and adopt_outside_changes(), which the Repository protocol deliberately
                # does not promise.
                repo=store,
                autosave=services.autosave,
                actions=services.actions,
                switcher=services.switcher,
                status=services.window,
                parent=services.window,
                library=library,
                # An entry both writers changed goes to Run Agent's launcher with both
                # versions; the run is tracked on the step like any other.
                hand_to_agent=agent_instruction.hand_conflicts,
                agent_refusal=agent_instruction.conflict_refusal,
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
                actions=services.actions,
                tasks=services.tasks,
                parent=services.window,
                open_url=open_in_browser,
            )
        ),
        LlmAnthropicModule(
            LlmAnthropicDeps(
                llm_providers=services.llm_providers,
                llm=services.llm,
                settings_sections=services.settings_sections,
                actions=services.actions,
                tasks=services.tasks,
                parent=services.window,
                open_url=open_in_browser,
            )
        ),
        LlmModule(
            LlmDeps(
                llm_providers=services.llm_providers,
                llm=services.llm,
                settings_sections=services.settings_sections,
            )
        ),
        # After the providers it lists, before the checklist and Settings: its action is
        # the remedy the dictation rows offer, and its page is a section the dialog shows.
        DictationModule(
            DictationDeps(
                dictation=services.dictation,
                settings_sections=services.settings_sections,
                actions=services.actions,
                context=services.context,
                open_settings=settings.open,
            )
        ),
        DebugModule(
            DebugDeps(
                llm=services.llm,
                telemetry=services.telemetry,
                actions=services.actions,
                tabs=services.tabs,
                context=services.context,
                parent=services.window,
                debounce=services.debounce,
                theme=services.theme,
                tasks=services.tasks,
            )
        ),
        # -- the planner ------------------------------------------------------------------
        ProjectsModule(
            ProjectsDeps(
                library=library,
                debounce=services.debounce,
                actions=services.actions,
                context=services.context,
                undo=services.undo,
                segments=services.index_segments,
                theme=services.theme,
                parent=services.window,
                status=services.window,
                tasks=services.tasks,
                autosave=services.autosave,
                switcher=services.switcher,
                settings_sections=services.settings_sections,
                # The Repositories card: registered here, before project_editor builds
                # the project panel from whatever has registered by then.
                cards=services.detail_cards,
                repos=repos,
                # The index opens a project without knowing what an editor is.
                open_project=project_editor.open,
                # The store's membership face: attach/detach track directories, the
                # model change itself is applied here, off the undo stack, with the
                # membership origin the `library add` verb uses too.
                detach=store.detach,
                connect_project=connect_project,
                project_dirs=lambda: (
                    [store.project_dir(project.id).resolve() for project in library.projects]
                    + [problem.path.resolve() for problem in store.problems()]
                ),
                problems=store.problems,
                # Rows under each project — a project row itself only folds; these are
                # what opens. Each renders the Project menu: the row stands for its
                # project, and the project's verbs all live there.
                # A single click opens the same surface as a preview tab — the VS Code
                # gesture: the next click's preview replaces it, activation keeps it.
                entries=(
                    ProjectEntry(
                        id="steps",
                        label="Steps",
                        open=project_editor.open,
                        open_preview=lambda pid: project_editor.open(pid, preview=True),
                        icon=graph_icon,
                        menu="Project",
                        order=10,
                    ),
                    ProjectEntry(
                        id="order",
                        label="Order",
                        open=step_order.open,
                        open_preview=lambda pid: step_order.open(pid, preview=True),
                        icon=list_icon,
                        menu="Project",
                        order=15,
                    ),
                    ProjectEntry(
                        id="spec",
                        label="Specs",
                        open=spec.open,
                        open_preview=lambda pid: spec.open(pid, preview=True),
                        icon=spec_icon,
                        menu="Project",
                        order=20,
                        # A mark while a source of that project has updates waiting, so it
                        # is visible without opening the tab. What the window has found,
                        # not a claim about the source now: checking runs while a Specs tab
                        # is open, and a project nobody has opened is not being checked.
                        badge=spec.updates_mark,
                        changed=spec.updates_changed,
                    ),
                    ProjectEntry(
                        id="coverage",
                        label="Coverage",
                        open=coverage.open,
                        open_preview=lambda pid: coverage.open(pid, preview=True),
                        icon=coverage_icon,
                        menu="Project",
                        order=22,
                    ),
                    ProjectEntry(
                        id="assets",
                        label="Assets",
                        open=project_assets.open,
                        open_preview=lambda pid: project_assets.open(pid, preview=True),
                        icon=image_icon,
                        menu="Project",
                        order=25,
                    ),
                    ProjectEntry(
                        id="progression",
                        label="Ready to start",
                        open=progression.open,
                        open_preview=lambda pid: progression.open(pid, preview=True),
                        icon=gauge_icon,
                        menu="Project",
                        order=30,
                    ),
                    ProjectEntry(
                        id="time",
                        label="Time Estimates",
                        open=time_estimates.open,
                        open_preview=lambda pid: time_estimates.open(pid, preview=True),
                        icon=clock_icon,
                        menu="Project",
                        order=40,
                    ),
                ),
            )
        ),
        # Before spec: the Specs tab's + menu lists its kinds, and its settings section
        # must exist before the settings dialog is built.
        confluence,
        spec,
        coverage,
        project_assets,
        # -- the step aspects --------------------------------------------------------------
        # Each registers one tab into the step detail panel — or, for the estimate and
        # description, a block into its Details tab (services.step_details). They must
        # come before step_properties, which builds the panel from whatever has
        # registered by then.
        estimation,
        StepTicketModule(
            StepTicketDeps(
                library=library,
                undo=services.undo,
                sections=services.inspector_sections,
                actions=services.actions,
            )
        ),
        StepDescriptionModule(
            StepDescriptionDeps(
                dictation=services.dictation,
                actions=services.actions,
                library=library,
                undo=services.undo,
                details=services.step_details,
                files=store.files,
                # The "Separate agent instruction" checkbox: the agent aspect through
                # typed callbacks, so neither module learns the other's name.
                agent_link=SeparateInstructionLink(
                    agent_enabled=lambda sid: agent_enabled(library.step(sid)),
                    separate=lambda sid: agent_separate(library.step(sid)),
                    has_text=lambda sid: bool(agent_instruction_read(library.step(sid))),
                    set_separate=set_separate_instruction,
                ),
                # Insert from Assets…, composed above over every module's catalog slice.
                pick_assets=pick_assets,
            )
        ),
        # Run Agent, built above the list; the library watcher borrows its launcher.
        agent_instruction,
        # The shells Run Agent above spawns, and the canvas reads the aspect through
        # step_accents above.
        agent_runs,
        DocsModule(
            DocsDeps(
                dictation=services.dictation,
                library=library,
                debounce=services.debounce,
                undo=services.undo,
                actions=services.actions,
                sections=services.inspector_sections,
                context=services.context,
                tabs=services.tabs,
                segments=services.index_segments,
                theme=services.theme,
                # Read, never added to: grouping the Documentation view by feature or
                # milestone is the same walk the Tests tab makes. A fourth ScopeKind of its
                # own would teach four tests surfaces about documentation to serve none of it.
                scopes=_scope_kinds(check_read, is_feature, milestone_read),
                files=store.files,
                # Its project-level card: the compilation instructions every document
                # compiled in this project follows.
                cards=services.detail_cards,
                # The description *is* the instructions (ARCHITECTURE.md), so it is what a
                # collector says about itself — context in the briefing, and a cross-module
                # fact, so it is decided here.
                instructions=description_read,
                # Compiling is a launch: the briefing is the docs module's words, the
                # terminal and the desk's limit are Run Agent's, and neither imports the
                # other. The run is tracked on the collector like any other agent run.
                compile_profiles=agent_instruction.compile_profiles,
                compile_with_agent=agent_instruction.compile_documentation,
                # Whether an agent is already at work on a collector — the run aspect's own
                # reader, so the words are the status module's and not a second copy.
                run_state=lambda step_id: (
                    agent_run_state(library.step(step_id)) if library.has(step_id) else ""
                ),
                # How a step is named everywhere, for the briefing's verbs and the rows.
                step_key=_step_key,
                # A milestone group's medallion in the milestone's own shade — the same
                # sequence the Tests tab's headings and the calendar show.
                milestone_color=milestone_color,
                parent=services.window,
                pick_assets=pick_assets,
                # The Implementation notes tab — the notes the project made along the way,
                # which every briefing indexes — as a row under each project in its folder.
                more_rows=(notes.index_row(),),
            )
        ),
        # Declares the compiled-document format only; DocsModule and the CLI write it.
        DocsCompiledModule(),
        # Registers nothing; in the list for its data format, and because it is a module.
        notes,
        StepMilestoneModule(
            StepMilestoneDeps(
                library=library,
                undo=services.undo,
                sections=services.inspector_sections,
                actions=services.actions,
                # The swatch beside the label, and the words that say what it means.
                shade=milestone_shade,
            )
        ),
        # No tab: the status vocabulary is a Status submenu of checkable Step verbs.
        StepStatusModule(
            StepStatusDeps(library=library, undo=services.undo, actions=services.actions)
        ),
        # No tab either: a check carries nothing, and the Covers tab that shows what it
        # gathers is the tests module's — it renders a list of tests, which is that
        # module's business, not this one's.
        StepCheckModule(
            StepCheckDeps(library=library, undo=services.undo, actions=services.actions)
        ),
        # A feature is a step: one a person would name and demo, gathering the work behind
        # it and stopping at the previous feature. The Covers tab that shows what it
        # gathers is still the tests module's.
        feature,
        # Registers nothing: it owns the widget the graph tab stands beside the canvas.
        problems,
        TestsModule(
            TestsDeps(
                dictation=services.dictation,
                library=library,
                debounce=services.debounce,
                undo=services.undo,
                actions=services.actions,
                context=services.context,
                tabs=services.tabs,
                sections=services.inspector_sections,
                segments=services.index_segments,
                theme=services.theme,
                parent=services.window,
                files=store.files,
                # A check declares a scope; a feature and a milestone already were ones, and
                # all three are the same walk with a different stopping rule. Named here,
                # the one place that may know every aspect, so none learns the others.
                scopes=_scope_kinds(check_read, is_feature, milestone_read),
                pick_assets=pick_assets,
                # Grouping by milestone writes each heading in that milestone's own shade,
                # so the Tests tab reads as the same sequence the calendar does.
                milestone_color=milestone_color,
            )
        ),
        GithubModule(
            GithubDeps(
                actions=services.actions,
                library=library,
                undo=services.undo,
                sections=services.inspector_sections,
                tasks=services.tasks,
                parent=services.window,
                repository_for=repository_for,
            )
        ),
        step_properties,
        project_editor,
        step_order,
        progression,
        time_estimates,
        # After every module whose report_source it renders; before Settings, whose dialog
        # is built from the sections registered by then.
        reporting,
        # Declares the progress history's format only; the recorder above writes it.
        ProgressHistoryModule(),
        InstallModule(
            InstallDeps(
                actions=services.actions,
                tasks=services.tasks,
                parent=services.window,
                # The window writes exactly what `dplanner skill install` writes, from the
                # same generator over the same registry.
                skill_files=skill_files,
            )
        ),
        # After the installer, whose three rows it shows: its action is the remedy the
        # DPlanner rows offer, and an action must be registered before one is run.
        ChecklistModule(
            ChecklistDeps(
                actions=services.actions,
                context=services.context,
                tasks=services.tasks,
                parent=services.window,
                # Every module's rows, over the same skill files the installer compares
                # against — the tuple `dplanner checklist show` reads.
                checks=lambda: _machine_checks(files=skill_files),
            )
        ),
        # After every module that registers an activity factory: it reopens the tabs the
        # last session had, and a kind whose factory has not arrived yet is one it would
        # decide this build no longer has.
        ReopenTabsModule(
            ReopenTabsDeps(
                tabs=services.tabs,
                settings_sections=services.settings_sections,
                # Which tabs were open is true of this library alone.
                scope=services.source_scope,
                # A remembered tab whose project has since been deleted is dropped; the
                # module never learns what a project is.
                exists=library.has,
            )
        ),
        # Last: its dialog is built during register() and must see every other module's
        # settings sections.
        settings,
    ]


def _module_asset_paths(
    files: "Callable[[str, str], ModuleFileArea]", node_id: str, module_id: str
) -> tuple[str, ...]:
    """A node's module files as absolute paths; a never-flushed node has none."""
    from dplanner.domain.assets import assets

    try:
        area = files(node_id, module_id)
    except KeyError:
        return ()
    return tuple(str(area.absolute(name)) for name in assets(area))


def _note_parts(
    library: "Library", step: "Step", files: "Callable[[str, str], ModuleFileArea]"
) -> "list[PromptPart]":
    """The briefing's blocks after the instructions: the notes addressed to this step in
    full, and the index of everything else that reaches it — the notes module's own
    blocks, made prompt parts here so neither module learns the other's name. Both
    surfaces and ``dplanner note index`` read the same blocks, so the window, the verb
    and the CLI cannot brief a step two ways."""
    from dplanner.modules.notes.log import note_files
    from dplanner.modules.notes.reach import briefing_blocks, reaching
    from dplanner.modules.step_agent_instruction.prompt import PromptPart

    project = library.project_of(step.id)
    return [
        PromptPart(
            heading=block.heading,
            body=block.body,
            files=tuple(
                path for note in block.carried for path in note_files(files, project.id, note)
            ),
        )
        for block in briefing_blocks(project, reaching(library, step), _step_key)
    ]


def _passage_place(source: "FeatureSource") -> str:
    page = f" p.{source.page}" if source.page is not None else ""
    return f"{source.document}{page}"


def _briefing_sections(
    library: "Library", step: "Step", files: "Callable[[str, str], ModuleFileArea]"
) -> "list[PromptPart]":
    """The step's own facts as briefing sections: what it is, why it exists, where the
    work lands. Cross-module prose, so it is worded here in the one file allowed to know
    every module's vocabulary — the agent module renders the blocks without learning what
    a description, a requirement or a PR is. An empty fact contributes no section.
    """
    from dplanner.domain.scope import gatherers
    from dplanner.modules.feature.aspect import is_feature
    from dplanner.modules.feature.aspect import read as feature_read
    from dplanner.modules.github.aspect import pr_label
    from dplanner.modules.github.aspect import read as github_read
    from dplanner.modules.spec.aspect import attachment_paths
    from dplanner.modules.step_agent_instruction.aspect import read as instruction_read
    from dplanner.modules.step_agent_instruction.prompt import PromptPart
    from dplanner.modules.step_description.aspect import MODULE_ID as DESCRIPTION_ID
    from dplanner.modules.step_description.aspect import read as description_read
    from dplanner.modules.step_milestone.aspect import read as milestone_read

    sections: list[PromptPart] = []
    # Without a separate instruction the description IS the ## Instructions block (see
    # _briefing_instruction), so a Description section here would say everything twice.
    description = description_read(step)
    description_files = _module_asset_paths(files, step.id, DESCRIPTION_ID)
    if instruction_read(step) and (description or description_files):
        sections.append(
            PromptPart(heading="Description", body=description, files=description_files)
        )
    project = library.project_of(step.id)

    def passage_lines(holder: "Step") -> list[str]:
        """Where one feature was read from — its step's title, then each passage."""
        cites = feature_read(holder) or ()
        where = f", from {_passage_place(cites[0])}" if len(cites) == 1 else ""
        lines = [f"- **{holder.title}**{where}"]
        for source in cites:
            if len(cites) > 1:
                lines.append(f"  from {_passage_place(source)}:")
            lines += [f"  > {quoted}" for quoted in source.quote.splitlines()]
        return lines

    if is_feature(step):
        # The feature's name and its prose are this step's own — already the title of the
        # briefing and its ## Instructions block — so what is left to say is where in the
        # specification it was read from.
        cites = feature_read(step) or ()
        if cites:
            sections.append(
                PromptPart(heading="Read from the spec", body="\n".join(passage_lines(step)))
            )
    else:
        # A work step reaches the spec through the feature it flows into: the graph's
        # answer, the same walk the Covers tab and `scope show` read.
        owners = gatherers(
            library,
            project,
            carried_by=is_feature,
            stops_at=lambda other: is_feature(other) or bool(milestone_read(other)),
        ).get(step.id, ())
        holders = [owned for owner in owners if (owned := project.step(owner)) is not None]
        lines = [line for holder in holders for line in passage_lines(holder)]
        if lines:
            sections.append(PromptPart(heading="Flows into", body="\n".join(lines)))
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
            pr = pr_label(refs)
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


def _briefing_project_sections(
    library: "Library", step: "Step", _files: "Callable[[str, str], ModuleFileArea]"
) -> "list[PromptPart]":
    """The project's own facts as briefing sections: its topology — how the graph is
    shaped, which every step is read against. (What the project recorded along the way
    — decisions included — is the notes index after the instructions, ``_note_parts``.)
    Root prose for the same reason as the step's sections: it names other modules'
    vocabulary."""
    from dplanner.modules.spec.aspect import read_topology
    from dplanner.modules.step_agent_instruction.prompt import PromptPart

    project = library.project_of(step.id)
    sections: list[PromptPart] = []
    topology = read_topology(project)
    if topology.strip():
        sections.append(
            PromptPart(heading="Topology — how this project's graph is shaped", body=topology)
        )
    return sections


def _briefing_instruction(
    library: "Library", step: "Step", files: "Callable[[str, str], ModuleFileArea]"
) -> "PromptPart":
    """The briefing's ``## Instructions`` block: the description is the instructions.

    A step's separate instruction wins when one exists; otherwise the description body and
    its images take the block — one text an agent step needs, written once. Cross-module
    (it reads the description on the agent module's behalf), so it is decided here, in the
    one file allowed to know both. Instruction-area files always ride with the block: they
    were attached to it.
    """
    from dplanner.modules.step_agent_instruction.aspect import asset_paths
    from dplanner.modules.step_agent_instruction.aspect import read as instruction_read
    from dplanner.modules.step_agent_instruction.prompt import PromptPart
    from dplanner.modules.step_description.aspect import MODULE_ID as DESCRIPTION_ID
    from dplanner.modules.step_description.aspect import read as description_read

    own = instruction_read(step)
    instruction_files = asset_paths(files, step.id)
    if own:
        return PromptPart(heading="Instructions", body=own, files=instruction_files)
    description_files = _module_asset_paths(files, step.id, DESCRIPTION_ID)
    return PromptPart(
        heading="Instructions",
        body=description_read(step),
        files=(*description_files, *instruction_files),
    )


def _default_briefing() -> "Briefing":
    """The briefing every surface assembles from: the shared block builders below, and
    the root's own opening and closing prose. One object, two callers — the window's
    Deps and ``dplanner agent prompt`` — so what an agent is launched with and what the
    verb prints are the same text by construction."""
    from dplanner.modules.step_agent_instruction.prompt import Briefing

    return Briefing(
        parts=_note_parts,
        sections=_briefing_sections,
        project_sections=_briefing_project_sections,
        epilogue=_agent_epilogue,
        preamble=_agent_preamble,
        instruction=_briefing_instruction,
    )


def _step_key(step: "Step") -> str:
    """The step's readable key: a letter for what it is, the number the project dealt.

    ``M`` a milestone, ``F`` a feature, ``C`` a check, ``S`` any other step — the coarser
    claim wins, in the order the body tone ranks them, so a milestone that is also a
    feature reads ``M``. The letter is presentation over the stored number, which is why
    a step keeps its number when its kind changes and the letter follows. Read by the
    canvas spine, every CLI row and lookup, the branch a run is named after, and the
    briefing that tells the agent which step it holds.
    """
    from dplanner.modules.feature.aspect import is_feature
    from dplanner.modules.step_check.aspect import read as check_read
    from dplanner.modules.step_milestone.aspect import read as milestone_read

    if not step.number:
        return ""
    letter = (
        "M"
        if milestone_read(step)
        else "F"
        if is_feature(step)
        else "C"
        if check_read(step)
        else "S"
    )
    return f"{letter}{step.number}"


def _step_kind(step: "Step") -> str:
    """What a step *is*, in one word, the coarser claim first — the same ranking as the key's
    letter and the body tone: milestone, feature, check, agent step, or nothing."""
    from dplanner.modules.feature.aspect import is_feature
    from dplanner.modules.step_agent_instruction.aspect import enabled as agent_enabled
    from dplanner.modules.step_check.aspect import read as check_read
    from dplanner.modules.step_milestone.aspect import read as milestone_read

    if milestone_read(step):
        return "milestone"
    if is_feature(step):
        return "feature"
    if check_read(step):
        return "check"
    if agent_enabled(step):
        return "agent"
    return ""


def _milestone_stats(library: "Library", project: "Project") -> dict[str, str]:
    """What each milestone answers with: the schedule's accumulated days and landing date
    at its row — the same pair the order table's milestone row highlights.

    A milestone closes the block of work above it, so its number is the walk's total at
    that row. One walk per project rather than one per milestone, because a canvas sync
    asks for every milestone at once and the order is the same for all of them. A
    milestone the project cannot date is absent; so is every step when nothing is a
    milestone, which costs the sync no walk at all.
    """
    from dplanner.domain.schedule import format_date, format_days
    from dplanner.modules.estimation.schedule import project_schedule
    from dplanner.modules.step_milestone.aspect import read as milestone_read

    if not any(milestone_read(step) for step in project.steps):
        return {}
    stats: dict[str, str] = {}
    for scheduled in project_schedule(library, project):
        step = scheduled.place.step
        if not milestone_read(step):
            continue
        if scheduled.finish is not None:
            stats[step.id] = (
                f"{format_days(scheduled.accumulated)} · {format_date(scheduled.finish)}"
            )
        elif scheduled.accumulated:
            stats[step.id] = format_days(scheduled.accumulated)
    return stats


def _ordinal(place: int) -> str:
    """``1st``, ``2nd``, ``3rd``, ``4th`` — the teens are the exception every table forgets."""
    suffix = "th" if 10 <= place % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(place % 10, "th")
    return f"{place}{suffix}"


def _milestone_colors(library: "Library", project: "Project") -> dict[str, str]:
    """Each milestone's hex — the one deal, handed to every surface that draws one.

    The colour map is the *project's* assumption, not the user's: the window commits
    ``reports/`` on every Save, so a per-user map would churn the published report per
    committer and the Time tab's picker would name a map it was not painting.
    ARCHITECTURE.md's *Colour is a place on one map* has the rest.
    """
    from dplanner.modules.step_milestone.aspect import read as milestone_read
    from dplanner.modules.time_estimates.schedule import milestone_colors

    return milestone_colors(library, project, lambda step: bool(milestone_read(step)))


def _step_stats(library: "Library", project: "Project") -> dict[str, str]:
    """The figure at each card's bottom right: a milestone's total and landing, any other
    step's estimate — what the canvas paints, read once for the report's graph."""
    from dplanner.domain.schedule import format_days
    from dplanner.modules.estimation.aspect import read as estimated_days

    stats = _milestone_stats(library, project)
    for step in project.steps:
        if step.id in stats:
            continue
        days = estimated_days(step)
        if days is not None:
            stats[step.id] = format_days(days)
    return stats


def _step_type_icons(step: "Step") -> tuple[str, ...]:
    """What kind of thing a step is, in the medallion vocabulary the canvas painted
    first: "tag" a milestone, "layers" a feature, "spark" an agent step, "beaker" one
    carrying tests, "shield" a check. The order table's title column reads the same
    answer, so a step is the same kind everywhere."""
    from dplanner.modules.feature.aspect import is_feature
    from dplanner.modules.step_agent_instruction.aspect import enabled as agent_enabled
    from dplanner.modules.step_check.aspect import read as check_read
    from dplanner.modules.step_milestone.aspect import read as milestone_read
    from dplanner.modules.testing.aspect import enabled as test_enabled

    return (
        *(("tag",) if milestone_read(step) else ()),
        *(("layers",) if is_feature(step) else ()),
        *(("spark",) if agent_enabled(step) else ()),
        *(("beaker",) if test_enabled(step) else ()),
        *(("shield",) if check_read(step) else ()),
    )


def _report_sources() -> tuple["ReportSource", ...]:
    """Every module's say in a report, in page order.

    The tuple both surfaces read — ``dplanner report`` and the window's exports and
    on-Save site — assembled here because each ``report_source()`` lives in its owner's
    Qt-free half and no module may import another. Cross-module readers are handed in as
    functions, the way the CLI verbs get theirs; the order is the order parts land in
    their slots when two modules place at the same rank.
    """
    from dplanner.modules.estimation.aspect import MODULE_ID as ESTIMATION_ID
    from dplanner.modules.estimation.aspect import read as estimated_days
    from dplanner.modules.estimation.aspect import read_history as estimate_history
    from dplanner.modules.estimation.report import report_source as estimates
    from dplanner.modules.estimation.schedule import project_schedule, start_of
    from dplanner.modules.feature.report import report_source as features
    from dplanner.modules.github.report import report_source as github
    from dplanner.modules.notes.report import report_source as notes
    from dplanner.modules.progression.report import report_source as progression
    from dplanner.modules.project_editor.report import report_source as graph
    from dplanner.modules.step_agent_instruction.aspect import enabled as agent_enabled
    from dplanner.modules.step_description.report import report_source as descriptions
    from dplanner.modules.step_milestone.aspect import read as milestone_read
    from dplanner.modules.step_milestone.report import report_source as milestones
    from dplanner.modules.step_order.report import report_source as order
    from dplanner.modules.step_status.aspect import read as step_status
    from dplanner.modules.step_ticket.report import report_source as tickets
    from dplanner.modules.testing.report import report_source as tests
    from dplanner.modules.time_estimates.report import report_source as time_estimates

    summaries = aspect_summaries(skip={ESTIMATION_ID})

    def step_aspects(step: "Step") -> list[str]:
        return [phrase for phrase in (summary(step) for summary in summaries) if phrase]

    return (
        progression(status_for=step_status, days_for=estimated_days, key_of=_step_key),
        time_estimates(
            days_for=estimated_days,
            is_agent=agent_enabled,
            status_for=step_status,
            start_of=start_of,
            milestone_label=milestone_read,
            estimate_history=estimate_history,
            key_of=_step_key,
        ),
        graph(
            key_of=_step_key,
            kind_of=_step_kind,
            status_for=step_status,
            stats_of=_step_stats,
            badge_of=milestone_read,
            # The report's picture of the graph wears the same shades the window does.
            colors_of=_milestone_colors,
        ),
        order(
            schedule_of=project_schedule,
            step_aspects=step_aspects,
            milestone_label=milestone_read,
        ),
        estimates(),
        milestones(),
        features(),
        descriptions(),
        tests(key_of=_step_key),
        tickets(),
        github(),
        notes(key_of=_step_key),
    )


def _ticket_key(step: "Step") -> str:
    from dplanner.modules.step_ticket.aspect import read as ticket_read

    ticket = ticket_read(step)
    return ticket.key if ticket is not None else ""


def _run_name(step: "Step") -> str:
    """What a step's agent run is called — the same rule the launcher applies, read here
    so the briefing can name the worktree the script prepared."""
    from dplanner.modules.step_agent_instruction.launcher import run_name

    return run_name(_step_key(step), _ticket_key(step), step.title)


def _agent_preamble(step: "Step", in_worktree: bool, facts: "RepositoryFacts | None") -> str:
    """The briefing's preflight: the agent proves it can report back, that it is where
    this run said it would be, and knows where the plan lives, before it starts.

    An agent without the DPlanner skill would do the work and leave the plan blind — no
    status, no handoff — so the briefing makes the check the first move and stopping the
    honest fallback. The second check is the worktree: two agents once "launched into
    fresh worktrees" and did their work on the same branch, so an agent whose step asks
    for a worktree confirms it is in one — by the name the launcher prepared — and stops
    if it is not. ``in_worktree`` is the caller's word on *this run* — the step's own
    choice for Run Agent and ``agent prompt``, never for a conflict the window hands over.
    ``facts`` says where the plan lives: apart from the code, or inside it — the shape that
    drifts, so the agent is warned to leave the plan files alone and let the verbs write.
    Root prose for the same reason as the epilogue: it names other modules' verbs and the
    launcher's naming.
    """
    from dplanner.modules.step_agent_instruction.launcher import (
        WORKTREES_DIR,
        branch_name,
    )

    lines = [
        "First, confirm you can drive DPlanner: run `dplanner skill status`. If the"
        " command is missing or the skill is not installed, STOP — do not carry out the"
        " step — and tell the developer this step needs the DPlanner skill"
        " (`dplanner skill install`)."
    ]
    if in_worktree:
        name = _run_name(step)
        lines.append(
            "Second, confirm you are in this step's own git worktree: `git rev-parse"
            f" --show-toplevel` must end in `{WORKTREES_DIR}/{name}` and `git branch"
            f" --show-current` must print `{branch_name(name)}`. If either differs, STOP"
            " — do not touch the main checkout — and tell the developer the worktree"
            " was not prepared. Commit on that branch; every `dplanner` command still"
            " reaches the plan the window shows."
        )
    else:
        lines.append(
            "This step works in the checkout itself (its worktree option is off), on the"
            " branch that is checked out — take care: other agents may be in worktrees"
            " beside you, but this one shares the developer's working tree."
        )
    if facts is not None:
        lines.append(_plan_whereabouts(facts))
    lines.append(
        "Other agents may be working beside you in this repository, each in a worktree"
        " of its own, and their processes carry the same names and paths as yours. Never"
        " kill a process by name or pattern (`pkill -f`, `killall`, `kill $(pgrep …)`):"
        " kill only by a pid your own shell started."
    )
    return "\n\n".join(lines)


def _plan_whereabouts(facts: "RepositoryFacts") -> str:
    """Where the plan lives, told to the agent: in a repository of its own, or — warned
    about unless the people on the project accepted it — inside the code it plans."""
    from dplanner.domain.repositories import SEPARATED

    if facts.state == SEPARATED:
        code = f" ({facts.code_label})" if facts.code_label else ""
        return (
            f"The plan is kept in its own repository, {facts.plan_label}, apart from the"
            f" code you are working in{code}: every `dplanner` command writes to the plan"
            " there, never to this checkout, so nothing you commit here carries a plan"
            " file and `git status` never shows one."
        )
    lead = (
        "WARNING: this plan lives inside the code repository it plans"
        if facts.warns
        else "This plan is kept inside the code repository it plans, by the developer's choice"
    )
    text = (
        f"{lead}: its files (`project.dproj`, `steps/`, `modules/`) sit in the checkout"
        " beside the code. Every `dplanner` command reaches the plan of record — the copy"
        " the window shows, in the main checkout — never a branch's copy, so do not edit"
        " those files by hand, and do not stage or commit them with your work."
    )
    if facts.warns:
        text += (
            " Do not move the plan on your own; when the developer asks for it,"
            " `dplanner project move <project> --into <plan repository>` (`--init-repo`"
            " to start one) moves it, commits both sides and re-points the library, and"
            " every verb keeps reaching the plan where it lands."
        )
    return text


def _agent_epilogue(library: "Library", step: "Step") -> str:
    """The briefing's closing words: how the agent reports back through the CLI.

    Cross-module prose — it names the status and note verbs — so it is written here, in
    the one file allowed to know every module's vocabulary, and handed to the agent module
    as a callback on both surfaces. Every verb names the step by its key: a key is
    unambiguous where a title may match two steps, and it is what the branch and the
    PR are named after; the note verbs name the project too, since a note is the
    project's record.
    """
    from dplanner.modules.notes.reach import project_ref

    key = _step_key(step) or step.title or "Untitled step"
    ref = f"'{key}'" if " " in key else key
    project = project_ref(library.project_of(step.id))
    return (
        f"This step is {key}. Its branch and worktree carry that key; open the PR title"
        f" with it (`{key}: …`) and record the branch and the PR on the step as they"
        f" exist: `dplanner github set {ref} --branch $(git branch --show-current)`,"
        f" then `dplanner github set {ref} --pr <number>`.\n"
        "As you work, keep the run state current:\n"
        f"- `dplanner agent-state set {ref} plan-for-review` when your plan is ready"
        " to review\n"
        f"- `dplanner agent-state set {ref} working` while implementing\n"
        f"- `dplanner agent-state set {ref} pending-approval` while waiting on an"
        " approval\n"
        f"- `dplanner agent-state set {ref} needs-input` when you have a question the"
        " developer must answer before you can go on\n"
        "As you go, leave notes — the project's record, indexed into the briefing of every"
        " step that comes after the one you made them on. That is the reach: add"
        " `--reach project` when what you settled belongs to the whole plan rather than"
        " this branch. `dplanner note add --help` lists the labels:\n"
        f"- `dplanner note add {project} decision '<what you chose>' --step {ref}"
        " --text '<why>'` for each choice the plan should remember (`--supersedes N3`"
        " when it reverses an earlier one)\n"
        f"- `dplanner note add {project} spec-change '<what differs>' --step {ref}"
        " --text '<what and why>'` where the work had to depart from the spec\n"
        f"- `dplanner note add {project} later '<what>' --step {ref}` for work you"
        " noticed and did not do\n"
        "When the work is finished, record it in DPlanner:\n"
        f"- `dplanner status set {ref} done` and `dplanner agent-state clear {ref}`\n"
        f"- `dplanner note add {project} handoff '<one line the next worker needs>'"
        f" --step {ref} --file -` with what whoever picks up after you must know —"
        " where things are, what is half done, what bit you. Title it as the fact it"
        " is; the body carries the detail. Add `--for S12` for a step that must read it"
        " in full, `--reach project` if every step should see it regardless;"
        f" `dplanner note attach {project} <id> <file>` for files.\n"
        f"If you cannot finish, `dplanner status set {ref} blocked` and say why in the"
        " handoff note."
    )


def _scope_kinds(
    is_check: Callable[["Step"], bool],
    is_feature: Callable[["Step"], bool],
    milestone_label: Callable[["Step"], str],
) -> tuple["ScopeKind", ...]:
    """The collectors this build knows, and where each one's cone stops.

    Read most specific first: a step marked as both a milestone and a feature is a milestone,
    because that is the coarser claim and the one a person is looking for.

    The stopping rules are the whole design. A **check** stands for everything behind it
    having been verified, so it stops at nothing. A **milestone** collects what is new since
    the previous milestone, so it stops at milestones. A **feature** collects its own work up
    to the previous feature — and at a milestone too, since a milestone is a boundary anything
    below it also respects.

    A milestone and a check are then *read* as lists of features; a feature is the finest
    grain and is read flat. That is a different question from where the walk stops, and
    saying both here is what keeps a surface from having to guess either.

    Written literally rather than derived from a rank, because three lines a reader can
    check by eye beat an ordering abstraction over exactly three things.
    """
    from dplanner.domain.scope import ScopeKind

    # A milestone declares itself by carrying a label, so the aspect's reader is a string
    # one; the walk wants a predicate, and this is the one place that has to know both.
    def is_milestone(step: "Step") -> bool:
        return bool(milestone_label(step))

    return (
        ScopeKind("step_milestone", "Milestone", is_milestone, is_milestone, gathers="feature"),
        ScopeKind(
            "feature",
            "Feature",
            is_feature,
            lambda step: is_feature(step) or is_milestone(step),
        ),
        ScopeKind("step_check", "Check", is_check, lambda _step: False, gathers="feature"),
    )


def _coverage_trace(library: "Library", project: "Project", files: "FilesFor") -> "Trace":
    """The coverage picture: spec passages → features → milestones → tests and docs.

    The one place the spec, the feature steps, the collectors, the tests and the docs
    meet; each answers through its own Qt-free reader and ``coverage/trace.py`` only
    arranges them. Derived on every read, like everything the graph could contradict.
    """
    from dplanner.modules.coverage.trace import (
        Citation,
        Document,
        Feature,
        Readers,
        TestRow,
        build,
    )
    from dplanner.modules.docs.aspect import read as docs_read
    from dplanner.modules.docs.collect import sources_for
    from dplanner.modules.docs.collect import state_of as docs_state
    from dplanner.modules.feature.aspect import is_feature
    from dplanner.modules.feature.aspect import read as feature_read
    from dplanner.modules.spec.aspect import MODULE_ID as SPEC_ID
    from dplanner.modules.spec.cli import anchor_sources
    from dplanner.modules.spec.documents import document_text, read_index
    from dplanner.modules.step_check.aspect import read as check_read
    from dplanner.modules.step_milestone.aspect import read as milestone_read
    from dplanner.modules.step_status.aspect import read as step_status
    from dplanner.modules.testing.aspect import covered
    from dplanner.modules.testing.runs import latest_results
    from dplanner.modules.testing.runs import read as read_runs

    scopes = _scope_kinds(check_read, is_feature, milestone_read)

    def features(library: "Library", project: "Project", files: "FilesFor") -> list[Feature]:
        steps = [step for step in project.steps if is_feature(step)]
        cited = {step.id: feature_read(step) or () for step in steps}
        refs = [(s.document, s.quote, s.digest) for step in steps for s in cited[step.id]]
        anchors = iter(anchor_sources(files, project, refs))
        return [
            Feature(
                step.id,
                step.title,
                step.id,
                tuple(Citation(s.document, s.quote, s.page, next(anchors)) for s in cited[step.id]),
            )
            for step in steps
        ]

    def documents(project: "Project", files: "FilesFor") -> list[Document]:
        try:
            area = files(project.id, SPEC_ID)
        except KeyError:
            area = None
        return [
            Document(doc.name, doc.kind, document_text(area, doc) if area is not None else None)
            for doc in read_index(project).documents
        ]

    def tests(
        library: "Library",
        project: "Project",
        step_id: str,
        stops_at: "Callable[[Step], bool] | None",
    ) -> list[TestRow]:
        return [
            TestRow(test.id, test.title, step.id, step.title)
            for step, test in covered(library, project, step_id, stops_at=stops_at)
        ]

    def results(project: "Project") -> dict[str, str]:
        outcomes = latest_results(read_runs(project))
        return {test_id: outcome.result.status for test_id, outcome in outcomes.items()}

    def docs(library: "Library", project: "Project", step_id: str) -> str:
        step = project.step(step_id)
        if step is None:
            return ""
        state = docs_state(scopes, library, project, step_id)
        if state != "never":
            return state
        # Never compiled, but there is something to compile — or a note of its own.
        has_notes = bool(docs_read(step)) or bool(sources_for(scopes, library, project, step_id))
        return "never" if has_notes else ""

    return build(
        Readers(
            features=features,
            documents=documents,
            is_feature=is_feature,
            is_milestone=lambda step: bool(milestone_read(step)),
            milestone_label=milestone_read,
            is_done=lambda step: step_status(step) == "done",
            tests=tests,
            results=results,
            docs=docs,
            # The milestone lane wears the same shades the canvas and the calendar do.
            milestone_colors=_milestone_colors,
        ),
        library,
        project,
        files,
    )


def _covered_tests(
    library: "Library",
    project: "Project",
    step_id: str,
    stops_at: "Callable[[Step], bool] | None" = None,
) -> list[tuple[str, str, str]]:
    """What a collector stands for: (test id, test title, owning step's title).

    The one place the collector aspects and the tests aspect meet. None imports another; the
    walk is the domain's and the filtering is testing's, and this hands the pair over as the
    tuple a report can print. ``stops_at`` is where that walk gives way to the next collector
    — passed through rather than interpreted here. Derived on every read: a stored coverage
    list could disagree with the graph the moment ``dplanner step link`` runs with no window
    open to notice.
    """
    from dplanner.modules.testing.aspect import covered

    return [
        (test.id, test.title, step.title)
        for step, test in covered(library, project, step_id, stops_at=stops_at)
    ]


def _paste_policies() -> tuple["PastePolicy", ...]:
    """What a copied step may not carry verbatim, one policy per module that has a say.

    Assembled here because each policy lives in its owner's Qt-free half and no module may
    import another's; both the window's Paste/Duplicate and ``step duplicate`` read this
    tuple. Four entries, on purpose: an id minted per project (a test's), the state of a
    shell somebody is running and what its runs consumed — both facts about the
    original — and a feature's passages, which were read into *that* feature and are not
    a claim a copy may make. Everything else a step carries copies as it is.
    """
    from dplanner.modules.feature.aspect import drop_cites_for_paste
    from dplanner.modules.step_agent_run.aspect import forget_for_paste
    from dplanner.modules.step_agent_run.usage import forget_for_paste as forget_usage
    from dplanner.modules.testing.aspect import remint_for_paste

    return (remint_for_paste, forget_for_paste, forget_usage, drop_cites_for_paste)


def _source_kinds(
    folder: "DocumentSourceKind",
    git: "DocumentSourceKind",
    confluence_page: "DocumentSourceKind",
    confluence_folder: "DocumentSourceKind",
) -> tuple["DocumentSourceKind", ...]:
    """The document source kinds the Specs tab offers, in the + menu's order: what is on
    this computer first, then what is fetched. One seam: a test patches this to hand in a
    fake, so the whole tab is proven without Confluence.

    Named parameters rather than ``*kinds``: the order is the menu's, and a decision
    belongs in the function that owns it."""
    return (folder, git, confluence_page, confluence_folder)


def _keychain() -> "SecretStore":
    """The OS keychain as the Confluence module's four doors — the only place the
    secret store is named for it."""
    from dplanner.core import secrets
    from dplanner.modules.spec_confluence.module import SecretStore

    class Keychain(SecretStore):
        get = staticmethod(secrets.get_secret)
        set = staticmethod(secrets.set_secret)
        delete = staticmethod(secrets.delete_secret)
        problem = staticmethod(secrets.backend_problem)

    return Keychain()


def _machine_checks(*, files: "Callable[[], dict[str, str]]") -> tuple["MachineCheck", ...]:
    """What this machine has of what DPlanner needs, from every module that owns a row.

    The tuple both surfaces read — ``dplanner checklist show`` and *Tools ▸ Setup
    Checklist…* — assembled here for ``_asset_sources``' reason: each ``checks()`` lives in
    its owner's Qt-free half and no module may import another's. Order inside a group is
    the order they are listed; the group itself is ``cli/checklist.py``'s ``GROUPS``.

    ``files`` is the generated skill the installer's rows compare against — the same
    closure the Install dialog is handed.
    """
    from dplanner.modules.checklist import checks as generic
    from dplanner.modules.dictation import checks as dictation_checks
    from dplanner.modules.github import checks as github_checks
    from dplanner.modules.install import checks as install_checks
    from dplanner.modules.llm import checks as llm_checks
    from dplanner.modules.spec_confluence import checks as confluence_checks
    from dplanner.modules.step_agent_instruction import checks as agent_checks

    return (
        *install_checks.checks(files=files),
        *generic.checks(),
        *github_checks.checks(),
        *agent_checks.checks(harnesses=agent_harnesses()),
        *confluence_checks.checks(),
        # The provider modules' ids and labels: the keychain is asked under each module's
        # own id, and the llm module never learns which providers exist by importing them.
        *llm_checks.checks(providers=_llm_providers()),
        *dictation_checks.checks(providers=dictation_providers()),
    )


def _llm_providers() -> tuple[tuple[str, str], ...]:
    """``(module id, label)`` per AI provider module, in the order the settings page lists
    them — written literally, as ``_scope_kinds`` writes its predicates.

    Not imported from each provider: a provider module's ``MODULE_ID`` sits beside its SDK
    adapter, and reaching for it would load Qt in a CLI run. A test asserts the two agree.
    """
    return (("llm_openai", "OpenAI"), ("llm_anthropic", "Anthropic"))


def _lint_checks() -> tuple["LintCheck", ...]:
    """What a plan can be wrong about, from every module that knows a kind of wrong.

    One assembler, two surfaces — ``dplanner project lint`` and the window's Problems
    panel — because a gap in a plan is one fact whoever is asking, and a second list
    would be a second answer. ``cli/lint.py``'s arrangement exactly, and
    :func:`_machine_checks`'s: the verb owns the shapes and the report, each owning
    module exports ``lint_checks()`` from its own Qt-free ``cli.py``, and nothing here
    is imported by ``cli/``.

    The order is the report's order — the graph's integrity first, then authoring, then
    the spec.
    """
    from dplanner.cli.scopes import lint_checks as scope_lint
    from dplanner.modules.docs import cli as docs_cli
    from dplanner.modules.estimation import cli as estimation_cli
    from dplanner.modules.feature import cli as feature_cli
    from dplanner.modules.feature.aspect import is_feature
    from dplanner.modules.projects import cli as projects_cli
    from dplanner.modules.spec import cli as spec_cli
    from dplanner.modules.step_agent_instruction import cli as agent_cli
    from dplanner.modules.step_check.aspect import read as check_read
    from dplanner.modules.step_description import cli as description_cli
    from dplanner.modules.step_description.aspect import read as description_read
    from dplanner.modules.step_milestone.aspect import read as milestone_read
    from dplanner.modules.testing import cli as testing_cli
    from dplanner.modules.testing.aspect import enabled as test_enabled

    scopes = _scope_kinds(check_read, is_feature, milestone_read)
    return (
        *projects_cli.lint_checks(),
        *description_cli.lint_checks(),
        *docs_cli.lint_checks(kinds=scopes),
        # An agent step is briefed by its description unless it carries a separate
        # instruction; the description's reader arrives here, not by import.
        *agent_cli.lint_checks(described=lambda step: bool(description_read(step))),
        *estimation_cli.lint_checks(),
        *spec_cli.lint_checks(),
        *feature_cli.lint_checks(anchor=spec_cli.anchor_sources, key_of=_step_key),
        *testing_cli.lint_checks(),
        # A step's *own* tests are a different question from what it gathers; testing's
        # Qt-free reader answers it, handed over rather than imported.
        *scope_lint(
            kinds=scopes,
            covered_by=_covered_tests,
            carries_tests=test_enabled,
        ),
    )


def _asset_sources() -> tuple["AssetSource", ...]:
    """Every module's slice of the asset catalog, in reading order.

    The tuple both surfaces read — ``asset list``/``uses``/``prune`` and the Assets tab —
    assembled here because each ``asset_source()`` lives in its owner's Qt-free half and
    no module may import another's. The order is the report order: the prose surfaces a
    person writes first, then what rides along to agents, then the spec's figures, then
    the pool. A feature has no area of its own: its pictures are its step's description's.
    """
    from dplanner.modules.docs.aspect import asset_source as documentation
    from dplanner.modules.notes.log import asset_source as notes
    from dplanner.modules.project_assets.cli import asset_source as pool
    from dplanner.modules.spec.documents import asset_source as spec_figures
    from dplanner.modules.step_agent_instruction.aspect import asset_source as instructions
    from dplanner.modules.step_description.aspect import asset_source as descriptions
    from dplanner.modules.testing.aspect import asset_source as tests

    return (
        descriptions(),
        tests(),
        documentation(),
        instructions(),
        notes(),
        spec_figures(),
        pool(),
    )


def _rename_spec_references(project: "Project", name: str, chosen: str) -> list["Command"]:
    """What else in a project points at a spec document by its name, renamed with it.

    A feature's citation keys on the document's name — the one thing that must not go
    stale when the name moves, because a lost citation is a coverage answer that quietly
    changes. A feature is a step, so this walks the project's steps and writes only the
    ones that actually cited the old name. `modules/spec/` may not import
    `modules/feature/`, so the cross is here, and the commands ride in the rename's own
    undo entry — one per feature that moved, inside the one `CompositeCommand`.
    """
    from dataclasses import replace

    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.feature.aspect import MODULE_ID as FEATURE_ID
    from dplanner.modules.feature.aspect import read as feature_read
    from dplanner.modules.feature.aspect import write as feature_write

    commands: list[Command] = []
    for step in project.steps:
        cites = feature_read(step)
        if cites is None:
            continue  # Not a feature, so it cites nothing.
        moved = tuple(
            replace(cite, document=chosen) if cite.document == name else cite for cite in cites
        )
        if moved != cites:
            commands.append(SetModuleDataCommand(step.id, FEATURE_ID, feature_write(moved)))
    return commands


def default_cli_commands(gate: "TopologyGate | None" = None) -> list["CliCommand"]:
    """Every ``dplanner <noun> <verb>``, from the same modules the window is built from.

    The headless half of the composition root. It imports each module's ``cli.py`` and
    nothing else — no ``module.py``, no Qt — which is what lets ``dplanner project list``
    start in milliseconds and run where a graphics stack does not exist.

    ``gate`` is the topology gate every graph-editing verb runs behind; None builds the
    real one over the user's config directory. The test suite's shared registry passes a
    gate with no record file, so no test ever writes the per-user file.
    """
    from dplanner.cli.aspects import commands as aspect_commands
    from dplanner.cli.assets import catalog_commands
    from dplanner.cli.checklist import commands as checklist_commands
    from dplanner.cli.command import CliRegistry
    from dplanner.cli.desktop import commands as desktop_commands
    from dplanner.cli.gate import RECORD_FILE, TopologyGate, gated
    from dplanner.cli.install import commands as install_commands
    from dplanner.cli.lint import commands as lint_commands
    from dplanner.cli.report.commands import commands as report_commands
    from dplanner.cli.scopes import commands as scope_commands
    from dplanner.cli.skill import commands as skill_commands
    from dplanner.cli.skill import generate
    from dplanner.cli.telemetry import commands as telemetry_commands
    from dplanner.core.config_dir import config_dir
    from dplanner.core.telemetry import crash_log_path, journal_path
    from dplanner.modules.coverage import cli as coverage_cli
    from dplanner.modules.docs import cli as docs_cli
    from dplanner.modules.estimation import cli as estimation_cli
    from dplanner.modules.estimation.aspect import read as estimated_days
    from dplanner.modules.estimation.aspect import read_history as estimate_history
    from dplanner.modules.estimation.schedule import start_of
    from dplanner.modules.feature import cli as feature_cli
    from dplanner.modules.feature.aspect import is_feature
    from dplanner.modules.github import cli as github_cli
    from dplanner.modules.library import cli as library_cli
    from dplanner.modules.notes import cli as note_cli
    from dplanner.modules.progression import cli as progression_cli
    from dplanner.modules.project_assets import cli as assets_cli
    from dplanner.modules.project_assets.cli import read_titles
    from dplanner.modules.project_editor import cli as layout_cli
    from dplanner.modules.projects import cli as projects_cli
    from dplanner.modules.spec import cli as spec_cli
    from dplanner.modules.spec.aspect import read_topology
    from dplanner.modules.step_agent_instruction import cli as agent_cli
    from dplanner.modules.step_agent_instruction.aspect import enabled as agent_marked
    from dplanner.modules.step_agent_run import cli as agent_state_cli
    from dplanner.modules.step_check import cli as check_cli
    from dplanner.modules.step_check.aspect import read as check_read
    from dplanner.modules.step_description import cli as description_cli
    from dplanner.modules.step_milestone import cli as milestone_cli
    from dplanner.modules.step_milestone.aspect import read as milestone_read
    from dplanner.modules.step_order import cli as order_cli
    from dplanner.modules.step_status import cli as status_cli
    from dplanner.modules.step_status.aspect import read as step_status
    from dplanner.modules.step_ticket import cli as ticket_cli
    from dplanner.modules.testing import cli as testing_cli
    from dplanner.modules.time_estimates import cli as time_cli

    specs = aspect_specs()
    scopes = _scope_kinds(check_read, is_feature, milestone_read)
    sources = _asset_sources()
    if gate is None:
        gate = TopologyGate(record_path=config_dir() / RECORD_FILE, topology_of=read_topology)
    commands = [
        *library_cli.commands(),
        # The step authors let `step add` author the step in the same call; the list
        # order is the report order — the same order the skill teaches authoring in.
        *projects_cli.commands(
            step_authors=[
                description_cli.step_author(),
                agent_cli.step_author(),
                estimation_cli.step_author(),
                # The feature author carries the spec-passage flags: creating a feature
                # *is* creating its step, so there is no verb of its own to put them on.
                feature_cli.step_author(anchor=spec_cli.anchor_sources),
                spec_cli.step_author(),
                testing_cli.step_author(),
            ],
            # The key a row prints is the one the canvas paints: one rule, here.
            key_of=_step_key,
        ),
        # `topology show` tells the gate what it printed; the gate is built here, so the
        # spec module never learns where the record lives.
        *spec_cli.commands(note_read=gate.record, rename_references=_rename_spec_references),
        *estimation_cli.commands(),
        *ticket_cli.commands(),
        *description_cli.commands(),
        *docs_cli.commands(kinds=scopes),
        *agent_cli.commands(briefing=_default_briefing()),
        # What a run consumed is read through the harness that ran it, so the verbs are
        # handed the same tuple the window's tracker reads.
        *agent_state_cli.commands(harnesses=agent_harnesses()),
        *status_cli.commands(),
        *milestone_cli.commands(),
        # A feature's passages are anchored in the spec documents by the spec module's
        # one derivation, handed across here — `cite`, `reanchor`, `step add --feature`
        # and lint all judge a quote the same way.
        *feature_cli.commands(anchor=spec_cli.anchor_sources, key_of=_step_key),
        *testing_cli.commands(),
        *check_cli.commands(),
        # What any collector gathers is one derivation asked three ways, so it is one verb
        # rather than one per aspect. The kinds and the coverage walk arrive as arguments,
        # so cli/scopes.py imports no module and no module imports it.
        *scope_commands(kinds=scopes, covered_by=_covered_tests),
        # The coverage picture is every module's Qt-free half read once and arranged;
        # assembled here, so neither the verbs nor the tab import any of them.
        *coverage_cli.commands(trace_of=_coverage_trace),
        # The asset catalog is the same shape one level down: every file-carrying module
        # exports an asset_source(), the reports live in cli/assets.py, and the browser
        # module's own writes (attach, name) stay in its cli.py — the `scope` split.
        *catalog_commands(sources=sources, titles=read_titles),
        *assets_cli.commands(sources=sources),
        *order_cli.commands(days_for=estimated_days),
        # Progression reads statuses and estimates through the aspects' Qt-free readers —
        # handed over here so no cli.py imports another module's.
        *progression_cli.commands(status_for=step_status, days_for=estimated_days),
        # The timeline sort reads a step's length through estimation's Qt-free reader —
        # handed over here so neither cli.py imports the other.
        *layout_cli.commands(
            days_for=estimated_days,
            paste_policies=_paste_policies(),
            file_modules=tuple(source.id for source in sources),
            key_of=_step_key,
        ),
        # The staffing matrix reads estimates, agent-ness and the start date through the
        # owners' Qt-free readers — handed over here so no cli.py imports another module's.
        *time_cli.commands(
            days_for=estimated_days,
            is_agent=agent_marked,
            status_for=step_status,
            start_of=start_of,
            milestone_label=milestone_read,
            # What each estimate was before, for the change report — and the key every
            # row prints, the one rule.
            estimate_history=estimate_history,
            key_of=_step_key,
        ),
        *github_cli.commands(),
        # A note names the step it was made on by id and prints it by key — the
        # same rule every row prints, handed over rather than imported.
        *note_cli.commands(key_of=_step_key),
        # The report is every module's Qt-free say, assembled once (`_report_sources`) for
        # the terminal and the window alike; the readers every step row needs come with it.
        *report_commands(
            sources=_report_sources(),
            key_of=_step_key,
            kind_of=_step_kind,
            status_for=step_status,
        ),
        # The journal both surfaces write, read back: the paths are the process's, handed
        # over here so a test can point the same verbs at a file of its own.
        *telemetry_commands(journal=journal_path(), crash_log=crash_log_path()),
        *aspect_commands(specs),
        # Each module exports what "missing" means for its own aspect; the assembler is
        # shared with the window's Problems panel, which is a second presenter of exactly
        # this list.
        *lint_commands(checks=list(_lint_checks())),
    ]
    # Every verb that declared it reshapes a graph runs behind the topology gate. Wrapped
    # before the skill reads the registry, so the skill describes the gated verbs.
    commands = [gated(command, gate) for command in commands]
    # The desktop launcher's verbs: no module's, and no library's — the skill lists them.
    commands += desktop_commands()
    # The skill describes the registry it is registered into, so the loop is closed here
    # rather than by anything going looking for a registry at run time.
    described = CliRegistry()
    described.register_all(commands)
    skill = skill_commands(specs, described)
    described.register_all(skill)
    # The one act over the three pieces — the command, the launcher and the skill — reads
    # the same registry, and is registered into it so the skill it writes lists it too.
    installer = install_commands(specs, described)
    described.register_all(installer)
    # What this machine has, from every module that owns a row. The installer's rows read
    # the generated skill, so the checks are built over the registry the skill describes —
    # ``files`` is lazy, which is why registering the verb afterwards still lists it.
    checklist = checklist_commands(_machine_checks(files=lambda: generate(described, specs)))
    described.register_all(checklist)
    return [*commands, *skill, *installer, *checklist]


def _names_session(harness_id: str) -> bool:
    from dplanner.domain.agents import harness_by_id

    harness = harness_by_id(agent_harnesses(), harness_id)
    return harness is not None and harness.names_session


def agent_harnesses() -> tuple["AgentHarness", ...]:
    """Every agent CLI this build can launch, first is the default.

    One provider module per CLI, each exporting a Qt-free ``HARNESS`` — the command, how
    it resumes, the marks it leaves in its shells, and a reader of its own records. Read
    by Run Agent's launcher and settings page, by the run tracker's bookkeeping, by the
    CLI's ``usage`` verbs and by the entry point's shell guard: a fourth agent is a fourth
    module listed here and nothing else.
    """
    from dplanner.modules.agent_claude import harness as claude
    from dplanner.modules.agent_codex import harness as codex
    from dplanner.modules.agent_opencode import harness as opencode

    return (claude.HARNESS, codex.HARNESS, opencode.HARNESS)


def dictation_providers() -> tuple["DictationProvider", ...]:
    """Every dictation engine this build can transcribe with, first is what a fresh
    profile tries first.

    The whisper commands lead — local and free — then OpenAI's live session and its batch
    endpoint, on the key the OpenAI module keeps. Each is a Qt-free record from its own
    module; the service, Settings ▸ Dictation and the checklist all read this tuple, and a
    fourth engine is a fourth module listed here and nothing else.
    """
    from dplanner.modules.dictation_whisper import dictation as whisper
    from dplanner.modules.llm_openai import dictation as openai_dictation

    return (*whisper.providers(), openai_dictation.LIVE, openai_dictation.BATCH)


def theme_providers() -> tuple["ThemeProvider", ...]:
    """Every theme provider this build has, first is the default.

    The built-in first: the fallback every build has, and the head of the Theme menu.
    Then the following providers in the order "System theme" is served in — Omarchy before
    the desktop's own dark or light, because the first that applies on this machine
    serves it and Omarchy knows the whole palette where the desktop knows only the
    polarity. Called once, in ``app.main`` after the ``QApplication`` exists and before
    any theme is applied, and handed to both the startup apply and the session — every
    later reader takes the tuple from ``ThemeService``. The desktop's readings are Qt's,
    so they are wired here: the scheme as it stands now is read at this call, since the
    live reading echoes the application's own override once one is set, and so is the
    accent, before the application's own palette replaces the platform's.
    """
    import sys

    from PySide6.QtGui import QGuiApplication

    from dplanner.modules.theme_omarchy.themes import omarchy_provider
    from dplanner.modules.theme_system.themes import system_provider
    from dplanner.theme.providers import BUILTIN

    def scheme() -> str:
        return QGuiApplication.styleHints().colorScheme().name.lower()

    at_start = scheme()
    accent = (
        QGuiApplication.palette().accent().color().name()
        if sys.platform in ("darwin", "win32")
        else None
    )
    desktop = system_provider(
        sys.platform, scheme_at_start=lambda: at_start, scheme=scheme, accent=lambda: accent
    )
    return (BUILTIN, omarchy_provider(), desktop)


def aspect_specs() -> list["AspectSpec"]:
    """Every step aspect this build knows about.

    What ``dplanner aspect list`` prints and the generated skill describes — the entry point
    an agent uses to find out what a step can carry. Each package declares its own ``SPEC``;
    this is only the list of packages, in the order a person would read them.
    """
    from dplanner.modules.docs import aspect as docs
    from dplanner.modules.estimation import aspect as estimation
    from dplanner.modules.feature import aspect as feature
    from dplanner.modules.github import aspect as github
    from dplanner.modules.spec import aspect as spec
    from dplanner.modules.step_agent_instruction import aspect as agent
    from dplanner.modules.step_agent_run import aspect as agent_run
    from dplanner.modules.step_agent_run import usage as agent_usage
    from dplanner.modules.step_check import aspect as check
    from dplanner.modules.step_description import aspect as description
    from dplanner.modules.step_milestone import aspect as milestone
    from dplanner.modules.step_status import aspect as status
    from dplanner.modules.step_ticket import aspect as ticket
    from dplanner.modules.testing import aspect as testing

    return [
        agent.SPEC,
        agent_run.SPEC,
        agent_usage.SPEC,
        check.SPEC,
        description.SPEC,
        docs.SPEC,
        docs.COMPILED_SPEC,
        estimation.SPEC,
        feature.SPEC,
        github.SPEC,
        milestone.SPEC,
        spec.SPEC,
        status.SPEC,
        testing.SPEC,
        ticket.SPEC,
    ]


# Row phrases lead with where a step *stands* (status, agent run, milestone) before what it
# *carries*. Only a preference: an aspect not named here still appears, after these, in
# aspect_specs() order — so a new aspect reaches every step row without editing this list.
_PHRASE_ORDER = (
    "step_status",
    "step_agent_run",
    "step_milestone",
    "feature",
    "estimation",
    "step_ticket",
    "github",
    "spec",
    "step_description",
    "step_agent_instruction",
)


def aspect_summaries(skip: "Container[str]" = ()) -> list[Callable[["Step"], str]]:
    """Each aspect's one-phrase description of a step, for whoever renders a step row.

    A projection of :func:`aspect_specs` — the ``phrase`` on each SPEC — so an aspect
    cannot exist without a row presence. ``skip`` is for a surface that already shows one
    of them in a column of its own — the order table and its Estimate column — so the
    phrase is not printed twice.
    """
    specs = {spec.id: spec for spec in aspect_specs()}
    ordered = [specs.pop(aspect_id) for aspect_id in _PHRASE_ORDER if aspect_id in specs]
    ordered += specs.values()
    return [spec.phrase for spec in ordered if spec.id not in skip]


def default_module_formats() -> list[ModuleDataFormat]:
    """Every module data format, for the CLI to migrate with.

    The GUI gets these from the module objects themselves (``AppBuilder`` reads
    ``data_format`` off anything that declares one). The CLI never builds those objects, so
    the same list has to be reachable without them — and it must stay complete, because a
    format missing here is data the CLI silently declines to bring forward.
    """
    from dplanner.domain import shelf
    from dplanner.modules.notes import migrate as notes
    from dplanner.modules.project_assets import cli as project_assets
    from dplanner.modules.project_editor import positions
    from dplanner.modules.time_estimates import progress as time_progress
    from dplanner.modules.time_estimates import schedule as time_schedule

    # The aspects, plus the module data that is not an aspect: the graph's node positions,
    # the time report's focus factor and the asset browser's display titles. Deriving this
    # list from aspect_specs() alone would silently omit them. A project's start date
    # needs no entry: it rides on the estimation aspect's format, which is the same module
    # writing under the same id on another node.
    # The shelf is the fourth: the domain's own, holding turned-off aspects' data. The
    # note log and the progress history are the fifth and sixth — project records no
    # step aspect declares; the log's format also carries the takeover of the retired
    # decision log and the absorption of the retired handoff aspect.
    return [spec.data_format for spec in aspect_specs()] + [
        positions.DATA_FORMAT,
        time_schedule.DATA_FORMAT,
        time_progress.DATA_FORMAT,
        project_assets.DATA_FORMAT,
        shelf.DATA_FORMAT,
        notes.DATA_FORMAT,
    ]
