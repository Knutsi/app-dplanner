"""Run Agent: launching a coding agent in a terminal the person owns.

Take the step's briefing from ``agent_briefing`` (its ``compose.brief``, which the CLI's
``agent prompt`` prints too), stage its attached files beside the prompt in a per-run temp
directory, and open a terminal on it. The terminal is a **peer process the user owns**,
deliberately not a TaskRunner task — see ``launcher.py``. Preview Prompt and the
no-terminal fallback show the same assembled text, because the prompt is the library and
the terminal was only one way to hand it over. The briefing is the agent-instruction
aspect's (``step_agent_instruction``); its Agent tab shows :meth:`AgentLaunchModule.assembled`
and runs these verbs by their action ids.

**And an agent may be opened with nothing to do.** *Project ▸ Open Agent in Code* runs
the same launch profiles in the same terminals, in the project's code, with no briefing
and none of the modes a briefed run picks — the harness's own ``open_command``. It is
what the planning *before* the plan needs: a spec has been imported, there are no steps
to brief yet, and the agent's first instruction is the one the person types.

**It runs one agent per chosen step, up to a limit.** The verb reads the selection the way
Delete does, so lassoing three agent steps is *Run 3 Agents…* and one gesture; past
*Settings ▸ Agent profiles*'s limit (four by default) the count itself is the refusal, greyed with
its reason like any other precondition. Each step whose shell opened is also claimed
*in progress* — the workflow's claim, applied off the undo stack, unless the person
switched that off on the settings page — since the agent's own first report may be
minutes away.

**A step's launch is the one ``dplanner agent run`` runs too** (``launch.py``, and
``workflows.py``'s claim): under the step's launch lock, the briefing and the run's record,
then the claim saved, then the terminal — so the two cannot drift. What is the window's own
is what it asks a person: the graph gate, the clone, the limit, the prompt fallback. A
step's worktree is prepared by git on a task, since it fetches, and the terminals open once
it is there.

The launch settings and profiles are kept under the agent aspect's id
(``planning.agent.MODULE_ID``), where they were stored before this package existed.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtWidgets import QDialog, QMenu, QWidget

from dplanner.core.clock import Clock
from dplanner.core.storage.locations import remote_label
from dplanner.core.telemetry import current
from dplanner.domain.agents import AgentHarness
from dplanner.domain.locations import LocationRole
from dplanner.domain.model import Library, Node, NodeId, Step, StepId
from dplanner.domain.repositories import RepositoryFacts
from dplanner.domain.store import Conflict, FilesFor
from dplanner.framework.action_menu import append_action
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
    DataMenuSpec,
)
from dplanner.framework.context import Context, ContextService
from dplanner.framework.notices import Notice
from dplanner.framework.settings_registry import (
    SettingsSection,
    SettingsSectionRegistry,
)
from dplanner.framework.step_selection import chosen_steps, focused_step
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.user_config import get_global
from dplanner.framework.widgets import notice
from dplanner.framework.window import NoticeHost, StatusHost
from dplanner.modules.agent_briefing import worktree as where
from dplanner.modules.agent_briefing.prompt import (
    AssembledPrompt,
    conflict_prompt,
    handover_prompt,
    problems_prompt,
    reconcile_prompt,
)
from dplanner.modules.agent_briefing.protocol import preamble
from dplanner.modules.agent_launch import launch, launcher, workflows
from dplanner.modules.agent_launch.profiles import (
    Profile,
    adopt,
    agent_command,
    default_profile,
    launch_command,
    problem,
    profile_named,
    read_profiles,
    seed_profiles,
)
from dplanner.modules.agent_launch.run_dialog import PromptFallbackDialog, RunAnywayDialog
from dplanner.modules.agent_launch.settings_page import (
    build_page,
    max_agents,
    start_in_progress,
)
from dplanner.modules.agent_supervisor import supervisor
from dplanner.planning.agent import MODULE_ID, enabled, uses_worktree
from dplanner.planning.branches import DEFAULT_BRANCHES, BranchPlan
from dplanner.planning.kinds import key_of
from dplanner.planning.schedule import status_on
from dplanner.planning.status import MODULE_ID as STATUS_MODULE_ID
from dplanner.planning.status import Reading, Status, phrase, stored
from dplanner.theme.icons import spark_icon

# The Step menu's Run Agent child: the profiles, then the way to Settings. The data menu
# is its seat; the two verbs name it as their submenu so the palette says where they live.
RUN_MENU_ID = "agent.run_with"
RUN_MENU_TITLE = "Run Agent"
# The Project menu's Open Agent child: the same profiles, opening the agent where the code
# is with nothing to do. It is the *project's* verb and not a step's because it is what the
# planning before the steps needs — there is no step to be about yet.
OPEN_MENU_ID = "agent.open_with"
OPEN_MENU_TITLE = "Open Agent in Code"
SETTINGS_SECTION = f"{MODULE_ID}.launch"
PROFILES_NOTICE = f"{MODULE_ID}.profiles"

PREVIEW_NOTE = (
    "This is the exact briefing Run Agent will launch with. File paths are relative to"
    " the workspace here; at launch the files are copied beside prompt.md and referenced"
    " by their staged paths."
)


def _no_record(_step_id: StepId, _files: launcher.LaunchFiles, _harness: str) -> None:
    return None


def _no_clone(_repositories: Sequence[str], done: Callable[[dict[str, Path], str], None]) -> None:
    """A build with nothing to clone with: the verb is refused where it would have cloned."""
    done({}, "nothing here can clone a repository")


def _profiles_refused(shared: str) -> list[tuple[str, str]]:
    """Every launch profile and why it cannot run: ``shared`` when the gesture itself is
    refused, else the profile's own terminal. The default first, as everywhere this list
    is shown, and plain data so a panel can render it without learning what a profile is."""
    return [
        (profile.name, shared or launcher.template_refusal(launch_command(profile)))
        for profile in read_profiles()
    ]


def _window_title(subject: str, note: str) -> str:
    """What the terminal's window is called. ``subject`` is the step's key and title, or
    the project a run with no step is about; ``note`` is what this run is *for* when it is
    not the step's work: two runs on one step are told apart by their windows or not at
    all."""
    return f"{subject} ({note})" if note else subject


def _titled(step: Step) -> str:
    """A step's title as a person reads it — the placeholder when it has none."""
    return step.title or "Untitled step"


