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
renders them is built. Every constrained position carries a comment saying why.

``default_modules()`` holds that order alone; each cluster's wiring is a builder over the
shared ``_Root`` (``_agents``, ``_graph``, ``_aspects``, …), and a new module joins one.

**The imports are inside the functions on purpose.** Importing this package must not load Qt,
because the CLI reaches a module's ``cli.py`` through it and has to start in milliseconds on
machines with no GUI libraries at all. The inventory is still in one place: it is the first
lines of each function instead of the first lines of the file, and
``tests/test_architecture.py`` reads them either way.
"""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, NamedTuple

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
    from dplanner.core.clock import Clock
    from dplanner.domain.agents import AgentHarness
    from dplanner.domain.aspects import AspectSpec
    from dplanner.domain.assets import AssetSource
    from dplanner.domain.at_work import AtWorkBoard
    from dplanner.domain.commands import Command
    from dplanner.domain.dictation import DictationProvider
    from dplanner.domain.locations import Location, LocationRole, ManagedFor
    from dplanner.domain.model import Edge, Library, LinkRule, Project, ProjectId, Step, StepId
    from dplanner.domain.repositories import RepositoryFacts
    from dplanner.domain.store import FilesFor
    from dplanner.domain.workflow import Actor, EndClaim, PlanView
    from dplanner.framework.context import ContextService
    from dplanner.framework.debounce import DebounceService
    from dplanner.framework.mime_files import Payload
    from dplanner.framework.module import Module
    from dplanner.framework.services import AppServices
    from dplanner.framework.undo import UndoService
    from dplanner.modules.agent_at_work.module import AgentAtWorkModule
    from dplanner.modules.agent_claims.module import AgentClaimsModule
    from dplanner.modules.agent_launch.availability import Availability
    from dplanner.modules.agent_launch.module import AgentLaunchModule
    from dplanner.modules.agent_questions.module import AgentQuestionsModule
    from dplanner.modules.agent_usage.module import AgentUsageModule
    from dplanner.modules.branches.module import BranchesModule
    from dplanner.modules.canvas.clipboard.clip import PastePolicy
    from dplanner.modules.canvas.module import CanvasModule
    from dplanner.modules.coverage.module import CoverageModule
    from dplanner.modules.coverage.trace import Trace
    from dplanner.modules.estimation.module import EstimationModule
    from dplanner.modules.feature.module import FeatureModule
    from dplanner.modules.notes.module import NotesModule
    from dplanner.modules.problems.module import ProblemsModule
    from dplanner.modules.project_archive.module import ProjectArchiveModule
    from dplanner.modules.project_assets.module import ProjectAssetsModule
    from dplanner.modules.projects.checkouts import CheckoutService
    from dplanner.modules.projects.module import ProjectsModule
    from dplanner.modules.projects.repos import RepositoryServices
    from dplanner.modules.reporting.module import ReportingModule
    from dplanner.modules.schedule.module import TimeEstimatesModule
    from dplanner.modules.schedule.simulator_activity import TimeSimulationModule
    from dplanner.modules.settings.module import SettingsModule
    from dplanner.modules.spec.module import SpecModule
    from dplanner.modules.spec.source_kind import DocumentSourceKind
    from dplanner.modules.spec_confluence.module import SecretStore, SpecConfluenceModule
    from dplanner.modules.status_board.module import ProgressionModule
    from dplanner.modules.step_agent_instruction.module import StepAgentInstructionModule
    from dplanner.modules.step_agent_run.module import StepAgentRunModule
    from dplanner.modules.step_order.module import StepOrderModule
    from dplanner.modules.step_playbook.module import PassStandings
    from dplanner.modules.step_properties.module import StepPropertiesModule
    from dplanner.modules.step_status.workflows import StatusWorkflow
    from dplanner.planning.status import Reading, Status, Unknown
    from dplanner.theme.providers import ThemeProvider

__all__ = [
    "agent_harnesses",
    "aspect_specs",
    "at_work_board",
    "default_cli_commands",
    "default_module_formats",
    "default_modules",
    "dictation_providers",
    "start_window",
    "theme_providers",
]


def default_modules(
    services: "AppServices",
    board: "AtWorkBoard | None" = None,
) -> list["Module"]:
    """Every module, in registration order. The clusters are built first, in the order they
    hand each other what they need — the agents before the graph editor whose Problems panel
    hands them findings, the editor before the feature module that places steps in it."""
    from dplanner.modules.schedule.module import ProgressHistoryModule
    from dplanner.modules.settings.module import SettingsDeps, SettingsModule

    root = _Root(services)
    # Built ahead of the list: Run Agent and dictation deep-link to their own settings pages
    # through it.
    settings = SettingsModule(
        SettingsDeps(
            actions=services.actions,
            settings_sections=services.settings_sections,
            parent=services.window,
        )
    )
    # The board comes from `app.new_session` — the machine's when the application runs, one
    # holding nothing when a test builds — and is named nowhere deeper: no feature module
    # reaches `config_dir`, the same rule the topology gate's record path follows.
    if board is None:
        board = at_work_board()
    branches = _branches(root)
    agents = _agents(root, branches=branches, settings=settings, board=board)
    graph = _graph(root, branches=branches, agents=agents)
    knowledge = _knowledge(root, editor=graph.editor)
    tabs = _project_tabs(root, agents)
    return [
        *_shell(root, agents),
        *_assistants(root, settings),
        _projects(root, editor=graph.editor, knowledge=knowledge, tabs=tabs, agents=agents),
        _project_archive(root),
        # Before spec: the Specs tab's + menu lists its kinds, and its settings section
        # must exist before the settings dialog is built.
        knowledge.confluence,
        knowledge.spec,
        knowledge.coverage,
        tabs.assets,
        # Each registers one tab into the step detail panel — or, for the estimate and
        # description, a block into its Details tab (services.step_details). They must
        # come before step_properties, which reads the registry when it opens a dialog.
        *_aspects(
            root,
            graph=graph,
            knowledge=knowledge,
            tabs=tabs,
            agents=agents,
            branches=branches,
            board=board,
        ),
        _step_properties(root),
        graph.editor,
        tabs.step_order,
        agents.usage,
        agents.questions,
        tabs.progression,
        tabs.time,
        # After every module whose report_source it renders; before Settings, whose dialog
        # is built from the sections registered by then.
        tabs.reporting,
        # Declares the progress history's format only; the recorder above writes it.
        ProgressHistoryModule(),
        tabs.simulation,
        *_machine(root),
        # Last: its dialog is built during register() and must see every other module's
        # settings sections.
        settings,
    ]


class _Root:
    """What every cluster is wired over: the window's services, its library and the concrete
    store behind it, the location roles — and the seams more than one cluster hands on."""

    def __init__(self, services: "AppServices") -> None:
        from dplanner.domain.locations import roles_by_id
        from dplanner.domain.store import LibraryStore
        from dplanner.modules.agent_launch.availability import Availability

        self.services = services
        self.library: Library = services.document
        # What may link to what, beyond the graph's own four refusals — the same rules the
        # CLI's library asks (`default_link_rules`), so a drop and `step link` refuse alike. A
        # reload builds a new library and comes back through here; a refresh keeps this one.
        self.library.link_rules = default_link_rules()
        # The composition root knows the concrete store, exactly as it knows the concrete
        # document — modules reach a file area only through the typed callback on their Deps.
        store = services.repo
        assert isinstance(store, LibraryStore)
        self.store = store
        self.roles = roles_by_id(default_location_roles())
        self.managed = managed_for(self.roles)
        # Whether each agent CLI is usable here: the checklist probes, Run Playbook greys.
        self.availability = Availability(agent_harnesses())
        # The tuple the CLI reports read (`_asset_sources`), so the Assets tab, the picker
        # and `dplanner asset list` can never disagree about what a project holds.
        self.asset_sources = _asset_sources()
        self.repos = _repository_services(self)
        # A checkout recorded for a repository — by the Project dialog, or by an agent's
        # first `dplanner` call from the code and adopted through the library file — is what
        # turns Run Agent from greyed to runnable, and nothing in the context graph changed.
        store.checkout_changed.connect(lambda _repository: services.context.refresh())

    def connect_project(self, directory: "Path") -> "Project":
        """Attach a directory and add its project off the undo stack, with the membership
        origin `library add` uses too — what New Project, Open Project and Restore end in."""
        from dplanner.modules.library.membership import LIBRARY_ORIGIN

        project = self.store.attach(directory)
        self.library.add_child(self.library.id, project, origin=LIBRARY_ORIGIN)
        return project

    def facts_of(self, project_id: str) -> "RepositoryFacts":
        """The plan repository and every location of a project placed against this
        machine's checkouts — the one derivation every seam reads."""
        from dplanner.core.config_dir import config_dir
        from dplanner.domain.repositories import repository_facts

        return repository_facts(
            self.library.project(project_id),
            self.store.project_dir(project_id),
            self.store.checkouts(),
            managed=self.managed,
            kept_root=config_dir(),
        )

    def facts_for(self, node_id: str) -> "RepositoryFacts":
        """The facts for a step — or for a project named directly, which is what a run
        with no step (the Problems panel's) has to ask about."""
        from dplanner.domain.model import Project

        node = self.library.node(node_id)
        project_id = node.id if isinstance(node, Project) else self.library.project_of(node_id).id
        return self.facts_of(project_id)

    def reporting_site(self, project_id: str) -> "SiteTarget | None":
        """Where the project publishes instead of beside its plan: its reporting row placed
        on this machine — a checkout, the person's or one DPlanner keeps — or None, when it
        names none or nothing here has it yet."""
        from dplanner.cli.report.website import SiteTarget
        from dplanner.modules.reporting.roles import ROLE as REPORTING_ROLE

        placement = self.facts_of(project_id).of_role(REPORTING_ROLE.id)
        if placement is None or not placement.here:
            return None
        if placement.root is None or placement.directory is None:
            return None
        return SiteTarget(placement.root, placement.directory)

    def reporting_dir(self, project_id: str) -> "Path | None":
        site = self.reporting_site(project_id)
        return site.site if site is not None else None

    def milestone_colors(self, project: "Project") -> dict[str, str]:
        from dplanner.modules.schedule.assumptions import milestone_colors

        return milestone_colors(self.library, project)

    def milestone_color(self, step_id: str) -> str:
        """One milestone's shade, for a surface that draws a row at a time. A surface that
        draws many at once takes the whole dict instead — this deals the project each call."""
        if not self.library.has(step_id):
            return ""
        return self.milestone_colors(self.library.project_of(step_id)).get(step_id, "")

    def pick_assets(self, node_id: str) -> "list[Payload]":
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

        library, store = self.library, self.store
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
        for entry in catalog(library, project, store.files, self.asset_sources):
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
        dialog = AssetPickerDialog(choices, self.services.window)
        picked = dialog.chosen() if dialog.exec() == AssetPickerDialog.DialogCode.Accepted else []
        dialog.deleteLater()
        return picked


