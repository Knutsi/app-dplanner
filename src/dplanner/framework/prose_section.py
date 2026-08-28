"""A detail-panel section over one prose document.

The framework already owns the hard half of editing prose — :class:`TextBinding` turns every
keystroke into an undo command and keeps other views of the same document in sync. What was
missing is the small, easy-to-get-wrong half around it: a widget that re-binds when the panel
is told to show something else, and detaches when it is told to show nothing.

That is worth writing once because getting it wrong is quiet. A binding left pointing at a
deleted node reaches the model on the next keystroke and fails to find it; a binding not
closed before re-binding leaves the old one listening.

It knows nothing about any model: the caller supplies a factory that turns a target id into a
:class:`TextField`, or into ``None`` when there is nothing to edit.
"""

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from dplanner.framework.text_binding import TextBinding, TextField
from dplanner.framework.undo import UndoService

# DESIGN.md: side panels get 16 px outer margins.
PANEL_MARGIN = 16


class ProseSection(QWidget):
    """One editable document, bound through the undo stack, re-bound on every target."""

    def __init__(
        self,
        field_for: Callable[[str], TextField[Any] | None],
        undo: UndoService[Any],
        placeholder: str = "",
    ) -> None:
        super().__init__()
        self._field_for = field_for
        self._undo = undo
        self._binding: TextBinding[Any] | None = None

        self.edit = QPlainTextEdit(self)
        self.edit.setObjectName("InspectorNotes")
        self.edit.setPlaceholderText(placeholder)
        self.edit.setFrameShape(QPlainTextEdit.Shape.NoFrame)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.addWidget(self.edit)

    # -- the InspectorExtension contract -------------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def show_target(self, target_id: str | None) -> None:
        self._close_binding()
        field = self._field_for(target_id) if target_id is not None else None
        if field is None:
            self.edit.setPlainText("")
            self.setEnabled(False)
            return
        self.setEnabled(True)
        self._binding = TextBinding(self.edit, field, self._undo)

    def dispose(self) -> None:
        self._close_binding()

    def _close_binding(self) -> None:
        if self._binding is not None:
            self._binding.close()
            # close() only disconnects; the binding is parented to the editor, which
            # outlives it, so without this every selection change would leave one behind.
            self._binding.setParent(None)
            self._binding = None
