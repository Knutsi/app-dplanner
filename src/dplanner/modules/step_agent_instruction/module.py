"""The agent-instruction aspect, in the running application: the Agent tab, the project
panel's Agent card, and Run Agent.

The tab is the writing half — :class:`AgentSection` stacks the briefing's three parts
(the project's standing instruction, what earlier steps handed forward, this step's own)
and ``ModuleTextField`` does the binding work. The card is the same project field in the
project panel, registered into ``deps.cards`` like any other project-level section.

Run Agent is the reading half: assemble the step's briefing (both instructions, plus
whatever context the composition root hands in — this module never learns what a handoff
is), stage its attached files beside the prompt in a per-run temp directory, and open a
terminal on it. The terminal is a **peer process the user owns**, deliberately not a
TaskRunner task — see ``launcher.py``. Preview Prompt and the no-terminal fallback show
the same assembled text, because the prompt is the library and the terminal was only one
way to hand it over.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtWidgets import QMessageBox, QWidget

from dplanner.core.fsio import slugify
from dplanner.domain.model import Library, Node, Step, StepId
from dplanner.domain.progression import DONE
from dplanner.domain.store import Conflict, FilesFor
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.aspect_toggle import aspect_toggle, focused_step
from dplanner.framework.context import Context, ContextService
from dplanner.framework.debounce import DebounceService
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.mime_files import Payload
from dplanner.framework.settings_registry import (
    SettingsSection,
    SettingsSectionRegistry,
)
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
    write_state,
)
from dplanner.modules.step_agent_instruction.prompt import (
    EMPTY_BRIEFING,
    AssembledPrompt,
    Briefing,
    PromptPart,
    assemble,
    conflict_prompt,
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
    use_worktree,
)
from dplanner.theme.icons import spark_icon, typewriter_icon

PLACEHOLDER = "How to carry this step out: which files, which conventions, what done means."

PREVIEW_NOTE = (
    "This is the exact briefing Run Agent will launch with. File paths are relative to"
    " the workspace here; at launch the files are copied beside prompt.md and referenced"
    " by their staged paths."
)


def _no_record(_step_id: StepId, _files: launcher.LaunchFiles) -> None:
    return None


def _all_done(_step: Step) -> str:
    """A build with nobody to ask about status: nothing is unfinished, nothing warns."""
    return DONE


def _our_version(node: Node, entry: str) -> str:
    """The window's version of one entry, in the shape the file on disk has."""
    if entry == "meta":
        meta: dict[str, object] = {"title": getattr(node, "title", "")}
        if isinstance(node, Step):
            meta["edges"] = node.edges
        else:
            meta["summary"] = getattr(node, "summary", "")
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
    # Where the agent runs: the project's git repository root, resolved by the composition
    # root from the step's project directory. "" when the repository cannot be found.
    workdir_for: Callable[[StepId], str]
    # The project panel's card registry; None is a build without a project panel.
    cards: InspectorSectionRegistry | None = None
    # The cross-module half of the prompt, assembled by the composition root — the one
    # place allowed to know what the other aspects store. The same object feeds
    # ``dplanner agent prompt``, so the two surfaces cannot drift.
    briefing: Briefing = EMPTY_BRIEFING
    # Hands the spawned shell over: the step_agent_run module stamps the aspect and
    # watches the run's files for the shell's end — reached through the root because
    # modules never import each other.
    record_launch: Callable[[StepId, launcher.LaunchFiles], None] = field(default=_no_record)
    # Insert from Assets…: a modal picker over the node's project's catalog, composed by
    # the root. Node id in, picked payloads out; None is a build without the browser.
    pick_assets: Callable[[str], "list[Payload]"] | None = None
    # What a step's status claims, through the status aspect's Qt-free reader — the
    # progression board's seam. Run Agent asks before launching on a step whose
    # prerequisites do not all read done; this module never learns the vocabulary's shape.
    status_for: Callable[[Step], str] = field(default=_all_done)


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
        deps.actions.register(
            ActionSpec(
                id="agent.run",
                label="Run &Agent…",
                menu="Step",
                group="agent",
                order=10,
                tip="Open a terminal with the agent briefed on this step",
                state=self._can_run,
                run=self._run,
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
                id=f"{MODULE_ID}.launch",
                category=("Agent",),
                factory=build_page,
            )
        )

    # -- running -------------------------------------------------------------------------------

    def _can_run(self, context: Context) -> ActionState:
        """Present whenever a step is; greyed with the reason when a prerequisite is not.

        The idiom from `CLAUDE.md`: a disabled entry carries what to do about it. The same
        state drives the menu bar, the palette and the Agent tab's button.
        """
        step = focused_step(context, self._deps.library)
        if step is None:
            return DISABLED
        deps = self._deps
        if not enabled(step):
            return ActionState(
                enabled=False,
                label="Run Agent — mark the step as an agent step first (Step ▸ Type ▸ Agent)",
            )
        briefed = deps.briefing.instruction(deps.library, step, deps.files)
        if (
            not briefed.body
            and not briefed.files
            and not read_project(deps.library.project_of(step.id))
        ):
            return ActionState(
                enabled=False,
                label="Run Agent — describe the step, or write an agent instruction first",
            )
        if not deps.workdir_for(step.id):
            return ActionState(
                enabled=False,
                label="Run Agent — the project's folder is not in a git repository",
            )
        return ENABLED

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
        """The briefing, with every referenced file path mapped through ``staged``."""
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
            step_title=step.title or "Untitled step",
            project_title=project.title or "Untitled project",
            instruction=instruction.body,
            parts=parts,
            sections=sections,
            project_sections=deps.briefing.project_sections(deps.library, step, deps.files),
            epilogue=deps.briefing.epilogue(step),
            preamble=deps.briefing.preamble,
            project_instruction=read_project(project),
            project_files=project_files,
            instruction_files=place(instruction.files),
        )

    def _run(self, context: Context) -> None:
        step = focused_step(context, self._deps.library)
        if step is None:
            return
        deps = self._deps
        unfinished = [
            required
            for required in deps.library.requires(step.id)
            if deps.status_for(required) != DONE
        ]
        if unfinished and not self._confirm_unfinished(step, unfinished):
            return
        run_dir = launcher.new_run_dir()
        staged = launcher.stage_assets(run_dir, self._assembled(step).files, deps.read_asset)
        assembled = self._assembled(step, staged)
        # The slug carries a short id so two steps with one title never share a worktree.
        worktree = f"{slugify(step.title, fallback='step')}-{step.id[:6]}" if use_worktree() else ""
        spawned, prepared = self._launch(step, assembled.text, run_dir, worktree)
        if not spawned:
            # No shell was started, so nothing is stamped: the fallback hands over the prompt.
            PromptFallbackDialog(assembled.text, str(prepared.prompt_file), deps.parent).exec()

    def _confirm_unfinished(self, step: Step, unfinished: Sequence[Step]) -> bool:
        """The graph gates launching: an agent briefed on a step whose prerequisites are
        not done works without what they were to produce. Say which, and ask — the
        person may know the work landed without the status being recorded."""
        deps = self._deps
        box = QMessageBox(deps.parent)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Run Agent")
        count = f"{len(unfinished)} step{'s' if len(unfinished) != 1 else ''}"
        box.setText(f"“{step.title or 'Untitled step'}” waits on {count} not done yet.")
        listed = "\n".join(
            f"• {required.title or 'Untitled step'} — {deps.status_for(required)}"
            for required in unfinished
        )
        box.setInformativeText(
            f"{listed}\n\nThe agent would start without what those steps produce. Run it anyway?"
        )
        run_anyway = box.addButton("Run Anyway", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return box.clickedButton() is run_anyway

    def _launch(
        self, step: Step, text: str, run_dir: Path, worktree: str
    ) -> tuple[bool, launcher.LaunchFiles]:
        """Open the configured terminal on ``text`` for ``step``; the run is recorded only
        when a shell was actually spawned. Both prompts this module launches come through
        here, so a change to how a terminal opens is made once."""
        deps = self._deps
        workdir = Path(deps.workdir_for(step.id)).expanduser()
        prepared = launcher.prepare(
            text,
            workdir,
            agent_command=agent_command(),
            worktree=worktree,
            directory=run_dir,
            step_title=step.title,
        )
        command = None
        if workdir.is_dir():
            command = launcher.resolve_command(launch_command(), prepared, workdir)
        if command is None:
            return False, prepared
        launcher.spawn(command, workdir)
        deps.record_launch(step.id, prepared)
        deps.status.show_status(f"Agent launched on “{step.title}”", 4000)
        return True, prepared

    # -- reconciling a conflict ----------------------------------------------------------------

    def conflict_refusal(self, step_id: StepId) -> str:
        """Why a conflict on ``step_id`` cannot be handed to an agent; "" when it can."""
        if not self._deps.library.has(step_id):
            return "the step is gone"
        if not self._deps.workdir_for(step_id):
            return "the project's folder is not in a git repository"
        return ""

    def hand_conflicts(self, step_id: StepId, conflicts: Sequence[Conflict]) -> bool:
        """Launch the agent on the entries two writers changed at once; True when a shell
        was spawned.

        The window's version of every entry is written beside the prompt first, because the
        window yields to the plan on disk once the agent is on its way — the run directory
        is the one place the unsaved version survives. No worktree: the agent must write to
        the checkout the window is showing, or its merge lands somewhere nobody is looking.
        """
        deps = self._deps
        library = deps.library
        step = library.step(step_id)
        run_dir = launcher.new_run_dir()
        entries: list[tuple[str, str]] = []
        for conflict in conflicts:
            if not library.has(conflict.node_id):
                continue
            ours = run_dir / "mine" / conflict.path
            ours.parent.mkdir(parents=True, exist_ok=True)
            ours.write_text(_our_version(library.node(conflict.node_id), conflict.entry))
            entries.append((conflict.path, str(ours)))
        text = conflict_prompt(
            step_title=step.title or "Untitled step",
            project_title=library.project_of(step_id).title or "Untitled project",
            preamble=deps.briefing.preamble,
            entries=entries,
        )
        spawned, prepared = self._launch(step, text, run_dir, worktree="")
        if not spawned:
            PromptFallbackDialog(
                text, str(prepared.prompt_file), deps.parent, title="Resolve Conflict"
            ).exec()
        return spawned

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
