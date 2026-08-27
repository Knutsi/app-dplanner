"""The handoff aspect, in the running application: one registration, the Handoff tab."""

from dataclasses import dataclass

from dplanner.domain.model import Product
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.undo import UndoService
from dplanner.modules.step_handoff.aspect import DATA_FORMAT, MODULE_ID, SPEC
from dplanner.modules.step_handoff.handoff import FilesFor
from dplanner.modules.step_handoff.section import HandoffSection


@dataclass(frozen=True)
class StepHandoffDeps:
    product: Product
    undo: UndoService[Product]
    sections: InspectorSectionRegistry
    # Where a step's handoff files live — the store's `files`, handed in so this module
    # never names a store.
    files: FilesFor


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
                factory=lambda: HandoffSection(deps.product, deps.undo, deps.files),
            )
        )
