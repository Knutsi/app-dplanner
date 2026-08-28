"""The Ticket tab: where a step is tracked outside DPlanner.

Three line edits and no integration — recording the link is the whole feature, and it is
deliberately not the beginning of a tracker client.
"""

from typing import Any

from PySide6.QtWidgets import QFormLayout, QLineEdit

from dplanner.domain.model import Product, Step
from dplanner.framework.module_data_section import FORM_SPACING, PANEL_MARGIN, ModuleDataSection
from dplanner.framework.undo import UndoService
from dplanner.modules.step_ticket.aspect import FIELDS, MODULE_ID, Ticket, read, write

PLACEHOLDERS = {
    "system": "jira, github, linear…",
    "key": "WID-14",
    "url": "https://…",
}


class TicketSection(ModuleDataSection):
    def __init__(self, product: Product, undo: UndoService[Product]) -> None:
        super().__init__(product, undo, module_id=MODULE_ID, undo_label="Set Ticket")

        layout = QFormLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(FORM_SPACING)
        self.edits: dict[str, QLineEdit] = {}
        for field in FIELDS:
            edit = QLineEdit(self)
            edit.setPlaceholderText(PLACEHOLDERS[field])
            edit.editingFinished.connect(self.commit)
            self.edits[field] = edit
            layout.addRow(field.title(), edit)

    def load_step(self, step: Step | None) -> None:
        ticket = read(step) if step is not None else None
        for field, edit in self.edits.items():
            edit.setText(getattr(ticket, field) if ticket else "")

    def entry(self, step: Step) -> dict[str, Any]:
        return write(Ticket(**{f: self.edits[f].text().strip() for f in FIELDS}))
