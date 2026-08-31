"""The description aspect, in the running application: one registration, the Description
block on the step panel's Details tab.

The editor itself is :class:`~dplanner.framework.prose_section.ProseSection` — the framework
owns the binding mechanics, so all this module supplies is which document to edit.
"""

from dataclasses import dataclass
from typing import Any

from PySide6.QtWidgets import QWidget

from dplanner.domain.commands import (
    Command,
    CompositeCommand,
    EditTextCommand,
    SetModuleDataCommand,
)
from dplanner.domain.fields import ModuleTextField
from dplanner.domain.model import Library, Step, TextEdit
from dplanner.domain.store import FilesFor
from dplanner.framework.action_registry import (
    DISABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.asset_gallery import AreaFor
from dplanner.framework.context import Context
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.text_binding import TextField
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import confirm
from dplanner.modules.step_description.aspect import (
    DATA_FORMAT,
    MODULE_ID,
    SPEC,
    enabled,
    read,
    write_state,
)
from dplanner.modules.step_description.section import (
    DescriptionSection,
    SeparateInstructionLink,
)

PLACEHOLDER = (
    "What this step is — and, on an agent step, what the agent is briefed with."
    " Markdown; paste or drop an image straight in."
)


@dataclass(frozen=True)
class StepDescriptionDeps:
    library: Library
    undo: UndoService[Library]
    # The step panel's Details tab — the description is its main block, not a tab.
    details: InspectorSectionRegistry
    actions: ActionRegistry
    # The store's file areas — how the tab shows the images `describe attach` wrote.
    # None is a build without file storage.
    files: FilesFor | None = None
    # The agent aspect through this module's own vocabulary, wired by the composition
    # root — the "Separate agent instruction" checkbox. None is a build without agents.
    agent_link: SeparateInstructionLink | None = None
    parent: QWidget | None = None  # confirm()'s parent, as the other Type toggles have.


class StepDescriptionModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepDescriptionDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps

        def field_for(step_id: str) -> TextField[Any] | None:
            if not deps.library.has(step_id):
                return None
            return ModuleTextField(deps.library, step_id, MODULE_ID)

        def area_for_target(step_id: str) -> AreaFor | None:
            files = deps.files
            if files is None or not deps.library.has(step_id):
                return None
            return lambda: files(step_id, MODULE_ID)

        deps.details.register(
            InspectorSection(
                id=f"{MODULE_ID}.details",
                label=SPEC.label,
                order=20,
                stretch=1,  # The prose is what the leftover height is for.
                factory=lambda: DescriptionSection(
                    field_for,
                    deps.undo,
                    PLACEHOLDER,
                    area_for_target,
                    agent_link=deps.agent_link,
                    library=deps.library,
                ),
                shown_for=lambda step_id: step_id is not None
                and deps.library.has(step_id)
                and enabled(deps.library.step(step_id)),
            )
        )
        deps.actions.register(
            ActionSpec(
                id="description.toggle",
                label=SPEC.label,
                menu="Step",
                group="type",
                submenu="Type",
                order=80,
                tip="Give this step prose saying what it is — and what an agent is briefed with",
                state=self._current,
                run=self._toggle,
            )
        )

    def _current(self, context: Context) -> ActionState:
        step = self._focused(context)
        if step is None:
            return DISABLED
        return ActionState(checked=enabled(step))

    def _toggle(self, context: Context) -> None:
        step = self._focused(context)
        if step is None:
            return
        if not enabled(step):
            self._deps.undo.push(
                SetModuleDataCommand(
                    step.id, MODULE_ID, write_state(True), label="Add Description"
                )
            )
            return
        prose = read(step)
        if prose and not confirm(
            self._deps.parent,
            "Clear Description",
            f"Remove the description from {step.title or 'this step'!r}? It is not kept.",
        ):
            return
        # Mark and prose in one command, so a single Ctrl+Z restores both — the shape the
        # agent toggle established for exactly this pair of stores.
        clear: list[Command] = [
            SetModuleDataCommand(step.id, MODULE_ID, write_state(False), label="Clear Description")
        ]
        if prose:
            edit = TextEdit(step.id, MODULE_ID, 0, prose, "")
            clear.insert(0, EditTextCommand(edit, label="Clear Description"))
        self._deps.undo.push(
            clear[0] if len(clear) == 1 else CompositeCommand("Clear Description", clear)
        )

    def _focused(self, context: Context) -> Step | None:
        step_id = context.focus_entity("step")
        if step_id is None or not self._deps.library.has(step_id):
            return None
        return self._deps.library.step(step_id)
