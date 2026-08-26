"""Estimation, in the running application.

One registration and one offer. The registration is the Estimate tab: which panel shows it,
and what else is beside it, is not this module's business. The offer is the start-date bar —
a widget somebody else hosts, exposed as a ``create_…`` the way ``step_properties`` exposes
its panel, because a control that belongs to *one* surface has no business in a registry.
"""

from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from dplanner.domain.model import Product, ProjectId
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.undo import UndoService
from dplanner.modules.estimation.aspect import DATA_FORMAT, MODULE_ID, SPEC
from dplanner.modules.estimation.section import EstimateSection
from dplanner.modules.estimation.start_bar import StartDateBar


@dataclass(frozen=True)
class EstimationDeps:
    product: Product
    undo: UndoService[Product]
    sections: InspectorSectionRegistry


class EstimationModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: EstimationDeps) -> None:
        self._deps = deps

    def create_start_bar(
        self, project_id: ProjectId, parent: QWidget | None = None
    ) -> StartDateBar:
        """One project's start date, for whichever surface wants to show the schedule."""
        return StartDateBar(self._deps.product, self._deps.undo, project_id, parent)

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
