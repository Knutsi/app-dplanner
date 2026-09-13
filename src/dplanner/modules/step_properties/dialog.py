"""The step detail panel, briefly modal: what a double-click on a step opens.

A second :class:`StepPanel` in a dialog — the sanctioned second host of the section
contract — driven by ``show_step`` directly rather than by the context, so it stays on the
step it was opened about. On the frame like every other dialog, and **carrying Close and
nothing else**: every edit inside it is already applied and already on the undo stack, so
there is nothing to confirm and nothing to cancel — but a window manager that draws no
title bar leaves Escape as the only way out, and a way out nothing shows is not one. So
the footer holds the single dismissal and no primary; DESIGN.md's *Buttons* has the rule.

The frame prints no heading, so what the dialog shows is the panel and nothing above it —
the same surface the dock anchors, briefly modal. Its **window** title is the step's own
name, which is what a task switcher needs to tell two of these apart.

It opens with the Name field focused and its text selected: a step just born by New or a
double-click on empty canvas arrives here titled "New step", and typing replaces that.
"""

from collections.abc import Sequence

from PySide6.QtWidgets import QLineEdit, QWidget

from dplanner.domain.model import Library, NodeId, StepId
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.aspect_bar import AspectTemplate
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.inspector import InspectorSection
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.modules.step_properties.panel import StepPanel

# Room for the Tests tab's list beside its editor. The frame clamps it to SCREEN_SHARE of
# the screen, so a laptop still gets a dialog it can show whole.
DIALOG_WIDTH = 900
DIALOG_HEIGHT = 850
TITLE = "Step details"


class StepDetailsDialog(DialogFrame):
    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        actions: ActionRegistry,
        *,
        sections: Sequence[InspectorSection],
        templates: Sequence[AspectTemplate],
        theme: ThemeService,
        step_id: StepId,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(TITLE, parent, size=(DIALOG_WIDTH, DIALOG_HEIGHT))
        self._library = library
        self._step_id = step_id

        self.panel = StepPanel(
            library,
            undo,
            actions,
            sections=sections,
            templates=templates,
            theme=theme,
            parent=self,
        )
        self.panel.show_step(step_id)
        self._retitle()
        self._unsubscribe = library.field_changed.connect(self._on_field)

        self.body_layout.addWidget(self.panel, 1)
        self.add_dismiss("Close")

        name = self.name_edit()
        if name is not None:
            name.setFocus()
            name.selectAll()

    def name_edit(self) -> QLineEdit | None:
        """The Name field — the block this module registers first on the Details tab."""
        return self.panel.findChild(QLineEdit, "InspectorTitle")

    def dispose(self) -> None:
        self._unsubscribe()
        self.panel.dispose()

    def _retitle(self) -> None:
        """The window title is the step's own name, and follows a rename.

        A task switcher showing four identical *Step details* entries says nothing about
        which step each one holds.
        """
        title = self._library.step(self._step_id).title if self._library.has(self._step_id) else ""
        self.setWindowTitle(title or TITLE)

    def _on_field(self, node_id: NodeId, field: str, _origin: object) -> None:
        if node_id == self._step_id and field == "title":
            self._retitle()
