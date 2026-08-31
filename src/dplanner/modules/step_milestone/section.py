"""The Milestone tab: one label, committed as one undoable command."""

from typing import Any

from PySide6.QtWidgets import QLabel, QLineEdit, QVBoxLayout

from dplanner.domain.model import Library, Step
from dplanner.framework.module_data_section import FIELD_GAP, PANEL_MARGIN, ModuleDataSection
from dplanner.framework.undo import UndoService
from dplanner.modules.step_milestone.aspect import MODULE_ID, read, write


class MilestoneSection(ModuleDataSection):
    def __init__(self, library: Library, undo: UndoService[Library]) -> None:
        super().__init__(library, undo, module_id=MODULE_ID, undo_label="Set Milestone")

        self.label = QLineEdit(self)
        self.label.setPlaceholderText("MVP, v1.0, v2…")
        self.label.editingFinished.connect(self.commit)

        note = QLabel(
            "Marks this step as a milestone point. When it lands is the schedule's answer;"
            " clearing the label makes it an ordinary step again.",
            self,
        )
        note.setObjectName("InspectorNote")
        note.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(FIELD_GAP)
        layout.addWidget(self.label)
        layout.addWidget(note)
        layout.addStretch(1)

    def load_step(self, step: Step | None) -> None:
        self.label.setText(read(step) if step is not None else "")

    def entry(self, step: Step) -> dict[str, Any]:
        return write(self.label.text())
