"""The ticket aspect, in the running application: the Ticket tab, and a Type toggle.

Off by default — most steps are not tracked anywhere else, so a plain step carries no
Ticket tab. The Type ▸ Ticket toggle turns the aspect on (an empty entry the tab then
fills in) and off (asking first when a reference exists — it is not kept).
"""

from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Step
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
from dplanner.modules.step_ticket.aspect import (
    DATA_FORMAT,
    MODULE_ID,
    SPEC,
    enabled,
    enabled_entry,
    read,
)
from dplanner.modules.step_ticket.section import TicketSection


@dataclass(frozen=True)
class StepTicketDeps:
    library: Library
    undo: UndoService[Library]
    sections: InspectorSectionRegistry
    actions: ActionRegistry
    parent: QWidget  # confirm()'s parent, as the delete verb's is.


class StepTicketModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepTicketDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.tab",
                label=SPEC.label,
                order=20,
                factory=lambda: TicketSection(deps.library, deps.undo),
                shown_for=lambda step_id: (
                    step_id is not None
                    and deps.library.has(step_id)
                    and enabled(deps.library.step(step_id))
                ),
            )
        )
        deps.actions.register(
            ActionSpec(
                id="ticket.toggle",
                label="Ticket",
                menu="Step",
                group="classify",
                submenu="Type",
                order=40,
                tip="Track this step against a ticket elsewhere; fill it in on the tab",
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
                SetModuleDataCommand(step.id, MODULE_ID, enabled_entry(), label="Add Ticket")
            )
            return
        if read(step) is not None:
            question = (
                f"Remove the ticket reference from {step.title or 'this step'!r}?"
                " The reference is not kept."
            )
            if not confirm(self._deps.parent, "Clear Ticket", question):
                return
        self._deps.undo.push(SetModuleDataCommand(step.id, MODULE_ID, {}, label="Clear Ticket"))

    def _focused(self, context: Context) -> Step | None:
        step_id = context.focus_entity("step")
        if step_id is None or not self._deps.library.has(step_id):
            return None
        return self._deps.library.step(step_id)