@dataclass(frozen=True)
class _Job:
    """One step of a launch, read on the GUI thread before its worktree is prepared."""

    step: StepId
    facts: RepositoryFacts
    branches: BranchPlan
    checkout: Path
    name: str

    def changed(
        self,
        facts: RepositoryFacts,
        branch_plan: Callable[[Library, Step, RepositoryFacts | None], BranchPlan],
        library: Library,
        step: Step,
    ) -> bool:
        """Whether the step now names another worktree or branch than was prepared — a
        rename, a ticket, a stretch — so the briefing would send the agent elsewhere."""
        now = launch.worktree_of(step, facts)
        return (
            now != (self.checkout, self.name) or branch_plan(library, step, facts) != self.branches
        )


def _run_words(
    harnesses: tuple[AgentHarness, ...], profile: Profile, files: launcher.LaunchFiles
) -> str:
    """Which agent a launch handed the work to, for a surface that records it — the CLI's
    own name and the run's session, or just the name for a harness that mints its own id."""
    harness = launcher.harness_of(agent_command(harnesses, profile), harnesses)
    label = harness.label if harness is not None else "An agent"
    session = files.session if harness is not None and harness.names_session else ""
    return f"{label} · session {session}" if session else label


def _our_version(node: Node, entry: str) -> str:
    """The window's version of one entry, in the shape the file on disk has."""
    if entry == "meta":
        meta: dict[str, object] = {"title": getattr(node, "title", "")}
        if isinstance(node, Step):
            meta["edges"] = node.edges
        else:
            meta["summary"] = getattr(node, "summary", "")
            for key in ("repository", "colocation"):
                if value := getattr(node, key, ""):
                    meta[key] = value
        return json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    module_id, suffix = entry.rsplit(".", 1)
    if suffix == "json":
        data = node.module_data.get(module_id, {})
        return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return node.module_text.get(module_id, "")


# A person's own shell where a step's work is: its worktree, or the checkout a step that
# works in place uses. Not a run — nothing is briefed, tracked or claimed.
SHELL_IN_WORKTREE = "&Open Terminal in Worktree"
SHELL_IN_CHECKOUT = "&Open Terminal in Checkout"
NO_WORKTREE = "no worktree of it on this machine yet — Run Agent prepares one"


@dataclass(frozen=True)
class AgentLaunchDeps:
    library: Library
    actions: ActionRegistry
    context: ContextService
    settings_sections: SettingsSectionRegistry
    status: StatusHost
    parent: QWidget
    # The store's file areas and raw byte access — how instruction images are listed for
    # the prompt and staged beside it at launch.
    files: FilesFor
    read_asset: Callable[[str], bytes | None]
    # Both repositories of the step's project as this machine sees them — the one
    # derivation ``domain/repositories.py`` makes, handed over by the composition root.
    # Which of the two an agent works in is this module's decision (``_workdir``); a
    # conflict is settled in the plan's own repository, whatever the step's code is.
    facts_for: Callable[[StepId], RepositoryFacts]
    # A checkout of each repository on this machine, cloned where the person's policy
    # says when there is none — the projects module's checkout service, handed over by
    # the root. Answers on the GUI thread with what landed and the first refusal.
    ensure_checkouts: Callable[[Sequence[str], Callable[[dict[str, Path], str], None]], None] = (
        field(default=_no_clone)
    )
    # Which branches a run of a step works between — where its worktree starts, what its
    # PR opens against — decided by the plan's stretches, which the branches module reads
    # and caches; the briefing tells the agent and the script prepares the same plan.
    branch_plan: Callable[[Library, Step, RepositoryFacts | None], BranchPlan] = field(
        default=lambda _library, _step, _facts: DEFAULT_BRANCHES
    )
    # The kinds of place a project can name — every module's ``roles.py``, collected by the
    # root — which the briefing's preamble words when it says where each location is.
    location_roles: tuple[LocationRole, ...] = ()
    # Hands the spawned shell over — with the id of the harness that runs in it, "" for
    # a custom command: the step_agent_run module stamps the aspect, watches the run's
    # files for the shell's end and reads the harness's record back — reached through
    # the root because modules never import each other.
    record_launch: Callable[[StepId, launcher.LaunchFiles, str], None] = field(default=_no_record)
    # Every agent CLI this build can launch, first is the default — the composition
    # root's ``agent_harnesses()``. What a profile's command is read against.
    harnesses: tuple[AgentHarness, ...] = ()
    # Opens Settings on the section with this id — *Manage Agent Profiles…* at the foot
    # of the Run Agent child menu lands on this module's own page. The settings module
    # owns the dialog; the root closes over it.
    open_settings: Callable[[str], None] = field(default=lambda _section_id: None)
    clock: Clock = field(default_factory=Clock)
    # Where each step's project keeps its ledger — the store's to know — so a launch writes
    # the run's record before it spawns anything.
    project_dir: Callable[[StepId], Path | None] = field(default=lambda _step_id: None)
    # Prepares the steps' worktrees off the GUI thread (a fetch); None prepares them inline.
    tasks: TaskService | None = None
    # Where a profiles file that cannot be read is said, until it is fixed.
    notices: NoticeHost | None = None
    # Autosave's flush now, and whether everything is on disk: a launch's claim is saved
    # before its terminal is started.
    flush: Callable[[], bool] = field(default=lambda: True)


