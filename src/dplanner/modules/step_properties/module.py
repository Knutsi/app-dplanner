"""The module that provides THE step detail panel, and registers nothing at all.

Its whole job is :meth:`create_panel`, which the composition root hands to every host as a
typed capability. That is the seam: a host declares the panel interface it needs as its own
``Protocol`` and receives a factory for it, so no module ever imports another, and the day a
second surface wants a step panel it costs one line in the composition root.

The pattern is Writer's ``segment_properties``, which serves three unrelated hosts —
a corkboard, a segment editor and a continuous editor — the same way.
"""

from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from dplanner.domain.model import Product
from dplanner.framework.inspector import InspectorSectionRegistry
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.modules.step_properties.panel import StepPanel

MODULE_ID = "step_properties"


@dataclass(frozen=True)
class StepPropertiesDeps:
    product: Product
    undo: UndoService[Product]
    # Whoever registered an aspect editor. Read when a panel is built, not here, so a
    # contributing module's position in the composition root is free.
    sections: InspectorSectionRegistry
    theme: ThemeService  # Tab glyphs follow the theme's secondary text colour.


class StepPropertiesModule:
    id = MODULE_ID

    def __init__(self, deps: StepPropertiesDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        """Nothing to install — this module only builds panels for its hosts."""

    def create_panel(self, empty: QWidget | None = None) -> StepPanel:
        """One panel for one host. ``empty`` is what shows when no step is selected."""
        return StepPanel(
            self._deps.product,
            self._deps.undo,
            sections=self._deps.sections.sections(),
            empty=empty,
            theme=self._deps.theme,
        )