def _repository_services(root: _Root) -> "RepositoryServices":
    """git and GitHub for the project surfaces. The Project dialog, Open Project and Move
    Plan reach both repositories through this one bundle; the root names the providers
    (rule 8) and the github module's gh door (rule 5) so the projects module names neither."""
    from pathlib import Path

    from dplanner.core.config_dir import config_dir
    from dplanner.core.storage.git import GitStorage
    from dplanner.core.storage.github import GitHubStorage
    from dplanner.core.storage.kept import clone_full
    from dplanner.core.storage.locations import find_repo_root, origin_url, repo_storage
    from dplanner.core.storage.provider import StorageError, VersionedStorage
    from dplanner.domain.relocate import move_project
    from dplanner.modules.github.aspect import PR_OPEN
    from dplanner.modules.github.aspect import read as github_read
    from dplanner.modules.projects.repos import (
        LogEntry,
        PullRequest,
        RepoLog,
        RepositoryServices,
    )
    from dplanner.modules.spec_git.source import SPEC_GIT_CACHE, probe
    from dplanner.planning.kinds import key_of

    library, store = root.library, root.store

    def plan_roots() -> list[Path]:
        roots: list[Path] = []
        for project in library.projects:
            found = find_repo_root(store.project_dir(project.id))
            if found is not None and found not in roots:
                roots.append(found)
        return roots

    def pr_steps(project_id: str) -> dict[int, str]:
        named: dict[int, str] = {}
        for step in library.project(project_id).steps:
            refs = github_read(step)
            if refs is not None and refs.pr_number is not None:
                named[refs.pr_number] = f"{key_of(step)} {step.title}".strip()
        return named

    def history_for(repo_root: Path, scope: str, limit: int) -> RepoLog:
        storage = repo_storage(repo_root, (scope,) if scope else ())
        if not isinstance(storage, VersionedStorage):
            raise StorageError(f"{repo_root} has no history")
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

    def publish(repo_root: Path, name: str) -> str:
        storage = repo_storage(repo_root)
        assert isinstance(storage, GitStorage)
        storage.commit("Start the plan repository")  # gh needs a commit to push.
        GitHubStorage.publish(storage, name)
        return origin_url(repo_root)

    def create_repository(name: str, dest: Path) -> str:
        GitHubStorage.create(name, dest)
        return origin_url(dest)

    return RepositoryServices(
        facts_of=root.facts_of,
        roles=root.roles,
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


def _branches(root: _Root) -> "BranchesModule":
    """The branch cut and its landing. Built before everything that reads it: the briefing
    reads its cached stretches — Run Agent's state asks which branch a step is on at every
    announce — and the canvas draws its lanes."""
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.branches.module import BranchesDeps, BranchesModule
    from dplanner.modules.canvas.stacks.stack import stack_split
    from dplanner.planning.agent import enabled as is_agent
    from dplanner.planning.kinds import key_of

    services, library = root.services, root.library

    def branch_seats(step_ids: "Sequence[str]", cut: "Step", land: "Step") -> "list[Command]":
        """Where Put on a Branch's two new cards stand: the cut a column left of the picked
        card furthest left, the landing a column right of the one furthest right — when those
        were placed by hand; otherwise the ambient layout places them, as it does the rest."""
        from dplanner.modules.canvas.layouts.positions import MODULE_ID as POSITION_ID
        from dplanner.modules.canvas.layouts.positions import read_position, write_position
        from dplanner.modules.canvas.layouts.sorts import H_PITCH

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

    return BranchesModule(
        BranchesDeps(
            library=library,
            undo=services.undo,
            actions=services.actions,
            details=services.step_details,
            is_agent=is_agent,
            stacked_apart=stack_split,
            seats=branch_seats,
            key_of=key_of,
            parent=services.window,
        )
    )


class _Agents(NamedTuple):
    runs: "StepAgentRunModule"
    at_work: "AgentAtWorkModule"
    claims: "AgentClaimsModule"
    checkouts: "CheckoutService"
    instruction: "StepAgentInstructionModule"
    launch: "AgentLaunchModule"
    usage: "AgentUsageModule"
    questions: "AgentQuestionsModule"
    standings: "PassStandings"  # Read by the canvas; the playbook module starts its polling.


def _agents(
    root: _Root,
    *,
    branches: "BranchesModule",
    settings: "SettingsModule",
    board: "AtWorkBoard",
) -> _Agents:
    """Run Agent, the tracker that watches the shells it spawns, and the banner that says an
    agent is at work. Built before the clusters that hand work to Run Agent: the Problems
    panel its findings, the docs module its compilations, the library watcher an entry two
    writers changed at once, sync its reconciling."""
    from getpass import getuser
    from pathlib import Path

    from dplanner.core.config_dir import config_dir
    from dplanner.domain.agents import names_session
    from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri
    from dplanner.modules.agent_at_work.module import AgentAtWorkDeps, AgentAtWorkModule
    from dplanner.modules.agent_briefing.worktree import mainline
    from dplanner.modules.agent_claims.module import AgentClaimsDeps, AgentClaimsModule
    from dplanner.modules.agent_launch.launch import read_absolute
    from dplanner.modules.agent_launch.module import AgentLaunchDeps, AgentLaunchModule
    from dplanner.modules.agent_questions import inbox
    from dplanner.modules.agent_questions.module import AgentQuestionsDeps, AgentQuestionsModule
    from dplanner.modules.agent_usage.aspect import ledger_dir, step_usage_words
    from dplanner.modules.agent_usage.module import AgentUsageDeps, AgentUsageModule
    from dplanner.modules.branches.plan import branch_plan
    from dplanner.modules.projects.checkouts import CheckoutService
    from dplanner.modules.step_agent_instruction.module import (
        StepAgentInstructionDeps,
        StepAgentInstructionModule,
    )
    from dplanner.modules.step_agent_run.module import StepAgentRunDeps, StepAgentRunModule
    from dplanner.modules.step_playbook.module import PassStandings
    from dplanner.planning.kinds import key_of
    from dplanner.planning.status import Status

    services, library, store = root.services, root.library, root.store

    def ledger_of(step_id: str) -> Path | None:
        """Where a step's runs are recorded: its project's ledger directory."""
        return ledger_dir(store, library.project_of(step_id).id) if library.has(step_id) else None

    def reveal_step(step_id: str) -> None:
        """Select a step in its project: ``steps.reveal`` against a context naming it."""
        services.actions.run(
            "steps.reveal",
            Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step_id)),)}),
        )

    def ended() -> None:
        """A run ended: what it consumed is due a harvest. The module is built below, and
        nothing ends before the build is up."""
        usage.sweep()

    # Whoever answers in the window is the person at it, and what the answer resumes reaches
    # the window's library.
    person, chosen = {"kind": "person", "name": getuser()}, store.library_path

    def retry_now(step_id: str) -> str:
        """Step ▸ Retry Now: the step's parked run answered ``Retry now`` by the person here."""
        return inbox.retry_step(ledger_of(step_id), step_id, person, library=chosen).said

    # Every launch is handed here, and this is the one place that keeps an eye on the shell
    # afterwards.
    runs = StepAgentRunModule(
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
            ended=ended,
            # Where each run's ledger record lives.
            project_dir=ledger_of,
            retry_refusal=lambda step_id: inbox.retry_refusal(ledger_of(step_id), step_id),
            retry_now=retry_now,
        )
    )
    # The ledger's sweep and the Expenditure tab, whose rows look as the Order tab's do.
    usage = AgentUsageModule(
        AgentUsageDeps(
            library=library,
            store=store,
            actions=services.actions,
            context=services.context,
            parent=services.window,
            debounce=services.debounce,
            tabs=services.tabs,
            harnesses=agent_harnesses(),
            tasks=services.tasks,
            swept=runs.refresh,
            step_icons=lambda step_id: _step_type_icons(library.step(step_id)),
            milestone_color=root.milestone_color,
            step_done=lambda step_id: _card_status(library.step(step_id)) is Status.DONE,
        )
    )

    # The library watcher asks it one question — whether an agent is at work on the project
    # a conflict is in — and stands its modal down while one is.
    at_work = AgentAtWorkModule(
        AgentAtWorkDeps(
            board=board,
            notices=services.window,
            library=library,
            parent=services.window,
            # The dialog behind the banner selects the step a row's agent is on.
            reveal=reveal_step,
            key_of=key_of,
        )
    )

    claims = AgentClaimsModule(
        AgentClaimsDeps(library, store.project_dir, services.actions, parent=services.window)
    )
    # A repository on this machine for a verb that needs one, cloned where the clone
    # policy says: the projects module's service, built here because Run Agent is handed
    # it too. Owned by the window, so its task runner outlives every dialog.
    checkouts = CheckoutService(
        root.repos, services.tasks, kept_root=config_dir(), parent=services.window
    )

    launch = AgentLaunchModule(
        AgentLaunchDeps(
            library=library,
            actions=services.actions,
            context=services.context,
            settings_sections=services.settings_sections,
            status=services.window,
            parent=services.window,
            files=store.files,
            # How staged assets are read at launch — bytes by absolute path.
            read_asset=read_absolute,
            # Where the agent runs is the module's reading of these: the code checkout
            # for a project that records its code repository, the plan's own repository
            # for one that does not.
            facts_for=root.facts_for,
            # Code nobody checked out here is cloned before the agent opens in it.
            ensure_checkouts=checkouts.ensure_many,
            # Which branches a run works between — read through the branches module's
            # cached stretches, since Run Agent's state asks on every announce.
            branch_plan=lambda library, step, facts: branch_plan(
                library, step, mainline(facts, step), branches.reading_of
            ),
            # The kinds of place a project names, which the briefing's preamble words.
            location_roles=default_location_roles(),
            # The spawned shell goes to the run tracker: it stamps the launch — directly,
            # off the undo stack, since Ctrl+Z cannot un-launch a shell — and watches
            # the run's files for the shell's end.
            record_launch=lambda step_id, files, harness: runs.track(
                step_id,
                str(files.shell_file),
                str(files.exit_file),
                harness,
                # The session the command named, for a harness that names one; a harness
                # that mints its own is found by its record once the run ends.
                files.session if names_session(agent_harnesses(), harness) else "",
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
            # Manage Agent Profiles… lands on the module's own settings page.
            open_settings=settings.open,
            clock=services.clock,
            # A run's record is written before its terminal opens; worktrees on a task.
            project_dir=ledger_of,
            tasks=services.tasks,
            notices=services.window,
            flush=services.autosave.saved,
            # A playbook's pass starts as `dplanner agent run --playbook` on this library.
            library_path=store.library_path,
        )
    )
    instruction = StepAgentInstructionModule(
        StepAgentInstructionDeps(
            dictation=services.dictation,
            library=library,
            debounce=services.debounce,
            undo=services.undo,
            sections=services.inspector_sections,
            actions=services.actions,
            context=services.context,
            # Its Project ▸ Settings… tab: the standing instruction every briefing opens with.
            project_settings=services.project_settings,
            files=store.files,
            read_asset=read_absolute,
            facts_for=root.facts_for,
            # The Prompt view shows exactly what Run Agent launches with.
            assembled=launch.assembled,
            # The Agent tab's "tokens so far" line: the run tracker's ledger, worded.
            usage_words=lambda step_id: step_usage_words(store, library, step_id),
            pick_assets=root.pick_assets,
        )
    )
    # The question cards the Control Centre hosts: a person answering in the window, through
    # the same inbox `question answer` uses, so the two cannot drift.
    questions = AgentQuestionsModule(
        AgentQuestionsDeps(
            library=library,
            status=services.window,
            project_dir=lambda project_id: ledger_dir(store, project_id),
            answer=lambda project_dir, question_id, given: (
                inbox.answer(project_dir, question_id, given, person, library=chosen).said
            ),
            retry_now=lambda project_dir, run: (
                inbox.retry_now(project_dir, run, person, library=chosen).said
            ),
            reveal=reveal_step,
            harnesses=agent_harnesses(),
            key_of=key_of,
        )
    )
    standings = PassStandings(library, store.project_dir, services.window)
    return _Agents(
        runs, at_work, claims, checkouts, instruction, launch, usage, questions, standings
    )


class _Graph(NamedTuple):
    problems: "ProblemsModule"
    editor: "CanvasModule"


def _graph(root: _Root, *, branches: "BranchesModule", agents: _Agents) -> _Graph:
    """The graph editor, the Problems panel it stands beside the canvas, and the canvas's
    reading of every aspect a card or an arrow wears."""
    from dplanner.framework.side_panel import SidePanel
    from dplanner.modules.branches.plan import lanes as branch_lanes
    from dplanner.modules.branches.plan import strips as branch_strips
    from dplanner.modules.canvas.module import CanvasDeps, CanvasModule
    from dplanner.modules.canvas.renderers import EdgeAccent, NodeAccent
    from dplanner.modules.github.aspect import PR_CLOSED, PR_MERGED, pr_label
    from dplanner.modules.github.aspect import read as github_read
    from dplanner.modules.problems.module import ProblemsDeps, ProblemsModule
    from dplanner.modules.schedule.landings import card_stats
    from dplanner.modules.step_agent_run.aspect import chip as agent_run_chip
    from dplanner.planning.kinds import Kind, key_of, kind_of
    from dplanner.planning.milestone import read as milestone_read
    from dplanner.planning.status import REVIEW_AND_MERGE, Status, word
    from dplanner.theme.icons import problem_icon
    from dplanner.theme.tones import STEP_STATUS_TONES

    services, library, store = root.services, root.library, root.store

    def step_accents(project_id: str) -> "dict[str, NodeAccent]":
        """How every step of a project looks on the canvas — one call per canvas sync, so
        the schedule behind the milestone stats and the project's colour deal are each
        walked once for all of them."""
        project = library.project(project_id)
        stats = card_stats(library, project, services.clock.today())
        colors = root.milestone_colors(project)
        # The settled reading, never a fresh lint pass: the checks are super-linear in the
        # size of a plan (66 ms at 300 steps) and this runs on every canvas sync.
        flagged = problems.flagged(project_id)
        status_for = _ready_in(library, services.clock.today())
        strips = branch_strips(branches.reading_of(project))
        return {
            step.id: step_accent(
                step,
                stats.get(step.id, ""),
                colors.get(step.id, ""),
                flagged=step.id in flagged,
                # Finished work waits on a person: to review it, or to merge it.
                pulse=status_for(step) in REVIEW_AND_MERGE,
                strip=strips.get(step.id, ("", "")),
                playbook=agents.standings.card(project_id, step.id),
            )
            for step in project.steps
        }

    def edge_accents(project_id: str) -> "dict[Edge, EdgeAccent]":
        """How the arrows of a project look beyond their kind: every arrow of work on a
        feature branch not yet landed lies on that branch's lane."""
        project = library.project(project_id)
        return {
            edge: EdgeAccent(lane=color)
            for edge, color in branch_lanes(library, branches.reading_of(project)).items()
        }

    def step_accent(
        step: "Step",
        stat: str,
        milestone_color: str = "",
        *,
        flagged: bool = False,
        pulse: bool = False,
        strip: tuple[str, str] = ("", ""),
        playbook: tuple[str, str, str] = ("", "", ""),
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
        moves next — ready for review or to merge — pulses. The card says nothing in words
        beyond its title and its key — every aspect it wears is one of these, never a
        phrase — but in two strips under the body: the feature branch its work goes onto
        (``strip``, the branch and its lane colour, ``plan.strips``) and where its playbook
        pass stands (``playbook``: ``passes.standing``'s phrase, tone and stages).
        """
        refs = github_read(step)

        pill = ""
        if refs is not None and refs.has_pr():
            pill = pr_label(refs)
        chip_text, chip_tone = agent_run_chip(step)
        status = _card_status(step)
        milestone = milestone_read(step)
        key_glyph, key_glyph_tone = _primary_glyph(step)
        kind = kind_of(step)
        return NodeAccent(
            muted=status is Status.DONE,
            badge=milestone,
            pill_text=pill,
            pill_tone={PR_MERGED: "good", PR_CLOSED: "bad"}.get(refs.pr_state, "") if refs else "",
            branch=bool(refs is not None and refs.branch),
            key_text=key_of(step),
            key_tone=STEP_STATUS_TONES.get(word(status), ""),
            key_glyph=key_glyph,
            key_glyph_tone=key_glyph_tone,
            chip_text=chip_text,
            chip_tone=chip_tone,
            squad=agents.claims.chip(library.project_of(step.id).id, step.id),
            # Done outranks a kind; otherwise the kind tints the body, and the medallion
            # still says what the node also is.
            body_tone=(
                "good"
                if status is Status.DONE
                else "highlight"
                if kind is Kind.MILESTONE
                else "feature"
                if kind is Kind.FEATURE
                else ""
            ),
            # A milestone recolours the kind it is rather than gaining a second mark: the
            # body, the badge and the tag medallion all take its shade of the project's map.
            tone_color=milestone_color if milestone else "",
            icons=_step_type_icons(step),
            # Something in the plan is wrong about this step. The canvas draws the
            # squiggle; what is wrong is the Problems panel's to say.
            flagged=flagged,
            # A person moves this step next: the card breathes in its key block's tone.
            pulse=pulse,
            stat_text=stat,
            stat_strong=bool(milestone),
            strip=strip[0],
            strip_tone=strip[1],
            playbook=playbook,
        )

    # Built before the graph editor because the editor stands its panel beside the canvas.
    # What it shows is the lint registry — the very list `dplanner project lint` runs — so
    # the window and the terminal cannot disagree about what is wrong with a plan.
    problems = ProblemsModule(
        ProblemsDeps(
            library=library,
            actions=services.actions,
            files=store.files,
            checks=_lint_checks,
            debounce=services.debounce,
            parent=services.window,
            facts_of=root.facts_of,
            key_of=key_of,
            # Handing the problems to an agent is Run Agent's.
            fix_profiles=agents.launch.plan_profiles,
            fix=lambda project_id, findings, profile: agents.launch.fix_problems(
                project_id,
                [(row.check, row.subject, row.message) for row in findings],
                profile,
            ),
        )
    )

    editor = CanvasModule(
        CanvasDeps(
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
            file_modules=tuple(source.id for source in root.asset_sources),
            paste_policies=_paste_policies(),
            step_accents=step_accents,
            accents_changed=(
                problems.findings.flagged_changed,
                agents.claims.changed,
                agents.standings.changed,
            ),
            edge_accents=edge_accents,
            # The cards that wear a branch strip, from the same reading their accents are.
            strips=lambda project_id: frozenset(
                branch_strips(branches.reading_of(library.project(project_id)))
            ),
            # What stands beside the canvas: what is wrong with this plan, where it is
            # fixed. The editor never learns whose widget it is — only that it may carry
            # a reading for the button that opens it.
            side_panel=SidePanel("Problems", problem_icon, problems.create_panel),
        )
    )
    return _Graph(problems, editor)


class _Knowledge(NamedTuple):
    feature: "FeatureModule"
    coverage: "CoverageModule"
    confluence: "SpecConfluenceModule"
    spec: "SpecModule"


def _knowledge(root: _Root, *, editor: "CanvasModule") -> _Knowledge:
    """What a plan answers to: the feature steps, the Specs tab and its document sources,
    and Coverage between the two."""
    from dplanner.core.config_dir import config_dir
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri
    from dplanner.modules.coverage.activity import CoverageDeps
    from dplanner.modules.coverage.module import CoverageModule
    from dplanner.modules.feature.module import FeatureDeps, FeatureModule
    from dplanner.modules.projects.location_dialog import ask_location
    from dplanner.modules.spec.aspect import MODULE_ID as SPEC_ID
    from dplanner.modules.spec.cli import digest_of as spec_digest_of
    from dplanner.modules.spec.cli import document_names as spec_document_names
    from dplanner.modules.spec.module import SpecDeps, SpecModule
    from dplanner.modules.spec.module import open_url as open_in_browser
    from dplanner.modules.spec_confluence.module import SpecConfluenceDeps, SpecConfluenceModule
    from dplanner.modules.spec_folder.module import SpecFolderKind
    from dplanner.modules.spec_git.module import SpecGitDeps, SpecGitKind
    from dplanner.modules.spec_git.source import SPEC_GIT_CACHE
    from dplanner.modules.testing.aspect import read as tests_read
    from dplanner.planning.estimate import MODULE_ID as ESTIMATION_ID
    from dplanner.planning.estimate import write as estimate_write
    from dplanner.planning.feature import MODULE_ID as FEATURE_ID
    from dplanner.planning.feature import is_feature
    from dplanner.planning.feature import read as feature_read
    from dplanner.planning.kinds import flows_into
    from dplanner.planning.milestone import is_milestone

    services, library, store = root.services, root.library, root.store

    def place_feature_step(project_id: str, title: str, marker: dict[str, Any]) -> str:
        """A feature step born where nobody pointed — the Specs tab's *New feature step…*.

        It arrives as the *Feature* template: the marker, and the estimate opted out, since
        a collector carries no estimate of its own — the set written here and the template's
        set are the same fact; change one, change the other. Where it lands is the graph
        editor's answer (``layouts/placement.free_spot``), so nothing is born on top of a card
        somebody placed, and it is one undo entry like every other placed step.
        """
        from dplanner.modules.canvas.layouts.placement import free_spot

        return editor.create_step(
            project_id,
            title,
            at=free_spot(library, library.project(project_id)),
            carrying=lambda step: [
                SetModuleDataCommand(step.id, FEATURE_ID, marker),
                SetModuleDataCommand(step.id, ESTIMATION_ID, estimate_write(None, on=False)),
            ],
            label="New Feature",
        ).id

    # Built before spec because the Specs tab cites a selection into it — the feature side
    # of one seam.
    feature = FeatureModule(
        FeatureDeps(
            library=library,
            undo=services.undo,
            actions=services.actions,
            sections=services.inspector_sections,
            parent=services.window,
            documents_of=lambda project_id: spec_document_names(library.project(project_id)),
            digest_of=lambda project_id, name: spec_digest_of(library.project(project_id), name),
            # Births a feature step somewhere free on the graph.
            place_step=place_feature_step,
        )
    )

    def step_passages(step_id: str) -> list[tuple[str, str]]:
        """The passages a step reaches: its own, or its gathering features'."""
        if not library.has(step_id):
            return []
        step = library.step(step_id)
        project = library.project_of(step_id)
        holders = [step] if is_feature(step) else flows_into(library, project, step_id)
        return [
            (source.document, source.quote)
            for holder in holders
            for source in feature_read(holder) or ()
            if source.quote
        ]

    # Its picture is every module's Qt-free half read once (coverage/readers.py); the
    # surfaces a double-click reaches arrive as callables, and the Specs tab's is resolved
    # lazily because the two modules point at each other.
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
            passages_of=step_passages,
        )
    )

    # Built before spec: it owns the two Confluence document source kinds the Specs tab
    # runs, and the credential's four doors are the keychain's, handed over as callables so
    # a test can hand in a dict instead.
    confluence = SpecConfluenceModule(
        SpecConfluenceDeps(
            parent=services.window,
            tasks=services.tasks,
            settings_sections=services.settings_sections,
            secrets=_keychain(),
            open_url=open_in_browser,
        )
    )
    # The document source kinds the Specs tab runs are named here — ``_source_kinds`` — and
    # nowhere else; a test hands in a fake through the same function.
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
            kinds=_source_kinds(spec_folder, spec_git, confluence.page, confluence.folder),
            roles=root.roles,
            # From Repository…: the projects module's location dialog for a spec row,
            # so a spec author names their repository from the Specs tab itself.
            ask_location=lambda project_id, role_id: ask_location(
                root.roles[role_id],
                project=library.project(project_id),
                library=library,
                services=root.repos,
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
    return _Knowledge(feature, coverage, confluence, spec)


class _Tabs(NamedTuple):
    progression: "ProgressionModule"
    estimation: "EstimationModule"
    notes: "NotesModule"
    time: "TimeEstimatesModule"
    simulation: "TimeSimulationModule"
    assets: "ProjectAssetsModule"
    reporting: "ReportingModule"
    step_order: "StepOrderModule"


def _project_tabs(root: _Root, agents: _Agents) -> _Tabs:
    """The tabs a project's index rows open — each built ahead of the list because the
    projects index opens it — and the Time tab's simulator, over a world of its own."""
    from dplanner.core.storage.locations import find_repo_root, origin_url
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.framework.context import ContextService
    from dplanner.framework.undo import UndoService
    from dplanner.modules.agent_launch.module import RUN_MENU_ID
    from dplanner.modules.estimation.module import EstimationDeps, EstimationModule
    from dplanner.modules.notes.module import NotesDeps, NotesModule
    from dplanner.modules.project_assets.module import (
        ProjectAssetsDeps,
        ProjectAssetsModule,
    )
    from dplanner.modules.reporting.module import ReportingDeps, ReportingModule
    from dplanner.modules.schedule.cli import Readers as TimeReaders
    from dplanner.modules.schedule.module import TimeEstimatesDeps, TimeEstimatesModule
    from dplanner.modules.schedule.simulation.frames import Writers as TimeWriters
    from dplanner.modules.schedule.simulator_activity import (
        TimeSimulationDeps,
        TimeSimulationModule,
    )
    from dplanner.modules.status_board.module import ProgressionDeps, ProgressionModule, StripVerb
    from dplanner.modules.step_agent_run.aspect import asks_person
    from dplanner.modules.step_description.aspect import read as description_read
    from dplanner.modules.step_order.module import StepOrderDeps, StepOrderModule
    from dplanner.planning.estimate import MODULE_ID as ESTIMATION_ID
    from dplanner.planning.estimate import write_start
    from dplanner.planning.kinds import key_of, kind_word
    from dplanner.planning.milestone import is_milestone
    from dplanner.planning.milestone import read as milestone_read
    from dplanner.planning.status import Status, readiness_of, stored

    services, library, store = root.services, root.library, root.store

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
        return key_badge_icon(key_of(step), root.milestone_color(step_id))

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
            # An agent that waits on a person is a row of its own: Waits for you.
            asks_person=asks_person,
            holders=agents.claims,
            verbs=(
                StripVerb("agent.run", data_menu=RUN_MENU_ID, face="Run Agents"),
                StripVerb("status.ready-to-merge"),
                StripVerb("status.done"),
            ),
            # A milestone's row leads with its key in its own shade: the group already says
            # where the work stands, so the one colour that is not a status says what the
            # work is leading to.
            milestone_badge=milestone_badge,
            key_of=key_of,
            # Who works the step, as its key block and Find's rows say it.
            glyph_of=lambda step: _primary_glyph(step)[0],
            # The open questions, a card each, on top of the Control Centre.
            question_cards=agents.questions.create_cards,
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
    # The Docs folder carries its Implementation notes row; the key rule is the root's,
    # handed over like every row's.
    notes = NotesModule(
        NotesDeps(
            dictation=services.dictation,
            library=library,
            undo=services.undo,
            debounce=services.debounce,
            context=services.context,
            tabs=services.tabs,
            step_key=key_of,
        )
    )

    def time_deps(
        library: "Library",
        *,
        undo: "UndoService[Library]",
        context: "ContextService",
        clock: "Clock",
        debounce: "DebounceService",
        estimate_missing: "Callable[[ProjectId], None]",
        day_over: bool,
    ) -> "TimeEstimatesDeps":
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
            # Agent-ness, waits and milestones through the owners' Qt-free readers; the
            # estimate and the status are planning facts the tab reads itself.
            readers=TimeReaders(),
            # Clicking the calendar re-dates the plan: one undoable write of the project's
            # start (``planning/estimate.py``), pushed here on the window's undo stack.
            set_start=lambda project_id, when: undo.push(
                SetModuleDataCommand(
                    project_id, ESTIMATION_ID, write_start(when), label="Set Start Date"
                )
            ),
            estimate_missing=estimate_missing,
            details=services.step_details,
            parent=services.window,
        )

    time = TimeEstimatesModule(
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
    # Debug ▸ Time Simulation: the real Time tab over a scratch world of its own — its own
    # library, undo stack, context, clock and debounce service, so nothing it does reaches
    # the window's. It shares only the verbs, which run against its own context.
    simulation = TimeSimulationModule(
        TimeSimulationDeps(
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            readers=TimeReaders(),
            writers=TimeWriters(),
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
    )
    assets = ProjectAssetsModule(
        ProjectAssetsDeps(
            library=library,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            undo=services.undo,
            parent=services.window,
            debounce=services.debounce,
            files=store.files,
            sources=root.asset_sources,
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
            key_of=key_of,
            kind_of=kind_word,
            status_for=stored,
            clock=services.clock,
            reporting_site=root.reporting_site,
        )
    )

    def step_aspects(step_id: str, skip: "Container[str]" = ()) -> list[str]:
        """One short phrase per aspect that has something to say about this step."""
        step = library.step(step_id)
        return [
            phrase for phrase in (summary(step) for summary in aspect_summaries(skip)) if phrase
        ]

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
            # A milestone row wears a rule and a tint; the name itself stays in the
            # trailing aspects column, which is why the milestone is not skipped here.
            milestone_label=lambda step_id: milestone_read(library.step(step_id)),
            # The same kind vocabulary the canvas medallions wear, one translation.
            step_icons=lambda step_id: _step_type_icons(library.step(step_id)),
            # The rule, the tint and the key badge all take the milestone's own shade —
            # the same one its card wears on the canvas and its band in the calendar.
            milestone_color=root.milestone_color,
            step_key=lambda step_id: key_of(library.step(step_id)),
            # The same answer the canvas card's ✓ and the report's read: a wait is never
            # done here, whatever its day.
            step_done=lambda step_id: _card_status(library.step(step_id)) is Status.DONE,
        )
    )
    return _Tabs(progression, estimation, notes, time, simulation, assets, reporting, step_order)


def _shell(root: _Root, agents: _Agents) -> list["Module"]:
    """The window itself, its library and the status bar, in left-to-right order."""
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.framework.context import Context
    from dplanner.modules.appearance.module import AppearanceDeps, AppearanceModule
    from dplanner.modules.appshell.module import AppShellDeps, AppShellModule
    from dplanner.modules.library.module import LibraryDeps, LibraryModule
    from dplanner.modules.library_watch.module import LibraryWatchDeps, LibraryWatchModule
    from dplanner.modules.schedule.assumptions import MODULE_ID as TIME_ID
    from dplanner.modules.schedule.assumptions import read_palette, write_project
    from dplanner.modules.sync.module import SyncDeps, SyncModule
    from dplanner.modules.taskcenter.module import TaskCenterDeps, TaskCenterModule

    services, library, store = root.services, root.library, root.store

    def milestone_palette(project_id: str) -> str:
        """Which colour map a project's milestones are shaded from."""
        if not library.has(project_id):
            return ""
        return read_palette(library.project(project_id)).id

    def set_milestone_palette(project_id: str, palette_id: str) -> None:
        """The same undoable write the Time tab's picker and ``schedule palette`` make —
        one choice, three ways in, so the window and the published report cannot disagree."""
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
        library.module_data_changed.connect(
            lambda _node_id, module_id, _origin: restate() if module_id == TIME_ID else None
        )

    def focused_project(context: object) -> str | None:
        """The project the user is in: the focused project, else the focused step's."""
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

    return [
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
                reconcile_profiles=lambda: agents.launch.plan_profiles(),
                reconcile=lambda root, branch, profile: agents.launch.reconcile_remote(
                    root, branch, profile
                ),
            )
        ),
        # Before the watcher: the banner that says an agent is at work is what makes the
        # watcher's stood-down modal legible, so it must already be on screen.
        agents.at_work,
        agents.claims,
        # After sync, so the conflict button lands to the right of the library path.
        LibraryWatchModule(
            LibraryWatchDeps(
                # The narrowed store: the watcher needs changed_underneath() and
                # adopt_outside_changes(), which the Repository protocol deliberately
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
                hand_to_agent=agents.launch.hand_conflicts,
                agent_refusal=agents.launch.conflict_refusal,
                # Whether an agent says it is at work on a project: the modal stands down
                # while one is, and the dialog says so when it does open.
                agent_at_work=agents.at_work.at_work_words,
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
    ]


def _assistants(root: _Root, settings: "SettingsModule") -> list["Module"]:
    """The language models, dictation and the Debug menu. Providers before the llm module:
    its settings page lists whatever has registered."""
    from dplanner.modules.anthropic.module import LlmAnthropicDeps, LlmAnthropicModule
    from dplanner.modules.debug.module import DebugDeps, DebugModule
    from dplanner.modules.dictation.module import DictationDeps, DictationModule
    from dplanner.modules.llm.module import LlmDeps, LlmModule
    from dplanner.modules.openai.module import LlmOpenAIDeps, LlmOpenAIModule
    from dplanner.modules.spec.module import open_url as open_in_browser

    services = root.services
    return [
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
    ]


def _project_archive(root: _Root) -> "ProjectArchiveModule":
    """Archive, Restore and Remove from Library, the Archive tab and its index folder."""
    from dplanner.modules.library.membership import LIBRARY_ORIGIN
    from dplanner.modules.project_archive.module import ProjectArchiveDeps, ProjectArchiveModule

    services, library, store = root.services, root.library, root.store

    # The store lets go first, then the model: sync rewires its repository groups on the
    # structure signal, and reads them from the store's records.
    def disconnect_project(project_id: str) -> None:
        store.detach(project_id)
        library.remove_child(project_id, origin=LIBRARY_ORIGIN)

    def archive_project(project_id: str) -> None:
        store.archive(project_id)
        library.remove_child(project_id, origin=LIBRARY_ORIGIN)

    return ProjectArchiveModule(
        ProjectArchiveDeps(
            library=library,
            actions=services.actions,
            context=services.context,
            segments=services.index_segments,
            tabs=services.tabs,
            theme=services.theme,
            parent=services.window,
            status=services.window,
            autosave=services.autosave,
            # Restoring is connecting: an attach takes its directory off the list.
            connect_project=root.connect_project,
            disconnect_project=disconnect_project,
            # The archive is the store's — per user, in the library file.
            archive_project=archive_project,
            archived=store.archived,
            archive_changed=store.archive_changed,
            forget_archived=store.forget_archived,
            has_unflushed=store.has_unflushed,
        )
    )


def _projects(
    root: _Root,
    *,
    editor: "CanvasModule",
    knowledge: _Knowledge,
    tabs: _Tabs,
    agents: _Agents,
) -> "ProjectsModule":
    """The projects in the index, and the rows under each that open what a project has."""
    from dplanner.modules.projects.module import ProjectEntry, ProjectsDeps, ProjectsModule
    from dplanner.theme.icons import (
        clock_icon,
        coverage_icon,
        gauge_icon,
        graph_icon,
        image_icon,
        list_icon,
        spark_icon,
        spec_icon,
    )

    services, library, store = root.services, root.library, root.store
    spec, coverage = knowledge.spec, knowledge.coverage

    return ProjectsModule(
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
            # The Project dialog's tabs after Repositories: whatever other modules
            # registered about a project, read when the dialog is first built.
            project_settings=services.project_settings,
            checkouts=agents.checkouts,
            repos=root.repos,
            # The index opens a project without knowing what an activity is: *Show
            # Steps* and the Steps row open the graph; the project's row only selects.
            open_steps=editor.open,
            connect_project=root.connect_project,
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
                    open=tabs.assets.open,
                    open_preview=lambda pid: tabs.assets.open(pid, preview=True),
                    icon=image_icon,
                    menu="Project",
                    order=20,
                ),
                ProjectEntry(
                    id="steps",
                    label="Steps",
                    open=editor.open,
                    open_preview=lambda pid: editor.open(pid, preview=True),
                    icon=graph_icon,
                    menu="Project",
                    order=30,
                ),
                ProjectEntry(
                    id="order",
                    label="Order",
                    open=tabs.step_order.open,
                    open_preview=lambda pid: tabs.step_order.open(pid, preview=True),
                    icon=list_icon,
                    menu="Project",
                    order=35,
                ),
                ProjectEntry(
                    id="expenditure",
                    label="Expenditure",
                    open=agents.usage.open_expenditure,
                    open_preview=lambda pid: agents.usage.open_expenditure(pid, preview=True),
                    icon=spark_icon,
                    menu="Project",
                    order=37,
                ),
                ProjectEntry(
                    id="progression",
                    label="Step statuses",
                    open=tabs.progression.open,
                    open_preview=lambda pid: tabs.progression.open(pid, preview=True),
                    icon=gauge_icon,
                    menu="Project",
                    order=40,
                ),
                ProjectEntry(
                    id="time",
                    label="Time Estimates",
                    open=tabs.time.open,
                    open_preview=lambda pid: tabs.time.open(pid, preview=True),
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
    )


def _aspects(
    root: _Root,
    *,
    graph: _Graph,
    knowledge: _Knowledge,
    tabs: _Tabs,
    agents: _Agents,
    branches: "BranchesModule",
    board: "AtWorkBoard",
) -> list["Module"]:
    """The step aspects, in the order their tabs and blocks appear in Step Details."""
    from dplanner.domain.commands import (
        Command,
        CompositeCommand,
        EditTextCommand,
        SetModuleDataCommand,
    )
    from dplanner.domain.model import TextEdit
    from dplanner.modules.agent_claims.ownership import released_by_person
    from dplanner.modules.branches.module import LandingModule
    from dplanner.modules.branches.plan import merged_into_its_branch
    from dplanner.modules.docs.module import DocsCompiledModule, DocsDeps, DocsModule
    from dplanner.modules.github.module import GithubDeps, GithubModule
    from dplanner.modules.schedule.assumptions import read_palette
    from dplanner.modules.step_agent_run.aspect import read as agent_run_state
    from dplanner.modules.step_check.module import StepCheckDeps, StepCheckModule
    from dplanner.modules.step_description.aspect import read as description_read
    from dplanner.modules.step_description.module import (
        StepDescriptionDeps,
        StepDescriptionModule,
    )
    from dplanner.modules.step_description.section import SeparateInstructionLink
    from dplanner.modules.step_milestone.module import StepMilestoneDeps, StepMilestoneModule
    from dplanner.modules.step_playbook.module import StepPlaybookDeps, StepPlaybookModule
    from dplanner.modules.step_start.module import StepStartDeps, StepStartModule
    from dplanner.modules.step_status.module import StepStatusDeps, StepStatusModule
    from dplanner.modules.step_ticket.module import StepTicketDeps, StepTicketModule
    from dplanner.modules.step_wait.module import StepWaitDeps, StepWaitModule
    from dplanner.modules.testing.module import TestsDeps, TestsModule
    from dplanner.planning.agent import MODULE_ID as AGENT_INSTRUCTION_ID
    from dplanner.planning.agent import enabled as is_agent
    from dplanner.planning.agent import read as agent_instruction_read
    from dplanner.planning.agent import separate_instruction as agent_separate
    from dplanner.planning.agent import write_state as agent_write_state
    from dplanner.planning.estimate import MODULE_ID as ESTIMATION_ID
    from dplanner.planning.estimate import write as estimate_write
    from dplanner.planning.kinds import key_of, scope_kinds, works_nobody
    from dplanner.planning.status import record_merged
    from dplanner.planning.wait import Wait

    services, library, store = root.services, root.library, root.store
    # The collectors, wired once: the docs and tests modules group by them, and every walk
    # either module makes stops where these say.
    scopes = scope_kinds()

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

    def milestone_shade(step_id: str) -> tuple[str, str]:
        """A milestone's shade and the sentence for it: *2nd of 4 · Viridis*.

        The words are what make a swatch teach rather than decorate — a colour means "this
        far along the roadmap", and the tooltip is where that is said once (DESIGN.md's
        *Words*) instead of as a line under every field.
        """
        if not library.has(step_id):
            return "", ""
        project = library.project_of(step_id)
        colors = root.milestone_colors(project)
        color = colors.get(step_id, "")
        if not color:
            return "", ""
        place = list(colors).index(step_id) + 1
        return color, f"{_ordinal(place)} of {len(colors)} · {read_palette(project).name}"

    def insert_wait_before(step_id: str) -> None:
        """Step ▸ Insert Wait Before: a wait of a working day in front of the step — it takes
        over what the step waited on, and the step waits on it — as the *Wait* template makes
        one (no estimate, no description), and one undo entry like every other placed step.
        A loose step's wait lands a column to its left where the step was placed; a stacked
        step's joins its stack in its slot, where the column seats it."""
        from dplanner.modules.canvas.layouts.positions import read_position
        from dplanner.modules.canvas.layouts.sorts import H_PITCH
        from dplanner.modules.step_description.aspect import MODULE_ID as DESCRIPTION_ID
        from dplanner.modules.step_description.aspect import write_state as description_state
        from dplanner.planning.wait import MODULE_ID as WAIT_ID
        from dplanner.planning.wait import write as write_wait

        where = read_position(library.step(step_id))
        graph.editor.create_step(
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

    return [
        tabs.estimation,
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
                    agent_enabled=lambda sid: is_agent(library.step(sid)),
                    separate=lambda sid: agent_separate(library.step(sid)),
                    has_text=lambda sid: bool(agent_instruction_read(library.step(sid))),
                    set_separate=set_separate_instruction,
                ),
                # Insert from Assets…, composed over every module's catalog slice.
                pick_assets=root.pick_assets,
            )
        ),
        # Run Agent; the library watcher borrows its launcher.
        agents.instruction,
        agents.launch,
        # The shells Run Agent spawns; the canvas reads the aspect through its accents.
        agents.runs,
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
                # The description *is* the instructions (docs/architecture/), so it is what a
                # collector says about itself — context in the briefing, and a cross-module
                # fact, so it is decided here.
                instructions=description_read,
                # Compiling is a launch: the briefing is the docs module's words, the
                # terminal and the desk's limit are Run Agent's, and neither imports the
                # other. The run is tracked on the collector like any other agent run.
                compile_profiles=agents.launch.compile_profiles,
                compile_with_agent=agents.launch.compile_documentation,
                # Whether an agent is already at work on a collector — the run aspect's own
                # reader, so the words are the status module's and not a second copy.
                run_state=lambda step_id: (
                    agent_run_state(library.step(step_id)) if library.has(step_id) else ""
                ),
                # How a step is named everywhere, for the briefing's verbs and the rows.
                step_key=key_of,
                # A milestone group's medallion in the milestone's own shade — the same
                # sequence the Tests tab's headings and the calendar show.
                milestone_color=root.milestone_color,
                parent=services.window,
                pick_assets=root.pick_assets,
                # The Implementation notes tab — the notes the project made along the way,
                # which every briefing indexes — as a row under each project in its folder.
                more_rows=(tabs.notes.index_row(),),
            )
        ),
        # Declares the compiled-document format only; DocsModule and the CLI write it.
        DocsCompiledModule(),
        # Registers nothing; in the list for its data format, and because it is a module.
        tabs.notes,
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
        StepPlaybookModule(
            StepPlaybookDeps(
                library=library,
                undo=services.undo,
                details=services.step_details,
                project_settings=services.project_settings,
                harness_ids=tuple(harness.id for harness in agent_harnesses()),
                actions=services.actions,
                context=services.context,
                # Run Playbook: Run Agent's launch and gates, and whether its agents work here.
                launcher=agents.launch,
                readings=root.availability,
                parent=services.window,
                standings=agents.standings,
                tasks=services.tasks,
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
                release=lambda f: released_by_person(store.project_dir(f.project), f),
                notices=services.window,
                flush=services.autosave.saved,
            )
        ),
        # No tab either: a check carries nothing, and the Covers tab that shows what it
        # gathers is the tests module's — it renders a list of tests, which is that
        # module's business, not this one's.
        StepCheckModule(
            StepCheckDeps(library=library, undo=services.undo, actions=services.actions)
        ),
        # No tab either: the start is a marker, and what it means is the walks' business,
        # wired in scope_kinds().
        StepStartModule(
            StepStartDeps(library=library, undo=services.undo, actions=services.actions)
        ),
        # A feature is a step: one a person would name and demo, gathering the work behind
        # it and stopping at the previous feature. The Covers tab that shows what it
        # gathers is still the tests module's.
        knowledge.feature,
        # Registers nothing: it owns the widget the graph tab stands beside the canvas.
        graph.problems,
        TestsModule(
            TestsDeps(
                works_nobody=works_nobody,
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
                pick_assets=root.pick_assets,
                # Grouping by milestone writes each heading in that milestone's own shade,
                # so the Tests tab reads as the same sequence the calendar does.
                milestone_color=root.milestone_color,
                # An export is offered where colleagues read reports from.
                reporting_dir=root.reporting_dir,
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
                # Which repository a step's GitHub refs belong to: the code repository the
                # project records, else — the older shape, a plan kept beside its code — the
                # plan's own origin, and none while the code is not set. Git's answer either
                # way; nothing stored can disagree with it.
                repository_for=lambda step_id: root.facts_for(step_id).code_remote,
                finish_merged=lambda step_id: record_merged(
                    library,
                    step_id,
                    services.clock.today(),
                    accepted_by_merge=library.has(step_id)
                    and merged_into_its_branch(library, library.step(step_id), branches.reading_of),
                ),
            )
        ),
    ]


