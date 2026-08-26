"""The module that provides THE step detail panel, and anchors it in the window.

There is one panel, not one per tab: a panel built inside an activity is duplicated the moment
the window is split, and two copies of one editor is the same width spent twice. So this
registers a :class:`~dplanner.framework.panels.PanelSpec` and the dock puts it in an area.

Two seams keep it from knowing anything else in the application. **It never learns who selected
a step** — the panel reads the context, so a canvas, a table and anything added later reach it
without being its host. **It never learns which aspects exist** — those arrive from
``sections``, read when the panel is built, so a contributing module's position in the
composition root is free (its position *ahead of this one* is not; see the root's comment).
"""

from dataclasses import dataclass

from dplanner.domain.model import Product
from dplanner.framework.inspector import InspectorSectionRegistry
from dplanner.framework.panels import PanelArea, PanelRegistry, PanelSpec
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.modules.step_properties.panel import StepPanel

MODULE_ID = "step_properties"
PANEL_ID = f"{MODULE_ID}.step"


@dataclass(frozen=True)
class StepPropertiesDeps:
    product: Product
    undo: UndoService[Product]
    panels: PanelRegistry
    # Whoever registered an aspect editor. Read when the panel is built, not here, so a
    # contributing module's position in the composition root is free.
    sections: InspectorSectionRegistry
    theme: ThemeService  # Tab glyphs follow the theme's secondary text colour.


class StepPropertiesModule:
    id = MODULE_ID

    def __init__(self, deps: StepPropertiesDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        # Order 20: below the project form, which is about the thing the step is part of.
        self._deps.panels.register(
            PanelSpec(
                id=PANEL_ID,
                title="Step",
                factory=self._create_panel,
                area=PanelArea.RIGHT,
                order=20,
            )
        )

    def _create_panel(self) -> StepPanel:
        return StepPanel(
            self._deps.product,
            self._deps.undo,
            sections=self._deps.sections.sections(),
            theme=self._deps.theme,
        )
