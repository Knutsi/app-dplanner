"""The release aspect, in the running application: one registration, the Release tab."""

from dataclasses import dataclass

from dplanner.domain.model import Product
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.undo import UndoService
from dplanner.modules.step_release.aspect import DATA_FORMAT, MODULE_ID, SPEC
from dplanner.modules.step_release.section import ReleaseSection


@dataclass(frozen=True)
class StepReleaseDeps:
    product: Product
    undo: UndoService[Product]
    sections: InspectorSectionRegistry


class StepReleaseModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: StepReleaseDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.tab",
                label=SPEC.label,
                order=50,
                factory=lambda: ReleaseSection(deps.product, deps.undo),
            )
        )
