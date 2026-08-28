"""The module that provides THE step detail panel, and anchors it in the window.

There is one panel, not one per tab: a panel built inside an activity is duplicated the moment
the window is split, and two copies of one editor is the same width spent twice. So this
registers a :class:`~dplanner.framework.panels.PanelSpec` and the dock puts it in an area.

Two seams keep it from knowing anything else in the application. **It never learns who selected
a step** — the panel reads the context, so a canvas, a table and anything added later reach it
without being its host. **It never learns which aspects exist** — those arrive from
``sections``, read when the panel is built, so a contributing module's position in the
composition root is free (its position *ahead of this one* is not; see the root's comment).

It also owns ``steps.details``: the same panel as a modal dialog, which is what every view's
double-click on a step runs. One spec, so the gesture is in the palette and the Step menu
too, and the state gate decides once.
"""

from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from dplanner.domain.model import Library
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context
from dplanner.framework.inspector import InspectorSectionRegistry
from dplanner.framework.panels import PanelArea, PanelRegistry, PanelSpec
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.modules.step_properties.dialog import StepDetailsDialog
from dplanner.modules.step_properties.panel import StepPanel

MODULE_ID = "step_properties"
PANEL_ID = f"{MODULE_ID}.step"


@dataclass(frozen=True)
class StepPropertiesDeps:
    library: Library
    undo: UndoService[Library]
    panels: PanelRegistry
    actions: ActionRegistry
    parent: QWidget  # The details dialog's parent.
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
        # The same panel, modally. Every view's double-click runs this one spec, so the
        # gesture exists in the palette and the Step menu too, and is state-gated once.
        self._deps.actions.register(
            ActionSpec(
                id="steps.details",
                label="Step De&tails…",  # &t: D and R are Delete's and Rename's.
                menu="Step",
                group="open",
                order=10,
                tip="Edit this step's title and aspects in a dialog",
                state=self._one_step,
                run=self._open_details,
            )
        )

    def _one_step(self, context: Context) -> ActionState:
        step_id = context.selected_entity("step")
        if step_id is None or not self._deps.library.has(step_id):
            return DISABLED
        return ENABLED

    def _open_details(self, context: Context) -> None:
        step_id = context.selected_entity("step")
        if step_id is None or not self._deps.library.has(step_id):
            return
        # Fresh per invocation: a cached dialog would need re-target and re-show logic for
        # nothing — the panel is cheap, and dispose() guarantees it stops hearing signals.
        dialog = StepDetailsDialog(
            self._deps.library,
            self._deps.undo,
            sections=self._deps.sections.sections(),
            theme=self._deps.theme,
            step_id=step_id,
            parent=self._deps.parent,
        )
        dialog.exec()
        dialog.dispose()

    def _create_panel(self) -> StepPanel:
        return StepPanel(
            self._deps.library,
            self._deps.undo,
            sections=self._deps.sections.sections(),
            theme=self._deps.theme,
        )
