"""The agent-instruction aspect, in the running application: the Agent tab, and Run Agent.

The tab is the writing half — :class:`AgentSection` is ``ProseSection`` plus the Run
button, and ``ModuleTextField`` does the binding work; what is left here is which document,
what to call it, and where it sits among the tabs.

Run Agent is the reading half: assemble the step's briefing (the instruction, plus whatever
context the composition root hands in — this module never learns what a handoff is), write
it to a temp directory, and open a terminal on it. The terminal is a **peer process the
user owns**, deliberately not a TaskRunner task — see ``launcher.py``. When no terminal can
be opened, the fallback dialog delivers the prompt itself, because the prompt is the
product and the terminal was only one way to hand it over.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QWidget

from dplanner.core.fsio import slugify
from dplanner.domain.fields import ModuleTextField
from dplanner.domain.model import Product, Step, StepId
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
from dplanner.framework.text_binding import TextField
from dplanner.framework.undo import UndoService
from dplanner.framework.window import StatusHost
from dplanner.modules.step_agent_instruction import launcher
from dplanner.modules.step_agent_instruction.aspect import DATA_FORMAT, MODULE_ID, SPEC, read
from dplanner.modules.step_agent_instruction.prompt import PromptPart, assemble
from dplanner.modules.step_agent_instruction.run_dialog import PromptFallbackDialog
from dplanner.modules.step_agent_instruction.section import AgentSection
from dplanner.modules.step_agent_instruction.settings_page import (
    agent_command,
    build_page,
    launch_command,
    use_worktree,
)

PLACEHOLDER = "How to carry this step out: which files, which conventions, what done means."


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
    context: ContextService  # The Agent tab's button evaluates agent.run against it.
    settings_sections: SettingsSectionRegistry
    status: StatusHost
    parent: QWidget
    # The briefing's context blocks and its opening and closing words, assembled by the
    # composition root — the one place allowed to know what the other aspects store.
    prompt_parts: Callable[[StepId], Sequence[PromptPart]] = field(default=_no_parts)
    epilogue: Callable[[StepId], str] = field(default=_no_epilogue)
    preamble: str = ""


class StepAgentInstructionModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepAgentInstructionDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps

        def field_for(step_id: str) -> TextField[Any] | None:
            if not deps.product.has(step_id):
                return None
            return ModuleTextField(deps.product, step_id, MODULE_ID)

        def make_section() -> AgentSection:
            # The tab's button is the same verb the menus run — evaluated lazily, so the
            # registration order of action and section never matters.
            return AgentSection(
                field_for,
                deps.undo,
                PLACEHOLDER,
                run_state=lambda: deps.actions.spec("agent.run").state(deps.context.current()),
                run=lambda: deps.actions.run("agent.run", deps.context.current()),
            )

        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.tab",
                label=SPEC.label,
                order=40,
                factory=make_section,
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
        if not self._deps.product.checkout:
            return ActionState(enabled=False, label="Run Agent — set the product's checkout first")
        return ENABLED

    def _run(self, context: Context) -> None:
        step = self._focused(context)
        if step is None:
            return
        deps = self._deps
        project = deps.product.project_of(step.id)
        assembled = assemble(
            step_title=step.title or "Untitled step",
            project_title=project.title or "Untitled project",
            instruction=read(step),
            parts=deps.prompt_parts(step.id),
            epilogue=deps.epilogue(step.id),
            preamble=deps.preamble,
        )
        workdir = Path(deps.product.checkout).expanduser()
        # The slug carries a short id so two steps with one title never share a worktree.
        worktree = f"{slugify(step.title, fallback='step')}-{step.id[:6]}" if use_worktree() else ""
        prepared = launcher.prepare(
            assembled.text, workdir, agent_command=agent_command(), worktree=worktree
        )
        command = None
        if workdir.is_dir():
            command = launcher.resolve_command(launch_command(), prepared, workdir)
        if command is not None:
            launcher.spawn(command, workdir)
            deps.status.show_status(f"Agent launched on “{step.title}”", 4000)
            return
        PromptFallbackDialog(assembled.text, str(prepared.prompt_file), deps.parent).exec()

    def _focused(self, context: Context) -> Step | None:
        step_id = context.focus_entity("step")
        if step_id is None or not self._deps.product.has(step_id):
            return None
        return self._deps.product.step(step_id)