def _step_properties(root: _Root) -> "StepPropertiesModule":
    """THE step editor — `steps.details`, a modal and nothing else — and the templates its
    bar offers."""
    from dplanner.framework.aspect_bar import AspectTemplate
    from dplanner.modules.step_properties.module import (
        StepPropertiesDeps,
        StepPropertiesModule,
    )

    services = root.services
    return StepPropertiesModule(
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
            library=root.library,
            undo=services.undo,
            actions=services.actions,
            parent=services.window,
            sections=services.inspector_sections,
            details=services.step_details,
            theme=services.theme,
        )
    )


def _machine(root: _Root) -> list["Module"]:
    """This machine and this session: the installer and the checklist over the skill the
    CLI generates, Home, and the tabs the last session had open."""
    from dplanner.modules.checklist.module import ChecklistDeps, ChecklistModule
    from dplanner.modules.home.module import HomeDeps, HomeModule
    from dplanner.modules.install.module import InstallDeps, InstallModule
    from dplanner.modules.reopen_tabs.module import ReopenTabsDeps, ReopenTabsModule

    services = root.services

    def skill_files() -> dict[str, str]:
        from dplanner.cli.command import CliRegistry
        from dplanner.cli.skill import generate

        registry = CliRegistry()
        registry.register_all(default_cli_commands())
        return generate(registry, aspect_specs())

    return [
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
                checks=lambda: _machine_checks(files=skill_files, availability=root.availability),
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
                exists=root.library.has,
            )
        ),
    ]


