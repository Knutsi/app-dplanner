"""Expanding an editor is a second view, never a copy.

A side panel gives prose a few hundred pixels; a long description or instruction deserves
a window. Nothing is ever copied out and back — the dialog holds no state of its own, so
closing it loses nothing — and there are two ways to mean that, because there are two
kinds of thing an editor can be showing.

:meth:`ExpandedTextDialog.over_field` is for a document the **model** owns. The dialog
opens the same :class:`TextField` with its own :class:`TextBinding`, and the inline editor
stays live because each binding sees the other's commands as foreign changes — exactly the
mechanism that keeps a CLI edit or an undo visible everywhere.

:meth:`ExpandedTextDialog.over_document` is for one where the **buffer** is the authority
until something else persists it: the Specs tab's editing session, whose document is a
content-addressed blob rather than a field, and whose typing belongs to the widget's own
undo stack. There the dialog shows the *same* ``QTextDocument``, so the two views are one
document by construction — one buffer, one undo history, one highlighter, in step without
a mechanism. That is the base case and the binding pair is the derived one; a `TextField`
adapter over a session buffer would have had to push a command per keystroke onto the
application's stack, which is the one thing that model says it must not do.

:func:`attach_expand` is the one affordance that opens either — a small corner button on
the editor itself, so every host offers the same gesture without growing a header row.

It inherits the inline editor's powers too: handed the same ``attach`` callable, a paste in
the big window lands in the same file area and refreshes the same gallery behind it, and
the markdown strip over it is the same strip.
"""

from typing import Any

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QPlainTextEdit, QToolButton, QWidget

from dplanner.framework.dialog import DialogFrame
from dplanner.framework.dictation import DictationService
from dplanner.framework.markdown_highlight import MarkdownHighlighter
from dplanner.framework.markdown_toolbar import MarkdownToolbar
from dplanner.framework.prose_edit import Attach, Pick, ProseEdit
from dplanner.framework.text_binding import TextBinding, TextField
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import (
    EDITOR_MEASURE,
    centered_column,
    make_text_well,
    space_lines,
)

BUTTON_INSET = 4  # The expand button's distance from the editor's corner.


class ExpandedTextDialog(DialogFrame):
    """One document, briefly in a window of its own. The opener owes ``dispose()``.

    An *editor* dialog on the frame — a place to work claims its share of the screen —
    with Close alone in the footer: every keystroke is live, so there is nothing to
    confirm and nothing to cancel.
    """

    def __init__(
        self,
        undo: UndoService[Any],
        *,
        title: str,
        placeholder: str = "",
        attach: Attach | None = None,
        pick: Pick | None = None,
        dictation: DictationService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """The chrome only — one of the two constructors below says where the text is."""
        super().__init__(title, parent, editor=True)
        self._binding: TextBinding[Any] | None = None
        # Only the field path makes one: on the shared-document path the owner's is
        # already on the document, and a second would recompute the same formats.
        self._highlighter: MarkdownHighlighter | None = None

        self.edit = ProseEdit(self, undo=undo)
        self.edit.set_attach(attach)
        self.edit.set_pick(pick)
        self.edit.setObjectName("InspectorNotes")
        self.edit.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.edit.setPlaceholderText(placeholder)
        self.tools = MarkdownToolbar(self.edit, undo=undo, dictation=dictation, parent=self)

        self.body_layout.addWidget(self.tools)
        self.body_layout.addWidget(centered_column(self.edit, EDITOR_MEASURE), stretch=1)
        self.add_dismiss("Close")
        self.edit.setFocus()

    @classmethod
    def over_field(
        cls,
        field: TextField[Any],
        undo: UndoService[Any],
        *,
        title: str,
        placeholder: str = "",
        attach: Attach | None = None,
        pick: Pick | None = None,
        dictation: DictationService | None = None,
        parent: QWidget | None = None,
    ) -> "ExpandedTextDialog":
        """The model is the authority: its own document, its own highlighter, and a second
        binding over the same field, so each view sees the other's edits as foreign."""
        dialog = cls(
            undo,
            title=title,
            placeholder=placeholder,
            attach=attach,
            pick=pick,
            dictation=dictation,
            parent=parent,
        )
        dialog._highlighter = MarkdownHighlighter(dialog.edit.document(), dialog.edit)
        make_text_well(dialog.edit)
        dialog._binding = TextBinding(dialog.edit, field, undo)
        space_lines(dialog.edit)  # After the binding's setPlainText, or the format is lost.
        return dialog

    @classmethod
    def over_document(
        cls,
        document: QTextDocument,
        undo: UndoService[Any],
        *,
        title: str,
        placeholder: str = "",
        attach: Attach | None = None,
        pick: Pick | None = None,
        dictation: DictationService | None = None,
        parent: QWidget | None = None,
    ) -> "ExpandedTextDialog":
        """The buffer is the authority: the *same* document, so the two views are one.

        It brings the owner's highlighter and the owner's well metrics with it, because
        both live on the document — and applying either again here would edit the shared
        buffer, which the owner would hear as the person typing.
        """
        dialog = cls(
            undo,
            title=title,
            placeholder=placeholder,
            attach=attach,
            pick=pick,
            dictation=dictation,
            parent=parent,
        )
        dialog.edit.setDocument(document)
        return dialog

    def dispose(self) -> None:
        """Detach the binding — same contract as the step details dialog's opener.

        Nothing is handed back on the shared-document path: the document belongs to the
        editor that made it, and this view only ever borrowed it.
        """
        self.tools.abandon_dictation()
        if self._binding is not None:
            self._binding.close()
            self._binding.setParent(None)
            self._binding = None


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
