"""The module that provides THE step detail panel, and anchors it in the window.

There is one panel, not one per tab: a panel built inside an activity is duplicated the moment
the window is split, and two copies of one editor is the same width spent twice. So this
registers a :class:`~dplanner.framework.panels.PanelSpec` and the dock puts it in an area.

Two seams keep it from knowing anything else in the application. **It never learns who selected
a step** — the panel reads the context, so a canvas, a table and anything added later reach it
without being its host. **It never learns which aspects exist** — those arrive from
``sections``, read when the panel is built, so a contributing module's position in the
composition root is free (its position *ahead of this one* is not; see the root's comment).
The bar across the panel's top renders the Step ▸ Type submenu the same way; the
*templates* worded on its left — combinations of those toggles — are ``templates``, named
by the root.

It also owns ``steps.details``: the same panel as a modal dialog, which is what every view's
double-click on a step runs — and what New opens on the step it just made. One spec, so the
gesture is in the palette and the Step menu too, and the state gate decides once.
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
from dplanner.framework.aspect_bar import AspectTemplate
from dplanner.framework.context import Context
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.panels import PanelArea, PanelRegistry, PanelSpec
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.modules.step_properties.details import DetailsSection
from dplanner.modules.step_properties.dialog import StepDetailsDialog
from dplanner.modules.step_properties.name import NameBlock
from dplanner.modules.step_properties.panel import StepPanel

MODULE_ID = "step_properties"
PANEL_ID = f"{MODULE_ID}.step"
NAME_BLOCK_ID = f"{MODULE_ID}.name"


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
    # Whoever registered a block for the first tab. Read inside the Details factory, so
    # the same freedom holds — a block registrant only has to come before a panel exists.
    details: InspectorSectionRegistry
    theme: ThemeService  # Tab glyphs and the bar's follow the theme's secondary text colour.
    # The templates the bar words on its left — named combinations of Type toggles,
    # each with the body tone it wears when the step carries exactly that set. Wired,
    # never inferred: the root names them, as it names the scope kinds.
    templates: tuple[AspectTemplate, ...] = ()


class StepPropertiesModule:
    id = MODULE_ID

    def __init__(self, deps: StepPropertiesDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        # The name leads the Details tab: a block like any other, at order 0, so the stack
        # reads top-down from the one field every step has.
        deps.details.register(
            InspectorSection(
                id=NAME_BLOCK_ID,
                label="Name",
                order=0,
                factory=lambda: NameBlock(deps.library, deps.undo),
            )
        )
        # The first tab: the blocks other modules registered into `details`, stacked. This
        # module contributes the host, not the content — same seam as the panel itself.
        # Always shown: a step always has a name.
        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.details",
                label="Details",
                order=10,
                factory=lambda: DetailsSection(deps.library, deps.details.sections()),
            )
        )
        # Order 20: below the project form, which is about the thing the step is part of.
        deps.panels.register(
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
        deps.actions.register(
            ActionSpec(
                id="steps.details",
                label="Step De&tails…",  # &t: D and R are Delete's and Rename's.
                menu="Step",
                group="open",
                order=10,
                tip="Edit this step's name and aspects in a dialog",
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
            self._deps.actions,
            sections=self._deps.sections.sections(),
            templates=self._deps.templates,
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
            self._deps.actions,
            sections=self._deps.sections.sections(),
            templates=self._deps.templates,
            theme=self._deps.theme,
        )