def _pr_base(step: "Step") -> str:
    """The branch a step's PR merges into, as GitHub last said; "" when unknown."""
    from dplanner.modules.github.aspect import read as github_read

    refs = github_read(step)
    return refs.pr_base if refs is not None else ""


def _ordinal(place: int) -> str:
    """``1st``, ``2nd``, ``3rd``, ``4th`` — the teens are the exception every table forgets."""
    suffix = "th" if 10 <= place % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(place % 10, "th")
    return f"{place}{suffix}"


def _step_type_icons(step: "Step") -> tuple[str, ...]:
    """What kind of thing a step is, in the medallion vocabulary the canvas painted
    first: "tag" a milestone, "layers" a feature, "beaker" one carrying tests, "shield" a
    check, "merge" a landing, "playbook" one that chose its playbook. The order table's title
    column reads the same answer, so a step is the same kind everywhere. Who works it is
    :func:`_primary_glyph`'s, and a card says a thing once."""
    from dplanner.modules.step_playbook.aspect import read as playbook_read
    from dplanner.modules.testing.aspect import enabled as test_enabled
    from dplanner.planning.branches import is_land
    from dplanner.planning.check import read as check_read
    from dplanner.planning.feature import is_feature
    from dplanner.planning.milestone import is_milestone

    return (
        *(("tag",) if is_milestone(step) else ()),
        *(("layers",) if is_feature(step) else ()),
        *(("beaker",) if test_enabled(step) else ()),
        *(("shield",) if check_read(step) else ()),
        *(("merge",) if is_land(step) else ()),
        # Its own choice only: an inherited default would mark every landing beside its
        # merge medallion, and with a project default every card.
        *(("playbook",) if playbook_read(step) else ()),
    )


