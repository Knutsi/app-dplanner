"""The estimation aspect, in the running application.

One registration: the Estimate tab. Which panel shows it, and what else is beside it, is
not this module's business — it registers an :class:`InspectorSection` and the composition
root does the rest.
"""

from dataclasses import dataclass

from dplanner.domain.model import Product
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.undo import UndoService
from dplanner.modules.step_estimation.aspect import DATA_FORMAT, MODULE_ID, SPEC
from dplanner.modules.step_estimation.section import EstimateSection


@dataclass(frozen=True)
class StepEstimationDeps:
    product: Product
    undo: UndoService[Product]
    sections: InspectorSectionRegistry


class StepEstimationModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepEstimationDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.tab",
                label=SPEC.label,
                order=10,
                factory=lambda: EstimateSection(deps.product, deps.undo),
            )
        )
