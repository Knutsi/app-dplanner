"""The agent-instruction aspect, in the running application: one registration, the Agent tab.

Deliberately a near-twin of ``step_description``'s module, and that is the price of "modules
never import each other". The part worth sharing is already shared:
:class:`~dplanner.framework.prose_section.ProseSection` and ``ModuleTextField`` do all the
work, and what is left here is the three facts that make this aspect itself — which document,
what to call it, and where it sits among the tabs.
"""

from dataclasses import dataclass
from typing import Any

from dplanner.domain.fields import ModuleTextField
from dplanner.domain.model import Product
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.prose_section import ProseSection
from dplanner.framework.text_binding import TextField
from dplanner.framework.undo import UndoService
from dplanner.modules.step_agent_instruction.aspect import DATA_FORMAT, MODULE_ID, SPEC

PLACEHOLDER = "How to carry this step out: which files, which conventions, what done means."


@dataclass(frozen=True)
class StepAgentInstructionDeps:
    product: Product
    undo: UndoService[Product]
    sections: InspectorSectionRegistry


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

        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.tab",
                label=SPEC.label,
                order=40,
                factory=lambda: ProseSection(field_for, deps.undo, PLACEHOLDER),
            )
        )