def _card_status(step: "Step") -> "Status | Unknown":
    """A step's status as its card wears it — the key block's wash, a done body — on the
    canvas, the coverage lanes and the report: none for a step nobody works — a wait, a
    branch cut — which has no status, whatever it carried before it became one. A wait's
    clock is the block's one amber then."""
    from dplanner.planning.kinds import works_nobody
    from dplanner.planning.status import Status, stored

    return Status.PENDING if works_nobody(step) else stored(step)


def _primary_glyph(step: "Step") -> tuple[str, str]:
    """Who works a step, as the glyph beside its key and that glyph's tone: an agent's
    sparkle, a person otherwise — a milestone, a feature and a check included, since a
    person closes those — and for a wait nobody at all, so an amber clock, always; a branch
    cut, nobody either, wears the branch it starts.

    The one rule, read by every card that shows a key — the canvas, the coverage lanes and
    the report's graph — and by Find's rows and the Step statuses tab's. The tone is a
    status tone's word — "warn" is the attention amber — so each surface resolves it the way
    it resolves its status washes."""
    from dplanner.planning.agent import enabled as agent_enabled
    from dplanner.planning.branches import is_cut
    from dplanner.planning.wait import is_wait

    if is_wait(step):
        return "clock", "warn"
    if is_cut(step):
        return "branch", ""
    return ("spark" if agent_enabled(step) else "person"), ""


