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

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtWidgets import QWidget

from dplanner.core.fsio import slugify
from dplanner.domain.commands import (
    Command,
    CompositeCommand,
    EditTextCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import Library, Step, StepId, TextEdit
from dplanner.domain.store import FilesFor
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context, ContextService
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.settings_registry import (
    SettingsSection,
    SettingsSectionRegistry,
)
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import confirm
from dplanner.framework.window import StatusHost
from dplanner.modules.step_agent_instruction import launcher
from dplanner.modules.step_agent_instruction.aspect import (
    DATA_FORMAT,
    MODULE_ID,
    SPEC,
    asset_paths,
    enabled,
    read,
    read_project,
    write_state,
)
from dplanner.modules.step_agent_instruction.prompt import (
    EMPTY_BRIEFING,
    AssembledPrompt,
    Briefing,
    PromptPart,
    assemble,
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
from dplanner.theme.icons import typewriter_icon

PLACEHOLDER = "How to carry this step out: which files, which conventions, what done means."

PREVIEW_NOTE = (
    "This is the exact briefing Run Agent will launch with. File paths are relative to"
    " the workspace here; at launch the files are copied beside prompt.md and referenced"
    " by their staged paths."
)


def _no_record(_step_id: StepId) -> None:
    return None


@dataclass(frozen=True)
class StepAgentInstructionDeps:
    library: Library
    undo: UndoService[Library]
    sections: InspectorSectionRegistry
    actions: ActionRegistry
    context: ContextService  # The Agent tab's buttons evaluate their verbs against it.
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
    # Stamps "an agent shell was launched on this step" — the step_agent_run aspect,
    # reached through the root because modules never import each other.
    record_launch: Callable[[StepId], None] = field(default=_no_record)


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
            )

        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.tab",
                label=SPEC.label,
                order=40,
                factory=make_section,
                shown_for=lambda step_id: step_id is not None
                and deps.library.has(step_id)
                and enabled(deps.library.step(step_id)),
            )
        )
        if deps.cards is not None:
            deps.cards.register(
                InspectorSection(
                    id=f"{MODULE_ID}.card",
                    label="Agent",
                    order=20,
                    factory=lambda: ProjectInstructionCard(
                        deps.library, deps.undo, deps.files
                    ),
                    icon=typewriter_icon,
                )
            )
        deps.actions.register(
            ActionSpec(
                id="agent.toggle",
                label="Agent",
                menu="Step",
                group="type",
                submenu="Type",
                order=20,
                tip="Mark this step for agent execution; its description is the briefing",
                state=self._aspect_state,
                run=self._toggle_aspect,
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

    # -- the aspect itself ---------------------------------------------------------------------

    def _aspect_state(self, context: Context) -> ActionState:
        step = self._focused(context)
        if step is None:
            return DISABLED
        return ActionState(checked=enabled(step))

    def _toggle_aspect(self, context: Context) -> None:
        step = self._focused(context)
        if step is None:
            return
        if not enabled(step):
            self._deps.undo.push(
                SetModuleDataCommand(
                    step.id, MODULE_ID, write_state(True), label="Mark as Agent Step"
                )
            )
            return
        current = read(step)
        if current:
            question = (
                f"Stop treating {step.title or 'this step'!r} as an agent step?"
                " Its separate agent instruction is not kept."
            )
            if not confirm(self._deps.parent, "Clear Agent Aspect", question):
                return
        commands: list[Command] = []
        if current:
            commands.append(
                EditTextCommand(
                    TextEdit(step.id, MODULE_ID, 0, current, ""),
                    label="Set Agent Instruction",
                )
            )
        commands.append(
            SetModuleDataCommand(step.id, MODULE_ID, {}, label="Clear Agent Aspect")
        )
        # One undo step restores both the mark and the instruction text.
        self._deps.undo.push(
            commands[0]
            if len(commands) == 1
            else CompositeCommand("Clear Agent Aspect", commands)
        )

    # -- running -------------------------------------------------------------------------------

    def _can_run(self, context: Context) -> ActionState:
        """Present whenever a step is; greyed with the reason when a prerequisite is not.

        The idiom from `CLAUDE.md`: a disabled entry carries what to do about it. The same
        state drives the menu bar, the palette and the Agent tab's button.
        """
        step = self._focused(context)
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
        step = self._focused(context)
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
            epilogue=deps.briefing.epilogue(step),
            preamble=deps.briefing.preamble,
            project_instruction=read_project(project),
            project_files=project_files,
            instruction_files=place(instruction.files),
        )

    def _run(self, context: Context) -> None:
        step = self._focused(context)
        if step is None:
            return
        deps = self._deps
        run_dir = launcher.new_run_dir()
        staged = launcher.stage_assets(run_dir, self._assembled(step).files, deps.read_asset)
        assembled = self._assembled(step, staged)
        workdir = Path(deps.workdir_for(step.id)).expanduser()
        # The slug carries a short id so two steps with one title never share a worktree.
        worktree = f"{slugify(step.title, fallback='step')}-{step.id[:6]}" if use_worktree() else ""
        prepared = launcher.prepare(
            assembled.text,
            workdir,
            agent_command=agent_command(),
            worktree=worktree,
            directory=run_dir,
        )
        command = None
        if workdir.is_dir():
            command = launcher.resolve_command(launch_command(), prepared, workdir)
        if command is not None:
            launcher.spawn(command, workdir)
            deps.record_launch(step.id)
            deps.status.show_status(f"Agent launched on “{step.title}”", 4000)
            return
        # No shell was started, so nothing is stamped: the fallback hands over the prompt.
        PromptFallbackDialog(assembled.text, str(prepared.prompt_file), deps.parent).exec()

    def _preview(self, context: Context) -> None:
        step = self._focused(context)
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

    def _focused(self, context: Context) -> Step | None:
        step_id = context.focus_entity("step")
        if step_id is None or not self._deps.library.has(step_id):
            return None
        return self._deps.library.step(step_id)
