"""The agent-instruction aspect, in the running application: the Agent tab, the Agent tab
of Project ▸ Settings…, and Run Agent.

The tab is the writing half — :class:`AgentSection` stacks the briefing's three parts
(the project's standing instruction, what the project's notes hold for it, this step's own)
and ``ModuleTextField`` does the binding work. The project's own tab is the same field in
the Project dialog, registered into ``deps.project_settings`` like any project-level section.

Run Agent is the reading half: assemble the step's briefing (both instructions, plus
whatever context the composition root hands in — this module never learns what a note
is), stage its attached files beside the prompt in a per-run temp directory, and open a
terminal on it. The terminal is a **peer process the user owns**, deliberately not a
TaskRunner task — see ``launcher.py``. Preview Prompt and the no-terminal fallback show
the same assembled text, because the prompt is the library and the terminal was only one
way to hand it over.

**And an agent may be opened with nothing to do.** *Project ▸ Open Agent in Code* runs
the same launch profiles in the same terminals, in the project's code, with no briefing
and none of the modes a briefed run picks — the harness's own ``open_command``. It is
what the planning *before* the plan needs: a spec has been imported, there are no steps
to brief yet, and the agent's first instruction is the one the person types.

**It runs one agent per chosen step, up to a limit.** The verb reads the selection the way
Delete does, so lassoing three agent steps is *Run 3 Agents…* and one gesture; past
*Settings ▸ Agent profiles*'s limit (four by default) the count itself is the refusal, greyed with
its reason like any other precondition. Each step whose shell opened is also claimed
*in progress* — through ``deps.mark_started``, unless the person switched that off on the
settings page — since the agent's own first report may be minutes away.

**And the window launches what the plan made due, with nobody clicking** — when the person
turned that on (``auto_launch.py``). :meth:`launch_due` is Run Agent for one step with every
question a person answers taken out: no graph gate to confirm (a due step waits on nothing),
no clone, no prompt fallback — a refusal is a sentence for the status bar — and the claim
always made, whatever *On launch* says.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtWidgets import QDialog, QMenu, QWidget

from dplanner.core.clock import Clock
from dplanner.core.storage.locations import remote_label
from dplanner.core.telemetry import current
from dplanner.domain.agents import AgentHarness
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Node, NodeId, Step, StepId
from dplanner.domain.progression import DONE, UNKNOWN, outstanding, phrase
from dplanner.domain.repositories import UNSET, RepositoryFacts
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
from dplanner.framework.aspect_toggle import aspect_toggle
from dplanner.framework.context import Context, ContextService
from dplanner.framework.debounce import DebounceService
from dplanner.framework.dictation import DictationService
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.mime_files import Payload
from dplanner.framework.settings_registry import (
    SettingsSection,
    SettingsSectionRegistry,
)
from dplanner.framework.step_selection import chosen_steps, focused_step
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import notice
from dplanner.framework.window import NoticeHost, StatusHost
from dplanner.framework.window_watch import WatchableRepository
from dplanner.modules.step_agent_instruction import launcher
from dplanner.modules.step_agent_instruction.aspect import (
    DATA_FORMAT,
    MODULE_ID,
    SPEC,
    asset_paths,
    enabled,
    read_project,
    uses_worktree,
    with_worktree,
    workplace,
    write_state,
)
from dplanner.modules.step_agent_instruction.auto_launch import AutoLauncher, Due, LaunchLock
from dplanner.modules.step_agent_instruction.profiles import (
    Profile,
    default_profile,
    profile_named,
    read_profiles,
    seed_profiles,
)
from dplanner.modules.step_agent_instruction.prompt import (
    EMPTY_BRIEFING,
    AssembledPrompt,
    Briefing,
    PromptPart,
    assemble,
    conflict_prompt,
    handover_prompt,
    problems_prompt,
    reconcile_prompt,
)
from dplanner.modules.step_agent_instruction.run_dialog import PromptFallbackDialog, RunAnywayDialog
from dplanner.modules.step_agent_instruction.section import (
    AgentSection,
    ProjectInstructionSection,
)
from dplanner.modules.step_agent_instruction.settings_page import (
    agent_command,
    build_page,
    launch_command,
    max_agents,
    start_in_progress,
)
from dplanner.theme.icons import spark_icon, typewriter_icon

PLACEHOLDER = "How to carry this step out: which files, which conventions, what done means."

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

PREVIEW_NOTE = (
    "This is the exact briefing Run Agent will launch with. File paths are relative to"
    " the workspace here; at launch the files are copied beside prompt.md and referenced"
    " by their staged paths."
)


def _no_record(_step_id: StepId, _files: launcher.LaunchFiles, _harness: str) -> None:
    return None


def _no_start(_step_id: StepId) -> bool:
    """A build with nobody to tell that work started: nothing is claimed."""
    return False


def _no_clone(_repositories: Sequence[str], done: Callable[[dict[str, Path], str], None]) -> None:
    """A build with nothing to clone with: the verb is refused where it would have cloned."""
    done({}, "nothing here can clone a repository")


def _all_done(_step: Step) -> str:
    """A build with nobody to ask about status: nothing is unfinished, nothing warns."""
    return DONE


def _unplaced(facts: RepositoryFacts, step: Step | None = None) -> str:
    """The code repository this agent would work in that this machine has no checkout of
    — what Run Agent clones first — or "" when it is placed or there is none."""
    placement = launcher.code_placement(facts, step)
    if placement is not None and placement.root is None:
        return placement.location.repository
    return ""


def _workdir_refusal(facts: RepositoryFacts, step: Step | None = None) -> str:
    """Why no shell can open where this project's agent would work; "" when one can. A
    repository not checked out here is a refusal only for a verb that cannot clone — Run
    Agent asks :func:`_unplaced` first and clones."""
    placement = launcher.code_placement(facts, step)
    if placement is not None:
        label = placement.location.repository_label
        if not placement.here:
            return f"{label} is not checked out on this machine — Project ▸ Settings…"
        assert placement.root is not None
        if not placement.root.expanduser().is_dir():
            return f"the checkout of {label} is gone from {placement.root} — Project ▸ Settings…"
        return ""
    if facts.plan_root is None:
        return "the project's folder is not in a git repository"
    if facts.state == UNSET:
        return "no code repository is recorded — Project ▸ Settings…"
    return ""


def _no_key(_step: Step) -> str:
    return ""


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


def no_agent(kind: str) -> str:
    """Why a step nobody works — ``kind`` is what it is called, "a wait" — has no run."""
    return f"{kind} has no work for an agent"


# A person's own shell where a step's work is: its worktree, or the checkout a step that
# works in place uses. Not a run — nothing is briefed, tracked or claimed.
SHELL_IN_WORKTREE = "&Open Terminal in Worktree"
SHELL_IN_CHECKOUT = "&Open Terminal in Checkout"
NO_WORKTREE = "no worktree of it on this machine yet — Run Agent prepares one"


@dataclass(frozen=True)
class StepAgentInstructionDeps:
    library: Library
    undo: UndoService[Library]
    sections: InspectorSectionRegistry
    actions: ActionRegistry
    context: ContextService  # The Agent tab's buttons evaluate their verbs against it.
    debounce: DebounceService
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
    # The Project dialog's tabs; None is a build without one.
    project_settings: InspectorSectionRegistry | None = None
    # A checkout of each repository on this machine, cloned where the person's policy
    # says when there is none — the projects module's checkout service, handed over by
    # the root. Answers on the GUI thread with what landed and the first refusal.
    ensure_checkouts: Callable[[Sequence[str], Callable[[dict[str, Path], str], None]], None] = (
        field(default=_no_clone)
    )
    # The cross-module half of the prompt, assembled by the composition root — the one
    # place allowed to know what the other aspects store. The same object feeds
    # ``dplanner agent prompt``, so the two surfaces cannot drift.
    briefing: Briefing = EMPTY_BRIEFING
    # Hands the spawned shell over — with the id of the harness that runs in it, "" for
    # a custom command: the step_agent_run module stamps the aspect, watches the run's
    # files for the shell's end and reads the harness's record back — reached through
    # the root because modules never import each other.
    record_launch: Callable[[StepId, launcher.LaunchFiles, str], None] = field(default=_no_record)
    # Every agent CLI this build can launch, first is the default — the composition
    # root's ``agent_harnesses()``. What a profile's command is read against.
    harnesses: tuple[AgentHarness, ...] = ()
    # Insert from Assets…: a modal picker over the node's project's catalog, composed by
    # the root. Node id in, picked payloads out; None is a build without the browser.
    pick_assets: Callable[[str], "list[Payload]"] | None = None
    # What a step's status claims, through the status aspect's Qt-free reader — the
    # Step statuses tab's seam. Run Agent asks before launching on a step whose
    # prerequisites do not all read done; this module never learns the vocabulary's shape.
    status_for: Callable[[Step], str] = field(default=_all_done)
    # The writer half of the same seam: work on the step has begun. Run Agent calls it as
    # the terminal opens, when the person leaves *On launch* on; True when it wrote. The
    # status aspect owns the word and the fact that the write skips the undo stack — this
    # module only knows a run has started.
    mark_started: Callable[[StepId], bool] = field(default=_no_start)
    # Whether a waiter may start once a source is ready for review — an auto-progress
    # link, which the gate reads through the same domain answer the frontier does.
    auto_progresses: Callable[[Step, Step], bool] = field(default=lambda _waiter, _source: False)
    # A wait or a branch cut is no work, so there is nothing on one for an agent to do: the
    # Agent toggle greys on one and Run Agent refuses it. The root names what the step is
    # ("a wait"), "" for a step somebody works.
    works_nobody: Callable[[Step], str] = field(default=lambda _step: "")
    # The step's readable key ("F7") and its ticket key ("PROJ-12"), both composed by the
    # root from aspects this module never reads. They name the run — the worktree, the
    # branch, the terminal's title — through ``launcher.run_name``, which the briefing's
    # preamble reads too, so the agent is told the very name the script prepared.
    step_key: Callable[[Step], str] = field(default=_no_key)
    ticket_key: Callable[[Step], str] = field(default=_no_key)
    # What the step's agent runs have consumed, in words, for the Agent tab — the run
    # tracker's ledger, read through the root; "" when nothing has been recorded.
    usage_words: Callable[[StepId], str] = field(default=lambda _step_id: "")
    # Opens Settings on the section with this id — *Manage Agent Profiles…* at the foot
    # of the Run Agent child menu lands on this module's own page. The settings module
    # owns the dialog; the root closes over it.
    open_settings: Callable[[str], None] = field(default=lambda _section_id: None)
    # Dictation into the editors; None is a build without a microphone.
    dictation: DictationService | None = None
    # -- launching what becomes due (``auto_launch.py``) --------------------------------------
    # What the plan made due, across the library, each with the claim its launch makes —
    # the composition root's one derivation, read with the runs this window is watching.
    due: Callable[[], Sequence[Due]] = field(default=lambda: ())
    # The agent a step asks to be run by — a review's own choice, a harness id — or "" for
    # the default profile. The root reads the review aspect; which profile runs it is ours.
    preferred_agent: Callable[[Step], str] = field(default=lambda _step: "")
    # Whether a step's agent waits on a person, and the state it says — what the notice
    # about an agent launched here, waiting in plan mode, reads.
    asks_person: Callable[[Step], bool] = field(default=lambda _step: False)
    run_state: Callable[[Step], str] = field(default=lambda _step: "")
    # How many agent runs this window is watching live — the cap is on those.
    live_runs: Callable[[], int] = field(default=lambda: 0)
    # Whether the plan changed underneath: nothing is launched on a plan not taken in yet.
    repo: WatchableRepository | None = None
    notices: NoticeHost | None = None
    clock: Clock = field(default_factory=Clock)
    # Autosave's flush now: a launch's claim is on disk at once, not a second and a half on.
    flush: Callable[[], None] = field(default=lambda: None)
    # This library's launch lock on this machine; None is a build that never launches.
    launch_lock: LaunchLock | None = None


class StepAgentInstructionModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepAgentInstructionDeps) -> None:
        self._deps = deps
        self._auto: AutoLauncher | None = None

    def register(self) -> None:
        deps = self._deps

        # The tab thinks per step id; the briefing speaks the shared (library, step,
        # files) vocabulary. The one adapter lives here, in the module that owns both.
        def parts_for(step_id: StepId) -> Sequence[PromptPart]:
            return deps.briefing.parts(deps.library, deps.library.step(step_id), deps.files)

        def sections_for(step_id: StepId) -> Sequence[PromptPart]:
            step = deps.library.step(step_id)
            return deps.briefing.sections(deps.library, step, deps.files, deps.facts_for(step_id))

        def make_section() -> AgentSection:
            # The tab's buttons are the same verbs the menus run — evaluated lazily, so
            # the registration order of action and section never matters.
            return AgentSection(
                deps.library,
                deps.undo,
                PLACEHOLDER,
                debounce=deps.debounce,
                prompt_parts=parts_for,
                prompt_sections=sections_for,
                read_asset=deps.read_asset,
                # The Prompt tab shows the same assembly Run Agent launches with —
                # unstaged, so its paths are the on-disk absolutes read_asset resolves.
                assembled=lambda step_id: self._assembled(deps.library.step(step_id)),
                files=deps.files,
                run_state=lambda: deps.actions.spec("agent.run").state(deps.context.current()),
                run=lambda: deps.actions.run("agent.run", deps.context.current()),
                preview_state=lambda: deps.actions.spec("agent.preview").state(
                    deps.context.current()
                ),
                preview=lambda: deps.actions.run("agent.preview", deps.context.current()),
                pick_assets=deps.pick_assets,
                worktree=lambda step_id: deps.briefing.worktree(deps.library.step(step_id)),
                set_worktree=self._set_worktree,
                no_worktree=lambda step_id: deps.briefing.no_worktree(deps.library.step(step_id)),
                usage=deps.usage_words,
                dictation=deps.dictation,
            )

        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.tab",
                label=SPEC.label,
                order=40,
                factory=make_section,
                shown_for=lambda step_id: (
                    step_id is not None
                    and deps.library.has(step_id)
                    and enabled(deps.library.step(step_id))
                ),
            )
        )
        if deps.project_settings is not None:
            deps.project_settings.register(
                InspectorSection(
                    id=f"{MODULE_ID}.project",
                    label="Agent",
                    order=20,
                    factory=lambda: ProjectInstructionSection(
                        deps.library, deps.undo, deps.files, deps.pick_assets, deps.dictation
                    ),
                    icon=typewriter_icon,
                )
            )
        deps.actions.register(
            aspect_toggle(
                id="agent.toggle",
                label="Agent",
                order=30,
                module_id=MODULE_ID,
                library=deps.library,
                undo=deps.undo,
                enabled=enabled,
                fresh=lambda _step, _project: write_state(True),
                icon=spark_icon,
                tip="Mark this step for agent execution; its description is the briefing",
                refusal=lambda step: no_agent(kind) if (kind := deps.works_nobody(step)) else "",
            )
        )
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
                factory=lambda parent: build_page(
                    parent,
                    harnesses=deps.harnesses,
                    launching=lambda: self._auto.holder_words() if self._auto else "",
                    changed=lambda: self._auto.reconsider() if self._auto else None,
                ),
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
        # Once per user and machine: every harness in every terminal worth naming, so the
        # child menu offers the combinations before anybody builds one by hand.
        seed_profiles(deps.harnesses)
        self._auto = AutoLauncher(deps, self.launch_due)
        self._auto.start()

    def settle_launches(self) -> None:
        """Look again at what is due — a run ended, or the plan was taken in from outside
        without a model change this window heard."""
        if self._auto is not None:
            self._auto.settle()

    # -- running -------------------------------------------------------------------------------

    def _chosen(self, context: Context) -> list[Step]:
        """The steps Run Agent is about — what Delete acts on, read the same way."""
        library = self._deps.library
        return [library.step(step_id) for step_id in chosen_steps(context, library)]

    def _step_refusal(self, step: Step) -> str:
        """Why this step has no agent run in it; "" when it has. The step's own facts."""
        deps = self._deps
        if kind := deps.works_nobody(step):
            return no_agent(kind)
        if not enabled(step):
            return "mark the step as an agent step first (Agent, in Step Details)"
        if deps.status_for(step) == UNKNOWN:
            return "its status was written by a newer DPlanner — update to run it"
        briefed = deps.briefing.instruction(deps.library, step, deps.files)
        if (
            not briefed.body
            and not briefed.files
            and not read_project(deps.library.project_of(step.id))
        ):
            return "describe the step, or write an agent instruction first"
        return ""

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
            unplaced = _unplaced(facts, step)
            if unplaced and unplaced not in clones:
                clones.append(unplaced)
            reason = self._refusal_on(step, facts, by_project)
            if reason:
                named = reason if count == 1 else f"“{_titled(step)}”: {reason}"
                return ActionState(enabled=False, label=f"{verb} — {named}")
        if clones:
            named = ", ".join(remote_label(url) for url in clones)
            amp = "Run &Agent…" if count == 1 else f"Run {count} &Agents…"
            return ActionState(label=f"{amp} — clones {named} first")
        return ENABLED if count == 1 else ActionState(label=f"Run {count} &Agents…")

    def _refusal_on(
        self, step: Step, facts: RepositoryFacts, by_project: dict[str, str] | None = None
    ) -> str:
        """Why no agent can run on ``step`` here, "" when one can: the step's own facts, then
        where its shell would open. A repository not checked out here is no refusal — Run
        Agent clones it; ``by_project`` caches the answer per project, which costs git."""
        if reason := self._step_refusal(step):
            return reason
        if _unplaced(facts, step):
            return ""
        # A step naming a workplace of its own is asked about on its own.
        if workplace(step) or by_project is None:
            return _workdir_refusal(facts, step)
        project_id = self._deps.library.project_of(step.id).id
        return by_project.setdefault(project_id, _workdir_refusal(facts))

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

    def _assembled(self, step: Step, staged: Mapping[str, str] | None = None) -> AssembledPrompt:
        """The briefing, with every referenced file path mapped through ``staged``, opening
        with the preflight for the run the step gets — a worktree unless it opted out or is
        a step that takes none."""
        deps = self._deps
        project = deps.library.project_of(step.id)
        remap: Mapping[str, str] = staged or {}

        def place(paths: Sequence[str]) -> tuple[str, ...]:
            return tuple(remap.get(path, path) for path in paths)

        parts = [
            PromptPart(heading=part.heading, body=part.body, files=place(part.files))
            for part in deps.briefing.parts(deps.library, step, deps.files)
        ]
        sections = [
            PromptPart(heading=section.heading, body=section.body, files=place(section.files))
            for section in deps.briefing.sections(
                deps.library, step, deps.files, deps.facts_for(step.id)
            )
        ]
        project_files = place(asset_paths(deps.files, project.id))
        # The ## Instructions block comes from the briefing — the separate instruction
        # when one exists, the description otherwise, decided by the composition root.
        instruction = deps.briefing.instruction(deps.library, step, deps.files)
        facts = deps.facts_for(step.id)
        branches = deps.briefing.branch(deps.library, step, facts)
        return assemble(
            step_title=_titled(step),
            project_title=project.title or "Untitled project",
            instruction=instruction.body,
            parts=parts,
            sections=sections,
            project_sections=deps.briefing.project_sections(deps.library, step, deps.files),
            epilogue=deps.briefing.epilogue(deps.library, step, branches),
            preamble=deps.briefing.preamble(step, deps.briefing.worktree(step), facts, branches),
            project_instruction=read_project(project),
            project_files=project_files,
            instruction_files=place(instruction.files),
        )

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
        clones = list(dict.fromkeys(_unplaced(deps.facts_for(s.id), s) for s in chosen))
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
        """One agent per step, in order, stopping at the first no terminal opened for — the
        fallback dialog then holds that step's prompt.

        Each step whose shell opened is claimed in progress here, per step and only once its
        shell exists, rather than in ``_launch``: the conflict hand-over shares ``_launch``
        and must claim nothing — that agent is merging two writers' plan files, not doing
        the step's work."""
        deps = self._deps
        claim = start_in_progress()
        launched = claimed = 0
        for step in chosen:
            spawned, text, prepared = self._run_on(step, profile)
            if not spawned:
                # No shell was started, so nothing is stamped and nothing is claimed: the
                # fallback hands over the prompt.
                PromptFallbackDialog(text, str(prepared.prompt_file), deps.parent).exec()
                break
            launched += 1
            claimed += claim and deps.mark_started(step.id)
        if launched == 1:
            note = " — marked in progress" if claimed else ""
            deps.status.show_status(f"Agent launched on “{_titled(chosen[0])}”{note}", 4000)
        elif launched > 1:
            note = f", {claimed} marked in progress" if claimed else ""
            deps.status.show_status(f"{launched} agents launched{note}", 4000)

    def _unfinished(self, step: Step) -> list[Step]:
        """The step's prerequisites it still waits on — what the graph gate asks about."""
        deps = self._deps
        return outstanding(deps.library, step, deps.status_for, deps.auto_progresses)

    def _run_on(self, step: Step, profile: Profile) -> tuple[bool, str, launcher.LaunchFiles]:
        """Launch the agent on one step: whether a shell opened, the briefing it was handed
        and where it was written. Nothing is asked and nothing is claimed — what to do when
        no shell opened, and what a launch claims, is the caller's: a person's Run Agent
        shows the prompt, an unattended launch says why in the status bar."""
        deps = self._deps
        run_dir = launcher.new_run_dir()
        staged = launcher.stage_assets(run_dir, self._assembled(step).files, deps.read_asset)
        assembled = self._assembled(step, staged)
        worktree = self._run_name(step) if deps.briefing.worktree(step) else ""
        facts = deps.facts_for(step.id)
        spawned, prepared = self._launch(
            assembled.text,
            run_dir,
            worktree,
            launcher.workdir(facts, step),
            profile,
            project_id=deps.library.project_of(step.id).id,
            subject=f"{deps.step_key(step)} {step.title}".strip(),
            key=deps.step_key(step),
            step_id=step.id,
            branches=deps.briefing.branch(deps.library, step, facts),
        )
        return spawned, assembled.text, prepared

    def launch_due(self, due: Due) -> str:
        """Launch the agent on a step the plan made due, with nobody at the window: "" when a
        shell opened and the claim was made, else why not — a sentence, never a dialog.

        The questions are Run Agent's, in its order: the profile's terminal, the step's own
        facts, where the shell opens. A repository nobody checked out here is a refusal
        rather than a clone, which is a person's Run Agent to start. The claim is always
        made, whatever *On launch* says, or the step would be due again when its run ends.
        """
        deps = self._deps
        if not deps.library.has(due.step_id):
            return "the step is gone"
        step = deps.library.step(due.step_id)
        profile, refusal = self._profile_for(step)
        if profile is None:
            return refusal
        if refusal := launcher.template_refusal(launch_command(profile)):
            return refusal
        facts = deps.facts_for(step.id)
        if refusal := self._refusal_on(step, facts):
            return refusal
        if unplaced := _unplaced(facts, step):
            return f"{remote_label(unplaced)} is not checked out here — Run Agent clones it"
        spawned, _text, _prepared = self._run_on(step, profile)
        if not spawned:
            return f"no terminal opened — check {profile.name} in Settings ▸ Agent profiles"
        due.claim()
        return ""

    def _profile_for(self, step: Step) -> tuple[Profile | None, str]:
        """The profile an unattended launch runs ``step`` through, and why none can: the
        agent the step asks for — a review's own — through the first profile running it,
        else the default. A named agent no profile runs is refused rather than swapped for
        the default, which may be the very agent whose work the review is about."""
        deps = self._deps
        wanted = deps.preferred_agent(step)
        profiles = read_profiles()
        if not wanted:
            return profiles[0], ""
        for profile in profiles:
            harness = launcher.harness_of(agent_command(deps.harnesses, profile), deps.harnesses)
            if harness is not None and harness.id == wanted:
                return profile, ""
        label = next((each.label for each in deps.harnesses if each.id == wanted), wanted)
        return None, f"no launch profile runs {label} — Settings ▸ Agent profiles"

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

        The worktree is found by the same name the wrapper script gives it (``_run_name``),
        so a step renamed since its agent ran is looked for under its new name."""
        deps = self._deps
        if refusal := launcher.template_refusal(launch_command()):
            return None, refusal
        facts = deps.facts_for(step.id)
        if refusal := _workdir_refusal(facts, step):
            return None, refusal
        workdir = launcher.workdir(facts, step)
        if workdir is None:
            return None, "the project's code is not on this machine — Project ▸ Settings…"
        if not deps.briefing.worktree(step):
            return workdir.expanduser(), ""
        tree = launcher.worktree_path(workdir.expanduser(), self._run_name(step))
        return (tree, "") if tree.is_dir() else (None, NO_WORKTREE)

    def _can_open_shell(self, context: Context) -> ActionState:
        step = focused_step(context, self._deps.library)
        if step is None:
            return DISABLED
        label = SHELL_IN_WORKTREE if self._deps.briefing.worktree(step) else SHELL_IN_CHECKOUT
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
        subject = f"{deps.step_key(step)} {step.title}".strip()
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

    def _run_name(self, step: Step) -> str:
        """What this step's worktree and branch are called: the launcher's rule over the
        root's key and ticket — the same rule the root applies when the briefing names
        the worktree, so the script and the preflight cannot disagree."""
        deps = self._deps
        return launcher.run_name(deps.step_key(step), deps.ticket_key(step), step.title)

    def _set_worktree(self, step_id: StepId, worktree: bool) -> None:
        """The Agent tab's checkbox: one undoable write of this aspect's own entry."""
        step = self._deps.library.step(step_id)
        if uses_worktree(step) == worktree:
            return
        label = "Agent Worktree On" if worktree else "Agent Worktree Off"
        self._deps.undo.push(
            SetModuleDataCommand(step_id, MODULE_ID, with_worktree(step, worktree), label=label)
        )

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
            return [f"• {_titled(r)} — {phrase(deps.status_for(r))}" for r in unfinished]

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
        if unplaced := _unplaced(facts):
            return ActionState(label=f"{OPEN_MENU_TITLE} — clones {remote_label(unplaced)} first")
        if refusal := _workdir_refusal(facts):
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
        if unplaced := _unplaced(deps.facts_for(project_id)):
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
            "",
            launcher.workdir(deps.facts_for(project_id)),
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
        worktree: str,
        workdir: Path | None,
        profile: Profile,
        *,
        project_id: NodeId | None,
        subject: str,
        key: str = "",
        note: str = "",
        step_id: StepId | None = None,
        branches: launcher.BranchPlan = launcher.DEFAULT_BRANCHES,
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
                worktree=worktree,
                directory=run_dir,
                step_title=_window_title(subject, note),
                project_id=project_id or "",
                harnesses=deps.harnesses,
                branches=branches,
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
            "",
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
            "",
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
            preamble=deps.briefing.preamble(step, False, facts, launcher.DEFAULT_BRANCHES),
            entries=entries,
        )
        spawned, prepared = self._launch(
            text,
            run_dir,
            "",
            facts.plan_root,
            default_profile(),
            project_id=library.project_of(step_id).id,
            subject=f"{deps.step_key(step)} {step.title}".strip(),
            key=deps.step_key(step),
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
                    by_project[project_id] = _workdir_refusal(deps.facts_for(step_id))
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
                deps.briefing.preamble(
                    step, False, deps.facts_for(step_id), launcher.DEFAULT_BRANCHES
                ),
                body,
            )
            run_dir = launcher.new_run_dir()
            spawned, prepared = self._launch(
                text,
                run_dir,
                "",
                launcher.workdir(deps.facts_for(step_id)),
                profile,
                project_id=project.id,
                subject=f"{deps.step_key(step)} {step.title}".strip(),
                key=deps.step_key(step),
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
        assembled = self._assembled(step)
        PromptFallbackDialog(
            assembled.text,
            "",
            self._deps.parent,
            note_text=PREVIEW_NOTE,
            title="Prompt Preview",
        ).exec()
