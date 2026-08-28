"""The step detail panel, briefly front and centre as a modal dialog.

This hosts a second :class:`StepPanel` — the same widget the window anchors on the right —
so the dialog and the panel cannot drift: an aspect module registers one
``InspectorSection`` and appears in both. Building a second stack is the section contract's
sanctioned use (one extension instance per host), not a workaround; the project panel
already hosts the same registry a third way, as cards.

The dialog is driven by ``show_step`` directly and never reads the context: it is opened
*about* a step and stays on it. Whoever opens it owes it a ``dispose()`` once ``exec()``
returns — the panel subscribes to model and theme signals, and a closed dialog must not
keep hearing them.
"""

from collections.abc import Sequence

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout, QWidget

from dplanner.domain.model import Library, StepId
from dplanner.framework.inspector import InspectorSection
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.modules.step_properties.panel import PANEL_MARGIN, StepPanel

# DESIGN.md: dialogs get 20 px outer margins and 12 px between sections. The panel brings
# its own 16 px side margins, so the dialog adds only the difference.
DIALOG_MARGIN = 20
SECTION_GAP = 12
SIDE_MARGIN = DIALOG_MARGIN - PANEL_MARGIN

# Roomier than the 360 px side panel it mirrors — prose and tables breathe here — but
# clamped to the screen so a laptop never gets a dialog it cannot show whole.
DIALOG_WIDTH = 680
DIALOG_HEIGHT = 620
SCREEN_CLEARANCE = 80  # Left around the dialog when the screen is the constraint.


class StepDetailsDialog(QDialog):
    """One step's details, modally. Edits go through the undo stack like the panel's."""

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        sections: Sequence[InspectorSection],
        theme: ThemeService | None,
        step_id: StepId,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        title = library.step(step_id).title if library.has(step_id) else ""
        self.setWindowTitle(title or "Step Details")

        self.panel = StepPanel(library, undo, sections=sections, theme=theme, parent=self)
        self.panel.show_step(step_id)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SIDE_MARGIN, DIALOG_MARGIN, SIDE_MARGIN, DIALOG_MARGIN)
        layout.setSpacing(SECTION_GAP)
        layout.addWidget(self.panel, 1)
        layout.addWidget(buttons)
        width, height = DIALOG_WIDTH, DIALOG_HEIGHT
        screen = self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(width, available.width() - SCREEN_CLEARANCE)
            height = min(height, available.height() - SCREEN_CLEARANCE)
        self.resize(width, height)

    def dispose(self) -> None:
        # A title still being typed commits on focus-out; force it before detaching, or
        # closing the dialog mid-edit would silently drop the rename.
        self.panel.title_edit.clearFocus()
        self.panel.dispose()
