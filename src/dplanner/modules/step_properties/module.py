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
from dplanner.framework.action_dialog import TogglesDialog
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import (
    SCOPE_SELECTION,
    Context,
    ContextNode,
    selection_uri,
)
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.panels import PanelArea, PanelRegistry, PanelSpec
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.modules.step_properties.details import DetailsSection
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
    # Whoever registered a block for the first tab. Read inside the Details factory, so
    # the same freedom holds — a block registrant only has to come before a panel exists.
    details: InspectorSectionRegistry
    theme: ThemeService  # Tab glyphs follow the theme's secondary text colour.


class StepPropertiesModule:
    id = MODULE_ID

    def __init__(self, deps: StepPropertiesDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        # The first tab: the blocks other modules registered into `details`, stacked. This
        # module contributes the host, not the content — same seam as the panel itself.
        self._deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.details",
                label="Details",
                order=10,
                factory=lambda: DetailsSection(
                    self._deps.library, self._deps.details.sections()
                ),
                # The tab *is* its blocks: once every one has hidden itself there is
                # nothing behind it, and a tab opening onto blank space teaches nothing.
                # Asked of the registry this module already holds, so nothing new is wired.
                shown_for=self._has_details,
            )
        )
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

    def _has_details(self, step_id: str | None) -> bool:
        return any(
            section.shown_for is None or section.shown_for(step_id)
            for section in self._deps.details.sections()
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
            on_add_aspect=self._choose_aspects,
        )
        dialog.exec()
        dialog.dispose()

    def _choose_aspects(self, panel: StepPanel) -> None:
        """The "+" beside the tabs: which aspects this step carries.

        A dialog that **renders** the Step ▸ Type submenu rather than listing aspects of its
        own — the same rule as a right-click menu, one level along. Each row runs the owning
        module's toggle, so it stays one undoable command with its own confirmation, and an
        aspect a build does not ship simply has no row.

        The context names the panel's own step rather than the window's selection: a panel
        inside the details dialog is showing a step nobody selected, and the toggles must
        act on what the user is looking at.
        """
        step_id = panel.current_step_id()
        if step_id is None or not self._deps.library.has(step_id):
            return
        node = ContextNode(selection_uri("step", step_id))
        dialog = TogglesDialog(
            self._deps.actions,
            lambda: Context({SCOPE_SELECTION: (node,)}),
            menu="Step",
            submenu="Type",
            title="Aspects",
            note="What this step carries. Turning one off drops what it held.",
            parent=panel,
        )
        dialog.exec()

    def _create_panel(self) -> StepPanel:
        panel = StepPanel(
            self._deps.library,
            self._deps.undo,
            sections=self._deps.sections.sections(),
            theme=self._deps.theme,
        )
        panel.add_aspect.clicked.connect(lambda: self._choose_aspects(panel))
        return panel
