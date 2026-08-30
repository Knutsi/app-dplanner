"""Expanding an editor is a second binding, not a copy.

A side panel gives prose a few hundred pixels; a long description or instruction deserves
a window. :class:`ExpandedTextDialog` opens the *same* :class:`TextField` in a modal
editor with its own :class:`TextBinding` — the inline editor stays live because each
binding sees the other's commands as foreign changes, exactly the mechanism that keeps a
CLI edit or an undo visible everywhere. The dialog holds no state of its own: closing it
loses nothing, because nothing ever lived only there.

:func:`attach_expand` is the one affordance that opens it — a small corner button on the
editor itself, so every host offers the same gesture without growing a header row.
"""

from typing import Any

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.markdown_highlight import MarkdownHighlighter
from dplanner.framework.text_binding import TextBinding, TextField
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import centered_column, make_text_well, space_lines

# DESIGN.md: dialogs get 20 px outer margins and 12 px between sections.
DIALOG_MARGIN = 20
SECTION_GAP = 12
SCREEN_SHARE = 0.8  # The same slice ImagePreviewDialog claims.
EDITOR_MEASURE = 760  # A readable prose measure; the column centres in a wider dialog.
BUTTON_INSET = 4  # The expand button's distance from the editor's corner.


class ExpandedTextDialog(QDialog):
    """One document, briefly in a window of its own. The opener owes ``dispose()``."""

    def __init__(
        self,
        field: TextField[Any],
        undo: UndoService[Any],
        *,
        title: str,
        placeholder: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)

        self.edit = QPlainTextEdit(self)
        self._highlighter = MarkdownHighlighter(self.edit.document(), self.edit)
        self.edit.setObjectName("InspectorNotes")
        self.edit.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.edit.setPlaceholderText(placeholder)
        make_text_well(self.edit)
        self._binding = TextBinding(self.edit, field, undo)
        space_lines(self.edit)  # After the binding's setPlainText, or the format is lost.

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)

        column = QVBoxLayout(self)
        column.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN)
        column.setSpacing(SECTION_GAP)
        column.addWidget(centered_column(self.edit, EDITOR_MEASURE), stretch=1)
        column.addWidget(buttons)

        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.resize(
                round(available.width() * SCREEN_SHARE),
                round(available.height() * SCREEN_SHARE),
            )
        self.edit.setFocus()

    def dispose(self) -> None:
        """Detach the binding — same contract as the step details dialog's opener."""
        self._binding.close()
        self._binding.setParent(None)


def attach_expand(editor: QPlainTextEdit) -> QToolButton:
    """A small expand button in ``editor``'s top-right corner; returns it for wiring.

    The caller connects ``clicked`` to whatever builds the dialog (the field is theirs to
    resolve) and may disable the button while there is nothing to edit.
    """
    button = QToolButton(editor)
    button.setText("⤢")
    button.setAutoRaise(True)
    button.setToolTip("Expand editor")
    _CornerAnchor(editor, button)
    button.show()
    return button


class _CornerAnchor(QObject):
    """Keeps a button pinned to its editor's top-right corner, clear of the scrollbar."""

    def __init__(self, editor: QPlainTextEdit, button: QToolButton) -> None:
        super().__init__(button)
        self._editor = editor
        self._button = button
        editor.installEventFilter(self)
        self._place()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        if obj is self._editor and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._place()
        return super().eventFilter(obj, event)

    def _place(self) -> None:
        bar = self._editor.verticalScrollBar()
        clearance = bar.sizeHint().width() if bar is not None and bar.isVisible() else 0
        size = self._button.sizeHint()
        self._button.resize(size)
        self._button.move(
            self._editor.width() - size.width() - clearance - BUTTON_INSET, BUTTON_INSET
        )
        self._button.raise_()
