"""The ticket aspect, in the running application: one registration, the Ticket tab."""

from dataclasses import dataclass

from dplanner.domain.model import Library
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.undo import UndoService
from dplanner.modules.step_ticket.aspect import DATA_FORMAT, MODULE_ID, SPEC
from dplanner.modules.step_ticket.section import TicketSection


@dataclass(frozen=True)
class StepTicketDeps:
    library: Library
    undo: UndoService[Library]
    sections: InspectorSectionRegistry


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
            )
        )
