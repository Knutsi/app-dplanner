"""The agent-instruction aspect, in the running application: the Agent tab, the project
panel's Agent card, and Run Agent.

The tab is the writing half — :class:`AgentSection` stacks the briefing's three parts
(the project's standing instruction, what the project's notes hold for it, this step's own)
and ``ModuleTextField`` does the binding work. The card is the same project field in the
project panel, registered into ``deps.cards`` like any other project-level section.

Run Agent is the reading half: assemble the step's briefing (both instructions, plus
whatever context the composition root hands in — this module never learns what a note
is), stage its attached files beside the prompt in a per-run temp directory, and open a
terminal on it. The terminal is a **peer process the user owns**, deliberately not a
TaskRunner task — see ``launcher.py``. Preview Prompt and the no-terminal fallback show
the same assembled text, because the prompt is the library and the terminal was only one
way to hand it over.

**It runs one agent per chosen step, up to a limit.** The verb reads the selection the way
Delete does, so lassoing three agent steps is *Run 3 Agents…* and one gesture; past
*Settings ▸ Agent profiles*'s limit (four by default) the count itself is the refusal, greyed with
its reason like any other precondition. Each step whose shell opened is also claimed
*in progress* — through ``deps.mark_started``, unless the person switched that off on the
settings page — since the agent's own first report may be minutes away.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtWidgets import QMenu, QMessageBox, QWidget

from dplanner.core.telemetry import current
from dplanner.domain.agents import AgentHarness
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Node, Step, StepId
from dplanner.domain.progression import DONE
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
from dplanner.framework.aspect_toggle import aspect_toggle
from dplanner.framework.context import Context, ContextService
from dplanner.framework.debounce import DebounceService
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.mime_files import Payload
from dplanner.framework.settings_registry import (
    SettingsSection,
    SettingsSectionRegistry,
)
from dplanner.framework.step_selection import chosen_steps, focused_step
from dplanner.framework.undo import UndoService
from dplanner.framework.window import StatusHost
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
    write_state,
)
from dplanner.modules.step_agent_instruction.profiles import (
    Profile,
    default_profile,
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
)
from dplanner.modules.step_agent_instruction.run_dialog import PromptFallbackDialog
from dplanner.modules.step_agent_instruction.section import (
    AgentSection,
    ProjectInstructionCard,
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


def _all_done(_step: Step) -> str:
    """A build with nobody to ask about status: nothing is unfinished, nothing warns."""
    return DONE


def _workdir(facts: RepositoryFacts) -> Path | None:
    """Where an agent on the step works: the code checkout when the project records a
    code repository, else the plan's own repository — the older shape, a plan kept beside
    its code. None when neither is here."""
    return facts.checkout if facts.repository else facts.plan_root


def _workdir_refusal(facts: RepositoryFacts) -> str:
    """Why Run Agent cannot open a shell for the step; "" when it can."""
    if facts.repository:
        if facts.checkout is None:
            return "the code repository is not checked out on this machine — Project ▸ Settings…"
        if not facts.checkout.expanduser().is_dir():
            return f"the code checkout is gone from {facts.checkout} — Project ▸ Settings…"
        return ""
    if facts.plan_root is None:
        return "the project's folder is not in a git repository"
    return ""


def _no_key(_step: Step) -> str:
    return ""


def _window_title(key: str, step: Step, note: str) -> str:
    """What the terminal's window is called. ``note`` is what this run is *for* when it is
    not the step's work: two runs on one step are told apart by their windows or not at
    all."""
    titled = f"{key} {step.title}".strip()
    return f"{titled} ({note})" if note else titled


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
    # The project panel's card registry; None is a build without a project panel.
    cards: InspectorSectionRegistry | None = None
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
    # progression board's seam. Run Agent asks before launching on a step whose
    # prerequisites do not all read done; this module never learns the vocabulary's shape.
    status_for: Callable[[Step], str] = field(default=_all_done)
    # The writer half of the same seam: work on the step has begun. Run Agent calls it as
    # the terminal opens, when the person leaves *On launch* on; True when it wrote. The
    # status aspect owns the word and the fact that the write skips the undo stack — this
    # module only knows a run has started.
    mark_started: Callable[[StepId], bool] = field(default=_no_start)
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


class StepAgentInstructionModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepAgentInstructionDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps

        # The tab thinks per step id; the briefing speaks the shared (library, step,
        # files) vocabulary. The one adapter lives here, in the module that owns both.
        def parts_for(step_id: StepId) -> Sequence[PromptPart]:
            return deps.briefing.parts(deps.library, deps.library.step(step_id), deps.files)

        def sections_for(step_id: StepId) -> Sequence[PromptPart]:
            return deps.briefing.sections(deps.library, deps.library.step(step_id), deps.files)

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
                worktree=lambda step_id: uses_worktree(deps.library.step(step_id)),
                set_worktree=self._set_worktree,
                usage=deps.usage_words,
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
        if deps.cards is not None:
            deps.cards.register(
                InspectorSection(
                    id=f"{MODULE_ID}.card",
                    label="Agent",
                    order=20,
                    factory=lambda: ProjectInstructionCard(
                        deps.library, deps.undo, deps.files, deps.pick_assets
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
        # Once per user and machine: every harness in every terminal worth naming, so the
        # child menu offers the combinations before anybody builds one by hand.
        seed_profiles(deps.harnesses)

    # -- running -------------------------------------------------------------------------------

    def _chosen(self, context: Context) -> list[Step]:
        """The steps Run Agent is about — what Delete acts on, read the same way."""
        library = self._deps.library
        return [library.step(step_id) for step_id in chosen_steps(context, library)]

    def _step_refusal(self, step: Step) -> str:
        """Why this step has no agent run in it; "" when it has. The step's own facts."""
        deps = self._deps
        if not enabled(step):
            return "mark the step as an agent step first (Step ▸ Type ▸ Agent)"
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
        for step in chosen:
            project_id = deps.library.project_of(step.id).id
            if project_id not in by_project:
                by_project[project_id] = _workdir_refusal(deps.facts_for(step.id))
            if reason := self._step_refusal(step) or by_project[project_id]:
                named = reason if count == 1 else f"“{_titled(step)}”: {reason}"
                return ActionState(enabled=False, label=f"{verb} — {named}")
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

    def _assembled(self, step: Step, staged: Mapping[str, str] | None = None) -> AssembledPrompt:
        """The briefing, with every referenced file path mapped through ``staged``, opening
        with the preflight for the run the step asks for — a worktree unless it opted out."""
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
            for section in deps.briefing.sections(deps.library, step, deps.files)
        ]
        project_files = place(asset_paths(deps.files, project.id))
        # The ## Instructions block comes from the briefing — the separate instruction
        # when one exists, the description otherwise, decided by the composition root.
        instruction = deps.briefing.instruction(deps.library, step, deps.files)
        return assemble(
            step_title=_titled(step),
            project_title=project.title or "Untitled project",
            instruction=instruction.body,
            parts=parts,
            sections=sections,
            project_sections=deps.briefing.project_sections(deps.library, step, deps.files),
            epilogue=deps.briefing.epilogue(deps.library, step),
            preamble=deps.briefing.preamble(step, uses_worktree(step), deps.facts_for(step.id)),
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
        if waiting and not self._confirm_unfinished(waiting):
            return
        profile = profile or default_profile()
        claim = start_in_progress()
        launched = claimed = 0
        for step in chosen:
            spawned, started = self._run_on(step, profile, claim)
            if not spawned:
                break
            launched += 1
            claimed += started
        if launched == 1:
            note = " — marked in progress" if claimed else ""
            deps.status.show_status(f"Agent launched on “{_titled(chosen[0])}”{note}", 4000)
        elif launched > 1:
            note = f", {claimed} marked in progress" if claimed else ""
            deps.status.show_status(f"{launched} agents launched{note}", 4000)

    def _unfinished(self, step: Step) -> list[Step]:
        """The step's prerequisites that do not read done — what the graph gate asks about."""
        deps = self._deps
        return [
            required
            for required in deps.library.requires(step.id)
            if deps.status_for(required) != DONE
        ]

    def _run_on(self, step: Step, profile: Profile, claim_started: bool) -> tuple[bool, bool]:
        """Launch the agent on one step: whether a shell opened (the fallback showed when
        not), and whether the step was thereby marked in progress.

        The claim is made here, per step and only once its shell exists, rather than in
        ``_launch``: the conflict hand-over shares ``_launch`` and must claim nothing —
        that agent is merging two writers' plan files, not doing the step's work."""
        deps = self._deps
        run_dir = launcher.new_run_dir()
        staged = launcher.stage_assets(run_dir, self._assembled(step).files, deps.read_asset)
        assembled = self._assembled(step, staged)
        worktree = self._run_name(step) if uses_worktree(step) else ""
        workdir = _workdir(deps.facts_for(step.id))
        spawned, prepared = self._launch(step, assembled.text, run_dir, worktree, workdir, profile)
        if not spawned:
            # No shell was started, so nothing is stamped and nothing is claimed: the
            # fallback hands over the prompt.
            PromptFallbackDialog(assembled.text, str(prepared.prompt_file), deps.parent).exec()
            return False, False
        return True, claim_started and deps.mark_started(step.id)

    def _fill_profiles(self, menu: QMenu) -> None:
        """Step ▸ Run Agent: one entry per profile, the default first and marked, each
        greyed with its own reason — a profile's terminal may be missing where another's
        is not — and rebuilt every time the menu opens, so a profile added in Settings
        is offered at once. Under a rule, the way to Settings — the same child menu the
        progression board's *Run Agents* button drops down."""
        deps = self._deps
        context = deps.context.current()
        for index, profile in enumerate(read_profiles()):
            state = self._can_run(context, profile)
            name = f"{profile.name} (default)" if index == 0 else profile.name
            reason = ""
            if not state.enabled and state.label:
                reason = state.label.partition(" — ")[2]
            entry = menu.addAction(f"{name} — {reason}" if reason else name)
            entry.setEnabled(state.enabled)
            entry.triggered.connect(
                lambda _checked=False, p=profile: self._run(deps.context.current(), p)
            )
        menu.addSeparator()
        append_action(menu, deps.actions, deps.context, "agent.profiles")

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

    def _confirm_unfinished(self, waiting: Sequence[tuple[Step, Sequence[Step]]]) -> bool:
        """The graph gates launching: an agent briefed on a step whose prerequisites are
        not done works without what they were to produce. Say which, and ask — the
        person may know the work landed without the status being recorded.

        One box for the whole gesture, so several chosen steps name their own unfinished
        work under their own heading and Cancel means *none of them*."""
        deps = self._deps
        box = QMessageBox(deps.parent)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Run Agent")

        def listed(unfinished: Sequence[Step]) -> str:
            return "\n".join(f"• {_titled(r)} — {deps.status_for(r)}" for r in unfinished)

        if len(waiting) == 1:
            step, unfinished = waiting[0]
            count = f"{len(unfinished)} step{'s' if len(unfinished) != 1 else ''}"
            box.setText(f"“{_titled(step)}” waits on {count} not done yet.")
            detail = listed(unfinished)
            closing = "The agent would start without what those steps produce. Run it anyway?"
        else:
            box.setText(f"{len(waiting)} of the chosen steps wait on work not done yet.")
            detail = "\n\n".join(
                f"{_titled(step)} waits on:\n{listed(unfinished)}" for step, unfinished in waiting
            )
            closing = "The agents would start without what those steps produce. Run them anyway?"
        box.setInformativeText(f"{detail}\n\n{closing}")
        run_anyway = box.addButton("Run Anyway", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return box.clickedButton() is run_anyway

    def _launch(
        self,
        step: Step,
        text: str,
        run_dir: Path,
        worktree: str,
        workdir: Path | None,
        profile: Profile,
        *,
        note: str = "",
    ) -> tuple[bool, launcher.LaunchFiles]:
        """Open the profile's terminal on ``text`` for ``step`` in ``workdir``; the run
        is recorded only when a shell was actually spawned. Both prompts this module
        launches come through here, so a change to how a terminal opens is made once.

        What the status bar says, and whether the step is claimed in progress, is the
        **caller's**: one launch names its step, a run over a selection counts what opened
        and claims each step as it goes, and neither is true of the other."""
        deps = self._deps
        workdir = (workdir or Path()).expanduser()
        key = deps.step_key(step)
        command_text = agent_command(deps.harnesses, profile)
        # A launch is a span of its own under the action's, not a detail on it: one gesture
        # opens a shell per chosen step, so three launches are three sizes and could never
        # be one key on the parent — and a verb cannot reach the enclosing span anyway,
        # since the journal hands out copies of what is open.
        with current().span("action", "agent.launch", step=key) as span:
            prepared = launcher.prepare(
                text,
                workdir,
                agent_command=command_text,
                worktree=worktree,
                directory=run_dir,
                step_title=_window_title(key, step, note),
                project_id=deps.library.project_of(step.id).id,
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
            deps.record_launch(step.id, prepared, harness.id if harness else "")
            return True, prepared

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
            preamble=deps.briefing.preamble(step, False, facts),
            entries=entries,
        )
        spawned, prepared = self._launch(
            step, text, run_dir, "", facts.plan_root, default_profile()
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
        return [
            (profile.name, shared or launcher.template_refusal(launch_command(profile)))
            for profile in read_profiles()
        ]

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
                deps.briefing.preamble(step, False, deps.facts_for(step_id)),
                body,
            )
            run_dir = launcher.new_run_dir()
            spawned, prepared = self._launch(
                step,
                text,
                run_dir,
                "",
                _workdir(deps.facts_for(step_id)),
                profile,
                note="documentation",
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
