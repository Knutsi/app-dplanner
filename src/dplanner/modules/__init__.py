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

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from dplanner.core.module_data import ModuleDataFormat

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from argparse import Namespace
    from collections.abc import Callable, Container, Mapping, Sequence
    from datetime import date
    from pathlib import Path

    from PySide6.QtGui import QIcon

    from dplanner.cli import CliCommand, CliContext
    from dplanner.cli.checklist import MachineCheck
    from dplanner.cli.gate import ReadRecord
    from dplanner.cli.lint import LintCheck
    from dplanner.cli.report.parts import ReportSource
    from dplanner.cli.report.website import SiteTarget
    from dplanner.domain.agents import AgentHarness
    from dplanner.domain.aspects import AspectSpec
    from dplanner.domain.assets import AssetSource
    from dplanner.domain.at_work import AtWorkBoard
    from dplanner.domain.branches import Reading as BranchReading
    from dplanner.domain.commands import Command
    from dplanner.domain.dictation import DictationProvider
    from dplanner.domain.expenditure import Rate, Spent
    from dplanner.domain.locations import Location, LocationRole, ManagedFor
    from dplanner.domain.model import Edge, Library, LinkRule, Project, ProjectId, Step, StepId
    from dplanner.domain.ordering import Placed
    from dplanner.domain.repositories import RepositoryFacts
    from dplanner.domain.scope import ScopeKind
    from dplanner.domain.store import FilesFor, LibraryStore, ModuleFileArea
    from dplanner.domain.workflow import Actor, EndClaim, PlanView
    from dplanner.framework.mime_files import Payload
    from dplanner.framework.module import Module
    from dplanner.framework.services import AppServices
    from dplanner.modules.coverage.trace import Trace
    from dplanner.modules.feature.aspect import FeatureSource
    from dplanner.modules.project_editor.clipboard import PastePolicy
    from dplanner.modules.spec.source_kind import DocumentSourceKind
    from dplanner.modules.spec_confluence.module import SecretStore
    from dplanner.modules.step_agent_instruction.auto_launch import LaunchLocks
    from dplanner.modules.step_agent_instruction.launcher import BranchPlan
    from dplanner.modules.step_agent_instruction.prompt import Briefing, PromptPart
    from dplanner.modules.step_review.rounds import TurnDue
    from dplanner.modules.step_status.workflows import StatusWorkflow
    from dplanner.modules.time_estimates.cli import Readers as TimeReaders
    from dplanner.modules.time_estimates.simulation.frames import Writers as TimeWriters
    from dplanner.planning.schedule import Scheduled
    from dplanner.planning.status import Reading, Status, Unknown
    from dplanner.theme.providers import ThemeProvider

__all__ = [
    "agent_harnesses",
    "aspect_specs",
    "at_work_board",
    "auto_launch_directory",
    "default_cli_commands",
    "default_module_formats",
    "default_modules",
    "dictation_providers",
    "launch_locks_in",
    "start_window",
    "theme_providers",
]


