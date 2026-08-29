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
from dplanner.framework.text_dialog import ExpandedTextDialog, attach_expand
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
        margin: int = PANEL_MARGIN,
        expand_title: str = "Editor",
    ) -> None:
        super().__init__()
        self._field_for = field_for
        self._undo = undo
        self._binding: TextBinding[Any] | None = None
        self._field: TextField[Any] | None = None
        self._placeholder = placeholder
        self._expand_title = expand_title

        self.edit = QPlainTextEdit(self)
        self.edit.setObjectName("InspectorNotes")
        self.edit.setPlaceholderText(placeholder)
        self.edit.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.expand_button = attach_expand(self.edit)
        self.expand_button.clicked.connect(self._open_expanded)
        self.expand_button.setEnabled(False)

        # ``margin`` is 0 when a host (a card, the Details tab) already owns the spacing.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.addWidget(self.edit)

    # -- the InspectorExtension contract -------------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def show_target(self, target_id: str | None) -> None:
        self._close_binding()
        field = self._field_for(target_id) if target_id is not None else None
        self._field = field
        self.expand_button.setEnabled(field is not None)
        if field is None:
            self.edit.setPlainText("")
            self.setEnabled(False)
            return
        self.setEnabled(True)
        self._binding = TextBinding(self.edit, field, self._undo)

    def dispose(self) -> None:
        self._field = None
        self._close_binding()

    def _open_expanded(self) -> None:
        """The same document in a big modal editor — a second binding, kept in sync
        through the foreign-change path, so typing in either shows in both."""
        if self._field is None:
            return
        dialog = ExpandedTextDialog(
            self._field,
            self._undo,
            title=self._expand_title,
            placeholder=self._placeholder,
            parent=self.window(),
        )
        dialog.exec()
        dialog.dispose()

    def _close_binding(self) -> None:
        if self._binding is not None:
            self._binding.close()
            # close() only disconnects; the binding is parented to the editor, which
            # outlives it, so without this every selection change would leave one behind.
            self._binding.setParent(None)
            self._binding = None