def _ready_in(library: "Library", today: "date") -> "Callable[[Step], Status]":
    """``schedule.status_on`` as readiness reads it (``status.held``): a word this build cannot
    read holds its step as blocked, and a wait not over is pending."""
    from dplanner.planning.schedule import status_on
    from dplanner.planning.status import readiness_of

    return readiness_of(status_on(library, today))


def _wait_aware(library: "Library", today: "Callable[[], date]") -> "Callable[[Step], Reading]":
    """``schedule.status_on`` for a window, on whatever day it is when asked."""
    from dplanner.planning.schedule import status_on

    return lambda step: status_on(library, today())(step)


def _status_workflow() -> "StatusWorkflow":
    """Setting a status, as the window and every CLI verb do it, with the notes module's way
    to keep a reason."""
    from dplanner.modules.step_status.workflows import StatusWorkflow

    return StatusWorkflow(keep_reason=_reason_note)


def _reason_note(
    view: "PlanView", step: "Step", reason: str, today: "date"
) -> "tuple[str, Command | None]":
    """Why a step went to done without review, as a decision note on it — added the way
    `note add` adds one, so a retried verb is one note."""
    from dplanner.modules.notes.aspect import note_on

    project = view.project_of(step.id)
    return note_on(project, step, "decision", "Done without review", reason, today)


def _counts_as_work(step: "Step") -> bool:
    """Whether a step is work: a wait and a branch cut are not — no worker takes them and no
    count holds them."""
    from dplanner.planning.kinds import works_nobody

    return not works_nobody(step)


# The status verbs that write one, each followed by the day's progress row.
STATUS_WRITES = (
    ("status", "set"),
    ("status", "clear"),
)


def _status_written(
    command: "CliCommand", record: "Callable[[CliContext, Project], bool]"
) -> "CliCommand":
    """``command`` followed by ``record`` for the project of the step it named."""
    from dataclasses import replace

    from dplanner.cli.lookup import find_step

    inner = command.run

    def run(context: "CliContext", args: "Namespace") -> int:
        project = context.library.project_of(
            find_step(context.library, args.step, context.current).id
        )
        code = inner(context, args)
        record(context, project)
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
    from dplanner.modules.canvas.report import report_source as graph
    from dplanner.modules.estimation.report import report_source as estimates
    from dplanner.modules.feature.report import report_source as features
    from dplanner.modules.github.report import report_source as github
    from dplanner.modules.notes.report import report_source as notes
    from dplanner.modules.schedule.assumptions import milestone_colors
    from dplanner.modules.schedule.cli import Readers as TimeReaders
    from dplanner.modules.schedule.landings import card_stats
    from dplanner.modules.schedule.report import report_source as time_estimates
    from dplanner.modules.status_board.report import report_source as progression
    from dplanner.modules.step_description.report import report_source as descriptions
    from dplanner.modules.step_milestone.report import report_source as milestones
    from dplanner.modules.step_order.report import report_source as order
    from dplanner.modules.step_ticket.report import report_source as tickets
    from dplanner.modules.testing.report import report_source as tests
    from dplanner.planning.estimate import MODULE_ID as ESTIMATION_ID
    from dplanner.planning.kinds import key_of, kind_word
    from dplanner.planning.milestone import read as milestone_read

    summaries = aspect_summaries(skip={ESTIMATION_ID})

    def step_aspects(step: "Step") -> list[str]:
        return [phrase for phrase in (summary(step) for summary in summaries) if phrase]

    return (
        progression(
            status_in=_ready_in,
            counts_as_work=_counts_as_work,
            key_of=key_of,
        ),
        time_estimates(TimeReaders()),
        graph(
            key_of=key_of,
            kind_of=kind_word,
            status_for=_card_status,
            stats_of=card_stats,
            badge_of=milestone_read,
            # The report's picture of the graph wears the same shades the window does, and
            # the same glyph in each card's key block.
            colors_of=milestone_colors,
            glyph_of=_primary_glyph,
        ),
        order(
            step_aspects=step_aspects,
            milestone_label=milestone_read,
        ),
        estimates(),
        milestones(),
        features(),
        descriptions(),
        tests(key_of=key_of),
        tickets(),
        github(),
        notes(key_of=key_of),
    )


