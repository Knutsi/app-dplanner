"""The step detail panel, briefly modal: what a double-click on a step opens.

A second :class:`StepPanel` in a dialog — the sanctioned second host of the section
contract — driven by ``show_step`` directly rather than by the context, so it stays on the
step it was opened about. It carries no buttons: every edit inside it is already applied
and already on the undo stack, so there is nothing to confirm and nothing to cancel, and
Escape (or the title bar) simply closes it. The aspect bar spans the top and the tab pages
run to the bottom edge, bringing their own margins.

It opens with the Name field focused and its text selected: a step just born by New or a
double-click on empty canvas arrives here titled "New step", and typing replaces that.
"""

from collections.abc import Sequence

from PySide6.QtWidgets import QDialog, QLineEdit, QVBoxLayout, QWidget

from dplanner.domain.model import Library, NodeId, StepId
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.aspect_bar import AspectTemplate
from dplanner.framework.inspector import InspectorSection
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.framework.undo_keys import install_undo_keys
from dplanner.modules.step_properties.panel import StepPanel

# Room for the Tests tab's list beside its editor, clamped to the screen with a margin
# so a laptop still gets a dialog it can show whole.
DIALOG_WIDTH = 900
DIALOG_HEIGHT = 850
SCREEN_CLEARANCE = 80


class StepDetailsDialog(QDialog):
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
        super().__init__(parent)
        self._library = library
        self._step_id = step_id
        self._retitle()
        install_undo_keys(self, undo)

        self.panel = StepPanel(
            library, undo, actions, sections=sections, templates=templates, theme=theme, parent=self
        )
        self.panel.show_step(step_id)
        self._unsubscribe = library.field_changed.connect(self._on_field)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.panel, 1)

        width, height = DIALOG_WIDTH, DIALOG_HEIGHT
        screen = self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(width, available.width() - SCREEN_CLEARANCE)
            height = min(height, available.height() - SCREEN_CLEARANCE)
        self.resize(width, height)

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
        title = self._library.step(self._step_id).title if self._library.has(self._step_id) else ""
        self.setWindowTitle(title or "Step Details")

    def _on_field(self, node_id: NodeId, field: str, _origin: object) -> None:
        if node_id == self._step_id and field == "title":
            self._retitle()