class AgentLaunchModule:
    id = "agent_launch"

    def __init__(self, deps: AgentLaunchDeps) -> None:
        self._deps = deps
        self._preparing: TaskRunner | None = None

    def register(self) -> None:
        deps = self._deps
        # The verb every button and the palette run — through the default profile. Its
        # seat in the Step menu is the child menu below, which lists every profile with
        # the default first, so it is not listed flat beside it.
        deps.actions.register(
            ActionSpec(
                id="agent.run",
                label="Run &Agent…",
                menu="Step",
                group="agent",
                submenu=RUN_MENU_TITLE,
                order=10,
                in_menus=False,
                tip="Open a terminal with the agent briefed on this step",
                icon=spark_icon,
                state=self._can_run,
                run=self._run,
            )
        )
        deps.actions.register_data_menu(
            DataMenuSpec(
                id=RUN_MENU_ID,
                menu="Step",
                group="agent",
                title=RUN_MENU_TITLE,
                order=10,
                fill=self._fill_profiles,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="agent.profiles",
                label="&Manage Agent Profiles…",
                menu="Step",
                group="agent",
                submenu=RUN_MENU_TITLE,
                order=90,
                in_menus=False,
                tip="Settings ▸ Agent profiles: the agents and terminals Run Agent offers",
                run=lambda _context: deps.open_settings(SETTINGS_SECTION),
            )
        )
        # Opening one with nothing to do: the project's verb, seated in its own child menu
        # of the same profiles. No step, so none of the step's questions are asked.
        deps.actions.register(
            ActionSpec(
                id="agent.open",
                label="&Open Agent in Code…",
                menu="Project",
                group="agent",
                submenu=OPEN_MENU_TITLE,
                order=10,
                in_menus=False,
                tip="Open a terminal with the agent in this project's code, briefed on"
                " nothing — for the planning that comes before there are steps",
                state=self._can_open,
                run=self._open,
            )
        )
        deps.actions.register_data_menu(
            DataMenuSpec(
                id=OPEN_MENU_ID,
                menu="Project",
                group="agent",
                title=OPEN_MENU_TITLE,
                order=10,
                fill=self._fill_open_profiles,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="agent.preview",
                label="Preview Agent &Prompt…",
                menu="Step",
                group="agent",
                order=20,
                tip="See the exact briefing Run Agent will launch with",
                state=self._can_preview,
                run=self._preview,
            )
        )
        deps.settings_sections.register(
            SettingsSection(
                id=SETTINGS_SECTION,
                category=("Agent profiles",),
                factory=lambda parent: build_page(parent, harnesses=deps.harnesses),
            )
        )
        deps.actions.register(
            ActionSpec(
                id="agent.open_shell",
                label=SHELL_IN_WORKTREE,
                menu="Step",
                group="agent",
                order=35,
                tip="A terminal of your own where the step's work is — not an agent — to run"
                " something there",
                state=self._can_open_shell,
                run=self._open_shell,
            )
        )
        # What QSettings kept before the profiles moved to the config directory, taken over
        # once; then, once per user and machine, every harness in every terminal worth
        # naming, so the child menu offers the combinations before anybody builds one.
        adopt(
            get_global(MODULE_ID, "profiles"),
            bool(get_global(MODULE_ID, "profiles_seeded")),
            str(get_global(MODULE_ID, "agent_command", "")),
            str(get_global(MODULE_ID, "launch_command", "")),
        )
        seed_profiles(deps.harnesses)
        if (unreadable := problem()) and deps.notices is not None:
            deps.notices.show_notice(
                Notice(PROFILES_NOTICE, f"Agent profiles: {unreadable}", tone="warn")
            )

    # -- running -------------------------------------------------------------------------------

    def _chosen(self, context: Context) -> list[Step]:
        """The steps Run Agent is about — what Delete acts on, read the same way."""
        library = self._deps.library
        return [library.step(step_id) for step_id in chosen_steps(context, library)]

    def _can_run(self, context: Context, profile: Profile | None = None) -> ActionState:
        """Present whenever a step is; greyed with the reason when a precondition is not.

        The idiom from `CLAUDE.md`: a disabled entry carries what to do about it. The same
        state drives the menu bar, the palette and the Agent tab's button.

        **The verb acts on the whole selection, and every chosen step must be launchable.**
        Running the subset that qualifies would launch fewer agents than were asked for and
        say nothing, so one step's refusal greys the verb for all of them and the label
        names which step and why. Past the *Settings ▸ Agent profiles* limit it is the count itself
        that refuses, and it refuses **before** the per-step questions: a lasso is one flick
        of the wrist and can hold the whole graph, and a deskful of terminals — or a walk
        over every step in it — is not what that flick meant.
        """
        chosen = self._chosen(context)
        if not chosen:
            return DISABLED
        deps = self._deps
        count = len(chosen)
        verb = "Run Agent" if count == 1 else f"Run {count} Agents"
        limit = max_agents()
        if count > limit:
            return ActionState(
                enabled=False,
                label=f"{verb} — at most {limit} at a time (Settings ▸ Agent profiles)",
            )
        # The profile's terminal is one probe, asked before any step is: a multiplexer
        # that is not running refuses the whole gesture the same way the count does.
        if refusal := launcher.template_refusal(launch_command(profile)):
            return ActionState(enabled=False, label=f"{verb} — {refusal}")
        # Where a shell can open is the *project's* fact and asking git for it is not free,
        # so it is asked once per project the selection touches rather than once per step.
        by_project: dict[str, str] = {}
        clones: list[str] = []
        for step in chosen:
            facts = deps.facts_for(step.id)
            # A code repository nobody checked out here is cloned first, not refused: the
            # policy decides where it lands, never whether the verb runs.
            unplaced = launch.unplaced(facts, step)
            if unplaced and unplaced not in clones:
                clones.append(unplaced)
            branches = deps.branch_plan(deps.library, step, facts)
            reason = launch.refusal(
                deps.library, step, deps.files, facts, branches, deps.clock.today(), by_project
            )
            if reason:
                named = reason if count == 1 else f"“{_titled(step)}”: {reason}"
                return ActionState(enabled=False, label=f"{verb} — {named}")
        if clones:
            named = ", ".join(remote_label(url) for url in clones)
            amp = "Run &Agent…" if count == 1 else f"Run {count} &Agents…"
            return ActionState(label=f"{amp} — clones {named} first")
        return ENABLED if count == 1 else ActionState(label=f"Run {count} &Agents…")

    def _can_preview(self, context: Context) -> ActionState:
        """A preview needs an agent step: with the aspect off there is no briefing to see."""
        step = focused_step(context, self._deps.library)
        if step is None:
            return DISABLED
        if not enabled(step):
            return ActionState(
                enabled=False,
                label="Preview Agent Prompt — mark the step as an agent step first",
            )
        return ENABLED

    def assembled(self, step: Step) -> AssembledPrompt:
        """The step's briefing, opening with the preflight for the run the step gets — a
        worktree unless it opted out or is a step that takes none."""
        deps = self._deps
        facts = deps.facts_for(step.id)
        return launch.briefing(
            deps.library, step, self._briefed, facts, deps.branch_plan(deps.library, step, facts)
        )

    @property
    def _briefed(self) -> launch.Briefed:
        deps = self._deps
        return launch.Briefed(deps.files, deps.read_asset, deps.location_roles)

    def _run(self, context: Context, profile: Profile | None = None) -> None:
        """One agent per chosen step, asked about once and launched in order — through
        ``profile``, the default one when none is named.

        The graph gate is asked **once for the whole gesture**: a box per step would make
        four selected steps four questions about one decision. The loop stops at the first
        step no terminal opened for — the template that refused one will refuse the rest,
        and the fallback dialog is already holding that step's prompt. With a multiplexer
        in the profile every step's shell lands in it, one pane each.
        """
        deps = self._deps
        chosen = self._chosen(context)
        if not chosen or len(chosen) > max_agents():
            return  # The state gate already prevents this; stay honest.
        waiting = [(step, unfinished) for step in chosen if (unfinished := self._unfinished(step))]
        if waiting and not self._confirm_unfinished(waiting, count=len(chosen)):
            return
        profile = profile or default_profile()
        clones = list(dict.fromkeys(launch.unplaced(deps.facts_for(s.id), s) for s in chosen))
        clones = [url for url in clones if url]
        if clones:
            # Cloned first, on a task; the launches follow on the GUI thread once every
            # repository has landed, reading the facts afresh — the checkout is recorded.
            deps.status.show_status(
                f"Cloning {', '.join(remote_label(url) for url in clones)} before the agent…", 0
            )

            def cloned(_landed: dict[str, Path], error: str) -> None:
                if error:
                    deps.status.show_status(f"No agent launched — could not clone {error}", 8000)
                    return
                self._launch_all(chosen, profile)

            deps.ensure_checkouts(clones, cloned)
            return
        self._launch_all(chosen, profile)

    def _launch_all(self, chosen: Sequence[Step], profile: Profile) -> None:
        """One agent per step, in order, in the order ``launch.py`` gives both surfaces.

        Each step's launch lock is taken first and held until its run started, and a step
        whose headless run is not over is refused — both as ``agent run`` does. The
        worktrees are then prepared — on a task, since git fetches — from plain values read
        here, and each step is launched on the GUI thread, stopping at the first that did
        not start: a worktree git refused, or a step that changed while it was prepared,
        says why in the status bar; a terminal that did not open hands the prompt over in
        the fallback dialog."""
        deps = self._deps
        held = ExitStack()
        jobs: list[_Job] = []
        for step in chosen:
            project_id = deps.library.project_of(step.id).id
            refused = ""
            try:
                held.enter_context(supervisor.launching(project_id, step.id))
            except BlockingIOError:
                refused = "it is being launched right now"
            project_dir = deps.project_dir(step.id)
            if not refused:
                refused = self._unowned(project_dir, step) or launch.stop_fenced(
                    project_dir, step.id
                )
            if not refused and (live := launch.unfinished_run(project_dir, step.id)):
                refused = f"its headless run {live} is not over — resume it instead"
            if refused:
                held.close()
                deps.status.show_status(f"No agent launched — “{_titled(step)}”: {refused}", 8000)
                return
            facts = deps.facts_for(step.id)
            branches = deps.branch_plan(deps.library, step, facts)
            jobs.append(_Job(step.id, facts, branches, *launch.worktree_of(step, facts)))
        placed: dict[StepId, Path | str] = {}

        def body() -> None:  # Worker thread: paths and branch names, never the model.
            for job in jobs:
                try:
                    placed[job.step] = launch.place(job.checkout, job.name, job.branches)
                except where.WorktreeError as error:
                    placed[job.step] = str(error)

        def go() -> None:
            with held:
                self._launch_placed(jobs, placed, profile)

        if deps.tasks is None or not any(job.name for job in jobs):
            body()
            go()
            return
        runner = self._preparing = self._preparing or TaskRunner(deps.tasks, deps.parent)

        def done(busy: bool) -> None:
            if not busy:
                runner.busy_changed.disconnect(done)
                go()

        runner.busy_changed.connect(done)
        count = len(chosen)
        label = "Preparing the worktree" if count == 1 else f"Preparing {count} worktrees"
        if not runner.run(label, body, key="agent.worktrees"):
            runner.busy_changed.disconnect(done)
            held.close()
            deps.status.show_status("No agent launched — still preparing the last one", 6000)
            return
        deps.status.show_status(f"{label}…", 0)

    @staticmethod
    def _unowned(project_dir: Path | None, step: Step) -> str:
        """Why a person may not launch the step: another squad's claim holds it — or ""."""
        try:
            launch.claim_for(project_dir, step.id)
        except ValueError as error:
            return str(error)
        return ""

    def _launch_placed(
        self, jobs: Sequence["_Job"], placed: Mapping[StepId, Path | str], profile: Profile
    ) -> None:
        deps = self._deps
        claim = start_in_progress()
        launched = claimed = 0
        first = ""
        for job in jobs:
            if not deps.library.has(job.step):
                continue  # Deleted while its worktree was being prepared.
            step = deps.library.step(job.step)
            workdir = placed.get(job.step, "its worktree was not prepared")
            if isinstance(workdir, str):
                deps.status.show_status(f"No agent launched on “{_titled(step)}” — {workdir}", 8000)
                break
            if job.changed(deps.facts_for(step.id), deps.branch_plan, deps.library, step):
                deps.status.show_status(
                    f"No agent launched on “{_titled(step)}” — it was renamed or moved to"
                    " another branch while its worktree was prepared; run it again",
                    8000,
                )
                break
            started, why = self._run_on(step, workdir, job.facts, job.branches, profile, claim)
            if started is None:
                deps.status.show_status(f"No agent launched on “{_titled(step)}” — {why}", 8000)
                break
            if why:
                # Nothing started, the record and the claim are taken back: the fallback
                # hands over the prompt.
                PromptFallbackDialog(started.text, str(started.prompt_file), deps.parent).exec()
                break
            launched += 1
            first = first or _titled(step)
            claimed += claim and stored(step) is Status.IN_PROGRESS
        if launched == 1:
            note = " — marked in progress" if claimed else ""
            deps.status.show_status(f"Agent launched on “{first}”{note}", 4000)
        elif launched > 1:
            note = f", {claimed} marked in progress" if claimed else ""
            deps.status.show_status(f"{launched} agents launched{note}", 4000)

    def _unfinished(self, step: Step) -> list[Step]:
        """The step's prerequisites it still waits on — what the graph gate asks about."""
        return launch.waiting_on(self._deps.library, step, self._deps.clock.today())

    def _status_of(self, step: Step) -> Reading:
        """What a step's status claims today — a wait reads done once it is over."""
        return status_on(self._deps.library, self._deps.clock.today())(step)

    def _run_on(
        self,
        step: Step,
        workdir: Path,
        facts: RepositoryFacts,
        branches: BranchPlan,
        profile: Profile,
        claim: bool,
    ) -> tuple[launch.Prepared | None, str]:
        """Launch the agent on one step in a terminal: its record, then its claim — off the
        undo stack, since the agent it records cannot be undone — saved, then the start as
        the follow-up. What was prepared and why nothing started ("" when it did); nothing
        prepared when the claim could not be saved. A start that fails takes the record and
        the claim back. The stamp and the watch are the run tracker's once a shell exists."""
        deps = self._deps
        with current().span("action", "agent.launch", step=key_of(step)) as span:
            prepared = launch.prepare_run(
                deps.library,
                step,
                self._briefed,
                workdir=workdir,
                facts=facts,
                branches=branches,
                project_dir=deps.project_dir(step.id),
                profile=profile,
                harnesses=deps.harnesses,
                mode=launch.TERMINAL,
            )
            span.detail["prompt_chars"] = len(prepared.text)
            # Ownership again, under the launch lock: a squad may have taken the step while
            # its worktree was prepared. Said as a refusal, never as a terminal that failed.
            if moved := launch.claim_moved(prepared):
                prepared.discard()
                span.detail["refused"] = "claimed"
                return None, moved
            before = step.module_data.get(STATUS_MODULE_ID)
            change = workflows.run_agent(step, today=deps.clock.today())
            command = change.command if claim else None
            if command is not None:
                command.redo(deps.library)
            # Saved every time, not only when this launch made the claim: a step that already
            # read in progress may hold a claim nobody has saved yet.
            if not deps.flush():
                if command is not None:
                    self._withdraw(step, before)
                prepared.discard()
                span.detail["refused"] = "unsaved"
                return None, "its claim could not be saved — save the plan, then run it again"
            if why := launch.start_run(prepared, deps.harnesses):
                span.detail["refused"] = why
                if command is not None:
                    self._withdraw(step, before)
                    deps.flush()
                return prepared, why
            if prepared.files is not None:
                deps.record_launch(step.id, prepared.files, prepared.record.harness)
        return prepared, ""

    def _withdraw(self, step: Step, before: object) -> None:
        back = workflows.withdraw(step, before if isinstance(before, dict) else None)
        if back.command is not None:
            back.command.redo(self._deps.library)

    def _fill_profiles(self, menu: QMenu) -> None:
        """Step ▸ Run Agent: the profiles over the step the context names — the same child
        menu the Step statuses tab's Run Agent arrow drops down."""
        self._fill_with(menu, self._can_run, self._run)

    def _fill_open_profiles(self, menu: QMenu) -> None:
        """Project ▸ Open Agent in Code: the same profiles over the project."""
        self._fill_with(menu, self._can_open, self._open)

    def _fill_with(
        self,
        menu: QMenu,
        state_of: Callable[[Context, Profile], ActionState],
        run: Callable[[Context, Profile], None],
    ) -> None:
        """One entry per launch profile, the default first and marked, each greyed with its
        own reason — a profile's terminal may be missing where another's is not — and
        rebuilt every time the menu opens, so a profile added in Settings is offered at
        once. Under a rule, the way to Settings.

        Both agent child menus fill through here: *Run Agent* and *Open Agent in Code* offer
        the one list of profiles and differ only in what each entry asks and does.
        """
        deps = self._deps
        context = deps.context.current()
        for index, profile in enumerate(read_profiles()):
            state = state_of(context, profile)
            name = f"{profile.name} (default)" if index == 0 else profile.name
            reason = ""
            if not state.enabled and state.label:
                reason = state.label.partition(" — ")[2]
            entry = menu.addAction(f"{name} — {reason}" if reason else name)
            entry.setEnabled(state.enabled)
            entry.triggered.connect(
                lambda _checked=False, p=profile: run(deps.context.current(), p)
            )
        menu.addSeparator()
        append_action(menu, deps.actions, deps.context, "agent.profiles")

    # -- a shell of one's own ------------------------------------------------------------------

    def _shell_place(self, step: Step) -> tuple[Path | None, str]:
        """Where a plain shell for ``step`` opens — its worktree, or the checkout for a step
        that works in place — or why nowhere can: the default profile's terminal first, as
        Run Agent asks it, then the checkout, then the worktree Run Agent would have made.

        The worktree is found by the same name the wrapper script gives it (``run_name_of``),
        so a step renamed since its agent ran is looked for under its new name."""
        deps = self._deps
        if refusal := launcher.template_refusal(launch_command()):
            return None, refusal
        facts = deps.facts_for(step.id)
        if refusal := launch.workdir_refusal(facts, step):
            return None, refusal
        workdir = where.workdir(facts, step)
        if workdir is None:
            return None, "the project's code is not on this machine — Project ▸ Settings…"
        if not uses_worktree(step):
            return workdir.expanduser(), ""
        tree = where.worktree_path(workdir.expanduser(), where.run_name_of(step))
        return (tree, "") if tree.is_dir() else (None, NO_WORKTREE)

    def _can_open_shell(self, context: Context) -> ActionState:
        step = focused_step(context, self._deps.library)
        if step is None:
            return DISABLED
        label = SHELL_IN_WORKTREE if uses_worktree(step) else SHELL_IN_CHECKOUT
        _directory, refusal = self._shell_place(step)
        plain = label.replace("&", "")
        if refusal:
            return ActionState(enabled=False, label=f"{plain} — {refusal}")
        return ActionState(label=label)

    def _open_shell(self, context: Context) -> None:
        """Open the default profile's terminal on a plain shell where the step's work is.
        No run is recorded and nothing is claimed; a terminal that does not open is a
        notice, since there is no prompt to hand over instead."""
        deps = self._deps
        step = focused_step(context, deps.library)
        if step is None:
            return
        directory, _refusal = self._shell_place(step)
        if directory is None:
            return  # The state gate already says why.
        subject = f"{key_of(step)} {step.title}".strip()
        files = launcher.shell_script(
            directory,
            _window_title(subject, "shell"),
            project_id=deps.library.project_of(step.id).id,
        )
        command = launcher.resolve_command(launch_command(), files, directory)
        if command is None or launcher.spawn(command, directory, harnesses=deps.harnesses):
            notice(
                deps.parent,
                "Open Terminal",
                f"No terminal opened in {directory} — check the default profile's terminal"
                " in Settings ▸ Agent profiles.",
            )
            return
        deps.status.show_status(f"Terminal opened in {directory}", 4000)

    def _confirm_unfinished(
        self, waiting: Sequence[tuple[Step, Sequence[Step]]], *, count: int
    ) -> bool:
        """The graph gates launching: an agent briefed on a step whose prerequisites are
        not done works without what they were to produce. Say which, and ask — the
        person may know the work landed without the status being recorded.

        One dialog for the whole gesture, so several chosen steps name their own
        unfinished work under their own heading and Cancel means *none of them*;
        ``count`` is every step the gesture would launch, which is what its title says."""
        deps = self._deps

        def listed(unfinished: Sequence[Step]) -> list[str]:
            return [f"• {_titled(r)} — {phrase(self._status_of(r))}" for r in unfinished]

        if len(waiting) == 1:
            step, unfinished = waiting[0]
            how_many = f"{len(unfinished)} step{'s' if len(unfinished) != 1 else ''}"
            lead = f"“{_titled(step)}” waits on {how_many} not done yet."
            groups = [("", listed(unfinished))]
            closing = "The agent would start without what those steps produce. Run it anyway?"
        else:
            lead = f"{len(waiting)} of the chosen steps wait on work not done yet."
            groups = [
                (f"{_titled(step)} waits on", listed(unfinished)) for step, unfinished in waiting
            ]
            closing = "The agents would start without what those steps produce. Run them anyway?"
        dialog = RunAnywayDialog(count, lead, groups, closing, deps.parent)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        dialog.deleteLater()
        return accepted

    # -- opening an agent with nothing to do ---------------------------------------------------

    def _can_open(self, context: Context, profile: Profile | None = None) -> ActionState:
        """Whether an agent can be opened in this project's code, greyed with the reason.

        Run Agent's questions without the step's: where a shell opens, whether the profile's
        terminal is there, and whether this build knows how to open that agent with nothing
        to do. No graph gate and no limit — one terminal, and nothing is claimed in progress,
        because nobody has been told to do anything yet. The cheap questions come first: a
        project's repositories cost git, and a missing terminal refuses either way.
        """
        deps = self._deps
        project_id = context.focus_entity("project")
        if not project_id or not deps.library.has(project_id):
            return ActionState(enabled=False, label=f"{OPEN_MENU_TITLE} — no project is open")
        if refusal := launcher.template_refusal(launch_command(profile)):
            return ActionState(enabled=False, label=f"{OPEN_MENU_TITLE} — {refusal}")
        if not self._open_command(profile):
            return ActionState(
                enabled=False,
                label=f"{OPEN_MENU_TITLE} — this profile's agent command is a custom one,"
                " and nothing here knows how to open it with no briefing",
            )
        facts = deps.facts_for(project_id)
        if unplaced := launch.unplaced(facts):
            return ActionState(label=f"{OPEN_MENU_TITLE} — clones {remote_label(unplaced)} first")
        if refusal := launch.workdir_refusal(facts):
            return ActionState(enabled=False, label=f"{OPEN_MENU_TITLE} — {refusal}")
        return ENABLED

    def _open(self, context: Context, profile: Profile | None = None) -> None:
        """Open the profile's terminal where the project's code is, with the agent briefed
        on nothing: no prompt, no worktree, no run recorded and no step claimed.

        There is nothing to hand over when no terminal opens, so the refusal is a notice
        rather than the prompt fallback every briefed launch ends in.
        """
        deps = self._deps
        project_id = context.focus_entity("project")
        if not project_id or not deps.library.has(project_id):
            return
        profile = profile or default_profile()
        if not self._open_command(profile):
            return  # The state gate already prevents this; stay honest.
        title = deps.library.project(project_id).title or "Untitled project"
        if unplaced := launch.unplaced(deps.facts_for(project_id)):
            deps.status.show_status(f"Cloning {remote_label(unplaced)} before the agent…", 0)

            def cloned(_landed: dict[str, Path], error: str) -> None:
                if error:
                    deps.status.show_status(f"No agent opened — could not clone {error}", 8000)
                    return
                self._open_in(project_id, profile, title)

            deps.ensure_checkouts([unplaced], cloned)
            return
        self._open_in(project_id, profile, title)

    def _open_in(self, project_id: NodeId, profile: Profile, title: str) -> None:
        deps = self._deps
        spawned, _files = self._launch(
            "",
            launcher.new_run_dir(),
            where.workdir(deps.facts_for(project_id)),
            profile,
            project_id=project_id,
            subject=title,
        )
        if spawned:
            deps.status.show_status(f"Agent opened in “{title}”", 4000)
        else:
            notice(
                deps.parent,
                OPEN_MENU_TITLE,
                f"No terminal opened for “{title}” — check this profile's terminal in"
                " Settings ▸ Agent profiles.",
            )

    def _open_command(self, profile: Profile | None) -> str:
        """How this profile's agent opens with nothing to do; "" when nothing here knows."""
        deps = self._deps
        return launcher.open_command(agent_command(deps.harnesses, profile), deps.harnesses)

    def _launch(
        self,
        text: str,
        run_dir: Path,
        workdir: Path | None,
        profile: Profile,
        *,
        project_id: NodeId | None,
        subject: str,
        key: str = "",
        note: str = "",
        step_id: StepId | None = None,
    ) -> tuple[bool, launcher.LaunchFiles]:
        """Open the profile's terminal on ``text`` in ``workdir``; the run is recorded only
        when a shell was actually spawned, and only when it is *a step's*.

        ``subject`` is what the terminal's window is named after — a step's key and title,
        or the project a plan-wide run is about — ``note`` what this run is *for* when it
        is not the step's work, and ``key`` what the journal records it by. Every prompt
        this module launches comes through here, so a change to how a terminal opens is
        made once.

        **A run with no step is not recorded.** The tracker keys a run by the step it is
        working on: a plan-wide fix has none, so it gets no chip, no end-of-shell watch
        and no usage row. That is a gap said out loud rather than a zero invented.

        **A launch with no ``text`` opens the agent bare.** Nothing is written to hand over,
        and the command is the harness's own ``open_command`` rather than the briefed one,
        whose flags — an opening line, a permission mode — are all about a briefing that
        does not exist.

        What the status bar says, and whether the step is claimed in progress, is the
        **caller's**: one launch names its step, a run over a selection counts what opened
        and claims each step as it goes, and neither is true of the other."""
        deps = self._deps
        workdir = (workdir or Path()).expanduser()
        command_text = agent_command(deps.harnesses, profile)
        if not text:
            command_text = launcher.open_command(command_text, deps.harnesses)
        # A launch is a span of its own under the action's, not a detail on it: one gesture
        # opens a shell per chosen step, so three launches are three sizes and could never
        # be one key on the parent — and a verb cannot reach the enclosing span anyway,
        # since the journal hands out copies of what is open.
        # A run with no step is journalled by the plan it is about: the detail key says
        # which of the two a reader is looking at, rather than one key meaning both.
        named = {"step": key} if step_id is not None else {"plan": subject}
        with current().span("action", "agent.launch", **named) as span:
            prepared = launcher.prepare(
                text,
                workdir,
                agent_command=command_text,
                directory=run_dir,
                step_title=_window_title(subject, note),
                project_id=project_id or "",
                harnesses=deps.harnesses,
            )
            span.detail["prompt_chars"] = prepared.prompt_chars
            command = None
            if workdir.is_dir():
                command = launcher.resolve_command(launch_command(profile), prepared, workdir)
            if command is None:
                span.detail["refused"] = "no terminal"
                return False, prepared
            if launcher.spawn(command, workdir, harnesses=deps.harnesses):
                span.detail["refused"] = "no shell"
                return False, prepared  # A multiplexer that refused is no shell at all.
            harness = launcher.harness_of(command_text, deps.harnesses)
            if step_id is not None:
                deps.record_launch(step_id, prepared, harness.id if harness else "")
            return True, prepared

    # -- fixing what is wrong with the plan ----------------------------------------------------

    def plan_profiles(self) -> list[tuple[str, str]]:
        """Every launch profile, and why it cannot open a terminal here ("" when it can).

        For a run in a plan repository rather than on a step — fixing problems, reconciling
        a save. Plain data, so a panel can list and grey them without learning what a
        profile is — the default first, as everywhere this list is shown. Nothing is shared
        to refuse on: one agent, one repository, and no step to be wrong about.
        """
        return _profiles_refused("")

    def fix_problems(
        self, project_id: NodeId, problems: Sequence[tuple[str, str, str]], profile_name: str
    ) -> bool:
        """Launch the named profile on what lint says is wrong with a plan.

        **No worktree, and the shell opens in the plan's own repository**: this agent
        changes the plan and not the code, so a checkout of the code would be the wrong
        room to stand in — the conflict hand-over's reasoning, for the same reason. The
        run has no step, so nothing is recorded and nothing is claimed in progress.
        """
        deps = self._deps
        profile = profile_named(profile_name) or default_profile()
        project = deps.library.project(project_id)
        title = project.title or "Untitled project"
        facts = deps.facts_for(project_id)
        text = problems_prompt(title, str(facts.plan_root or ""), problems)
        spawned, prepared = self._launch(
            text,
            launcher.new_run_dir(),
            facts.plan_root,
            profile,
            project_id=project_id,
            subject=f"Problems — {title}",
        )
        if spawned:
            deps.status.show_status(f"Agent launched on {len(problems)} problems", 4000)
        else:
            PromptFallbackDialog(
                text, str(prepared.prompt_file), deps.parent, title="Fix Problems"
            ).exec()
        return spawned

    def reconcile_remote(self, repo_root: Path, branch: str, profile_name: str) -> bool:
        """Launch the named profile to rebase a plan repository's refused save and push it.

        Like :meth:`fix_problems`, no worktree and the shell in the plan repository — this
        one named by the save that failed, since a repository may hold several projects and
        the run is about none of them in particular.
        """
        deps = self._deps
        profile = profile_named(profile_name) or default_profile()
        text = reconcile_prompt(str(repo_root), branch)
        spawned, prepared = self._launch(
            text,
            launcher.new_run_dir(),
            repo_root,
            profile,
            project_id=None,
            subject=f"Reconcile — {repo_root.name}",
        )
        if spawned:
            deps.status.show_status(f"Agent launched to reconcile {repo_root.name}", 4000)
        else:
            PromptFallbackDialog(
                text, str(prepared.prompt_file), deps.parent, title="Reconcile with Agent"
            ).exec()
        return spawned

    # -- reconciling a conflict ----------------------------------------------------------------

    def conflict_refusal(self, step_id: StepId) -> str:
        """Why a conflict on ``step_id`` cannot be handed to an agent; "" when it can."""
        if not self._deps.library.has(step_id):
            return "the step is gone"
        if self._deps.facts_for(step_id).plan_root is None:
            return "the plan's folder is not in a git repository"
        return ""

    def hand_conflicts(self, step_id: StepId, conflicts: Sequence[Conflict]) -> bool:
        """Launch the agent on the entries two writers changed at once; True when a shell
        was spawned.

        The window's version of every entry is written beside the prompt first, because the
        window yields to the plan on disk once the agent is on its way — the run directory
        is the one place the unsaved version survives. No worktree, and the shell opens in
        the **plan's** repository rather than the code's: the agent must write to the plan
        the window is showing, or its merge lands somewhere nobody is looking.
        """
        deps = self._deps
        library = deps.library
        step = library.step(step_id)
        facts = deps.facts_for(step_id)
        run_dir = launcher.new_run_dir()
        entries: list[tuple[str, str]] = []
        for conflict in conflicts:
            if not library.has(conflict.node_id):
                continue
            ours = run_dir / "mine" / conflict.path
            ours.parent.mkdir(parents=True, exist_ok=True)
            mine = _our_version(library.node(conflict.node_id), conflict.entry)
            ours.write_text(mine, encoding="utf-8", newline="\n")
            entries.append((conflict.path, str(ours)))
        text = conflict_prompt(
            step_title=_titled(step),
            project_title=library.project_of(step_id).title or "Untitled project",
            preamble=preamble(step, False, facts, DEFAULT_BRANCHES, deps.location_roles),
            entries=entries,
        )
        spawned, prepared = self._launch(
            text,
            run_dir,
            facts.plan_root,
            default_profile(),
            project_id=library.project_of(step_id).id,
            subject=f"{key_of(step)} {step.title}".strip(),
            key=key_of(step),
            step_id=step.id,
        )
        if spawned:
            deps.status.show_status(f"Agent launched on “{_titled(step)}”", 4000)
        else:
            PromptFallbackDialog(
                text, str(prepared.prompt_file), deps.parent, title="Resolve Conflict"
            ).exec()
        return spawned

    # -- compiling a collector's documentation ------------------------------------------------

    def compile_profiles(self, step_ids: Sequence[StepId]) -> list[tuple[str, str]]:
        """Every launch profile, with why it cannot compile *these* collectors right now —
        "" when it can. The default profile is first, as everywhere else.

        The docs module renders this: the strip's verb reads the first entry's reason and its
        dropdown greys each profile with its own. The questions are the ones ``_can_run``
        asks, minus the step ones — an agent mark and a briefing are what a *work* run needs,
        and a collector's document is neither.
        """
        deps = self._deps
        count = len(step_ids)
        limit = max_agents()
        shared = ""
        if not count:
            shared = "nothing to compile"
        elif count > limit:
            shared = f"at most {limit} agents at a time (Settings ▸ Agent profiles)"
        else:
            by_project: dict[str, str] = {}
            for step_id in step_ids:
                if not deps.library.has(step_id):
                    shared = "the step is gone"
                    break
                project_id = deps.library.project_of(step_id).id
                if project_id not in by_project:
                    by_project[project_id] = launch.workdir_refusal(deps.facts_for(step_id))
                if by_project[project_id]:
                    shared = by_project[project_id]
                    break
        return _profiles_refused(shared)

    def compile_documentation(
        self, requests: Sequence[tuple[StepId, str]], profile_name: str = ""
    ) -> list[tuple[StepId, str]]:
        """Launch one agent per (collector, briefing); the launches that opened a shell, each
        with the words naming what is working on it.

        ``requests`` carries the *body* of each briefing — the docs module's own words — and
        this wraps it with the header and the preflight every hand-over gets. The shell opens
        where a work run's would, in the code checkout, because a document about the product
        is written beside it; with **no worktree**, since a compile changes no code, and with
        **no claim on the step's status**: an agent writing a feature's documentation is not
        doing that feature's work.

        The returned words are how the docs module attributes a document without guessing.
        Reading the step's newest run back instead would credit a feature's document to
        whichever agent happened to be working on that feature.
        """
        deps = self._deps
        profile = (
            next((one for one in read_profiles() if one.name == profile_name), None)
            or default_profile()
        )
        opened: list[tuple[StepId, str]] = []
        for step_id, body in requests:
            if not deps.library.has(step_id):
                continue
            step = deps.library.step(step_id)
            project = deps.library.project_of(step_id)
            text = handover_prompt(
                f"# Documentation: {_titled(step)}",
                project.title or "Untitled project",
                preamble(
                    step, False, deps.facts_for(step_id), DEFAULT_BRANCHES, deps.location_roles
                ),
                body,
            )
            run_dir = launcher.new_run_dir()
            spawned, prepared = self._launch(
                text,
                run_dir,
                where.workdir(deps.facts_for(step_id)),
                profile,
                project_id=project.id,
                subject=f"{key_of(step)} {step.title}".strip(),
                key=key_of(step),
                note="documentation",
                step_id=step.id,
            )
            if not spawned:
                # The template that refused one will refuse the rest, and the fallback is
                # already holding this briefing — the same stop `_run` makes.
                PromptFallbackDialog(
                    text, str(prepared.prompt_file), deps.parent, title="Compile Documentation"
                ).exec()
                break
            opened.append((step_id, _run_words(deps.harnesses, profile, prepared)))
        if len(opened) == 1:
            deps.status.show_status(
                f"Agent compiling “{_titled(deps.library.step(opened[0][0]))}”", 4000
            )
        elif len(opened) > 1:
            deps.status.show_status(f"{len(opened)} agents compiling documentation", 4000)
        return opened

    def _preview(self, context: Context) -> None:
        step = focused_step(context, self._deps.library)
        if step is None:
            return
        assembled = self.assembled(step)
        PromptFallbackDialog(
            assembled.text,
            "",
            self._deps.parent,
            note_text=PREVIEW_NOTE,
            title="Prompt Preview",
        ).exec()
