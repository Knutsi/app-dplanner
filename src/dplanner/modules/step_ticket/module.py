"""The ticket aspect, in the running application: the Ticket tab, and a Type toggle.

Off by default — most steps are not tracked anywhere else, so a plain step carries no
Ticket tab. The Type ▸ Ticket toggle turns the aspect on (an empty entry the tab then
fills in) and off (shelving the reference, so turning it back on brings it back).
"""

from dataclasses import dataclass

from dplanner.domain.model import Library
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.aspect_toggle import aspect_toggle
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.undo import UndoService
from dplanner.modules.step_ticket.aspect import (
    DATA_FORMAT,
    MODULE_ID,
    SPEC,
    enabled,
    enabled_entry,
)
from dplanner.modules.step_ticket.section import TicketSection
from dplanner.theme.icons import ticket_icon


@dataclass(frozen=True)
class StepTicketDeps:
    library: Library
    undo: UndoService[Library]
    sections: InspectorSectionRegistry
    actions: ActionRegistry


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
            aspect_toggle(
                id="ticket.toggle",
                label="Ticket",
                order=40,
                module_id=MODULE_ID,
                library=deps.library,
                undo=deps.undo,
                enabled=enabled,
                fresh=lambda _step, _project: enabled_entry(),
                icon=ticket_icon,
                tip="Track this step against a ticket elsewhere; fill it in on the tab",
            )
        )
