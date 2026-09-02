"""The step's name, as the first block of the Details tab.

A block like any other — registered into ``step_details`` at order 0 — so the modal's
control stack reads top-down from the one field every step has. It commits on
``editingFinished`` through the undo stack and follows a rename made elsewhere, ignoring
the echo of its own write while it still has focus.
"""

from PySide6.QtWidgets import QLineEdit, QWidget

from dplanner.domain.commands import SetFieldCommand
from dplanner.domain.model import Library, NodeId, StepId
from dplanner.framework.undo import UndoService


class NameBlock:
    def __init__(self, library: Library, undo: UndoService[Library]) -> None:
        self._library = library
        self._undo = undo
        self._step_id: StepId | None = None
        self.edit = QLineEdit()
        self.edit.setObjectName("InspectorTitle")
        self.edit.setPlaceholderText("What this step is")
        self.edit.editingFinished.connect(self._commit)
        self._unsubscribe = library.field_changed.connect(self._on_field)

    @property
    def widget(self) -> QWidget:
        return self.edit

    def show_target(self, target_id: str | None) -> None:
        self._step_id = target_id if target_id and self._library.has(target_id) else None
        self.edit.setText(self._library.step(self._step_id).title if self._step_id else "")

    def dispose(self) -> None:
        self.edit.clearFocus()  # Flush an in-flight rename before the panel goes.
        self._unsubscribe()

    def _commit(self) -> None:
        # editingFinished also fires during teardown, when the step may already be gone.
        if self._step_id is None or not self._library.has(self._step_id):
            return
        value = self.edit.text().strip()
        if value != self._library.step(self._step_id).title:
            self._undo.push(SetFieldCommand(self._step_id, "title", value, view_origin=self))

    def _on_field(self, node_id: NodeId, field: str, origin: object) -> None:
        if node_id != self._step_id or field != "title":
            return
        # Not a plain `origin is self`: an undo performed while this field has focus still
        # has to reach it, and only a focused field is mid-edit.
        if not (origin is self and self.edit.hasFocus()):
            self.edit.setText(self._library.step(node_id).title)
