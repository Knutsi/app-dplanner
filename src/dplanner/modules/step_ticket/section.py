"""The Ticket tab: where a step is tracked outside DPlanner.

Three line edits and no integration — recording the link is the whole feature, and it is
deliberately not the beginning of a tracker client.
"""

from PySide6.QtWidgets import QFormLayout, QLineEdit, QWidget

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import NodeId, Product, StepId
from dplanner.framework.undo import UndoService
from dplanner.modules.step_ticket.aspect import FIELDS, MODULE_ID, Ticket, read, write

FORM_SPACING = 8
PANEL_MARGIN = 16

PLACEHOLDERS = {
    "system": "jira, github, linear…",
    "key": "WID-14",
    "url": "https://…",
}


class TicketSection(QWidget):
    def __init__(self, product: Product, undo: UndoService[Product]) -> None:
        super().__init__()
        self._product = product
        self._undo = undo
        self._step_id: StepId | None = None
        self._loading = False

        layout = QFormLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(FORM_SPACING)
        self.edits: dict[str, QLineEdit] = {}
        for field in FIELDS:
            edit = QLineEdit(self)
            edit.setPlaceholderText(PLACEHOLDERS[field])
            edit.editingFinished.connect(self._commit)
            self.edits[field] = edit
            layout.addRow(field.title(), edit)

        self._unsubscribe = product.module_data_changed.connect(self._on_module_data)

    @property
    def widget(self) -> QWidget:
        return self

    def show_target(self, target_id: str | None) -> None:
        self._step_id = target_id
        self.setEnabled(target_id is not None)
        self._load()

    def dispose(self) -> None:
        self._unsubscribe()

    def _load(self) -> None:
        ticket = None
        if self._step_id is not None and self._product.has(self._step_id):
            ticket = read(self._product.step(self._step_id))
        self._loading = True
        try:
            for field, edit in self.edits.items():
                edit.setText(getattr(ticket, field) if ticket else "")
        finally:
            self._loading = False

    def _commit(self) -> None:
        if self._loading or self._step_id is None or not self._product.has(self._step_id):
            return
        ticket = Ticket(**{f: self.edits[f].text().strip() for f in FIELDS})
        entry = write(ticket)
        if entry == self._product.step(self._step_id).module_data.get(MODULE_ID, {}):
            return
        self._undo.push(
            SetModuleDataCommand(
                self._step_id, MODULE_ID, entry, view_origin=self, label="Set Ticket"
            )
        )

    def _on_module_data(self, node_id: NodeId, module_id: str, origin: object) -> None:
        if node_id != self._step_id or module_id != MODULE_ID:
            return
        # The echo of our own write is ignored only while a field is being edited; an undo
        # made with the panel focused still has to reach the widgets.
        if origin is self and any(edit.hasFocus() for edit in self.edits.values()):
            return
        self._load()