def _coverage_trace(library: "Library", project: "Project", files: "FilesFor") -> "Trace":
    """The coverage picture: milestones → features → spec passages → steps → tests and docs.

    ``coverage/readers.py`` reads every owner and ``coverage/trace.py`` arranges them; what
    the coverage package may not import arrives here, as functions. Derived on every read,
    like everything the graph could contradict.
    """
    from dplanner.modules.coverage.readers import readers
    from dplanner.modules.coverage.trace import build
    from dplanner.modules.docs.collect import sources_for, state_of
    from dplanner.modules.schedule.assumptions import milestone_colors
    from dplanner.modules.spec.documents import anchor_sources, document_texts
    from dplanner.modules.testing.runs import latest_statuses
    from dplanner.planning.kinds import scope_kinds

    wired = readers(
        kinds=scope_kinds(),
        anchor=anchor_sources,
        documents=document_texts,
        results=latest_statuses,
        docs_state=state_of,
        docs_sources=sources_for,
        status=_card_status,
        glyph=_primary_glyph,
        milestone_colors=milestone_colors,
    )
    return build(wired, library, project, files)


def _paste_policies() -> tuple["PastePolicy", ...]:
    """What a copied step may not carry verbatim, one policy per module that has a say.

    Assembled here because each policy lives in its owner's Qt-free half and no module may
    import another's; both the window's Paste/Duplicate and ``step duplicate`` read this
    tuple. Five entries, on purpose: an id minted per project (a test's), the state of a
    shell somebody is running and what its runs consumed, and the days a status was said
    on — all facts about the original — a feature's
    passages, which were read into *that* feature and are not a claim a copy may make, and
    the steps a landing names, which become their copies'.
    Everything else a step carries copies as it is.
    """
    from dplanner.modules.step_agent_run.aspect import forget_for_paste
    from dplanner.modules.testing.aspect import remint_for_paste
    from dplanner.planning.branches import remap_for_paste as remap_landing
    from dplanner.planning.feature import drop_cites_for_paste
    from dplanner.planning.status import forget_days_for_paste

    return (
        remint_for_paste,
        forget_for_paste,
        forget_days_for_paste,
        drop_cites_for_paste,
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


def _machine_checks(
    *, files: "Callable[[], dict[str, str]]", availability: "Availability | None" = None
) -> tuple["MachineCheck", ...]:
    """What this machine has of what DPlanner needs, from every module that owns a row.

    The tuple both surfaces read — ``dplanner checklist show`` and *Tools ▸ Setup
    Checklist…* — assembled here for ``_asset_sources``' reason: each ``checks()`` lives in
    its owner's Qt-free half and no module may import another's. Order inside a group is
    the order they are listed; the group itself is ``cli/checklist.py``'s ``GROUPS``.

    ``files`` is the generated skill the installer's rows compare against — the same
    closure the Install dialog is handed; ``availability`` the window's one agent reading.
    """
    from dplanner.modules.agent_launch import checks as agent_checks
    from dplanner.modules.checklist import checks as generic
    from dplanner.modules.dictation import checks as dictation_checks
    from dplanner.modules.github import checks as github_checks
    from dplanner.modules.install import checks as install_checks
    from dplanner.modules.llm import checks as llm_checks
    from dplanner.modules.spec_confluence import checks as confluence_checks

    return (
        *install_checks.checks(files=files),
        *generic.checks(),
        *github_checks.checks(),
        *agent_checks.checks(harnesses=agent_harnesses(), availability=availability),
        *confluence_checks.checks(),
        # The provider modules' ids and labels: the keychain is asked under each module's
        # own id, and the llm module never learns which providers exist by importing them.
        *llm_checks.checks(providers=_llm_providers()),
        *dictation_checks.checks(providers=dictation_providers()),
    )


def _llm_providers() -> tuple[tuple[str, str], ...]:
    """``(module id, label)`` per AI provider module, in the order the settings page lists
    them — written literally, as ``scope_kinds`` writes its predicates.

    Not imported from each provider: a provider module's ``MODULE_ID`` sits beside its SDK
    adapter, and reaching for it would load Qt in a CLI run. A test asserts the two agree.
    """
    return (("llm_openai", "OpenAI"), ("llm_anthropic", "Anthropic"))


def _unsettling_notes(
    project: "Project",
) -> dict["StepId", tuple[tuple[str, str, str, str], ...]]:
    """The standing notes that put a test in doubt, by the step they were made on.

    **Which labels those are is named here, literally**, for the reason `scope_kinds()`
    names its predicates here: this is the one place that may know every aspect, and
    `modules/testing/` may not learn the notes module's vocabulary. A *decision* changes
    what the work should do and a *spec-change* records where it departed from the spec —
    either can leave a test proving last month's answer. A *handoff*, a *later* or a
    *post-project* note says nothing about what a test should assert, so neither should
    it put one in front of somebody.

    Superseded notes are dropped: the note that replaced one is itself a decision, made
    later, so it already stands for the doubt — reporting both would name one test twice.
    """
    from dplanner.modules.notes.aspect import read_log, standing

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
    from dplanner.modules.branches import cli as branches_cli
    from dplanner.modules.canvas import cli as layout_cli
    from dplanner.modules.coverage.readers import covered_tests
    from dplanner.modules.docs import cli as docs_cli
    from dplanner.modules.estimation import cli as estimation_cli
    from dplanner.modules.feature import cli as feature_cli
    from dplanner.modules.spec import cli as spec_cli
    from dplanner.modules.step_agent_instruction import cli as agent_cli
    from dplanner.modules.step_description import cli as description_cli
    from dplanner.modules.step_description.aspect import read as description_read
    from dplanner.modules.step_start import cli as start_cli
    from dplanner.modules.steps import cli as steps_cli
    from dplanner.modules.testing import cli as testing_cli
    from dplanner.modules.testing.aspect import enabled as test_enabled
    from dplanner.planning.agent import enabled as is_agent
    from dplanner.planning.branches import is_land
    from dplanner.planning.kinds import key_of, scope_kinds
    from dplanner.planning.milestone import is_milestone

    scopes = scope_kinds()
    return (
        *steps_cli.lint_checks(),
        *start_cli.lint_checks(),
        # A branch is one way in and one way out; what it says is its PRs' bases.
        *branches_cli.lint_checks(
            is_agent=is_agent,
            is_milestone=is_milestone,
            pr_base_of=_pr_base,
        ),
        *description_cli.lint_checks(),
        *docs_cli.lint_checks(kinds=scopes),
        # An agent step is briefed by its description unless it carries a separate
        # instruction, and a landing by its aspect; the readers arrive here, not by import.
        *agent_cli.lint_checks(
            described=lambda step: bool(description_read(step)) or is_land(step)
        ),
        *estimation_cli.lint_checks(counts_as_work=_counts_as_work),
        *spec_cli.lint_checks(),
        *feature_cli.lint_checks(anchor=spec_cli.anchor_sources, key_of=key_of),
        *layout_cli.lint_checks(key_of=key_of),
        *testing_cli.lint_checks(),
        # A step's *own* tests are a different question from what it gathers; testing's
        # Qt-free reader answers it, handed over rather than imported.
        *scope_lint(
            kinds=scopes,
            covered_by=covered_tests,
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
    from dplanner.modules.notes.aspect import asset_source as notes
    from dplanner.modules.project_assets.cli import asset_source as pool
    from dplanner.modules.spec.documents import asset_source as spec_figures
    from dplanner.modules.step_description.aspect import asset_source as descriptions
    from dplanner.modules.testing.aspect import asset_source as tests
    from dplanner.planning.agent import asset_source as instructions

    return (
        descriptions(),
        tests(),
        documentation(),
        instructions(),
        notes(),
        spec_figures(),
        pool(),
    )


def at_work_board() -> "AtWorkBoard":
    """Where an agent's *at work* claims live on this machine — ``domain/at_work.py``.

    Named here and nowhere deeper, like the topology gate's record file and the spec-git
    cache: a feature module never reaches ``config_dir()``. Both surfaces build it from
    this one function, so the window reads exactly the directory the CLI writes.
    """
    from dplanner.core.config_dir import config_dir
    from dplanner.domain.at_work import DIRECTORY, AtWorkBoard

    return AtWorkBoard(config_dir() / DIRECTORY)


def start_window(services: "AppServices") -> None:
    """What the program's first window shows once it is built: the tabs the last session
    had, which reopen_tabs brought back during the build — or, when that left none open,
    Home.

    Called by ``app.open_at_startup`` and nowhere else, because it is the *program's*
    start and nothing more: a reload rebuilds the window the person had, and a window
    whose last tab they closed stays blank — `docs/architecture/shell-ui.md`'s *Home is where a
    window starts*.
    """
    from dplanner.modules.home.activity import HOME_KIND

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
    from dplanner.domain.agents import shell_marker
    from dplanner.domain.locations import roles_by_id
    from dplanner.domain.workflow import AgentRun, Person
    from dplanner.modules.agent_at_work import cli as at_work_cli
    from dplanner.modules.agent_briefing.worktree import mainline
    from dplanner.modules.agent_claims import cli as claims_cli
    from dplanner.modules.agent_claims.ownership import released_by_person as release
    from dplanner.modules.agent_launch import cli as launch_cli
    from dplanner.modules.agent_questions import cli as questions_cli
    from dplanner.modules.agent_supervisor import cli as supervisor_cli
    from dplanner.modules.agent_usage import cli as usage_cli
    from dplanner.modules.branches import cli as branches_cli
    from dplanner.modules.branches.plan import (
        branch_plan,
        branch_reading,
        branches_in,
        merged_into_its_branch,
    )
    from dplanner.modules.branches.plan import strips as branch_strips
    from dplanner.modules.canvas import cli as layout_cli
    from dplanner.modules.canvas.stacks.edits import bridged_removal
    from dplanner.modules.canvas.stacks.stack import stack_split
    from dplanner.modules.coverage import cli as coverage_cli
    from dplanner.modules.coverage.readers import covered_tests
    from dplanner.modules.docs import cli as docs_cli
    from dplanner.modules.estimation import cli as estimation_cli
    from dplanner.modules.feature import cli as feature_cli
    from dplanner.modules.github import cli as github_cli
    from dplanner.modules.library import cli as library_cli
    from dplanner.modules.notes import cli as note_cli
    from dplanner.modules.project_assets import cli as assets_cli
    from dplanner.modules.project_assets.cli import read_titles
    from dplanner.modules.projects import cli as projects_cli
    from dplanner.modules.schedule import cli as schedule_cli
    from dplanner.modules.spec import cli as spec_cli
    from dplanner.modules.spec.aspect import read_topology
    from dplanner.modules.status_board import cli as progression_cli
    from dplanner.modules.step_agent_instruction import cli as agent_cli
    from dplanner.modules.step_agent_run import cli as agent_state_cli
    from dplanner.modules.step_agent_run.aspect import asks_person
    from dplanner.modules.step_check import cli as check_cli
    from dplanner.modules.step_description import cli as description_cli
    from dplanner.modules.step_milestone import cli as milestone_cli
    from dplanner.modules.step_order import cli as order_cli
    from dplanner.modules.step_playbook import cli as playbook_cli
    from dplanner.modules.step_playbook.engine import Engine as PlaybookEngine
    from dplanner.modules.step_start import cli as start_cli
    from dplanner.modules.step_status import cli as status_cli
    from dplanner.modules.step_ticket import cli as ticket_cli
    from dplanner.modules.step_wait import cli as wait_cli
    from dplanner.modules.steps import cli as steps_cli
    from dplanner.modules.testing import cli as testing_cli
    from dplanner.modules.testing.format import FORMAT_SUBJECT, FORMAT_VERB
    from dplanner.modules.testing.format import guide as test_format
    from dplanner.planning.agent import enabled as is_agent
    from dplanner.planning.kinds import key_of, kind_word, scope_kinds
    from dplanner.planning.status import Status, stored

    specs = aspect_specs()
    time_readers = schedule_cli.Readers()
    scopes = scope_kinds()
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
    plan_branches = lambda lib, step, facts: branch_plan(lib, step, mainline(facts, step))  # noqa: E731
    # Who answers is read like `status set`'s reporter: an agent's shell is the coordinator.
    harnesses = agent_harnesses()
    in_agent_shell: Callable[[], bool] = lambda: bool(shell_marker(harnesses))  # noqa: E731
    end_claim: Callable[[EndClaim], bool] = lambda c: board.end(c.project, c.step)  # noqa: E731

    def actor() -> "Actor":
        return AgentRun() if in_agent_shell() else Person()

    def set_status(context: "CliContext", step: "Step", status: "Status") -> None:
        """A status written as `status set` writes it — refused as one line, its claim
        ended once the run is written."""
        status_cli.write_status(context, workflow, end_claim, release, step, status, actor=actor())

    def finish_merged(context: "CliContext", step: "Step") -> bool:
        """A step waiting on its merge is done once its PR reads merged — written as
        `status set` writes it; True when it was finished. A step on a feature branch is
        accepted by its PR merging into that branch, whether or not it was under review."""
        status = stored(step)
        accepted = status is Status.READY_TO_MERGE or (
            status is Status.READY_FOR_REVIEW and merged_into_its_branch(context.library, step)
        )
        if not accepted:
            return False
        set_status(context, step, Status.DONE)
        return True

    # A playbook's stages launch as `agent run` launches, and `progress` merges into the
    # feature branch and accepts the step by the merge, as `github refresh` does.
    engine = PlaybookEngine(
        launch=launch_cli.StageLauncher(default_location_roles(), plan_branches, harnesses),
        accept=lambda context, step, base, head: github_cli.accept_by_merge(
            context, step, base=base, head=head, finish_merged=finish_merged
        ),
    )
    commands = [
        *library_cli.commands(),
        # The step authors let `step add` author the step in the same call; the list
        # order is the report order — the same order the skill teaches authoring in.
        *steps_cli.commands(
            step_authors=[
                start_cli.step_author(),
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
            key_of=key_of,
            # `step show` and `project graph` mark the feature branch a step's work is on.
            branches_in=branches_in,
            # A step removed from a stack closes the chain round it, as Delete does.
            remove_steps=bridged_removal,
            # The canvas's Duplicate: its clipboard clones, under the same policies.
            duplicate=layout_cli.duplicator(
                paste_policies=_paste_policies(),
                file_modules=tuple(source.id for source in sources),
            ),
        ),
        *projects_cli.commands(
            key_of=key_of,
            branches_in=branches_in,
            # The location roles every module declared, and where a read-only one's
            # managed clone stands — both cross-module facts, handed in here.
            roles=roles,
            managed=managed_for(roles),
            kept_root=config_dir(),
            remove_steps=bridged_removal,
        ),
        # `topology show` tells the gate what it printed; the gate is built here, so the
        # spec module never learns where the record lives.
        *spec_cli.commands(note_read=gate.record),
        *estimation_cli.commands(counts_as_work=_counts_as_work),
        *ticket_cli.commands(),
        *description_cli.commands(),
        *docs_cli.commands(kinds=scopes),
        *agent_cli.commands(roles=default_location_roles(), branch_plan=plan_branches),
        # Run Agent from a terminal: the window's launch workflow, headless or in a terminal.
        *launch_cli.commands(
            roles=default_location_roles(),
            branch_plan=plan_branches,
            harnesses=harnesses,
            start_pass=engine.start,
        ),
        *agent_state_cli.commands(),
        # A run's usage and its supervisor read the harness that ran it: the window's tuple.
        *usage_cli.commands(harnesses=harnesses),
        *supervisor_cli.commands(harnesses=harnesses),
        *questions_cli.commands(in_agent_shell=in_agent_shell),
        *claims_cli.commands(in_agent_shell=in_agent_shell),
        # The agent's own account of what it is doing while it does it: the window's
        # banner and the watcher's stood-down modal both read what these write.
        *at_work_cli.commands(board=board, key_of=key_of),
        # An agent's done waits for review: the verb reads who is reporting (an agent's
        # shell, the entry point's reading) and what the step is (an agent step), and a
        # `--because` lands as a decision note in the same run. A status that says nobody
        # is working the step ends the claim somebody made on it, on the board above.
        *status_cli.commands(
            workflow=workflow,
            in_agent_shell=in_agent_shell,
            end_claim=end_claim,
            release=release,
        ),
        *milestone_cli.commands(),
        *wait_cli.commands(),
        *playbook_cli.commands(
            harnesses=harnesses, advance=engine.advance, end_claim=end_claim, release=release
        ),
        # A branch's two ends are born dressed as the window's Put on a Branch makes them.
        *branches_cli.commands(
            stacked_apart=stack_split,
            key_of=key_of,
        ),
        # A feature's passages are anchored in the spec documents by the spec module's
        # one derivation, handed across here — `cite`, `reanchor`, `step add --feature`
        # and lint all judge a quote the same way.
        *feature_cli.commands(anchor=spec_cli.anchor_sources, key_of=key_of),
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
        *scope_commands(kinds=scopes, covered_by=covered_tests),
        # The coverage picture is every module's Qt-free half read once and arranged;
        # assembled here, so neither the verbs nor the tab import any of them.
        *coverage_cli.commands(trace_of=_coverage_trace),
        # The asset catalog is the same shape one level down: every file-carrying module
        # exports an asset_source(), the reports live in cli/assets.py, and the browser
        # module's own writes (attach, name) stay in its cli.py — the `scope` split.
        *catalog_commands(sources=sources, titles=read_titles),
        *assets_cli.commands(sources=sources),
        *order_cli.commands(counts_as_work=_counts_as_work),
        # Progression reads statuses through the aspects' Qt-free readers — handed over
        # here so no cli.py imports another module's.
        *progression_cli.commands(
            status_in=_ready_in,
            counts_as_work=_counts_as_work,
            is_agent=is_agent,
            asks_person=asks_person,
        ),
        *layout_cli.commands(
            key_of=key_of,
            # A sort leaves a card on a branch the room of its strip, as the window does.
            strips=lambda project: branch_strips(branch_reading(project)),
        ),
        # The staffing matrix reads estimates, agent-ness and the start date through the
        # owners' Qt-free readers — handed over here so no cli.py imports another module's.
        *schedule_cli.commands(time_readers, counts_as_work=_counts_as_work),
        *github_cli.commands(finish_merged=finish_merged),
        # A note names the step it was made on by id and prints it by key — the
        # same rule every row prints, handed over rather than imported.
        *note_cli.commands(key_of=key_of),
        # The report is every module's Qt-free say, assembled once (`_report_sources`) for
        # the terminal and the window alike; the readers every step row needs come with it.
        *report_commands(
            sources=_report_sources(),
            key_of=key_of,
            kind_of=kind_word,
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
    # agent reports with `status set`, and nobody opens a window to record it.
    commands = [
        _status_written(
            command,
            lambda context, project: schedule_cli.record_day(context, project, time_readers),
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
    from dplanner.modules.docs import aspect as docs
    from dplanner.modules.github import aspect as github
    from dplanner.modules.spec import aspect as spec
    from dplanner.modules.step_agent_run import aspect as agent_run
    from dplanner.modules.step_description import aspect as description
    from dplanner.modules.step_playbook import aspect as playbook
    from dplanner.modules.step_ticket import aspect as ticket
    from dplanner.modules.testing import aspect as testing
    from dplanner.planning import (
        agent,
        branches,
        check,
        estimate,
        feature,
        milestone,
        start,
        status,
        wait,
    )

    return [
        agent.SPEC,
        agent_run.SPEC,
        branches.CUT_SPEC,
        branches.LAND_SPEC,
        check.SPEC,
        description.SPEC,
        docs.SPEC,
        docs.COMPILED_SPEC,
        estimate.SPEC,
        feature.SPEC,
        github.SPEC,
        milestone.SPEC,
        playbook.SPEC,
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
    (``docs/architecture/canvas.md``'s *One in, one out is a rule the domain asks*). Qt-free,
    because ``entry.py`` hands it to every CLI run.
    """
    from dplanner.modules.canvas.stacks.stack import link_rule

    return (link_rule,)


def default_module_formats() -> list[ModuleDataFormat]:
    """Every module data format, for the CLI to migrate with.

    The GUI gets these from the module objects themselves (``AppBuilder`` reads
    ``data_format`` off anything that declares one). The CLI never builds those objects, so
    the same list has to be reachable without them — and it must stay complete, because a
    format missing here is data the CLI silently declines to bring forward.
    """
    from dplanner.domain import shelf
    from dplanner.modules.agent_usage import aspect as agent_usage
    from dplanner.modules.canvas.layouts import positions
    from dplanner.modules.notes import migrate as notes
    from dplanner.modules.project_assets import cli as project_assets
    from dplanner.modules.schedule import assumptions as schedule_assumptions
    from dplanner.modules.schedule import progress as schedule_progress

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
        schedule_assumptions.DATA_FORMAT,
        schedule_progress.DATA_FORMAT,
        project_assets.DATA_FORMAT,
        shelf.DATA_FORMAT,
        notes.DATA_FORMAT,
        agent_usage.DATA_FORMAT,
    ]
