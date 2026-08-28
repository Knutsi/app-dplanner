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
the same assembled text, because the prompt is the product and the terminal was only one
way to hand it over.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtWidgets import QWidget

from dplanner.core.fsio import slugify
from dplanner.domain.model import NodeId, Product, Step, StepId
from dplanner.domain.store import ModuleFileArea
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
    SettingsScope,
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
    read,
    read_project,
)
from dplanner.modules.step_agent_instruction.prompt import (
    AssembledPrompt,
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


def _no_parts(_step_id: StepId) -> Sequence[PromptPart]:
    return ()


def _no_epilogue(_step_id: StepId) -> str:
    return ""


@dataclass(frozen=True)
class StepAgentInstructionDeps:
    product: Product
    undo: UndoService[Product]
    sections: InspectorSectionRegistry
    actions: ActionRegistry
    context: ContextService  # The Agent tab's buttons evaluate their verbs against it.
    settings_sections: SettingsSectionRegistry
    status: StatusHost
    parent: QWidget
    # The project panel's card registry; None is a build without a project panel.
    cards: InspectorSectionRegistry | None = None
    # The store's file areas and raw byte access — how instruction images are listed for
    # the prompt and staged beside it at launch. None is a build without file storage.
    files: Callable[[NodeId, str], ModuleFileArea] | None = None
    read_asset: Callable[[str], bytes | None] | None = None
    # The briefing's blocks — handed-forward context, the step's own facts — and its
    # opening and closing words, assembled by the composition root — the one place
    # allowed to know what the other aspects store.
    prompt_parts: Callable[[StepId], Sequence[PromptPart]] = field(default=_no_parts)
    prompt_sections: Callable[[StepId], Sequence[PromptPart]] = field(default=_no_parts)
    epilogue: Callable[[StepId], str] = field(default=_no_epilogue)
    preamble: str = ""
    # Where the agent runs. The root resolves the project's checkout over the product's;
    # None is the product-only build, not a second copy of that rule.
    checkout_for: Callable[[StepId], str] | None = None


class StepAgentInstructionModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepAgentInstructionDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps

        def make_section() -> AgentSection:
            # The tab's buttons are the same verbs the menus run — evaluated lazily, so
            # the registration order of action and section never matters.
            return AgentSection(
                deps.product,
                deps.undo,
                PLACEHOLDER,
                prompt_parts=deps.prompt_parts,
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
            )
        )
        if deps.cards is not None:
            deps.cards.register(
                InspectorSection(
                    id=f"{MODULE_ID}.card",
                    label="Agent",
                    order=20,
                    factory=lambda: ProjectInstructionCard(
                        deps.product, deps.undo, deps.files
                    ),
                    icon=typewriter_icon,
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
                scope=SettingsScope.GLOBAL,
                factory=build_page,
            )
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
        if not read(step):
            return ActionState(
                enabled=False, label="Run Agent — write an agent instruction first"
            )
        if not self._checkout(step.id):
            return ActionState(
                enabled=False,
                label="Run Agent — set a checkout on the project or the product first",
            )
        return ENABLED

    def _can_preview(self, context: Context) -> ActionState:
        """A preview needs only a step: an empty instruction still has a project part and
        inherited context worth seeing."""
        return DISABLED if self._focused(context) is None else ENABLED

    def _checkout(self, step_id: StepId) -> str:
        deps = self._deps
        return deps.checkout_for(step_id) if deps.checkout_for else deps.product.checkout

    def _assembled(self, step: Step, staged: Mapping[str, str] | None = None) -> AssembledPrompt:
        """The briefing, with every referenced file path mapped through ``staged``."""
        deps = self._deps
        project = deps.product.project_of(step.id)
        remap: Mapping[str, str] = staged or {}

        def place(paths: Sequence[str]) -> tuple[str, ...]:
            return tuple(remap.get(path, path) for path in paths)

        parts = [
            PromptPart(heading=part.heading, body=part.body, files=place(part.files))
            for part in deps.prompt_parts(step.id)
        ]
        sections = [
            PromptPart(heading=section.heading, body=section.body, files=place(section.files))
            for section in deps.prompt_sections(step.id)
        ]
        project_files: tuple[str, ...] = ()
        instruction_files: tuple[str, ...] = ()
        if deps.files is not None:
            project_files = place(asset_paths(deps.files, project.id))
            instruction_files = place(asset_paths(deps.files, step.id))
        return assemble(
            step_title=step.title or "Untitled step",
            project_title=project.title or "Untitled project",
            instruction=read(step),
            parts=parts,
            sections=sections,
            epilogue=deps.epilogue(step.id),
            preamble=deps.preamble,
            project_instruction=read_project(project),
            project_files=project_files,
            instruction_files=instruction_files,
        )

    def _run(self, context: Context) -> None:
        step = self._focused(context)
        if step is None:
            return
        deps = self._deps
        run_dir = launcher.new_run_dir()
        staged: dict[str, str] = {}
        if deps.read_asset is not None:
            staged = launcher.stage_assets(
                run_dir, self._assembled(step).files, deps.read_asset
            )
        assembled = self._assembled(step, staged)
        workdir = Path(self._checkout(step.id)).expanduser()
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
            deps.status.show_status(f"Agent launched on “{step.title}”", 4000)
            return
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
        if step_id is None or not self._deps.product.has(step_id):
            return None
        return self._deps.product.step(step_id)