def default_modules(
    services: "AppServices",
    board: "AtWorkBoard | None" = None,
    launch_locks: "LaunchLocks | None" = None,
) -> list["Module"]:
    from pathlib import Path

    from dplanner.cli.report.website import SiteTarget
    from dplanner.core.clock import Clock
    from dplanner.core.config_dir import config_dir
    from dplanner.core.storage.git import GitStorage
    from dplanner.core.storage.github import GitHubStorage
    from dplanner.core.storage.kept import clone_full
    from dplanner.core.storage.locations import find_repo_root, origin_url, repo_storage
    from dplanner.core.storage.provider import StorageError, VersionedStorage
    from dplanner.domain.commands import (
        Command,
        CompositeCommand,
        EditTextCommand,
        SetModuleDataCommand,
    )
    from dplanner.domain.locations import Placement, roles_by_id
    from dplanner.domain.model import Library, Project, TextEdit
    from dplanner.domain.relocate import move_project
    from dplanner.domain.repositories import RepositoryFacts, repository_facts
    from dplanner.domain.store import LibraryStore
    from dplanner.framework.aspect_bar import AspectTemplate
    from dplanner.framework.context import (
        SCOPE_SELECTION,
        Context,
        ContextNode,
        ContextService,
        selection_uri,
    )
    from dplanner.framework.debounce import DebounceService
    from dplanner.framework.side_panel import SidePanel
    from dplanner.framework.undo import UndoService
    from dplanner.modules.agent_at_work.module import AgentAtWorkDeps, AgentAtWorkModule
    from dplanner.modules.anthropic.module import LlmAnthropicDeps, LlmAnthropicModule
    from dplanner.modules.appearance.module import AppearanceDeps, AppearanceModule
    from dplanner.modules.appshell.module import AppShellDeps, AppShellModule
    from dplanner.modules.auto_progress.module import AutoProgressDeps, AutoProgressModule
    from dplanner.modules.branches.module import BranchesDeps, BranchesModule, LandingModule
    from dplanner.modules.checklist.module import ChecklistDeps, ChecklistModule
    from dplanner.modules.coverage.activity import CoverageDeps
    from dplanner.modules.coverage.module import CoverageModule
    from dplanner.modules.debug.module import DebugDeps, DebugModule
    from dplanner.modules.dictation.module import DictationDeps, DictationModule
    from dplanner.modules.docs.module import DocsCompiledModule, DocsDeps, DocsModule
    from dplanner.modules.estimation.aspect import MODULE_ID as ESTIMATION_ID
    from dplanner.modules.estimation.aspect import read as estimated_days
    from dplanner.modules.estimation.aspect import write as estimate_write
    from dplanner.modules.estimation.module import EstimationDeps, EstimationModule
    from dplanner.modules.estimation.schedule import start_of, write_start
    from dplanner.modules.feature.aspect import MODULE_ID as FEATURE_ID
    from dplanner.modules.feature.aspect import is_feature
    from dplanner.modules.feature.aspect import read as feature_read
    from dplanner.modules.feature.module import FeatureDeps, FeatureModule
    from dplanner.modules.github.aspect import PR_CLOSED, PR_MERGED, PR_OPEN, pr_label
    from dplanner.modules.github.aspect import read as github_read
    from dplanner.modules.github.module import GithubDeps, GithubModule
    from dplanner.modules.home.module import HomeDeps, HomeModule
    from dplanner.modules.install.module import InstallDeps, InstallModule
    from dplanner.modules.library.module import LibraryDeps, LibraryModule
    from dplanner.modules.library_watch.module import LibraryWatchDeps, LibraryWatchModule
    from dplanner.modules.llm.module import LlmDeps, LlmModule
    from dplanner.modules.notes.module import NotesDeps, NotesModule
    from dplanner.modules.openai.module import LlmOpenAIDeps, LlmOpenAIModule
    from dplanner.modules.problems.module import ProblemsDeps, ProblemsModule
    from dplanner.modules.progression.module import (
        ProgressionDeps,
        ProgressionModule,
        StripVerb,
    )
    from dplanner.modules.project_assets.module import (
        ProjectAssetsDeps,
        ProjectAssetsModule,
    )
    from dplanner.modules.project_editor.module import ProjectEditorDeps, ProjectEditorModule
    from dplanner.modules.project_editor.renderers import EdgeAccent, NodeAccent
    from dplanner.modules.project_editor.verbs import picked_edges
    from dplanner.modules.projects.checkouts import CheckoutService
    from dplanner.modules.projects.location_dialog import ask_location
    from dplanner.modules.projects.module import ProjectEntry, ProjectsDeps, ProjectsModule
    from dplanner.modules.projects.repos import (
        LogEntry,
        PullRequest,
        RepoLog,
        RepositoryServices,
    )
    from dplanner.modules.reopen_tabs.module import ReopenTabsDeps, ReopenTabsModule
    from dplanner.modules.reporting.module import ReportingDeps, ReportingModule
    from dplanner.modules.reporting.roles import ROLE as REPORTING_ROLE
    from dplanner.modules.settings.module import SettingsDeps, SettingsModule
    from dplanner.modules.spec.aspect import MODULE_ID as SPEC_ID
    from dplanner.modules.spec.cli import digest_of as spec_digest_of
    from dplanner.modules.spec.cli import document_names as spec_document_names
    from dplanner.modules.spec.module import SpecDeps, SpecModule
    from dplanner.modules.spec.module import open_url as open_in_browser
    from dplanner.modules.spec_confluence.module import SpecConfluenceDeps, SpecConfluenceModule
    from dplanner.modules.spec_folder.module import SpecFolderKind
    from dplanner.modules.spec_git.module import SpecGitDeps, SpecGitKind
    from dplanner.modules.spec_git.source import SPEC_GIT_CACHE, probe
    from dplanner.modules.step_agent_instruction.aspect import MODULE_ID as AGENT_INSTRUCTION_ID
    from dplanner.modules.step_agent_instruction.aspect import enabled as agent_enabled
    from dplanner.modules.step_agent_instruction.aspect import read as agent_instruction_read
    from dplanner.modules.step_agent_instruction.aspect import (
        separate_instruction as agent_separate,
    )
    from dplanner.modules.step_agent_instruction.aspect import write_state as agent_write_state
    from dplanner.modules.step_agent_instruction.auto_launch import Due
    from dplanner.modules.step_agent_instruction.module import (
        RUN_MENU_ID,
        StepAgentInstructionDeps,
        StepAgentInstructionModule,
    )
    from dplanner.modules.step_agent_instruction.profiles import default_profile
    from dplanner.modules.step_agent_run.aspect import (
        LAUNCHED,
        NEEDS_INPUT,
        PENDING_APPROVAL,
        PLAN_FOR_REVIEW,
        WORKING,
    )
    from dplanner.modules.step_agent_run.aspect import read as agent_run_state
    from dplanner.modules.step_agent_run.module import StepAgentRunDeps, StepAgentRunModule
    from dplanner.modules.step_check.module import StepCheckDeps, StepCheckModule
    from dplanner.modules.step_description.aspect import read as description_read
    from dplanner.modules.step_description.module import (
        StepDescriptionDeps,
        StepDescriptionModule,
    )
    from dplanner.modules.step_description.section import SeparateInstructionLink
    from dplanner.modules.step_milestone.aspect import is_milestone
    from dplanner.modules.step_milestone.aspect import read as milestone_read
    from dplanner.modules.step_milestone.module import StepMilestoneDeps, StepMilestoneModule
    from dplanner.modules.step_order.module import StepOrderDeps, StepOrderModule
    from dplanner.modules.step_properties.module import (
        StepPropertiesDeps,
        StepPropertiesModule,
    )
    from dplanner.modules.step_review.module import (
        ReviewRoundsModule,
        StepReviewDeps,
        StepReviewModule,
    )
    from dplanner.modules.step_start.module import StepStartDeps, StepStartModule
    from dplanner.modules.step_status.module import StepStatusDeps, StepStatusModule
    from dplanner.modules.step_ticket.module import StepTicketDeps, StepTicketModule
    from dplanner.modules.step_wait.aspect import read as wait_read
    from dplanner.modules.step_wait.aspect import stat as wait_stat
    from dplanner.modules.step_wait.module import StepWaitDeps, StepWaitModule
    from dplanner.modules.sync.module import SyncDeps, SyncModule
    from dplanner.modules.taskcenter.module import TaskCenterDeps, TaskCenterModule
    from dplanner.modules.testing.aspect import read as tests_read
    from dplanner.modules.testing.module import TestsDeps, TestsModule
    from dplanner.modules.time_estimates.debugger import TimeSimulationDeps, TimeSimulationModule
    from dplanner.modules.time_estimates.module import (
        ProgressHistoryModule,
        TimeEstimatesDeps,
        TimeEstimatesModule,
    )
    from dplanner.planning.schedule import Wait, format_days, schedule
    from dplanner.planning.status import (
        Status,
        readiness_of,
        record_merged,
        record_started,
        stored,
        word,
    )
    from dplanner.theme.icons import (
        clock_icon,
        coverage_icon,
        gauge_icon,
        graph_icon,
        image_icon,
        list_icon,
        problem_icon,
        spark_icon,
        spec_icon,
    )
    from dplanner.theme.tones import STEP_STATUS_TONES

    library: Library = services.document
    # What may link to what, beyond the graph's own four refusals — the same rules the CLI's
    # library asks (`default_link_rules`), so a drop and `step link` refuse alike. A reload
    # builds a new library and comes back through here; a refresh keeps this one.
    library.link_rules = default_link_rules()
    # The composition root knows the concrete store, exactly as it knows the concrete
    # document — modules reach a file area only through the typed callback on their Deps.
    store = services.repo
    assert isinstance(store, LibraryStore)

    def project_dir_of(step_id: str) -> "Path":
        return store.project_dir(library.project_of(step_id).id)

    roles = roles_by_id(default_location_roles())
    managed = managed_for(roles)

    def facts_of(project_id: str) -> RepositoryFacts:
        """The plan repository and every location of a project placed against this
        machine's checkouts — the one derivation every seam below reads."""
        return repository_facts(
            library.project(project_id),
            store.project_dir(project_id),
            store.checkouts(),
            managed=managed,
            kept_root=config_dir(),
        )

    def facts_for(node_id: str) -> RepositoryFacts:
        """The facts for a step — or for a project named directly, which is what a run
        with no step (the Problems panel's) has to ask about."""
        node = library.node(node_id)
        return facts_of(node.id if isinstance(node, Project) else library.project_of(node_id).id)

    def reporting_placement(project_id: str) -> "Placement | None":
        """The project's reporting row placed on this machine — a checkout, the person's
        or one DPlanner keeps — or None: it names none, or nothing here has it yet."""
        placement = facts_of(project_id).of_role(REPORTING_ROLE.id)
        return placement if placement is not None and placement.here else None

    def reporting_site(project_id: str) -> "SiteTarget | None":
        """Where the project publishes instead of beside its plan, when it does."""
        placement = reporting_placement(project_id)
        if placement is None or placement.root is None or placement.directory is None:
            return None
        return SiteTarget(placement.root, placement.directory)

    def reporting_dir(project_id: str) -> "Path | None":
        site = reporting_site(project_id)
        return site.site if site is not None else None

    def repository_for(step_id: str) -> str:
        """Which repository a step's GitHub refs belong to: the code repository the
        project records, else — the older shape, a plan kept beside its code — the plan's
        own origin, and none while the code is not set. Git's answer either way; nothing
        stored can disagree with it."""
        return facts_for(step_id).code_remote

    # A checkout recorded for a repository — by the Project dialog, or by an agent's
    # first `dplanner` call from the code and adopted through the library file — is what
    # turns Run Agent from greyed to runnable, and nothing in the context graph changed.
    store.checkout_changed.connect(lambda _repository: services.context.refresh())

    # -- git and GitHub for the project surfaces ----------------------------------------
    # The Project dialog, Open Project and Move Plan reach both
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
            if row.state == PR_OPEN
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

    def connect_project(directory: Path) -> Project:
        from dplanner.modules.library.membership import LIBRARY_ORIGIN

        project = store.attach(directory)
        library.add_child(library.id, project, origin=LIBRARY_ORIGIN)
        return project

    # The store lets go first, then the model: sync rewires its repository groups on the
    # structure signal, and reads them from the store's records.
    def disconnect_project(project_id: str) -> None:
        from dplanner.modules.library.membership import LIBRARY_ORIGIN

        store.detach(project_id)
        library.remove_child(project_id, origin=LIBRARY_ORIGIN)

    def archive_project(project_id: str) -> None:
        from dplanner.modules.library.membership import LIBRARY_ORIGIN

        store.archive(project_id)
        library.remove_child(project_id, origin=LIBRARY_ORIGIN)

    repos = RepositoryServices(
        facts_of=facts_of,
        roles=roles,
        project_dir=store.project_dir,
        checkout_for=store.checkout_for,
        set_checkout=store.set_checkout,
        checkout_changed=store.checkout_changed,
        plan_roots=plan_roots,
        pr_steps=pr_steps,
        history_for=history_for,
        gh_refusal=gh_refusal,
        list_repositories=GitHubStorage.list_repositories,
        clone=lambda repo, dest: (GitHubStorage.clone(repo, dest), None)[1],
        clone_url=clone_full,
        publish=publish,
        create_repository=create_repository,
        open_prs=open_prs,
        # The git spec source's listing, worn by a location's position: folders only,
        # no file downloaded, into the same per-user cache.
        list_folders=lambda url, ref: probe(config_dir() / SPEC_GIT_CACHE, url, ref),
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
        if not is_milestone(step):
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
                write_project(project, today=services.clock.today(), palette_id=palette_id),
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
        status_for = _ready_in(library, services.clock.today())
        strips = _strips(branches.reading_of(project))
        return {
            step.id: step_accent(
                step,
                stats.get(step.id, ""),
                colors.get(step.id, ""),
                flagged=step.id in flagged,
                pulse=_persons_turn(library, step, status_for),
                strip=strips.get(step.id, ("", "")),
            )
            for step in project.steps
        }

    def edge_accents(project_id: str) -> "dict[Edge, EdgeAccent]":
        """How the arrows of a project look beyond their kind: an auto-progress link is
        doubled — the frontier's own answer, so the canvas draws what progression does —
        and its chevrons flow while its source wears the live ring: the motion the source's
        agent run already has, carried to the step that will take its work. A link into a
        review — doubled by that same answer — also wears the review's talk bubble at its
        middle: the work on this arrow is about to be talked over. And every arrow of work
        on a feature branch not yet landed lies on that branch's lane."""
        from dataclasses import replace

        from dplanner.modules.step_review.aspect import reviews

        project = library.project(project_id)
        accents = {
            (waiter.id, "requires", source.id): EdgeAccent(
                doubled=True,
                flowing=bool(agent_run_state(source)),
                medallion="review" if reviews(waiter, source) else "",
            )
            for waiter in project.steps
            for source in library.requires(waiter.id)
            if _auto_progresses(waiter, source)
        }
        for edge, color in _lanes(library, branches.reading_of(project)).items():
            accents[edge] = replace(accents.get(edge, EdgeAccent()), lane=color)
        return accents

    def step_accent(
        step: "Step",
        milestone_stat: str,
        milestone_color: str = "",
        *,
        flagged: bool = False,
        pulse: bool = False,
        strip: tuple[str, str] = ("", ""),
    ) -> "NodeAccent":
        """How a step looks on the canvas, translated from aspects the canvas never learns.


        A done step is muted with a green body — finished work recedes into a colour the
        eye can skip; the key block down the card's left carries the step's key under who
        works it (:func:`_primary_glyph`) and is shaded by status — busy for in-progress,
        warn for ready-for-review, good for ready-to-merge and done, bad for blocked, quiet
        otherwise, and quiet for a wait, which has none (:func:`_card_status`); a milestone is a
        purple-highlighted node wearing its label as a badge, a tag medallion and the
        schedule's accumulated days and date as its stat (done outranks it on the body — a
        shipped milestone reads finished, and the tag still says what it was); a PR is a
        pill with its state as a tone and a branch the fork glyph; a live agent run is the
        chip on the bottom edge; a plain step's stat is its own estimate; a step a person
        moves next pulses (:func:`_persons_turn`). The card says nothing in words beyond its
        title and its key — every aspect it wears is one of these, never a phrase — but for
        the one name a person has to read: the feature branch its work goes onto, in a
        strip under the body (``strip`` is the branch and its lane colour, :func:`_strips`).
        """
        refs = github_read(step)

        pill = ""
        if refs is not None and refs.has_pr():
            pill = pr_label(refs)
        chip_text, chip_tone = {
            LAUNCHED: ("launched", "info"),
            WORKING: ("working", "info"),
            PLAN_FOR_REVIEW: ("plan ready", "attention"),
            PENDING_APPROVAL: ("needs approval", "attention"),
            NEEDS_INPUT: ("needs input", "attention"),
        }.get(agent_run_state(step), ("", ""))
        status = _card_status(step)
        milestone = milestone_read(step)
        wait = wait_read(step)
        key_glyph, key_glyph_tone = _primary_glyph(step)
        if milestone:
            stat = milestone_stat
        elif wait is not None:
            stat = wait_stat(wait, services.clock.today())  # How long it holds.
        else:
            days = estimated_days(step)
            stat = format_days(days) if days is not None else ""
        return NodeAccent(
            muted=status is Status.DONE,
            badge=milestone,
            pill_text=pill,
            pill_tone={PR_MERGED: "good", PR_CLOSED: "bad"}.get(refs.pr_state, "") if refs else "",
            branch=bool(refs is not None and refs.branch),
            key_text=_step_key(step),
            key_tone=STEP_STATUS_TONES.get(word(status), ""),
            key_glyph=key_glyph,
            key_glyph_tone=key_glyph_tone,
            chip_text=chip_text,
            chip_tone=chip_tone,
            # Done outranks a kind, and a milestone outranks a feature: the coarser claim
            # wins the body, and the medallion still says what the node also is.
            body_tone=(
                "good"
                if status is Status.DONE
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
            # A person moves this step next: the card breathes in its key block's tone.
            pulse=pulse,
            stat_text=stat,
            stat_strong=bool(milestone),
            strip=strip[0],
            strip_tone=strip[1],
        )

    def step_schedule(project_id: str, order: "Sequence[Placed]") -> "list[Scheduled]":
        """The order carrying days and dates: the domain's walk, over one module's numbers.

        The domain never learns where an estimate is stored — it is handed a function that
        answers for a step — and the order view never learns that estimates exist.
        """
        return schedule(order, estimated_days, start_of(library.project(project_id)))

    def branch_seats(step_ids: "Sequence[str]", cut: "Step", land: "Step") -> "list[Command]":
        """Where Put on a Branch's two new cards stand: the cut a column left of the picked
        card furthest left, the landing a column right of the one furthest right — when those
        were placed by hand; otherwise the ambient layout places them, as it does the rest."""
        from dplanner.modules.project_editor.positions import MODULE_ID as POSITION_ID
        from dplanner.modules.project_editor.positions import read_position, write_position
        from dplanner.modules.project_editor.sorts import H_PITCH

        placed = [where for s in step_ids if (where := read_position(library.step(s)))]
        if not placed:
            return []
        left, right = min(placed), max(placed)
        return [
            SetModuleDataCommand(cut.id, POSITION_ID, write_position(left[0] - H_PITCH, left[1])),
            SetModuleDataCommand(
                land.id, POSITION_ID, write_position(right[0] + H_PITCH, right[1])
            ),
        ]

    # Constructed before the list because the briefing reads its cached stretches: Run
    # Agent's state asks which branch a step is on at every announce.
    branches = BranchesModule(
        BranchesDeps(
            library=library,
            undo=services.undo,
            actions=services.actions,
            details=services.step_details,
            is_done=_is_done,
            is_agent=_is_agent_step,
            stacked_apart=_stacked_apart,
            born=_branch_births,
            seats=branch_seats,
            key_of=_step_key,
            parent=services.window,
        )
    )

    # The one briefing both the window and the CLI assemble from — see _default_briefing.
    briefing = _default_briefing(read=branches.reading_of)

    # Modules constructed before the list, because what each one hands the others reads
    # better as wiring than as ordering:
    #
    #   step_properties  owns THE step editor — `steps.details`, a modal and nothing else
    #   project_editor   opens projects into graph tabs
    #   projects         puts projects in the index and opens them through the one above
    #   estimation       owns the estimate, the start date and the bulk Estimates tab; the
    #                    order view hosts its bar
    #
    # None of them imports any other. Construction is side-effect-free, so ordering here is
    # about legibility; what matters at run time is that the aspect modules have registered
    # their sections before step_properties builds a dialog, which is a position in the list
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
                # A review is an agent step whose work is reading another's.
                AspectTemplate(
                    "Review",
                    frozenset(
                        {"agent.toggle", "review.toggle", "description.toggle", "estimate.toggle"}
                    ),
                    tone="info",
                    glyph="review",
                ),
                AspectTemplate(
                    "Check", frozenset({"check.toggle", "description.toggle"}), glyph="shield"
                ),
                # A wait carries no estimate and no description: how long it holds is its
                # size, and there is nothing to do.
                AspectTemplate("Wait", frozenset({"wait.toggle"}), glyph="clock"),
                # A cut is nobody's work either; a landing is an agent step that closes one.
                AspectTemplate("Branch cut", frozenset({"cut.toggle"}), glyph="branch"),
                AspectTemplate(
                    "Landing",
                    frozenset({"agent.toggle", "land.toggle", "estimate.toggle"}),
                    tone="info",
                    glyph="merge",
                ),
            ),
            library=library,
            undo=services.undo,
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

    def insert_wait_before(step_id: str) -> None:
        """Step ▸ Insert Wait Before: a wait of a working day in front of the step — it takes
        over what the step waited on, and the step waits on it — as the *Wait* template makes
        one (no estimate, no description), and one undo entry like every other placed step.
        A loose step's wait lands a column to its left where the step was placed; a stacked
        step's joins its stack in its slot, where the column seats it."""
        from dplanner.modules.project_editor.positions import read_position
        from dplanner.modules.project_editor.sorts import H_PITCH
        from dplanner.modules.step_description.aspect import MODULE_ID as DESCRIPTION_ID
        from dplanner.modules.step_description.aspect import write_state as description_state
        from dplanner.modules.step_wait.aspect import MODULE_ID as WAIT_ID
        from dplanner.modules.step_wait.aspect import write as write_wait

        where = read_position(library.step(step_id))
        project_editor.create_step(
            library.project_of(step_id).id,
            "Wait",
            at=(where[0] - H_PITCH, where[1]) if where is not None else None,
            carrying=lambda wait: [
                SetModuleDataCommand(wait.id, WAIT_ID, write_wait(Wait(days=1.0))),
                SetModuleDataCommand(wait.id, ESTIMATION_ID, estimate_write(None, on=False)),
                SetModuleDataCommand(wait.id, DESCRIPTION_ID, description_state(False)),
            ],
            label="Insert Wait",
            before=step_id,
        )

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
            fix_profiles=lambda: agent_instruction.plan_profiles(),
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
            theme=services.theme,
            files=store.files,
            file_modules=tuple(source.id for source in _asset_sources()),
            paste_policies=_paste_policies(),
            step_accents=step_accents,
            accents_changed=problems.findings.flagged_changed,
            edge_accents=edge_accents,
            # The cards that wear a branch strip, from the same reading their accents are.
            strips=lambda project_id: frozenset(
                _strips(branches.reading_of(library.project(project_id)))
            ),
            # The timeline sort reads a step's length through this seam; estimation owns it.
            days_for=estimated_days,
            # What stands beside the canvas: what is wrong with this plan, where it is
            # fixed. The editor never learns whose widget it is — only that it may carry
            # a reading for the button that opens it.
            side_panel=SidePanel("Problems", problem_icon, problems.create_panel),
        )
    )
    # The collectors, wired once: the docs and tests modules group by them, and every walk
    # either module makes stops where these say.
    scopes = _scope_kinds()

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
        holders = [step] if is_feature(step) else _flows_into(library, project, step_id)
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
                library.has(step_id) and is_milestone(library.step(step_id))
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
            roles=roles,
            # From Repository…: the projects module's location dialog for a spec row,
            # so a spec author names their repository from the Specs tab itself.
            ask_location=lambda project_id, role_id: ask_location(
                roles[role_id],
                project=library.project(project_id),
                library=library,
                services=repos,
                tasks=services.tasks,
                theme=services.theme,
                parent=services.window,
            ),
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
    # Constructed before the list because the projects index opens the tab through it.
    # Its strip seats verbs other modules own, named here by id — Run Agent, worded as the
    # verb the tab leads with, with the Step menu's own profiles under its arrow, then the
    # status verbs a person moves finished work on with — so neither module knows the
    # other's name.
    progression = ProgressionModule(
        ProgressionDeps(
            library=library,
            debounce=services.debounce,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            segments=services.index_segments,
            # The statuses through the status aspect's Qt-free reader — the tab never
            # learns what one is stored as — with a wait done once it is over, on the
            # clock's day, which the tabs re-run on when it turns.
            status_for=readiness_of(_wait_aware(library, services.clock.today)),
            clock=services.clock,
            counts_as_work=_counts_as_work,
            # A step that collects its sources' work is ready once they are under review.
            auto_progresses=_auto_progresses,
            # An agent that waits on a person is a row of its own: Waits for you.
            asks_person=_asks_person,
            # Work under review an agent takes on is that agent's, not a person's row —
            # the same answer the canvas pulses by (step_accents above).
            is_agent=_is_agent_step,
            verbs=(
                StripVerb("agent.run", data_menu=RUN_MENU_ID, face="Run Agents"),
                StripVerb("status.ready-to-merge"),
                StripVerb("status.done"),
            ),
            # A milestone's row leads with its key in its own shade: the group already says
            # where the work stands, so the one colour that is not a status says what the
            # work is leading to.
            milestone_badge=milestone_badge,
            key_of=_step_key,
            # Who works the step, as its key block and Find's rows say it.
            glyph_of=lambda step: _primary_glyph(step)[0],
        )
    )
    estimation = EstimationModule(
        EstimationDeps(
            library=library,
            counts_as_work=_counts_as_work,
            undo=services.undo,
            details=services.step_details,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            debounce=services.debounce,
            # A step's description, one line for the row and the prose for its tooltip.
            # Handed as answers, so the estimation module never learns where prose lives.
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

    def time_deps(
        library: Library,
        *,
        undo: UndoService[Library],
        context: ContextService,
        clock: Clock,
        debounce: DebounceService,
        estimate_missing: "Callable[[ProjectId], None]",
        day_over: bool,
    ) -> TimeEstimatesDeps:
        """The Time tab's deps over ``library``: the window's, or the simulator's scratch
        world, which differs only in what is handed in here — one recipe, never two."""
        return TimeEstimatesDeps(
            library=library,
            debounce=debounce,
            undo=undo,
            actions=services.actions,
            context=context,
            tabs=services.tabs,
            clock=clock,
            day_over=day_over,
            # Estimates, agent-ness, statuses and milestones through the owners' Qt-free
            # readers — the tab never learns what any of them is stored as.
            readers=_time_readers(),
            # Clicking the calendar re-dates the plan: one undoable write of the
            # estimation module's own entry, composed here so neither module imports
            # the other.
            set_start=lambda project_id, when: undo.push(
                SetModuleDataCommand(
                    project_id, ESTIMATION_ID, write_start(when), label="Set Start Date"
                )
            ),
            estimate_missing=estimate_missing,
            details=services.step_details,
            parent=services.window,
        )

    # Constructed before the list because the projects index opens the tab through it.
    time_estimates = TimeEstimatesModule(
        time_deps(
            library,
            undo=services.undo,
            context=services.context,
            clock=services.clock,
            debounce=services.debounce,
            # The banner's *Estimate missing*: the Estimates tab, on the unsized rows.
            estimate_missing=lambda project_id: estimation.open_for_steps(
                project_id, unestimated=True
            ),
            day_over=False,
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

    # The sources are the tuple `dplanner report` reads (`_report_sources`), so the page the
    # window exports and the page the terminal writes are one page.
    reporting = ReportingModule(
        ReportingDeps(
            library=library,
            actions=services.actions,
            context=services.context,
            tasks=services.tasks,
            status=services.window,
            parent=services.window,
            files=store.files,
            project_dir=store.project_dir,
            repo_root=lambda project_id: find_repo_root(store.project_dir(project_id)),
            plan_remote=lambda project_id: origin_url(store.project_dir(project_id)),
            sources=_report_sources(),
            key_of=_step_key,
            kind_of=_step_kind,
            status_for=stored,
            clock=services.clock,
            reporting_site=reporting_site,
        )
    )

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
            counts_as_work=_counts_as_work,
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
            # The same answer the canvas card's ✓ and the report's read: a wait is never
            # done here, whatever its day.
            step_done=lambda step_id: _card_status(library.step(step_id)) is Status.DONE,
            # The Expenditure tab: what each step's runs consumed, from the project's
            # usage ledger, and a rate of tokens per estimated day learned from the
            # library's finished steps — where ledgers live is the store's to know.
            step_spent=lambda project_id: _step_spent(store, project_id),
            token_rate=lambda project_id: _token_rate(
                store,
                library,
                project_id,
                estimated_days,
                lambda step: _card_status(step) is Status.DONE,
            ),
            ledger_stamp=lambda project_id: _ledger_stamp(store, project_id),
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
            # A run that ended frees a slot for what is due — even when the agent had
            # cleared its state and the plan did not change. The agent module is built
            # below, and nothing ends before the build is up.
            ended=lambda: agent_instruction.settle_launches(),
            # Where each run's ledger record lives, and every project's ledger for the
            # sweep that reads what the runs consumed back into them.
            project_dir=lambda step_id: (
                _ledger_dir(store, library.project_of(step_id).id) if library.has(step_id) else None
            ),
            project_dirs=lambda: [
                directory
                for project in library.projects
                if (directory := _ledger_dir(store, project.id)) is not None
            ],
            tasks=services.tasks,
        )
    )

    def due_here() -> "list[Due]":
        """What this window would launch, across the library, each with its claim: in
        progress for what auto-progress made due, the round's stamp for a turn. Running is
        the plan's run stamp *or* a run this window is watching, so a claim still on its
        way to disk can never make a live shell's step due again."""
        from dplanner.modules.step_review.rounds import record_turn_launched

        today = services.clock.today()
        status_for = _ready_in(library, today)

        def running(step: "Step") -> bool:
            return bool(agent_run_state(step)) or agent_runs.live(step.id) > 0

        def claim(step: "Step", turn: "TurnDue | None") -> "Callable[[], None]":
            def claimed() -> None:
                if turn is not None:
                    record_turn_launched(library, turn.asker, turn.party)
                else:
                    record_started(library, step.id, today)

            return claimed

        return [
            Due(step.id, claim(step, turn))
            for project in library.projects
            for step, turn in _due_now(library, project, status_for, running)
        ]

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

    # Built ahead of the list because the library watcher asks it one question — whether an
    # agent is at work on the project a conflict is in — and stands its modal down while one
    # is. The board comes from `app.new_session` — the machine's when the application runs,
    # one holding nothing when a test builds — and is named nowhere deeper: no feature
    # module reaches `config_dir`, the same rule the topology gate's record path follows.
    if board is None:
        board = at_work_board()
    agent_at_work = AgentAtWorkModule(
        AgentAtWorkDeps(
            board=board,
            notices=services.window,
            library=library,
            parent=services.window,
            # The dialog behind the banner selects the step a row's agent is on.
            reveal=reveal_step,
            key_of=_step_key,
        )
    )

    # A repository on this machine for a verb that needs one, cloned where the clone
    # policy says: the projects module's service, built here because Run Agent is handed
    # it too. Owned by the window, so its task runner outlives every dialog.
    checkouts = CheckoutService(
        repos, services.tasks, kept_root=config_dir(), parent=services.window
    )

    # Built ahead of the list too: the library watcher hands an entry two writers changed
    # at once to this module's launcher, and it is listed before this module.
    agent_instruction = StepAgentInstructionModule(
        StepAgentInstructionDeps(
            works_nobody=_works_nobody,
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
            # Its Project ▸ Settings… tab: the standing instruction every briefing opens with.
            project_settings=services.project_settings,
            files=store.files,
            # How staged assets are read at launch — bytes by absolute path.
            read_asset=read_absolute,
            # Where the agent runs is the module's reading of these: the code checkout
            # for a project that records its code repository, the plan's own repository
            # for one that does not.
            facts_for=facts_for,
            # Code nobody checked out here is cloned before the agent opens in it.
            ensure_checkouts=checkouts.ensure_many,
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
                # A session that starts in plan mode waits for a person from the first
                # moment, and says nothing until its plan is approved.
                files.plans_first,
                # Its record in the ledger, and where it works: what is harvested into it.
                files.run,
                files.workdir,
            ),
            harnesses=agent_harnesses(),
            # The Agent tab's "tokens so far" line: the run tracker's ledger, worded.
            usage_words=lambda step_id: _step_usage_words(store, library, step_id),
            pick_assets=pick_assets,
            # Run Agent asks before launching on a step whose prerequisites are not
            # done — the same status reader the Step statuses tab's frontier uses.
            status_for=_wait_aware(library, services.clock.today),
            # A source under review does not hold a step that collects it.
            auto_progresses=_auto_progresses,
            # And says so on the step when the shell opens: the status aspect's own
            # writer, applied off the undo stack the way the launch stamp is. The
            # agent module holds the preference; the word is the status module's.
            mark_started=lambda step_id: record_started(library, step_id, services.clock.today()),
            # What names the run — its worktree, its branch, its window: the key and
            # the ticket, composed here from aspects the agent module never reads.
            step_key=_step_key,
            ticket_key=_ticket_key,
            # Manage Agent Profiles… lands on the module's own settings page.
            open_settings=settings.open,
            # What the window launches with nobody clicking, when this machine says so.
            due=due_here,
            preferred_agent=_preferred_agent,
            asks_person=_asks_person,
            run_state=agent_run_state,
            live_runs=agent_runs.live,
            repo=store,
            notices=services.window,
            clock=services.clock,
            flush=services.autosave.flush_now,
            launch_lock=(
                launch_locks.for_library(store.library_path) if launch_locks is not None else None
            ),
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
                reconcile_profiles=lambda: agent_instruction.plan_profiles(),
                reconcile=lambda root, branch, profile: agent_instruction.reconcile_remote(
                    root, branch, profile
                ),
            )
        ),
        # Before the watcher: the banner that says an agent is at work is what makes the
        # watcher's stood-down modal legible, so it must already be on screen.
        agent_at_work,
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
                notices=services.window,
                parent=services.window,
                library=library,
                # An entry both writers changed goes to Run Agent's launcher with both
                # versions; the run is tracked on the step like any other.
                hand_to_agent=agent_instruction.hand_conflicts,
                agent_refusal=agent_instruction.conflict_refusal,
                # Whether an agent says it is at work on a project: the modal stands down
                # while one is, and the dialog says so when it does open.
                agent_at_work=agent_at_work.at_work_words,
                # Every settle of an outside change — even one that changed nothing the
                # model heard, like Keep Mine — lets the launcher look again.
                settled=agent_instruction.settle_launches,
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
                tabs=services.tabs,
                theme=services.theme,
                parent=services.window,
                status=services.window,
                tasks=services.tasks,
                autosave=services.autosave,
                switcher=services.switcher,
                settings_sections=services.settings_sections,
                # The Project dialog's tabs after Repositories: whatever other modules
                # registered about a project, read when the dialog is first built.
                project_settings=services.project_settings,
                checkouts=checkouts,
                repos=repos,
                # The index opens a project without knowing what an activity is: *Show
                # Steps* and the Steps row open the graph; the project's row only selects.
                open_steps=project_editor.open,
                # The store's membership face: attach/detach track directories, the
                # model change itself is applied here, off the undo stack, with the
                # membership origin the `library add` verb uses too.
                connect_project=connect_project,
                disconnect_project=disconnect_project,
                # The archive is the store's too — per user, in the library file.
                # Restoring is connecting: an attach takes its directory off the list.
                archive_project=archive_project,
                archived=store.archived,
                archive_changed=store.archive_changed,
                forget_archived=store.forget_archived,
                has_unflushed=store.has_unflushed,
                project_dirs=lambda: (
                    [store.project_dir(project.id).resolve() for project in library.projects]
                    + [problem.path.resolve() for problem in store.problems()]
                ),
                problems=store.problems,
                # Rows under each project — the project row only selects; these open what
                # the project has. Each renders the Project menu: the row stands for its
                # project, and the project's verbs all live there.
                # A single click opens the same surface as a preview tab — the VS Code
                # gesture: the next click's preview replaces it, activation keeps it.
                # In the order a plan is made: what it answers to and carries (Specs,
                # Assets), the graph and its readings, then how the whole covers the spec.
                # Project ▸ Show … lists them the same way.
                entries=(
                    ProjectEntry(
                        id="spec",
                        label="Specs",
                        open=spec.open,
                        open_preview=lambda pid: spec.open(pid, preview=True),
                        icon=spec_icon,
                        menu="Project",
                        order=10,
                        # A mark while a source of that project has updates waiting, so it
                        # is visible without opening the tab. What the window has found,
                        # not a claim about the source now: checking runs while a Specs tab
                        # is open, and a project nobody has opened is not being checked.
                        badge=spec.updates_mark,
                        changed=spec.updates_changed,
                    ),
                    ProjectEntry(
                        id="assets",
                        label="Assets",
                        open=project_assets.open,
                        open_preview=lambda pid: project_assets.open(pid, preview=True),
                        icon=image_icon,
                        menu="Project",
                        order=20,
                    ),
                    ProjectEntry(
                        id="steps",
                        label="Steps",
                        open=project_editor.open,
                        open_preview=lambda pid: project_editor.open(pid, preview=True),
                        icon=graph_icon,
                        menu="Project",
                        order=30,
                    ),
                    ProjectEntry(
                        id="order",
                        label="Order",
                        open=step_order.open,
                        open_preview=lambda pid: step_order.open(pid, preview=True),
                        icon=list_icon,
                        menu="Project",
                        order=35,
                    ),
                    ProjectEntry(
                        id="expenditure",
                        label="Expenditure",
                        open=step_order.open_expenditure,
                        open_preview=lambda pid: step_order.open_expenditure(pid, preview=True),
                        icon=spark_icon,
                        menu="Project",
                        order=37,
                    ),
                    ProjectEntry(
                        id="progression",
                        label="Step statuses",
                        open=progression.open,
                        open_preview=lambda pid: progression.open(pid, preview=True),
                        icon=gauge_icon,
                        menu="Project",
                        order=40,
                    ),
                    ProjectEntry(
                        id="time",
                        label="Time Estimates",
                        open=time_estimates.open,
                        open_preview=lambda pid: time_estimates.open(pid, preview=True),
                        icon=clock_icon,
                        menu="Project",
                        order=50,
                    ),
                    ProjectEntry(
                        id="coverage",
                        label="Coverage",
                        open=coverage.open,
                        open_preview=lambda pid: coverage.open(pid, preview=True),
                        icon=coverage_icon,
                        menu="Project",
                        order=60,
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
        # come before step_properties, which reads the registry when it opens a dialog.
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
                scopes=scopes,
                files=store.files,
                # Its Project ▸ Settings… tab: the compilation instructions every document
                # compiled in this project follows.
                project_settings=services.project_settings,
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
        StepWaitModule(
            StepWaitDeps(
                library=library,
                undo=services.undo,
                actions=services.actions,
                details=services.step_details,
                today=services.clock.today,
                insert_before=insert_wait_before,
            )
        ),
        # The branch cut, and the landing's id beside it: after the wait, the other kind of
        # step nobody works.
        branches,
        LandingModule(),
        # No tab: the status vocabulary is a Status submenu of checkable Step verbs. The
        # window is the director's, so a status that says the work stopped ends the agent's
        # claim on the board the banner reads.
        StepStatusModule(
            StepStatusDeps(
                library=library,
                undo=services.undo,
                actions=services.actions,
                clock=services.clock,
                workflow=_status_workflow(),
                end_claim=lambda claim: board.end(claim.project, claim.step),
            )
        ),
        # No tab either: a check carries nothing, and the Covers tab that shows what it
        # gathers is the tests module's — it renders a list of tests, which is that
        # module's business, not this one's.
        StepCheckModule(
            StepCheckDeps(library=library, undo=services.undo, actions=services.actions)
        ),
        # No tab either: the start is a marker, and what it means is the walks' business,
        # wired in _scope_kinds().
        StepStartModule(
            StepStartDeps(library=library, undo=services.undo, actions=services.actions)
        ),
        # No tab either: one checkable verb among the arrow's, over the links the canvas
        # has picked — its reading of the selection, handed across here.
        AutoProgressModule(
            AutoProgressDeps(
                library=library,
                undo=services.undo,
                actions=services.actions,
                picked_links=lambda context: [
                    ref.as_edge() for ref in picked_edges(library, context)
                ],
                is_agent=_is_agent_step,
                key_of=_step_key,
                # A link into a review auto-progresses by the review's rule, not its flag.
                always=_always_progresses,
            )
        ),
        # The Review tab and toggle; the conversation is the `review` verbs' to write.
        StepReviewModule(
            StepReviewDeps(
                library=library,
                undo=services.undo,
                actions=services.actions,
                sections=services.inspector_sections,
                works_nobody=_works_nobody,
                key_of=_step_key,
                harnesses=agent_harnesses(),
                default_profile=lambda: default_profile().name,
                parent=services.window,
            )
        ),
        # Declares the conversation's format only; the `review` verbs write it.
        ReviewRoundsModule(),
        # A feature is a step: one a person would name and demo, gathering the work behind
        # it and stopping at the previous feature. The Covers tab that shows what it
        # gathers is still the tests module's.
        feature,
        # Registers nothing: it owns the widget the graph tab stands beside the canvas.
        problems,
        TestsModule(
            TestsDeps(
                works_nobody=_works_nobody,
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
                scopes=scopes,
                pick_assets=pick_assets,
                # Grouping by milestone writes each heading in that milestone's own shade,
                # so the Tests tab reads as the same sequence the calendar does.
                milestone_color=milestone_color,
                # An export is offered where colleagues read reports from.
                reporting_dir=reporting_dir,
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
                finish_merged=lambda step_id: record_merged(
                    library,
                    step_id,
                    services.clock.today(),
                    accepted_by_merge=library.has(step_id)
                    and _merged_into_its_branch(
                        library, library.step(step_id), branches.reading_of
                    ),
                ),
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
        # Debug ▸ Time Simulation: the real Time tab over a scratch world of its own — its
        # own library, undo stack, context, clock and debounce service, so nothing it does
        # reaches the window's. It shares only the verbs, which run against its own context.
        TimeSimulationModule(
            TimeSimulationDeps(
                actions=services.actions,
                context=services.context,
                tabs=services.tabs,
                readers=_time_readers(),
                writers=_time_writers(),
                time_deps=lambda scratch, clock, debounce: time_deps(
                    scratch,
                    undo=UndoService(scratch),
                    context=ContextService(),
                    clock=clock,
                    debounce=debounce,
                    estimate_missing=lambda _project_id: None,
                    day_over=True,
                ),
            )
        ),
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
        # After every module whose verb the guide names — its page reads their specs as it
        # is built — and before reopen_tabs, which reopens a Home tab like any other.
        HomeModule(
            HomeDeps(
                tabs=services.tabs,
                actions=services.actions,
                context=services.context,
                segments=services.index_segments,
                settings_sections=services.settings_sections,
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
    library: "Library",
    step: "Step",
    files: "Callable[[str, str], ModuleFileArea]",
    facts: "RepositoryFacts | None",
) -> "list[PromptPart]":
    """The step's own facts as briefing sections: what it is, why it exists, where the
    work lands, and the work it collects. Cross-module prose, so it is worded here in the
    one file allowed to know every module's vocabulary — the agent module renders the
    blocks without learning what a description, a requirement or a PR is. An empty fact
    contributes no section.
    """
    from dplanner.modules.feature.aspect import is_feature
    from dplanner.modules.feature.aspect import read as feature_read
    from dplanner.modules.github.aspect import pr_label
    from dplanner.modules.github.aspect import read as github_read
    from dplanner.modules.spec.aspect import attachment_paths
    from dplanner.modules.step_agent_instruction.aspect import read as instruction_read
    from dplanner.modules.step_agent_instruction.prompt import PromptPart
    from dplanner.modules.step_description.aspect import MODULE_ID as DESCRIPTION_ID
    from dplanner.modules.step_description.aspect import read as description_read

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
        holders = _flows_into(library, project, step.id)
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
            if refs.pr_base:
                pr += f" into {refs.pr_base}"
            if refs.pr_url:
                pr += f" {refs.pr_url}"
            lines.append(pr)
        if lines:
            sections.append(PromptPart(heading="Where the work lands", body="\n".join(lines)))
    reviewed = _reviewed_work(library, step, facts)
    if reviewed:
        sections.append(PromptPart(heading="Work you review", body=reviewed))
    collected = _collected_work(library, step, facts)
    if collected:
        sections.append(PromptPart(heading="Work you collect", body=collected))
    landed = _landed_work(library, step, facts)
    if landed:
        sections.append(PromptPart(heading="Work you land", body=landed))
    sections += _conversation_parts(library, step)
    return sections


def _landed_work(library: "Library", step: "Step", facts: "RepositoryFacts | None") -> str:
    """What a landing is handed about the branch it lands: each step on it where it stands,
    the line *Work you collect* prints. Empty for a step that lands nothing."""
    if not _is_land(step):
        return ""
    stretch = _branch_reading(library.project_of(step.id)).of_land(step.id)
    if stretch is None:
        return ""
    return "\n".join(_source_line(member, facts) for member in stretch.members)


def _source_line(source: "Step", facts: "RepositoryFacts | None") -> str:
    """One step whose work another step takes, where it stands: its status, its branch and
    PR, and its worktree on this machine — the line *Work you collect* and *Work you review*
    both list, so a collector and a review are told where work is the one way.

    The worktree is named from the same rule the launcher prepared it by (``_run_name``),
    under the checkout of the code location the step works in; whether it is *here* is the
    one thing only this machine can say, so it is asked.
    """
    from dplanner.modules.github.aspect import pr_label
    from dplanner.modules.github.aspect import read as github_read
    from dplanner.modules.step_agent_instruction.aspect import uses_worktree
    from dplanner.modules.step_agent_instruction.launcher import workdir, worktree_path
    from dplanner.planning.status import phrase, stored

    refs = github_read(source)
    facts_of = [phrase(stored(source))]
    facts_of.append(
        f"branch `{refs.branch}`" if refs is not None and refs.branch else "no branch recorded"
    )
    if refs is not None and refs.has_pr():
        pr = pr_label(refs)
        if refs.pr_base:
            pr += f" into `{refs.pr_base}`"
        if refs.pr_url:
            pr += f" {refs.pr_url}"
        facts_of.append(pr)
    if not uses_worktree(source):
        facts_of.append("worked in the checkout itself, no worktree")
    else:
        root = workdir(facts, source) if facts is not None else None
        path = worktree_path(root, _run_name(source)) if root is not None else None
        here = path is not None and path.is_dir()
        facts_of.append(f"worktree `{path}`" if here else "no worktree of it on this machine")
    return f"- **{_step_key(source)}** {source.title} — " + " · ".join(facts_of)


def _collected_work(library: "Library", step: "Step", facts: "RepositoryFacts | None") -> str:
    """What a step that collects other steps' work is handed: each source where it stands,
    then the duty to land that work, the right to finish the source, and the way to send
    work back that is not ready. Empty for a step that collects nothing."""
    from dplanner.modules.auto_progress.aspect import sources
    from dplanner.modules.step_review.aspect import settings

    collected = sources(library, step)
    if not collected:
        return ""
    lines = [_source_line(source, facts) for source in collected]
    keys = [_step_key(source) or source.title for source in collected]
    ref = _quoted(_step_key(step) or step.title)
    to = f"--to {_quoted(keys[0])}" if len(keys) == 1 else "--to <source>"
    lines += [
        "",
        f"This step collects the work of {_listed(keys)}: it may start once"
        f" {'that step reads' if len(keys) == 1 else 'each of them reads'} ready for review,"
        " and landing that work is its job. Take each one's branch or PR into yours as a"
        " merge commit of its own, reconcile what they could not see of each other, and"
        " review the whole before you ask for a review of it. Once a source's work has"
        " landed in your branch, set it done yourself — you are the step allowed to:"
        + "".join(
            f" `dplanner status set {_quoted(key)} done`{',' if i < len(keys) - 1 else '.'}"
            for i, key in enumerate(keys)
        ),
        "",
        "Work that is not ready to land goes back to its step rather than being mended here:"
        f" `dplanner review start {ref} {to}` opens a round, `dplanner review post {ref} {to}"
        f" --file <findings.md>` says what is wrong, and `dplanner review wait {ref} {to}`"
        f" waits for the answer — at most {settings(step).max_rounds} rounds with each.",
    ]
    return "\n".join(lines)


def _reviewed_work(library: "Library", step: "Step", facts: "RepositoryFacts | None") -> str:
    """What a review is handed about the work it reviews: its subject where it stands, and
    how to read that work without touching it. Empty for a step that is no review, and for
    a review with no subject — its instructions say to stop."""
    from dplanner.modules.step_review.aspect import is_review, subjects

    reviewed = subjects(library, step) if is_review(step) else []
    if not reviewed:
        return ""
    return "\n".join(
        [
            *(_source_line(subject, facts) for subject in reviewed),
            "",
            "Read the work where it is, and change nothing in it: in its worktree when the line"
            " names one here; otherwise from its PR (`gh pr diff <number>`) or its branch"
            " (`git fetch origin <branch>`, then read `FETCH_HEAD`) — never by checking its"
            " branch out in this checkout.",
        ]
    )


def _conversation_parts(library: "Library", step: "Step") -> "list[PromptPart]":
    """A section per review conversation the step is in and that is still going — as the
    step that asks or the one that answers — with what each side has said, so an agent
    relaunched mid-review picks it up where it stands. Who talks to whom is the
    ``_auto_progresses`` rule the ``review`` verbs read; an ended conversation tells the
    next worker nothing to do, and the Review tab keeps it."""
    from dplanner.modules.step_agent_instruction.prompt import PromptPart
    from dplanner.modules.step_review.rounds import (
        ENDED,
        PARTY,
        POSTED,
        messages,
        standing,
        turn,
        with_party,
    )

    def ref(other: "Step") -> str:
        return _quoted(_step_key(other) or other.title)

    askers = [each for each in library.dependents(step.id) if _auto_progresses(each, step)]
    talks = [
        *((step, party) for party in library.requires(step.id) if _auto_progresses(step, party)),
        *((asker, step) for asker in askers),
    ]
    parts = []
    for asker, party in talks:
        held = with_party(asker, party.id)
        if not held or turn(held[-1]) == ENDED:
            continue
        lines = [f"Where it stands: {standing(held[-1], ref(asker), ref(party))}."]
        for said in messages(held):
            who = f"{ref(asker)}'s findings" if said.kind == POSTED else f"{ref(party)}'s reply"
            lines += ["", f"### Round {said.round.number} — {who}", "", said.text.rstrip()]
        if party.id == step.id and turn(held[-1]) == PARTY:
            named = f" --from {ref(asker)}" if len(askers) > 1 else ""
            lines += [
                "",
                f"It waits on your answer: `dplanner review take {ref(step)}{named}`, settle each"
                " finding — or say why not — commit and push, then `dplanner review reply"
                f" {ref(step)}{named} --file <reply.md>`.",
            ]
        other = party if asker.id == step.id else asker
        parts.append(PromptPart(heading=f"Review rounds with {ref(other)}", body="\n".join(lines)))
    return parts


def _listed(words: "Sequence[str]") -> str:
    """``A``, ``A and B``, ``A, B and C`` — a list as a sentence says it."""
    if len(words) < 2:
        return "".join(words)
    return ", ".join(words[:-1]) + f" and {words[-1]}"


def _quoted(key: str) -> str:
    """A step's key or title as a verb takes it: quoted only when it has a space."""
    return f"'{key}'" if " " in key else key


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
    were attached to it. A review's block is generated (``_review_instruction``), and that
    same text rides inside it as what to look for.
    """
    from dplanner.modules.step_agent_instruction.aspect import asset_paths
    from dplanner.modules.step_agent_instruction.aspect import read as instruction_read
    from dplanner.modules.step_agent_instruction.prompt import PromptPart
    from dplanner.modules.step_description.aspect import MODULE_ID as DESCRIPTION_ID
    from dplanner.modules.step_description.aspect import read as description_read
    from dplanner.modules.step_review.aspect import is_review

    own = instruction_read(step)
    instruction_files = asset_paths(files, step.id)
    if own:
        body, carried = own, instruction_files
    else:
        description_files = _module_asset_paths(files, step.id, DESCRIPTION_ID)
        body, carried = description_read(step), (*description_files, *instruction_files)
    if is_review(step):
        body = _review_instruction(library, step, body)
    elif _is_land(step):
        body = _landing_instruction(library, step, body)
    return PromptPart(heading="Instructions", body=body, files=carried)


def _branches_in(project: "Project") -> "dict[str, str]":
    """The feature branch each step's work is on, for the steps a stretch not yet landed
    holds — and each landing, whose work is on the branch it brings back."""
    found = _branch_reading(project)
    on: dict[str, str] = {}
    for step in project.steps:
        stretch = found.of_land(step.id) or found.innermost(step.id, open_only=True)
        if stretch is not None and not stretch.landed:
            on[step.id] = stretch.branch
    return on


def _strips(found: "BranchReading") -> "dict[str, tuple[str, str]]":
    """What each card on a branch wears under its body: the branch's name, and its lane
    colour while the branch is open — "" once it has landed, when the strip goes quiet and
    keeps the name. Every step on a stretch and its landing wear one; a step on a branch off
    a branch wears the inner one's."""
    colors = _lane_colors(found)
    strips: dict[str, tuple[str, str]] = {}
    for stretch in sorted(found.stretches, key=lambda stretch: -len(stretch.members)):
        tone = "" if stretch.landed else colors[stretch.cut.id]
        for step in (*stretch.members, stretch.land):
            strips[step.id] = (stretch.branch, tone)
    return strips


def _lane_colors(found: "BranchReading") -> "dict[str, str]":
    """Each stretch's lane colour by its cut's id, dealt in the order the cuts were made, so
    a branch keeps its colour while others come and go after it."""
    from dplanner.theme.palettes import lane

    cuts = sorted((stretch.cut for stretch in found.stretches), key=lambda cut: cut.number)
    return {cut.id: lane(index) for index, cut in enumerate(cuts)}


def _lanes(library: "Library", found: "BranchReading") -> "dict[Edge, str]":
    """The arrows of work on a branch not yet landed, each with its branch's lane colour:
    from the cut or a step on it, into a step on it or its landing. An arrow on a branch
    off a branch wears the inner one's."""
    colors = _lane_colors(found)
    lanes: dict[Edge, str] = {}
    widest_first = sorted(found.stretches, key=lambda stretch: -len(stretch.members))
    for stretch in widest_first:
        if stretch.landed:
            continue
        on = {member.id for member in stretch.members}
        for waiter in (*stretch.members, stretch.land):
            for source in library.requires(waiter.id):
                if source.id in on or source.id == stretch.cut.id:
                    lanes[(waiter.id, "requires", source.id)] = colors[stretch.cut.id]
    return lanes


def _is_land(step: "Step") -> bool:
    from dplanner.modules.branches.aspect import is_land

    return is_land(step)


def _landing_instruction(library: "Library", land: "Step", look_for: str) -> str:
    """A landing's instructions, generated from the stretch it closes, as a review's are
    from its subject: the branch, what it merges into, the order it is done in — and its
    own prose after, as what else to see to. A landing whose cut is gone is told to stop."""
    found = _branch_reading(library.project_of(land.id))
    stretch = found.of_land(land.id)
    ref = _quoted(_step_key(land) or land.title)
    if stretch is None:
        return (
            "This step lands a feature branch, but the cut that started it is gone or no longer"
            " upstream of it — stop, and tell the developer: `dplanner land set"
            f" {ref} --cut <cut>` names it again."
        )
    branch = stretch.branch
    base = found.base_of(land.id, "")
    into = f"`{base}`" if base else "the repository's default branch"
    against = f"--base {base} " if base else ""
    lines = [
        f"Land the feature branch `{branch}` into {into}: every step on it has merged its work"
        " into that branch, and this step brings the branch back as one pull request.",
        "",
        f"1. `git fetch origin`. Make sure every step under *Work you land* has merged into"
        f" `origin/{branch}` — its PR reads merged into {branch}, or its branch is contained in"
        " it. One that has not: stop, and tell the developer which.",
        f"2. Merge `origin/{base or 'HEAD'}` into `{branch}` as a merge commit — never a rebase"
        " or a squash, since a branch cut from this one keeps its history — settle every"
        " conflict, and run the project's checks.",
        f"3. `git push origin {branch}`, then `gh pr create {against}--head {branch}`, the"
        " title opening with this step's key.",
        f"4. Leave `{branch}` on the remote until this step is done: a step still working on it"
        " would lose what it starts from.",
    ]
    if look_for.strip():
        lines += ["", "Also see to this:", "", look_for.strip()]
    return "\n".join(lines)


def _review_instruction(library: "Library", review: "Step", look_for: str) -> str:
    """A review's instructions, generated from its aspect and its subject: whom it reviews,
    through which lenses, how the rounds go and how many there may be — then ``look_for``,
    what the review's own prose asks it to watch. A review that does not have exactly one
    subject is told to stop, since every verb it would run names that one step."""
    from dplanner.modules.step_review.aspect import lens, settings, subjects

    ref = _quoted(_step_key(review) or review.title)
    reviewed = subjects(library, review)
    if len(reviewed) != 1:
        which = (
            "reviews nothing yet"
            if not reviewed
            else f"reviews {_listed([_step_key(each) or each.title for each in reviewed])} at once"
        )
        return (
            f"This review {which}, and a review takes exactly one subject — the step it waits"
            " on. Stop, and tell the developer: `dplanner step link"
            f" {ref} <step>` gives it one, `dplanner step unlink {ref} <step>` takes one away."
        )
    subject = reviewed[0]
    them = _quoted(_step_key(subject) or subject.title)
    chosen = settings(review)
    cap = chosen.max_rounds
    lines = [
        f"You review **{_step_key(subject)}** {subject.title} — *Work you review* says where its"
        f" work is. You comment; you never commit, push or edit its files: {them}'s own agent"
        " makes every change, in answer to what you find.",
        "",
    ]
    if chosen.lenses:
        lines.append("Look at it through these lenses:")
        for each in chosen.lenses:
            known = lens(each)
            lines.append(
                f"- **{known.label}** — {known.asks}"
                if known is not None
                else f"- **{each}** — a lens of the developer's own: use your `{each}` skill"
                " for it."
            )
        lines.append("")
    if look_for.strip():
        lines += ["What to look for, as this review says it:", "", look_for.rstrip(), ""]
    lines += [
        f"The review goes in rounds, at most {cap} with {them}:",
        f"1. `dplanner review wait {ref}` returns once {them} reads ready for review; exit 3"
        " means nothing yet after nine minutes — run it again.",
        f"2. `dplanner review start {ref}` opens the round. Read the work through every lens,"
        f" then `dplanner review post {ref} --file <findings.md>`: each finding with its file"
        f" and line, what is wrong and what would settle it. Posting puts {them} back in"
        " progress.",
        f"3. `dplanner agent-state set {ref} pending-approval`, then `dplanner review wait"
        f" {ref}` for the answer — read the reply and what changed since your last round.",
        f"4. Nothing left to ask: `dplanner review approve {ref}` — {them} is done, and this"
        f" review is ready to merge, carrying {them}'s branch and PR. Something left: back to"
        f" 2 for the next round. After round {cap}, approve, or hand it to a person:"
        f" `dplanner review escalate {ref} --text '<what they must decide>'`.",
    ]
    return "\n".join(lines)


def _default_briefing(read: "Callable[[Project], BranchReading] | None" = None) -> "Briefing":
    """The briefing every surface assembles from: the shared block builders below, and
    the root's own opening and closing prose. One object, two callers — the window's
    Deps and ``dplanner agent prompt`` — so what an agent is launched with and what the
    verb prints are the same text by construction. ``read`` is how the window reads a
    project's branch stretches — cached, since Run Agent's state asks on every announce —
    and the CLI, with none, reads them afresh."""
    from dplanner.modules.step_agent_instruction.prompt import Briefing

    return Briefing(
        parts=_note_parts,
        sections=_briefing_sections,
        project_sections=_briefing_project_sections,
        epilogue=_agent_epilogue,
        preamble=_agent_preamble,
        instruction=_briefing_instruction,
        no_worktree=_no_worktree,
        branch=lambda library, step, facts: _branch_plan(library, step, facts, read),
    )


def _branch_plan(
    library: "Library",
    step: "Step",
    facts: "RepositoryFacts | None",
    read: "Callable[[Project], BranchReading] | None" = None,
) -> "BranchPlan":
    """Which branches a run of ``step`` works between, from the stretches that hold it.

    A step on a branch starts its own from that branch and opens its PR against it; a
    landing works on the branch itself and opens its PR against the branch its stretch was
    cut from; anything else starts from the mainline its code location names — the remote's
    default when it names none — and opens against the same. The first run in a stretch may
    cut its branch on the remote: while nothing on it has recorded a branch or a PR, a
    missing branch is one nobody made yet, and after that it is one somebody deleted.
    """
    from dplanner.modules.step_agent_instruction.launcher import (
        DEFAULT_START,
        BranchPlan,
        mainline,
    )

    found = (read or _branch_reading)(library.project_of(step.id))
    base = mainline(facts, step)
    if found.overlaps(step.id):
        named = " and ".join(stretch.branch for stretch in found.holding(step.id))
        return BranchPlan(refusal=f"it is on {named}, and neither is inside the other")
    landing = found.of_land(step.id)
    stretch = landing or found.innermost(step.id, open_only=True)
    if stretch is None:
        return BranchPlan(start=f"origin/{base}" if base else "", pr_base=base)
    cut_from = found.base_of(stretch.cut.id, base)
    fresh = not stretch.landed and not any(
        _recorded_work(member) for member in (*stretch.members, stretch.land)
    )
    return BranchPlan(
        work_branch=stretch.branch if landing is not None else "",
        start=f"origin/{stretch.branch}",
        create=stretch.branch if fresh else "",
        create_from=(f"origin/{cut_from}" if cut_from else DEFAULT_START) if fresh else "",
        pr_base=found.base_of(step.id, base) if landing is not None else stretch.branch,
    )


def _pr_base(step: "Step") -> str:
    """The branch a step's PR merges into, as GitHub last said; "" when unknown."""
    from dplanner.modules.github.aspect import read as github_read

    refs = github_read(step)
    return refs.pr_base if refs is not None else ""


def _recorded_work(step: "Step") -> bool:
    """Whether a step has recorded a branch or a PR — that its work was carried out."""
    from dplanner.modules.github.aspect import read as github_read

    return github_read(step) is not None


def _branch_reading(project: "Project") -> "BranchReading":
    """The project's branch stretches, read afresh — the CLI's; the window reads the
    branches module's cached one."""
    from dplanner.modules.branches.aspect import reading

    return reading(project, _is_done)


def _is_done(step: "Step") -> bool:
    """Whether a step's own status says done — for a landing, that its branch landed."""
    from dplanner.planning.status import Status, stored

    return stored(step) is Status.DONE


def _branch_births(project: "Project", branch: str) -> "tuple[Step, Step]":
    """The two ends of a new stretch, dressed as the templates dress them: the cut named for
    its branch with no estimate and no description, since nobody works it; the landing an
    agent step of a quarter day, briefed by the stretch it closes rather than by a
    description of its own."""
    from dplanner.domain.model import Step
    from dplanner.modules.branches.aspect import CUT_ID, LAND_ID, write_cut, write_land
    from dplanner.modules.estimation.aspect import MODULE_ID as ESTIMATION_ID
    from dplanner.modules.estimation.aspect import write as estimate_write
    from dplanner.modules.step_agent_instruction.aspect import MODULE_ID as AGENT_ID
    from dplanner.modules.step_agent_instruction.aspect import write_state as agent_state
    from dplanner.modules.step_description.aspect import MODULE_ID as DESCRIPTION_ID
    from dplanner.modules.step_description.aspect import write_state as description_state

    cut = Step(title=branch)
    cut.module_data[CUT_ID] = write_cut(branch)
    cut.module_data[ESTIMATION_ID] = estimate_write(None, on=False)
    cut.module_data[DESCRIPTION_ID] = description_state(False)
    land = Step(title=f"Land {branch}")
    land.module_data[LAND_ID] = write_land(cut.id)
    land.module_data[AGENT_ID] = agent_state(True)
    land.module_data[ESTIMATION_ID] = estimate_write(0.25)
    land.module_data[DESCRIPTION_ID] = description_state(False)
    return cut, land


def _stacked_apart(project: "Project", chosen: "set[StepId]") -> str:
    """Why a pick would put part of a stack on a branch: a stack is one way in and one way
    out, and a bracket through its middle would link into it."""
    from dplanner.modules.project_editor.stacks import read_stacks

    for stack in read_stacks(project.steps):
        members = set(stack.members)
        if members & chosen and not members <= chosen:
            first = next(step for step in project.steps if step.id == stack.members[0])
            return f"it would split the stack {first.title!r} — pick all of it, or none"
    return ""


def _merged_into_its_branch(
    library: "Library",
    step: "Step",
    read: "Callable[[Project], BranchReading] | None" = None,
) -> bool:
    """Whether a step's PR merged into the branch of an open stretch holding it — the merge
    that accepts it, the branch's own review coming when the branch lands."""
    from dplanner.modules.github.aspect import read as github_read

    refs = github_read(step)
    if refs is None or not refs.pr_base:
        return False
    project = library.project_of(step.id)
    stretch = (read or _branch_reading)(project).innermost(step.id, open_only=True)
    return stretch is not None and stretch.branch == refs.pr_base


def _no_worktree(step: "Step") -> str:
    """Why a run of ``step`` gets no worktree whatever its agent aspect says, or "" — the
    review's rule: it reads the work it reviews where that work is, and commits none."""
    from dplanner.modules.step_review.aspect import NO_WORKTREE_FOR_A_REVIEW, is_review

    return NO_WORKTREE_FOR_A_REVIEW if is_review(step) else ""


def _step_key(step: "Step") -> str:
    """The step's readable key: a letter for what it is, the number the project dealt.

    ``M`` a milestone, ``F`` a feature, ``C`` a check, ``W`` a wait, ``B`` a branch cut,
    ``R`` a review, ``S`` any other step —
    the coarser claim wins, in the order the body tone ranks them, so a milestone that is
    also a feature reads ``M``. The letter is presentation over the stored number, which is why
    a step keeps its number when its kind changes and the letter follows. Read by the
    key block on every card, every CLI row and lookup, the branch a run is named after, and the
    briefing that tells the agent which step it holds.
    """
    from dplanner.modules.feature.aspect import is_feature
    from dplanner.modules.step_check.aspect import read as check_read
    from dplanner.modules.step_milestone.aspect import is_milestone
    from dplanner.modules.step_review.aspect import is_review
    from dplanner.modules.step_wait.aspect import is_wait

    if not step.number:
        return ""
    letter = (
        "M"
        if is_milestone(step)
        else "F"
        if is_feature(step)
        else "C"
        if check_read(step)
        else "W"
        if is_wait(step)
        else "B"
        if _is_cut(step)
        else "R"
        if is_review(step)
        else "S"
    )
    return f"{letter}{step.number}"


def _step_kind(step: "Step") -> str:
    """What a step *is*, in one word, the coarser claim first — the same ranking as the key's
    letter and the body tone: milestone, feature, check, wait, cut, review, agent step, or
    nothing."""
    from dplanner.modules.feature.aspect import is_feature
    from dplanner.modules.step_agent_instruction.aspect import enabled as agent_enabled
    from dplanner.modules.step_check.aspect import read as check_read
    from dplanner.modules.step_milestone.aspect import is_milestone
    from dplanner.modules.step_review.aspect import is_review
    from dplanner.modules.step_wait.aspect import is_wait

    if is_milestone(step):
        return "milestone"
    if is_feature(step):
        return "feature"
    if check_read(step):
        return "check"
    if is_wait(step):
        return "wait"
    if _is_cut(step):
        return "cut"
    if is_review(step):
        return "review"
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
    from dplanner.modules.estimation.schedule import project_schedule
    from dplanner.modules.step_milestone.aspect import is_milestone
    from dplanner.planning.schedule import format_date, format_days

    if not any(is_milestone(step) for step in project.steps):
        return {}
    stats: dict[str, str] = {}
    for scheduled in project_schedule(library, project):
        step = scheduled.place.step
        if not is_milestone(step):
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

    The colour map is the *project's* assumption, not the user's: a report site exported
    by any of a project's people should paint its milestones alike, and the Time tab's
    picker would otherwise name a map it was not painting.
    ARCHITECTURE.md's *Colour is a place on one map* has the rest.
    """
    from dplanner.modules.step_milestone.aspect import is_milestone
    from dplanner.modules.time_estimates.schedule import milestone_colors

    return milestone_colors(library, project, is_milestone)


def _step_stats(library: "Library", project: "Project") -> dict[str, str]:
    """The figure at each card's bottom right: a milestone's total and landing, how long a
    wait holds, any other step's estimate — what the canvas paints, read once for the
    report's graph."""
    from dplanner.modules.estimation.aspect import read as estimated_days
    from dplanner.modules.step_wait.aspect import read as wait_read
    from dplanner.modules.step_wait.aspect import stat as wait_stat
    from dplanner.planning.schedule import format_days

    stats = _milestone_stats(library, project)
    for step in project.steps:
        if step.id in stats:
            continue
        wait = wait_read(step)
        if wait is not None:
            stats[step.id] = wait_stat(wait, wait.until)  # A card prints no year.
            continue
        days = estimated_days(step)
        if days is not None:
            stats[step.id] = format_days(days)
    return stats


def _step_type_icons(step: "Step") -> tuple[str, ...]:
    """What kind of thing a step is, in the medallion vocabulary the canvas painted
    first: "tag" a milestone, "layers" a feature, "beaker" one carrying tests, "shield" a
    check, "review" a review, "merge" a landing. The order table's title column reads the
    same answer, so a
    step is the same kind everywhere. Who works it is :func:`_primary_glyph`'s, and a card
    says a thing once."""
    from dplanner.modules.feature.aspect import is_feature
    from dplanner.modules.step_check.aspect import read as check_read
    from dplanner.modules.step_milestone.aspect import is_milestone
    from dplanner.modules.step_review.aspect import is_review
    from dplanner.modules.testing.aspect import enabled as test_enabled

    return (
        *(("tag",) if is_milestone(step) else ()),
        *(("layers",) if is_feature(step) else ()),
        *(("beaker",) if test_enabled(step) else ()),
        *(("shield",) if check_read(step) else ()),
        *(("review",) if is_review(step) else ()),
        *(("merge",) if _is_land(step) else ()),
    )


def _card_status(step: "Step") -> "Status | Unknown":
    """A step's status as its card wears it — the key block's wash, a done body — on the
    canvas, the coverage lanes and the report: none for a step nobody works — a wait, a
    branch cut — which has no status, whatever it carried before it became one. A wait's
    clock is the block's one amber then."""
    from dplanner.planning.status import Status, stored

    return Status.PENDING if _works_nobody(step) else stored(step)


def _primary_glyph(step: "Step") -> tuple[str, str]:
    """Who works a step, as the glyph beside its key and that glyph's tone: an agent's
    sparkle, a person otherwise — a milestone, a feature and a check included, since a
    person closes those — and for a wait nobody at all, so an amber clock, always; a branch
    cut, nobody either, wears the branch it starts.

    The one rule, read by every card that shows a key — the canvas, the coverage lanes and
    the report's graph — and by Find's rows and the Step statuses tab's. The tone is a
    status tone's word — "warn" is the attention amber — so each surface resolves it the way
    it resolves its status washes."""
    from dplanner.modules.step_agent_instruction.aspect import enabled as agent_enabled
    from dplanner.modules.step_wait.aspect import is_wait

    if is_wait(step):
        return "clock", "warn"
    if _is_cut(step):
        return "branch", ""
    return ("spark" if agent_enabled(step) else "person"), ""


def _time_readers() -> "TimeReaders":
    """What the time module reads of other modules' aspects, for its verbs and its report:
    estimates, agent-ness, status and the days it changed and began, the start date, milestones, the
    estimate history and the key a row prints — the owners' Qt-free readers, handed over
    here so no module imports another's.

    **Time reads review and merge as work in flight.** A step under review or waiting on
    its merge is not landed — the percent, Step statuses and ``requires`` all say so — so the
    Time tab, the recorder, the matrix, the report and the simulator read it as in
    progress, *since the day it started*: its ``since`` moved when it went to review, and
    the model credits in-flight work from ``since``, so the raw day would re-cost the step
    at its whole estimate the moment an agent finished it. ``changed_on`` keeps the raw
    day for what a recorded day counts as a change. ARCHITECTURE.md's *An agent finishes
    at Ready for review* has the reasoning.
    """
    from dplanner.modules.estimation.aspect import enabled as estimate_enabled
    from dplanner.modules.estimation.aspect import read as estimated_days
    from dplanner.modules.estimation.aspect import read_history as estimate_history
    from dplanner.modules.estimation.schedule import start_of
    from dplanner.modules.step_agent_instruction.aspect import enabled as agent_enabled
    from dplanner.modules.step_milestone.aspect import read as milestone_read
    from dplanner.modules.step_wait.aspect import read as wait_read
    from dplanner.modules.time_estimates.cli import Readers
    from dplanner.planning.status import REVIEW_AND_MERGE, Status, held, stored
    from dplanner.planning.status import read_since as status_since
    from dplanner.planning.status import read_started as status_started

    def status_for(step: "Step") -> "Status":
        status = held(stored(step))
        return Status.IN_PROGRESS if status in REVIEW_AND_MERGE else status

    def since_for(step: "Step") -> "date | None":
        if stored(step) in REVIEW_AND_MERGE:
            return status_started(step) or status_since(step)
        return status_since(step)

    return Readers(
        days_for=estimated_days,
        is_agent=agent_enabled,
        status_for=status_for,
        since_for=since_for,
        started_for=status_started,
        changed_on=status_since,
        is_marker=lambda step: not estimate_enabled(step),
        wait_of=wait_read,
        start_of=start_of,
        milestone_label=milestone_read,
        estimate_history=estimate_history,
        key_of=_step_key,
    )


def _status_in(library: "Library", today: "date") -> "Callable[[Step], Reading]":
    """A step's status as the Step statuses tab, its report and the Run Agent gate read it on
    ``today``: a wait done once it is over and waiting until then (``schedule.wait_status``),
    so what follows a wait is ready on the day it may start; every other step as its status
    aspect says."""
    from dplanner.modules.step_wait.aspect import read as wait_read
    from dplanner.planning.schedule import Wait, wait_status
    from dplanner.planning.status import read_since as status_since
    from dplanner.planning.status import stored

    # A branch cut holds nothing once what it waits on is done: a wait of no days, read so
    # here and only here — the schedule's own waits never count one.
    held = Wait(days=0.0)
    return wait_status(
        library,
        stored,
        status_since,
        lambda step: wait_read(step) or (held if _is_cut(step) else None),
        today,
    )


def _ready_in(library: "Library", today: "date") -> "Callable[[Step], Status]":
    """:func:`_status_in` as readiness reads it (``status.held``): a word this build cannot
    read holds its step as blocked, and a wait not over is pending."""
    from dplanner.planning.status import readiness_of

    return readiness_of(_status_in(library, today))


def _wait_aware(library: "Library", today: "Callable[[], date]") -> "Callable[[Step], Reading]":
    """:func:`_status_in` for a window, on whatever day it is when asked."""
    return lambda step: _status_in(library, today())(step)


def _is_wait(step: "Step") -> bool:
    """Whether a step is a wait — the wait aspect's answer, for modules that may not ask it."""
    from dplanner.modules.step_wait.aspect import is_wait

    return is_wait(step)


def _is_cut(step: "Step") -> bool:
    """Whether a step is a branch cut — the branches module's answer."""
    from dplanner.modules.branches.aspect import is_cut

    return is_cut(step)


def _works_nobody(step: "Step") -> str:
    """What a step nobody works is called — "a wait", "a branch cut" — for the modules
    that refuse it a status, an agent, a review or a test; "" for a step somebody works."""
    from dplanner.modules.branches.aspect import A_CUT

    return "a wait" if _is_wait(step) else A_CUT if _is_cut(step) else ""


def _auto_progresses(waiter: "Step", source: "Step") -> bool:
    """Whether ``waiter`` may start once ``source`` is ready for review — the one answer
    the frontier, Run Agent's gate, the canvas and every CLI mark read: a flagged link, or
    any link into a review."""
    from dplanner.modules.auto_progress.aspect import progresses
    from dplanner.modules.step_review.aspect import reviews

    return progresses(waiter, source) or reviews(waiter, source)


def _persons_turn(library: "Library", step: "Step", status_for: "Callable[[Step], Status]") -> bool:
    """Whether a person moves ``step`` next — what its card pulses for: ready to merge,
    always; ready for review, unless an agent takes it on from there (``progression.taken``,
    the rule that keeps it off the boards' *Ready for review* too)."""
    from dplanner.planning.progression import taken
    from dplanner.planning.status import Status

    status = status_for(step)
    return status is Status.READY_TO_MERGE or (
        status is Status.READY_FOR_REVIEW
        and not taken(library, step, status_for, _auto_progresses, _is_agent_step)
    )


def _always_progresses(step: "Step") -> str:
    """Why every link into ``step`` auto-progresses whatever its flag says, or "" — the
    review's rule, which the Edge menu's toggle shows checked and greyed."""
    from dplanner.modules.step_review.aspect import TAKES_FROM_REVIEW, is_review

    return TAKES_FROM_REVIEW if is_review(step) else ""


def _is_agent_step(step: "Step") -> bool:
    """Whether an agent executes the step — the agent aspect's answer, for the status verb
    and the rows of `progression show`."""
    from dplanner.modules.step_agent_instruction.aspect import enabled

    return enabled(step)


def _preferred_agent(step: "Step") -> str:
    """The agent a step asks to be run by — a review's own choice, a harness id — or "" for
    the default profile."""
    from dplanner.modules.step_review.aspect import is_review, settings

    return settings(step).agent if is_review(step) else ""


def _asks_person(step: "Step") -> bool:
    """Whether a step's agent waits on a person — a plan to approve, a question to answer:
    what puts a running row under *Waits for you*."""
    from dplanner.modules.step_agent_run.aspect import asks_person

    return asks_person(step)


def _has_run(step: "Step") -> bool:
    """Whether the plan records an agent run on the step — the launch's own stamp."""
    from dplanner.modules.step_agent_run.aspect import read

    return bool(read(step))


def _due_now(
    library: "Library",
    project: "Project",
    status_for: "Callable[[Step], Status]",
    running: "Callable[[Step], bool]" = _has_run,
) -> "list[tuple[Step, TurnDue | None]]":
    """Every step of ``project`` a window that launches what becomes due would start, in
    project order: what auto-progress made due (``progression.due``), and a side of a
    conversation whose turn it is and whose agent has gone (``rounds.due_turns``) — carried
    with its turn, since its claim is a stamp on that round. One step due both ways is due
    for its turn: that claim is the one a later settle must read.

    The one derivation every surface reads: ``progression show`` marks it, the status verbs
    say what they made due, and the window launches it — with ``running`` widened there to
    the runs it is watching, which a claim not yet on disk cannot hide.
    """
    from dplanner.modules.step_review.rounds import due_turns
    from dplanner.planning.progression import due

    found: dict[str, tuple[Step, TurnDue | None]] = {
        turn.step.id: (turn.step, turn)
        for turn in due_turns(library, project, _is_agent_step, running, status_for)
    }
    for step in due(
        library, project, status_for, _auto_progresses, _is_agent_step, running, _counts_as_work
    ):
        found.setdefault(step.id, (step, None))
    place = {step.id: index for index, step in enumerate(project.steps)}
    return sorted(found.values(), key=lambda pair: place[pair[0].id])


def _due_steps(
    library: "Library", project: "Project", status_for: "Callable[[Step], Status]"
) -> "list[Step]":
    """The due steps alone — what the terminal marks and names."""
    return [step for step, _turn in _due_now(library, project, status_for)]


def _inherit_refs(subject: "Step", review: "Step") -> "Command | None":
    """The command giving ``review`` the branch and PR of the step it approved — so the
    review carries the PR's label into the merge — or None when there are none to carry."""
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.github.aspect import MODULE_ID as GITHUB_ID
    from dplanner.modules.github.aspect import read, write

    refs = read(subject)
    if refs is None:
        return None
    return SetModuleDataCommand(review.id, GITHUB_ID, write(refs), label="Inherit GitHub Refs")


def _note_escalation(context: "CliContext", review: "Step", title: str, body: str) -> str:
    """Keep what a person must decide as a handoff note on the escalated review — the note
    a blocked step says why in — and answer its id. A retried verb finds the same note."""
    from dplanner.modules.notes.log import Note, adding, check_label

    note, command = adding(
        context.library.project_of(review.id),
        Note(
            id="",
            label=check_label("handoff"),
            title=title,
            body=body,
            made=context.clock.today().isoformat(),
            step=review.id,
        ),
    )
    if command is not None:
        context.apply(command)
    return note.id


def _status_workflow() -> "StatusWorkflow":
    """Setting a status, as the window and every CLI verb do it: the root's answers for
    what nobody works and what an agent executes, and the notes module's way to keep a
    reason."""
    from dplanner.modules.step_status.workflows import StatusWorkflow

    return StatusWorkflow(
        works_nobody=_works_nobody, is_agent=_is_agent_step, keep_reason=_reason_note
    )


def _reason_note(
    view: "PlanView", step: "Step", reason: str, today: "date"
) -> "tuple[str, Command | None]":
    """Why a step went to done without review, as a decision note on it — added the way
    `note add` adds one, so a retried verb is one note: the note's id, and the command that
    adds it, None when the step already carries it."""
    from dplanner.modules.notes.log import Note, adding, check_label

    note, command = adding(
        view.project_of(step.id),
        Note(
            id="",
            label=check_label("decision"),
            title="Done without review",
            body=reason,
            made=today.isoformat(),
            step=step.id,
        ),
    )
    return note.id, command


def _counts_as_work(step: "Step") -> bool:
    """Whether a step is work: a wait and a branch cut are not — no worker takes them and no
    count holds them."""
    return not _works_nobody(step)


def _time_writers() -> "TimeWriters":
    """How a simulated day reaches the aspects it touches: each owner's own writer, handed
    the entry it replaces and the day — so a replayed status is dated by the status aspect,
    exactly as a person's edit on that day would have been."""
    from datetime import date

    from dplanner.domain.model import Project, Step
    from dplanner.modules.estimation.aspect import MODULE_ID as ESTIMATION_ID
    from dplanner.modules.estimation.aspect import write as write_estimate
    from dplanner.modules.estimation.schedule import write_start
    from dplanner.modules.step_agent_instruction.aspect import MODULE_ID as AGENT_ID
    from dplanner.modules.step_agent_instruction.aspect import write_state
    from dplanner.modules.step_milestone.aspect import MODULE_ID as MILESTONE_ID
    from dplanner.modules.step_milestone.aspect import write as write_label
    from dplanner.modules.step_wait.aspect import MODULE_ID as WAIT_ID
    from dplanner.modules.step_wait.aspect import write as write_wait
    from dplanner.modules.time_estimates.simulation.frames import PlanState, StepState, Writers
    from dplanner.planning.status import MODULE_ID as STATUS_ID
    from dplanner.planning.status import write as write_status

    def estimate(step: Step, state: StepState, today: date) -> tuple[str, dict[str, Any]]:
        previous = step.module_data.get(ESTIMATION_ID)
        return ESTIMATION_ID, write_estimate(
            state.estimate, on=not state.off, previous=previous, today=today
        )

    def status(step: Step, state: StepState, today: date) -> tuple[str, dict[str, Any]]:
        previous = step.module_data.get(STATUS_ID)
        return STATUS_ID, write_status(state.status, today=today, previous=previous)

    def milestone(_step: Step, state: StepState, _today: date) -> tuple[str, dict[str, Any]]:
        return MILESTONE_ID, write_label(state.milestone)

    def agent(_step: Step, state: StepState, _today: date) -> tuple[str, dict[str, Any]]:
        return AGENT_ID, write_state(state.agent)

    def wait(_step: Step, state: StepState, _today: date) -> tuple[str, dict[str, Any]]:
        return WAIT_ID, write_wait(state.wait)

    def start(_project: Project, plan: PlanState, _today: date) -> tuple[str, dict[str, Any]]:
        return ESTIMATION_ID, write_start(plan.start)

    return Writers(steps=(estimate, status, milestone, agent, wait), plan=(start,))


# The status verbs that write one, each followed by the day's progress row — the review
# verbs among them, since each moves a status too.
STATUS_WRITES = (
    ("status", "set"),
    ("status", "clear"),
    ("review", "post"),
    ("review", "reply"),
    ("review", "approve"),
    ("review", "escalate"),
)


def _status_written(
    command: "CliCommand", record: "Callable[[CliContext, Project], bool]"
) -> "CliCommand":
    """``command`` followed by ``record`` for the project of the step it named — and a line
    for every step the change made due, since only a window launches one and the terminal is
    where the agent that caused it reads what happens next.

    The line is text alone: ``--json`` keeps the one document the verb answers with, and
    ``progression show --json`` marks what is due for a caller that parses.
    """
    from dataclasses import replace

    from dplanner.cli.lookup import find_step

    inner = command.run

    def due_in(context: "CliContext", project: "Project") -> "list[Step]":
        today = context.clock.today()
        return _due_steps(context.library, project, _ready_in(context.library, today))

    def run(context: "CliContext", args: "Namespace") -> int:
        project = context.library.project_of(
            find_step(context.library, args.step, context.current).id
        )
        before = {step.id for step in due_in(context, project)}
        code = inner(context, args)
        record(context, project)
        if not context.as_json:
            for step in due_in(context, project):
                if step.id not in before:
                    print(
                        f"Now due: {_step_key(step)} {step.title or 'Untitled step'} — a DPlanner"
                        " window set to launch due steps starts its agent; with none open, a"
                        " person does",
                        file=context.out,
                    )
        return code

    return replace(command, run=run)


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
    from dplanner.modules.estimation.report import report_source as estimates
    from dplanner.modules.estimation.schedule import project_schedule
    from dplanner.modules.feature.report import report_source as features
    from dplanner.modules.github.report import report_source as github
    from dplanner.modules.notes.report import report_source as notes
    from dplanner.modules.progression.report import report_source as progression
    from dplanner.modules.project_editor.report import report_source as graph
    from dplanner.modules.step_description.report import report_source as descriptions
    from dplanner.modules.step_milestone.aspect import read as milestone_read
    from dplanner.modules.step_milestone.report import report_source as milestones
    from dplanner.modules.step_order.report import report_source as order
    from dplanner.modules.step_ticket.report import report_source as tickets
    from dplanner.modules.testing.report import report_source as tests
    from dplanner.modules.time_estimates.report import report_source as time_estimates

    summaries = aspect_summaries(skip={ESTIMATION_ID})

    def step_aspects(step: "Step") -> list[str]:
        return [phrase for phrase in (summary(step) for summary in summaries) if phrase]

    return (
        progression(
            status_in=_ready_in,
            counts_as_work=_counts_as_work,
            days_for=estimated_days,
            key_of=_step_key,
            auto_progresses=_auto_progresses,
        ),
        time_estimates(_time_readers()),
        graph(
            key_of=_step_key,
            kind_of=_step_kind,
            status_for=_card_status,
            stats_of=_step_stats,
            badge_of=milestone_read,
            # The report's picture of the graph wears the same shades the window does, and
            # the same glyph in each card's key block.
            colors_of=_milestone_colors,
            glyph_of=_primary_glyph,
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


def _agent_preamble(
    step: "Step", in_worktree: bool, facts: "RepositoryFacts | None", branches: "BranchPlan"
) -> str:
    """The briefing's preflight: the agent proves it can report back, that it is where
    this run said it would be, and knows where the plan lives, before it starts.

    An agent without the DPlanner skill would do the work and leave the plan blind — no
    status, no handoff — so the briefing makes the check the first move and stopping the
    honest fallback. The second check is the worktree: two agents once "launched into
    fresh worktrees" and did their work on the same branch, so an agent whose step asks
    for a worktree confirms it is in one — by the name the launcher prepared — and stops
    if it is not. ``in_worktree`` is the caller's word on *this run* — ``Briefing.worktree``
    for Run Agent and ``agent prompt``, never for a conflict the window hands over; a review
    that gets none is told to leave the checkout as it found it.
    ``facts`` says where the plan lives: apart from the code, or inside it — the shape that
    drifts, so the agent is warned to leave the plan files alone and let the verbs write.
    Root prose for the same reason as the epilogue: it names other modules' verbs and the
    launcher's naming. ``branches`` names the branch the worktree is on, the one the
    launcher prepared.
    """
    from dplanner.modules.step_agent_instruction.launcher import WORKTREES_DIR

    lines = [
        "First, confirm you can drive DPlanner: run `dplanner skill status`. If the"
        " command is missing or the skill is not installed, STOP — do not carry out the"
        " step — and tell the developer this step needs the DPlanner skill"
        " (`dplanner skill install`)."
    ]
    key = _step_key(step) or step.title or "this step"
    ref = _quoted(key)
    lines.append(
        "Then say you are working, before you touch anything: `dplanner agent-work start"
        f" '<what you are about to do>' --step {ref}`. A developer may have a DPlanner"
        " window open on this plan, and that is what tells them somebody else is editing"
        " it — without it they will edit the same steps you are rewriting and be asked to"
        " settle collisions they did not cause. Keep it current as you go"
        f" (`dplanner agent-work set '<what now>' --done N --of M`); setting the step's"
        " status when you finish ends it, and if you stop without one, end it yourself"
        f" (`dplanner agent-work end --step {ref}`)."
    )
    if in_worktree:
        name = _run_name(step)
        lines.append(
            "Second, confirm you are in this step's own git worktree: `git rev-parse"
            f" --show-toplevel` must end in `{WORKTREES_DIR}/{name}` and `git branch"
            f" --show-current` must print `{branches.branch_for(name)}`. If either differs, STOP"
            " — do not touch the main checkout — and tell the developer the worktree"
            " was not prepared. Commit on that branch; every `dplanner` command still"
            " reaches the plan the window shows."
        )
    elif withheld := _no_worktree(step):
        lines.append(
            f"This step runs in the checkout itself, with no worktree of its own — {withheld}."
            " Leave the checkout as you found it: no commits, no branch switches, no stashes."
            " Other agents may be in worktrees beside you, and this checkout is the"
            " developer's."
        )
    else:
        lines.append(
            "This step works in the checkout itself (its worktree option is off), on the"
            " branch that is checked out — take care: other agents may be in worktrees"
            " beside you, but this one shares the developer's working tree."
        )
    if facts is not None:
        lines.append(_plan_whereabouts(facts))
        told = _locations_told(facts)
        if told:
            lines.append(told)
    lines.append(
        "Other agents may be working beside you in this repository, each in a worktree"
        " of its own, and their processes carry the same names and paths as yours. Never"
        " kill a process by name or pattern (`pkill -f`, `killall`, `kill $(pgrep …)`):"
        " kill only by a pid your own shell started."
    )
    return "\n\n".join(lines)


def _locations_told(facts: "RepositoryFacts") -> str:
    """The project's locations, told to the agent: which repositories it is about and
    where each stands on this machine, so an agent never guesses a path. Root prose
    because it names the roles every module declared and the verb that prints them
    again."""
    from dplanner.domain.locations import CODE, roles_by_id

    if not facts.placements:
        return ""
    roles = roles_by_id(default_location_roles())
    told: list[str] = []
    for placement in facts.placements:
        location = placement.location
        role = roles.get(location.role)
        inside = f" at `{location.path}/`" if location.path else ""
        if placement.root is None:
            where = "not checked out on this machine — do not look for it"
        elif placement.managed:
            where = "read-only, fetched by the window into the plan's spec documents"
        elif role is not None and role.writes and location.role != CODE.id:
            where = f"DPlanner exports report sites to `{placement.directory}` — do not write there"
        elif placement.kept:
            where = (
                f"`{placement.directory}` — a clone DPlanner keeps; work there as in any checkout"
            )
        else:
            where = f"`{placement.directory}`"
        told.append(f"{location.name(roles)}: {location.repository_label}{inside} — {where}")
    return (
        "The project's locations — which repositories it is about, and where each is on"
        " this machine (`dplanner location list` prints them again): " + "; ".join(told) + "."
    )


def _plan_whereabouts(facts: "RepositoryFacts") -> str:
    """Where the plan lives, told to the agent: in a repository of its own, or — warned
    about unless the people on the project accepted it — inside the code it plans; or, before
    anybody named the code, in a repository of its own with nothing yet to work in."""
    from dplanner.domain.repositories import UNSET

    if facts.state == UNSET:
        return (
            f"The plan is kept in its own repository, {facts.plan_label}, and no code"
            " repository is recorded for the project yet: the plan repository is not the"
            " code, so change nothing in it by hand. The developer records the code with"
            " `dplanner location add <project> --role code --repository URL`."
        )
    if not facts.plan_in_code:
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


def _agent_epilogue(library: "Library", step: "Step", branches: "BranchPlan") -> str:
    """The briefing's closing words: how the agent reports back through the CLI.

    Cross-module prose — it names the status and note verbs — so it is written here, in
    the one file allowed to know every module's vocabulary, and handed to the agent module
    as a callback on both surfaces. Every verb names the step by its key: a key is
    unambiguous where a title may match two steps, and it is what the branch and the
    PR are named after; the note verbs name the project too, since a note is the
    project's record. A review reports through its verdict instead
    (``_review_epilogue``), and a step a review waits on does not stop at ready for
    review: it answers the rounds.
    """
    from dplanner.modules.auto_progress.aspect import collectors
    from dplanner.modules.notes.reach import project_ref
    from dplanner.modules.step_review.aspect import is_review, reviews, settings

    key = _step_key(step) or step.title or "Untitled step"
    ref = _quoted(key)
    project = project_ref(library.project_of(step.id))
    if is_review(step):
        return _review_epilogue(key, ref, project)
    takers = [_step_key(other) or other.title for other in collectors(library, step)]
    collected = (
        f"- {_listed(takers)} {'collects' if len(takers) == 1 else 'collect'} this step's work:"
        f" {'it' if len(takers) == 1 else 'each'} may start as soon as you set"
        " ready-for-review, and takes your branch or PR from there — so push everything"
        " and open the PR first. Leave this step's done to "
        f"{'it' if len(takers) == 1 else 'them'}.\n"
        if takers
        else ""
    )
    reviewers = [other for other in library.dependents(step.id) if reviews(other, step)]
    if reviewers:
        who = _listed([_step_key(other) or other.title for other in reviewers])
        one = len(reviewers) == 1
        cap = max(settings(other).max_rounds for other in reviewers)
        named = "" if one else " (with `--from <review>` when more than one has posted)"
        finished = (
            f"- `dplanner status set {ref} ready-for-review`, then `dplanner agent-state set"
            f" {ref} pending-approval` — push everything and open the PR first. {who}"
            f" {'reviews' if one else 'review'} this step next, in at most {cap} rounds, and"
            " you answer, so do not stop at ready for review:\n"
            f"  1. `dplanner review wait {ref}` returns when a round is posted to you or the"
            " review ends; exit 3 means nothing yet after nine minutes — run it again.\n"
            f"  2. Findings arrived: `dplanner review take {ref}`{named} prints them. Settle"
            " each one — or say why not — commit and push, then `dplanner review reply"
            f" {ref} --file <reply.md>`, which sets this step ready for review again. Back"
            " to 1.\n"
            f"  3. Stop waiting when the review approves — it sets this step done;"
            f" `dplanner agent-state clear {ref}` and you are finished — or when it hands the"
            " review to a person (a note says what they must decide: stop there), or after"
            " an hour of waiting with nothing new: stop, and relaunching this step briefs"
            " you with any round that arrived meanwhile.\n"
        )
    else:
        finished = (
            f"- `dplanner status set {ref} ready-for-review` and `dplanner agent-state clear"
            f" {ref}` — ready for review, never done: a person or a reviewing agent looks next"
            " and sets it done. That is the step's work finished, not the mid-run"
            " `plan-for-review` above, which is your plan waiting for a look. If nothing needs"
            f" reviewing, `dplanner status set {ref} done --because '<why>'` keeps the reason"
            " as a decision note.\n"
        )
    base = (
        f" Open it against `{branches.pr_base}`: `gh pr create --base {branches.pr_base}`."
        if branches.pr_base
        else ""
    )
    found = _branch_reading(library.project_of(step.id))
    stretch = None if found.of_land(step.id) else found.innermost(step.id, open_only=True)
    if stretch is not None:
        cut, land = _step_key(stretch.cut), _step_key(stretch.land)
        base += (
            f" This step is on the feature branch `{stretch.branch}`, which {cut} cuts and"
            f" {land} lands: its PR merges into that branch, never into the mainline, and merged"
            " there it is accepted — the branch's own review comes when it lands."
        )
    return (
        f"This step is {key}. Its branch and worktree carry that key; open the PR title"
        f" with it (`{key}: …`) and record the branch and the PR on the step as they"
        f" exist: `dplanner github set {ref} --branch $(git branch --show-current)`,"
        f" then `dplanner github set {ref} --pr <number>`.{base} Once the PR is open, set"
        " the status (below) straight away: it takes the window's banner down with it.\n"
        "As you work, keep the run state current:\n"
        f"- `dplanner agent-state set {ref} plan-for-review` when your plan is ready"
        " to review\n"
        f"- `dplanner agent-state set {ref} working` while implementing\n"
        f"- `dplanner agent-state set {ref} pending-approval` while waiting on an"
        " approval\n"
        f"- `dplanner agent-state set {ref} needs-input` when you have a question the"
        " developer must answer before you can go on\n"
        + _notes_told(project, ref)
        + "When the work is finished, record it in DPlanner:\n"
        + finished
        + collected
        + _handoff_told(project, ref)
        + f"If you cannot finish, `dplanner status set {ref} blocked` and say why in the"
        " handoff note.\n"
        "Each of those statuses ends your working claim. If you stop without setting one,"
        f" end it yourself: `dplanner agent-work end --step {ref}` — a banner nobody ended"
        " is one nobody believes next time."
    )


def _review_epilogue(key: str, ref: str, project: str) -> str:
    """A review's closing words. It opens no branch and no PR — approving carries its
    subject's — and its verdict is its status, so it is told the verdicts and never a
    status to set by hand."""
    return (
        f"This step is {key}. A review opens no branch and no PR of its own — approving"
        " carries its subject's onto it — and its verdict is its status: `dplanner review"
        f" approve {ref}` leaves the subject done and this review ready to merge; `dplanner"
        f" review escalate {ref} --text '<what they must decide>'` leaves it blocked, with a"
        " note for a person. Never `status set` either step yourself.\n"
        "As you work, keep the run state current:\n"
        f"- `dplanner agent-state set {ref} working` while you read the work and write"
        " findings\n"
        f"- `dplanner agent-state set {ref} pending-approval` while you wait on the answer\n"
        f"- `dplanner agent-state set {ref} needs-input` when you have a question the"
        " developer must answer before you can go on\n"
        + _notes_told(project, ref)
        + _handoff_told(project, ref)
        + f"Once the review has its verdict, `dplanner agent-state clear {ref}` — the verdict's"
        " status ends your working claim. If you stop without one, end it yourself:"
        f" `dplanner agent-work end --step {ref}` — a banner nobody ended is one nobody"
        " believes next time."
    )


def _notes_told(project: str, ref: str) -> str:
    """The notes an agent leaves as it goes, as every epilogue words them."""
    return (
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
    )


def _handoff_told(project: str, ref: str) -> str:
    """The handoff note an agent leaves when it stops, as every epilogue words it."""
    return (
        f"- `dplanner note add {project} handoff '<one line the next worker needs>'"
        f" --step {ref} --file -` with what whoever picks up after you must know —"
        " where things are, what is half done, what bit you. Title it as the fact it"
        " is; the body carries the detail. Add `--for S12` for a step that must read it"
        " in full, `--reach project` if every step should see it regardless;"
        f" `dplanner note attach {project} <id> <file>` for files.\n"
    )


def _scope_kinds() -> tuple["ScopeKind", ...]:
    """The collectors this build knows, and where each one's cone stops.

    Read most specific first: a step marked as both a milestone and a feature is a milestone,
    because that is the coarser claim and the one a person is looking for.

    The stopping rules are the whole design. A **check** stands for everything behind it
    having been verified, so it stops at nothing. A **milestone** collects what is new since
    the previous milestone, so it stops at milestones. A **feature** collects its own work up
    to the previous feature — and at a milestone too, since a milestone is a boundary anything
    below it also respects.

    The two that *own* work — a milestone and a feature — also stop at the plan's **start**:
    every parallel branch traces back to the origin, so without that every feature fanning
    out of it would gather it, and lint would call the recommended shape ambiguous. A check
    owns nothing and still stands for everything, the start included.

    A milestone and a check are then *read* as lists of features; a feature is the finest
    grain and is read flat. That is a different question from where the walk stops, and
    saying both here is what keeps a surface from having to guess either.

    Written literally rather than derived from a rank, because three lines a reader can
    check by eye beat an ordering abstraction over exactly three things.
    """
    from dplanner.domain.scope import ScopeKind
    from dplanner.modules.feature.aspect import is_feature
    from dplanner.modules.step_check.aspect import read as is_check
    from dplanner.modules.step_milestone.aspect import read as milestone_label
    from dplanner.modules.step_start.aspect import read as is_start

    # A milestone declares itself by carrying a label, so the aspect's reader is a string
    # one; the walk wants a predicate, and this is the one place that has to know both.
    def is_milestone(step: "Step") -> bool:
        return bool(milestone_label(step))

    return (
        ScopeKind(
            "step_milestone",
            "Milestone",
            is_milestone,
            lambda step: is_milestone(step) or is_start(step),
            gathers="feature",
        ),
        ScopeKind(
            "feature",
            "Feature",
            is_feature,
            lambda step: is_feature(step) or is_milestone(step) or is_start(step),
        ),
        ScopeKind("step_check", "Check", is_check, lambda _step: False, gathers="feature"),
    )


def _flows_into(library: "Library", project: "Project", step_id: str) -> list["Step"]:
    """The features that gather a step, in project order — what a work step's briefing
    and its passages reach the spec through. The wired feature kind's own walk, so it holds
    exactly what `scope show` says a feature holds, and the plan's start flows into none."""
    from dplanner.domain.scope import gatherers

    feature = next(kind for kind in _scope_kinds() if kind.id == "feature")
    owners = gatherers(
        library, project, carried_by=feature.carried_by, stops_at=feature.stops_at
    ).get(step_id, ())
    return [owned for owner in owners if (owned := project.step(owner)) is not None]


def _coverage_trace(library: "Library", project: "Project", files: "FilesFor") -> "Trace":
    """The coverage picture: milestones → features → spec passages → steps → tests and docs.

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
    from dplanner.modules.step_milestone.aspect import read as milestone_read
    from dplanner.modules.testing.aspect import covered
    from dplanner.modules.testing.runs import latest_results
    from dplanner.modules.testing.runs import read as read_runs

    scopes = _scope_kinds()
    kinds = {kind.id: kind for kind in scopes}

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
            feature_kind=kinds["feature"],
            milestone_kind=kinds["step_milestone"],
            milestone_label=milestone_read,
            step_key=_step_key,
            status=_card_status,
            tests=tests,
            results=results,
            docs=docs,
            # The milestone lane wears the same shades the canvas and the calendar do, and a
            # card that is a step the canvas's glyph in its key block.
            milestone_colors=_milestone_colors,
            glyph=_primary_glyph,
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
    tuple. Eight entries, on purpose: an id minted per project (a test's), the state of a
    shell somebody is running and what its runs consumed, the conversation a review held,
    and the days a status was said on — all facts about the original — a feature's
    passages, which were read into *that* feature and are not a claim a copy may make, and
    the steps an auto-progress entry and a landing name, which become their copies'.
    Everything else a step carries copies as it is.
    """
    from dplanner.modules.auto_progress.aspect import remap_for_paste
    from dplanner.modules.branches.aspect import remap_for_paste as remap_landing
    from dplanner.modules.feature.aspect import drop_cites_for_paste
    from dplanner.modules.step_agent_run.aspect import forget_for_paste
    from dplanner.modules.step_review.rounds import forget_for_paste as forget_rounds
    from dplanner.modules.testing.aspect import remint_for_paste
    from dplanner.planning.status import forget_days_for_paste

    return (
        remint_for_paste,
        forget_for_paste,
        forget_rounds,
        forget_days_for_paste,
        drop_cites_for_paste,
        remap_for_paste,
        remap_landing,
    )


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


def _unsettling_notes(
    project: "Project",
) -> dict["StepId", tuple[tuple[str, str, str, str], ...]]:
    """The standing notes that put a test in doubt, by the step they were made on.

    **Which labels those are is named here, literally**, for the reason `_scope_kinds()`
    names its predicates here: this is the one place that may know every aspect, and
    `modules/testing/` may not learn the notes module's vocabulary. A *decision* changes
    what the work should do and a *spec-change* records where it departed from the spec —
    either can leave a test proving last month's answer. A *handoff*, a *later* or a
    *post-project* note says nothing about what a test should assert, so neither should
    it put one in front of somebody.

    Superseded notes are dropped: the note that replaced one is itself a decision, made
    later, so it already stands for the doubt — reporting both would name one test twice.
    """
    from dplanner.modules.notes.log import read_log, standing

    unsettling = ("decision", "spec-change")
    found: dict[StepId, list[tuple[str, str, str, str]]] = {}
    for note in standing(read_log(project)):
        if note.label in unsettling and note.step:
            found.setdefault(note.step, []).append((note.id, note.label, note.title, note.made))
    return {step_id: tuple(notes) for step_id, notes in found.items()}


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
    from dplanner.modules.auto_progress import cli as auto_progress_cli
    from dplanner.modules.branches import cli as branches_cli
    from dplanner.modules.docs import cli as docs_cli
    from dplanner.modules.estimation import cli as estimation_cli
    from dplanner.modules.feature import cli as feature_cli
    from dplanner.modules.project_editor import cli as layout_cli
    from dplanner.modules.projects import cli as projects_cli
    from dplanner.modules.spec import cli as spec_cli
    from dplanner.modules.step_agent_instruction import cli as agent_cli
    from dplanner.modules.step_description import cli as description_cli
    from dplanner.modules.step_description.aspect import read as description_read
    from dplanner.modules.step_milestone.aspect import is_milestone
    from dplanner.modules.step_review import cli as review_cli
    from dplanner.modules.step_review.aspect import is_review
    from dplanner.modules.step_start import cli as start_cli
    from dplanner.modules.testing import cli as testing_cli
    from dplanner.modules.testing.aspect import enabled as test_enabled

    scopes = _scope_kinds()
    return (
        *projects_cli.lint_checks(),
        *start_cli.lint_checks(),
        # Collecting is an agent's job: the agent aspect's reader, handed over.
        *auto_progress_cli.lint_checks(is_agent=_is_agent_step, key_of=_step_key),
        # A branch is one way in and one way out; what it says is its PRs' bases.
        *branches_cli.lint_checks(
            is_done=_is_done,
            is_agent=_is_agent_step,
            is_milestone=is_milestone,
            pr_base_of=_pr_base,
        ),
        # A review needs an agent, one subject and an agent this build knows.
        *review_cli.lint_checks(
            is_agent=_is_agent_step, key_of=_step_key, harnesses=agent_harnesses()
        ),
        *description_cli.lint_checks(),
        *docs_cli.lint_checks(kinds=scopes),
        # An agent step is briefed by its description unless it carries a separate
        # instruction, and a review or a landing by its aspect; the readers arrive here, not
        # by import.
        *agent_cli.lint_checks(
            described=lambda step: bool(description_read(step)) or is_review(step) or _is_land(step)
        ),
        *estimation_cli.lint_checks(counts_as_work=_counts_as_work),
        *spec_cli.lint_checks(),
        *feature_cli.lint_checks(anchor=spec_cli.anchor_sources, key_of=_step_key),
        *layout_cli.lint_checks(key_of=_step_key),
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


def at_work_board() -> "AtWorkBoard":
    """Where an agent's *at work* claims live on this machine — ``domain/at_work.py``.

    Named here and nowhere deeper, like the topology gate's record file and the spec-git
    cache: a feature module never reaches ``config_dir()``. Both surfaces build it from
    this one function, so the window reads exactly the directory the CLI writes.
    """
    from dplanner.core.config_dir import config_dir
    from dplanner.domain.at_work import DIRECTORY, AtWorkBoard

    return AtWorkBoard(config_dir() / DIRECTORY)


def launch_locks_in(directory: "Path") -> "LaunchLocks":
    """The launch locks a session holds, one per library, under ``directory`` — built once
    per session so a reload's window keeps the hold (``auto_launch.py``)."""
    from dplanner.modules.step_agent_instruction.auto_launch import LaunchLocks

    return LaunchLocks(directory)


def auto_launch_directory() -> "Path":
    """Where this machine's launch locks live: which window launches what becomes due, one
    per library. Named here and nowhere deeper, like the at-work board."""
    from dplanner.core.config_dir import config_dir

    return config_dir() / "auto-launch"


def start_window(services: "AppServices") -> None:
    """What the program's first window shows once it is built: the tabs the last session
    had, which reopen_tabs brought back during the build — or, when that left none open,
    Home.

    Called by ``app.open_at_startup`` and nowhere else, because it is the *program's*
    start and nothing more: a reload rebuilds the window the person had, and a window
    whose last tab they closed stays blank — ARCHITECTURE.md's *Home is where a window
    starts*.
    """
    from dplanner.modules.home.page import HOME_KIND

    if not services.tabs.activities():
        services.tabs.open(HOME_KIND)


def default_cli_commands(
    reads: "ReadRecord | None" = None, board: "AtWorkBoard | None" = None
) -> list["CliCommand"]:
    """Every ``dplanner <noun> <verb>``, from the same modules the window is built from.

    The headless half of the composition root. It imports each module's ``cli.py`` and
    nothing else — no ``module.py``, no Qt — which is what lets ``dplanner project list``
    start in milliseconds and run where a graphics stack does not exist.

    ``reads`` is what this machine has read: the record both gates stand on — the topology
    every graph-editing verb waits for, and the house format a test body is written in —
    and None builds the real one over the user's config directory. The test suite's shared
    registry passes a record with no file, which refuses nothing and writes nothing, so no
    test ever writes the per-user file. ``board`` is the same arrangement for the *at work*
    claims — None builds :func:`at_work_board`, and a test hands in one over its own
    directory.
    """
    from dplanner.cli.aspects import commands as aspect_commands
    from dplanner.cli.assets import catalog_commands
    from dplanner.cli.checklist import commands as checklist_commands
    from dplanner.cli.command import CliRegistry
    from dplanner.cli.desktop import commands as desktop_commands
    from dplanner.cli.gate import RECORD_FILE, GuideGate, ReadRecord, TopologyGate, gated
    from dplanner.cli.install import commands as install_commands
    from dplanner.cli.lint import commands as lint_commands
    from dplanner.cli.report.commands import commands as report_commands
    from dplanner.cli.scopes import commands as scope_commands
    from dplanner.cli.skill import commands as skill_commands
    from dplanner.cli.skill import generate
    from dplanner.cli.telemetry import commands as telemetry_commands
    from dplanner.core.config_dir import config_dir
    from dplanner.core.telemetry import crash_log_path, journal_path
    from dplanner.domain.locations import roles_by_id
    from dplanner.domain.workflow import AgentRun, Person
    from dplanner.modules.agent_at_work import cli as at_work_cli
    from dplanner.modules.auto_progress import cli as auto_progress_cli
    from dplanner.modules.branches import cli as branches_cli
    from dplanner.modules.coverage import cli as coverage_cli
    from dplanner.modules.docs import cli as docs_cli
    from dplanner.modules.estimation import cli as estimation_cli
    from dplanner.modules.estimation.aspect import read as estimated_days
    from dplanner.modules.feature import cli as feature_cli
    from dplanner.modules.github import cli as github_cli
    from dplanner.modules.library import cli as library_cli
    from dplanner.modules.notes import cli as note_cli
    from dplanner.modules.progression import cli as progression_cli
    from dplanner.modules.project_assets import cli as assets_cli
    from dplanner.modules.project_assets.cli import read_titles
    from dplanner.modules.project_editor import cli as layout_cli
    from dplanner.modules.project_editor.stack_edits import bridged_removal
    from dplanner.modules.projects import cli as projects_cli
    from dplanner.modules.spec import cli as spec_cli
    from dplanner.modules.spec.aspect import read_topology
    from dplanner.modules.step_agent_instruction import cli as agent_cli
    from dplanner.modules.step_agent_run import cli as agent_state_cli
    from dplanner.modules.step_check import cli as check_cli
    from dplanner.modules.step_description import cli as description_cli
    from dplanner.modules.step_milestone import cli as milestone_cli
    from dplanner.modules.step_order import cli as order_cli
    from dplanner.modules.step_review import cli as review_cli
    from dplanner.modules.step_start import cli as start_cli
    from dplanner.modules.step_status import cli as status_cli
    from dplanner.modules.step_status.workflows import perform
    from dplanner.modules.step_ticket import cli as ticket_cli
    from dplanner.modules.step_wait import cli as wait_cli
    from dplanner.modules.testing import cli as testing_cli
    from dplanner.modules.testing.format import FORMAT_SUBJECT, FORMAT_VERB
    from dplanner.modules.testing.format import guide as test_format
    from dplanner.modules.time_estimates import cli as time_cli
    from dplanner.planning.status import Status, stored

    specs = aspect_specs()
    time_readers = _time_readers()
    scopes = _scope_kinds()
    sources = _asset_sources()
    roles = roles_by_id(default_location_roles())
    if reads is None:
        reads = ReadRecord(config_dir() / RECORD_FILE)
    gate = TopologyGate(reads=reads, topology_of=read_topology)
    # The second door: the house shape of a test body, read once per machine rather than
    # once per project, because the document is this build's own and not any plan's.
    format_gate = GuideGate(
        reads=reads, text=test_format(), verb=FORMAT_VERB, subject=FORMAT_SUBJECT
    )
    if board is None:
        board = at_work_board()

    workflow = _status_workflow()

    def end_claim(claim: "EndClaim") -> bool:
        return board.end(claim.project, claim.step)

    def actor() -> "Actor":
        return AgentRun() if agent_shell_marker() else Person()

    def set_status(context: "CliContext", step: "Step", status: "Status") -> bool:
        """A status written as `status set` writes it, ending a stopped step's claim."""
        change = workflow.set_status(
            context.library, step, status, actor=actor(), today=context.clock.today()
        )
        if change.command is not None:
            context.apply(change.command)
        return perform(change, end_claim)

    def finish_merged(context: "CliContext", step: "Step") -> bool:
        """A step waiting on its merge is done once its PR reads merged — written as
        `status set` writes it; True when it was finished. A step on a feature branch is
        accepted by its PR merging into that branch, whether or not it was under review."""
        status = stored(step)
        accepted = status is Status.READY_TO_MERGE or (
            status is Status.READY_FOR_REVIEW and _merged_into_its_branch(context.library, step)
        )
        if not accepted:
            return False
        set_status(context, step, Status.DONE)
        return True

    commands = [
        *library_cli.commands(),
        # The step authors let `step add` author the step in the same call; the list
        # order is the report order — the same order the skill teaches authoring in.
        *projects_cli.commands(
            step_authors=[
                start_cli.step_author(),
                description_cli.step_author(),
                agent_cli.step_author(),
                # After --after has made the links, and the agent aspect beside them.
                auto_progress_cli.step_author(),
                review_cli.step_author(),
                estimation_cli.step_author(),
                # The feature author carries the spec-passage flags: creating a feature
                # *is* creating its step, so there is no verb of its own to put them on.
                feature_cli.step_author(anchor=spec_cli.anchor_sources),
                spec_cli.step_author(),
                testing_cli.step_author(),
            ],
            # The key a row prints is the one the canvas paints: one rule, here.
            key_of=_step_key,
            # `project graph` and `step show` mark the links a step collects across, and
            # the feature branch a step's work is on.
            auto_progresses=_auto_progresses,
            branches_in=_branches_in,
            # The location roles every module declared, and where a read-only one's
            # managed clone stands — both cross-module facts, handed in here.
            roles=roles,
            managed=managed_for(roles),
            kept_root=config_dir(),
            # A step removed from a stack closes the chain round it, as Delete does.
            remove_steps=bridged_removal,
        ),
        # `topology show` tells the gate what it printed; the gate is built here, so the
        # spec module never learns where the record lives.
        *spec_cli.commands(note_read=gate.record, rename_references=_rename_spec_references),
        *estimation_cli.commands(counts_as_work=_counts_as_work),
        *ticket_cli.commands(),
        *description_cli.commands(),
        *docs_cli.commands(kinds=scopes),
        *agent_cli.commands(briefing=_default_briefing()),
        # What a run consumed is read through the harness that ran it, so the verbs are
        # handed the same tuple the window's tracker reads.
        *agent_state_cli.commands(harnesses=agent_harnesses()),
        # The agent's own account of what it is doing while it does it: the window's
        # banner and the watcher's stood-down modal both read what these write.
        *at_work_cli.commands(board=board, key_of=_step_key),
        # An agent's done waits for review: the verb reads who is reporting (an agent's
        # shell, the entry point's reading) and what the step is (an agent step), and a
        # `--because` lands as a decision note in the same run. A status that says nobody
        # is working the step ends the claim somebody made on it, on the board above.
        *status_cli.commands(
            workflow=workflow,
            in_agent_shell=lambda: bool(agent_shell_marker()),
            end_claim=end_claim,
        ),
        *milestone_cli.commands(),
        *wait_cli.commands(),
        # Who may collect (an agent step) and where each source stands, through the
        # owners' Qt-free readers.
        *auto_progress_cli.commands(is_agent=_is_agent_step, status_for=stored, key_of=_step_key),
        # A branch's two ends are born dressed as the window's Put on a Branch makes them.
        *branches_cli.commands(
            born=_branch_births,
            is_done=_is_done,
            stacked_apart=_stacked_apart,
            key_of=_step_key,
        ),
        # A review talks to whoever it takes work from review on — the root's one answer —
        # and moves their statuses through the writer `status set` uses, so a claim ends
        # the same way whichever verb stopped the work. Approving carries the reviewed
        # step's refs across; escalating keeps a note for a person.
        *review_cli.commands(
            auto_progresses=_auto_progresses,
            status_for=stored,
            set_status=set_status,
            inherit_refs=_inherit_refs,
            note_escalation=_note_escalation,
            works_nobody=_works_nobody,
            key_of=_step_key,
            harnesses=agent_harnesses(),
        ),
        # A feature's passages are anchored in the spec documents by the spec module's
        # one derivation, handed across here — `cite`, `reanchor`, `step add --feature`
        # and lint all judge a quote the same way.
        *feature_cli.commands(anchor=spec_cli.anchor_sources, key_of=_step_key),
        # `test review` reads a step's status and the notes made on it — both through
        # their modules' Qt-free readers, handed over here so no cli.py imports another's.
        # `test format` tells the gate what it printed, the way `topology show` does; the
        # gate is built here, so the testing module never learns where the record lives.
        *testing_cli.commands(
            status_for=stored, notes_for=_unsettling_notes, note_read=format_gate.record
        ),
        *check_cli.commands(),
        *start_cli.commands(),
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
        *order_cli.commands(days_for=estimated_days, counts_as_work=_counts_as_work),
        # Progression reads statuses and estimates through the aspects' Qt-free readers —
        # handed over here so no cli.py imports another module's.
        *progression_cli.commands(
            status_in=_ready_in,
            counts_as_work=_counts_as_work,
            days_for=estimated_days,
            auto_progresses=_auto_progresses,
            is_agent=_is_agent_step,
            asks_person=_asks_person,
            due=_due_steps,
        ),
        # The timeline sort reads a step's length through estimation's Qt-free reader —
        # handed over here so neither cli.py imports the other.
        *layout_cli.commands(
            days_for=estimated_days,
            paste_policies=_paste_policies(),
            file_modules=tuple(source.id for source in sources),
            key_of=_step_key,
            # A sort leaves a card on a branch the room of its strip, as the window does.
            strips=lambda project: _strips(_branch_reading(project)),
        ),
        # The staffing matrix reads estimates, agent-ness and the start date through the
        # owners' Qt-free readers — handed over here so no cli.py imports another module's.
        *time_cli.commands(time_readers),
        *github_cli.commands(finish_merged=finish_merged),
        # A note names the step it was made on by id and prints it by key — the
        # same rule every row prints, handed over rather than imported.
        *note_cli.commands(key_of=_step_key),
        # The report is every module's Qt-free say, assembled once (`_report_sources`) for
        # the terminal and the window alike; the readers every step row needs come with it.
        *report_commands(
            sources=_report_sources(),
            key_of=_step_key,
            kind_of=_step_kind,
            status_for=stored,
            reporting_site=_cli_reporting_site,
        ),
        # The journal both surfaces write, read back: the paths are the process's, handed
        # over here so a test can point the same verbs at a file of its own.
        *telemetry_commands(journal=journal_path(), crash_log=crash_log_path()),
        *aspect_commands(specs),
        # Each module exports what "missing" means for its own aspect; the assembler is
        # shared with the window's Problems panel, which is a second presenter of exactly
        # this list.
        *lint_commands(checks=list(_lint_checks()), roles=roles),
    ]
    # A status said from the terminal is a day of work on record, window or no window: an
    # agent reports with `status set`, and nobody opens a window to record it. It is also
    # the moment a step may become due, which the terminal says.
    commands = [
        _status_written(
            command, lambda context, project: time_cli.record_day(context, project, time_readers)
        )
        if command.path in STATUS_WRITES
        else command
        for command in commands
    ]
    # Every verb that declared a door runs behind it — the topology for a graph edit, the
    # house format for a test body. Wrapped before the skill reads the registry, so the
    # skill marks the gated verbs.
    commands = [gated(command, gate, {FORMAT_VERB: format_gate}) for command in commands]
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


def _ledger_dir(store: "LibraryStore", project_id: str) -> "Path | None":
    """Where a project keeps its ledger: its directory, or None for one the store does
    not hold."""
    try:
        return store.project_dir(project_id)
    except KeyError:
        return None


def _step_spent(store: "LibraryStore", project_id: str) -> "dict[str, Spent]":
    """What each step's agent runs consumed, per model, from the project's usage ledger."""
    from dplanner.domain.expenditure import spent_by_step
    from dplanner.domain.ledger import records

    directory = _ledger_dir(store, project_id)
    if directory is None:
        return {}
    return spent_by_step((record.step, record.models()) for record in records(directory))


def _token_rate(
    store: "LibraryStore",
    library: "Library",
    project_id: str,
    days_for: "Callable[[Step], float | None]",
    done_for: "Callable[[Step], bool]",
) -> "Rate | None":
    """Tokens of work per estimated day: learned from the library's *other* projects when
    they have finished history, since a rate learned from the steps it is compared with
    would make the offset end at nought; from this project only when nothing else has."""
    from dplanner.domain.expenditure import ELSEWHERE, HERE, Spent, learned_rate

    def over(project_ids: "list[str]", source: str) -> "Rate | None":
        spent: dict[str, Spent] = {}
        for other in project_ids:
            spent.update(_step_spent(store, other))
        steps = [step for other in project_ids for step in library.project(other).steps]
        return learned_rate(
            steps, lambda step: spent.get(step.id, Spent()), days_for, done_for, source
        )

    others = [project.id for project in library.projects if project.id != project_id]
    return over(others, ELSEWHERE) or over([project_id], HERE)


def _ledger_stamp(store: "LibraryStore", project_id: str) -> object:
    from dplanner.domain.ledger import fingerprint

    directory = _ledger_dir(store, project_id)
    return None if directory is None else fingerprint(directory)


def _step_usage_words(store: "LibraryStore", library: "Library", step_id: str) -> str:
    """What the agent runs on a step consumed, as the Agent tab says it; "" for none."""
    from dplanner.domain.ledger import records
    from dplanner.modules.step_agent_run.usage import summary

    if not library.has(step_id):
        return ""
    directory = _ledger_dir(store, library.project_of(step_id).id)
    if directory is None:
        return ""
    return summary(record for record in records(directory) if record.step == step_id)


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


def agent_shell_marker(env: "Mapping[str, str] | None" = None) -> str:
    """The marker set in ``env`` (this process's environment by default), or "" when no
    agent's shell is around us — ``domain/agents.py``'s reading over this build's
    harnesses. Read by the entry point's window guard and by ``status set``, which holds an
    agent's done at review."""
    import os

    from dplanner.domain.agents import shell_marker

    return shell_marker(agent_harnesses(), os.environ if env is None else env)


def dictation_providers() -> tuple["DictationProvider", ...]:
    """Every dictation engine this build can transcribe with, first is what a fresh
    profile tries first.

    The whisper commands lead — local and free — then OpenAI's live session and its batch
    endpoint, on the key the OpenAI module keeps. Each is a Qt-free record from its own
    module; the service, Settings ▸ Dictation and the checklist all read this tuple, and a
    fourth engine is a fourth module listed here and nothing else.
    """
    from dplanner.modules.dictation_whisper import dictation as whisper
    from dplanner.modules.openai import dictation as openai_dictation

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
    from dplanner.modules.auto_progress import aspect as auto_progress
    from dplanner.modules.branches import aspect as branches
    from dplanner.modules.docs import aspect as docs
    from dplanner.modules.estimation import aspect as estimation
    from dplanner.modules.feature import aspect as feature
    from dplanner.modules.github import aspect as github
    from dplanner.modules.spec import aspect as spec
    from dplanner.modules.step_agent_instruction import aspect as agent
    from dplanner.modules.step_agent_run import aspect as agent_run
    from dplanner.modules.step_check import aspect as check
    from dplanner.modules.step_description import aspect as description
    from dplanner.modules.step_milestone import aspect as milestone
    from dplanner.modules.step_review import aspect as review
    from dplanner.modules.step_review import rounds as review_rounds
    from dplanner.modules.step_start import aspect as start
    from dplanner.modules.step_ticket import aspect as ticket
    from dplanner.modules.step_wait import aspect as wait
    from dplanner.modules.testing import aspect as testing
    from dplanner.planning import status

    return [
        agent.SPEC,
        agent_run.SPEC,
        auto_progress.SPEC,
        branches.CUT_SPEC,
        branches.LAND_SPEC,
        check.SPEC,
        description.SPEC,
        docs.SPEC,
        docs.COMPILED_SPEC,
        estimation.SPEC,
        feature.SPEC,
        github.SPEC,
        milestone.SPEC,
        review.SPEC,
        review_rounds.SPEC,
        spec.SPEC,
        start.SPEC,
        status.SPEC,
        testing.SPEC,
        ticket.SPEC,
        wait.SPEC,
    ]


# Row phrases lead with where a step *stands* (status, agent run, milestone) before what it
# *carries*. Only a preference: an aspect not named here still appears, after these, in
# aspect_specs() order — so a new aspect reaches every step row without editing this list.
_PHRASE_ORDER = (
    "step_status",
    "step_agent_run",
    "step_milestone",
    "step_start",
    "step_wait",
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


def default_location_roles() -> tuple["LocationRole", ...]:
    """Every kind of place a project can name, first the domain's own ``code``, then one
    per module that declared a ``roles.py`` — the sibling of :func:`aspect_specs`: the
    dialog's Add menu, the card, `dplanner location roles`, lint and the briefing all
    read this one list, so a module adds a role and every surface learns it.

    The order is the order the Add menu offers them.
    """
    from dplanner.domain.locations import CODE
    from dplanner.modules.reporting.roles import ROLE as REPORTING
    from dplanner.modules.spec.roles import ROLE as SPEC

    return (CODE, SPEC, REPORTING)


def _cli_reporting_site(context: "CliContext", project: "Project") -> "SiteTarget | None":
    """Where ``dplanner report site`` writes a project's pages instead of beside the plan:
    its reporting location, when this machine has that repository."""
    from dplanner.cli.report.website import SiteTarget
    from dplanner.core.config_dir import config_dir
    from dplanner.domain.locations import roles_by_id
    from dplanner.domain.repositories import repository_facts
    from dplanner.modules.reporting.roles import ROLE as REPORTING_ROLE

    roles = roles_by_id(default_location_roles())
    facts = repository_facts(
        project,
        context.store.project_dir(project.id),
        context.store.checkouts(),
        managed=managed_for(roles),
        kept_root=config_dir(),
    )
    placement = facts.of_role(REPORTING_ROLE.id)
    if placement is None or not placement.here or placement.directory is None:
        return None
    assert placement.root is not None
    return SiteTarget(placement.root, placement.directory)


def managed_for(roles: "Mapping[str, LocationRole]") -> "ManagedFor":
    """Where a read-only location's managed clone stands: under the per-user cache the
    git spec source already keeps, keyed as it keys them, so a spec row and the source
    fetched from it share one clone. A role that writes has no such place — a managed
    clone is never written."""
    from dplanner.core.config_dir import config_dir
    from dplanner.core.storage.sparse import sparse_dir
    from dplanner.modules.spec_git.source import SPEC_GIT_CACHE

    cache_root = config_dir() / SPEC_GIT_CACHE

    def managed(location: "Location") -> "Path | None":
        role = roles.get(location.role)
        if role is None or role.writes:
            return None
        return sparse_dir(cache_root, location.repository, location.ref or "HEAD", location.path)

    return managed


def default_link_rules() -> tuple["LinkRule", ...]:
    """What modules add to what may link to what — asked by ``Library.link_refusal`` after
    the graph's own four refusals, on the window's library and the CLI's alike.

    One today: a stack takes links in at its first step and out from its last
    (``ARCHITECTURE.md``'s *One in, one out is a rule the domain asks*). Qt-free, because
    ``entry.py`` hands it to every CLI run.
    """
    from dplanner.modules.project_editor.stacks import link_rule

    return (link_rule,)


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
    from dplanner.modules.step_agent_run import usage as agent_usage
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
        agent_usage.DATA_FORMAT,
    ]
