"""The handoff aspect, in the running application: the Handoff tab and its Type toggle."""

from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from dplanner.domain.commands import (
    Command,
    CompositeCommand,
    EditTextCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import Library, Step, TextEdit
from dplanner.domain.store import FilesFor
from dplanner.framework.action_registry import (
    DISABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import confirm
from dplanner.modules.step_handoff.aspect import (
    DATA_FORMAT,
    MODULE_ID,
    SPEC,
    enabled,
    read_note,
    write_state,
)
from dplanner.modules.step_handoff.section import HandoffSection


@dataclass(frozen=True)
class StepHandoffDeps:
    library: Library
    undo: UndoService[Library]
    sections: InspectorSectionRegistry
    actions: ActionRegistry
    # Where a step's handoff files live — the store's `files`, handed in so this module
    # never names a store.
    files: FilesFor
    parent: QWidget | None = None  # confirm()'s parent, as the other Type toggles have.


class StepHandoffModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepHandoffDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.tab",
                label=SPEC.label,
                order=60,
                factory=lambda: HandoffSection(deps.library, deps.undo, deps.files),
                shown_for=lambda step_id: step_id is not None
                and deps.library.has(step_id)
                and enabled(deps.library.step(step_id)),
            )
        )
        deps.actions.register(
            ActionSpec(
                id="handoff.toggle",
                label=SPEC.label,
                menu="Step",
                group="type",
                submenu="Type",
                order=90,
                tip="Pass a note and files forward to whoever picks up the work after this",
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
                SetModuleDataCommand(step.id, MODULE_ID, write_state(True), label="Add Handoff")
            )
            return
        note = read_note(step)
        if note and not confirm(
            self._deps.parent,
            "Clear Handoff",
            f"Remove the handoff from {step.title or 'this step'!r}? The note is not kept.",
        ):
            return
        # Note and mark in one command, so one Ctrl+Z restores both. Files in the module's
        # area are left alone: they were never undoable, and dropping them here would make
        # a toggle destroy something no undo could bring back.
        clear: list[Command] = [
            SetModuleDataCommand(step.id, MODULE_ID, write_state(False), label="Clear Handoff")
        ]
        if note:
            edit = TextEdit(step.id, MODULE_ID, 0, note, "")
            clear.insert(0, EditTextCommand(edit, label="Clear Handoff"))
        self._deps.undo.push(
            clear[0] if len(clear) == 1 else CompositeCommand("Clear Handoff", clear)
        )

    def _focused(self, context: Context) -> Step | None:
        step_id = context.focus_entity("step")
        if step_id is None or not self._deps.library.has(step_id):
            return None
        return self._deps.library.step(step_id)
