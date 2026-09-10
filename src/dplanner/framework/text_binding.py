"""Two-way binding between a text widget and one field of one thing.

This is the smallest file in the framework that would be a bug factory if every feature
wrote it itself, so it is written once. The problem it solves: a text widget and a model
both hold the same string, either can change it, and neither may clobber the other.

The five-step discipline, which is worth understanding before changing anything here:

1. **capture** — ``contentsChange`` plus a shadow copy of the last-known text yields an
   exact ``(pos, removed, added)``; Qt reports *counts*, not the characters it removed.
2. **push, do not apply** — the widget has already changed. The command is pushed onto the
   application's undo stack with this binding as its origin, and *that* is what changes the
   model. A binding never writes to the model directly.
3. **echo suppression** — a model change whose ``origin is self`` is ignored: this widget
   already shows it. Any other origin is spliced in under a guard.
4. **undo arrives as everyone else's change** — undo and redo carry an origin that matches
   no binding, so every view applies them, including the one that made the original edit.
5. **shortcut reclaim** — an editable text widget swallows Ctrl+Z for its own (disabled)
   undo history. Leaving the ``ShortcutOverride`` unaccepted lets the application's Undo
   action fire instead. :class:`AppUndoShortcutFilter` does the same for editors with no
   binding of their own. **The window the editor is in owes that action**: the menu bar's
   is a window shortcut of the main window, so a dialog hosting a binding installs its own
   — :func:`dplanner.framework.undo_keys.install_undo_keys`, one call — or the key this
   step gives up is answered by nobody.

**What a field is.** The framework does not know your model, so a binding takes a
:class:`TextField`: read the value, watch it, and turn an edit into a command. Three small
methods per bindable field, written next to your model where they belong — see
``dplanner.domain.fields`` for the example implementations.
"""

from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QKeyEvent, QKeySequence, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from dplanner.framework.undo import Command, UndoService

# What a field reports when it changes: where, what went, what came, and who did it.
type Applied = Callable[[int, str, str, object], None]


class TextField[DocT](Protocol):
    """One editable string in your model, described to the framework."""

    def read(self) -> str:
        """The current value."""
        ...

    def command(self, pos: int, removed: str, added: str, origin: object) -> Command[DocT]:
        """An undoable command for one edit, carrying ``origin`` on its first application."""
        ...

    def connect(self, applied: Applied) -> Callable[[], None]:
        """Subscribe to changes of this field; returns an unsubscribe callable."""
        ...


def _is_undo_redo_override(event: QEvent) -> bool:
    return (
        event.type() == QEvent.Type.ShortcutOverride
        and isinstance(event, QKeyEvent)
        and (
            event.matches(QKeySequence.StandardKey.Undo)
            or event.matches(QKeySequence.StandardKey.Redo)
        )
    )


class AppUndoShortcutFilter(QObject):
    """Keeps Undo/Redo keys reaching the application's actions from any text widget.

    Install on editors whose own undo history must not answer Ctrl+Z but that have no
    :class:`TextBinding` to reclaim the shortcut for them.
    """

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        if _is_undo_redo_override(event):
            event.ignore()
            return True
        return super().eventFilter(obj, event)


class TextBinding[DocT](QObject):
    """Binds ``editor`` to ``field`` through ``undo``. Call :meth:`close` when done."""

    def __init__(
        self, editor: QPlainTextEdit, field: TextField[DocT], undo: UndoService[DocT]
    ) -> None:
        super().__init__(editor)
        self._editor = editor
        self._field = field
        self._undo = undo
        self._applying = False

        # The application stack is the only undo history; two histories fight over Ctrl+Z.
        editor.document().setUndoRedoEnabled(False)

        self._applying = True
        editor.setPlainText(field.read())
        self._applying = False
        self._shadow = editor.toPlainText()

        editor.document().contentsChange.connect(self._on_contents_change)
        self._unsubscribes = [field.connect(self._on_model_changed)]
        # Leaving the editor ends the typing burst: the next keystroke elsewhere (or back
        # here) starts a new undo step.
        editor.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        if obj is self._editor:
            if _is_undo_redo_override(event):
                event.ignore()
                return True
            if event.type() == QEvent.Type.FocusOut:
                self._undo.break_coalescing()
        return super().eventFilter(obj, event)

    def close(self) -> None:
        """Fully detach — the editor may outlive the binding and be bound again later."""
        if self._unsubscribes:
            self._editor.document().contentsChange.disconnect(self._on_contents_change)
            self._editor.removeEventFilter(self)
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    # -- widget → model ------------------------------------------------------------------------

    def _on_contents_change(self, pos: int, removed_count: int, added_count: int) -> None:
        if self._applying:
            return
        new_text = self._editor.toPlainText()
        old_text = self._shadow
        if new_text == old_text:
            return  # Format-only contentsChange — no edit to push.
        self._shadow = new_text
        pos, removed, added = exact_change(old_text, new_text, pos, removed_count, added_count)
        self._undo.push(self._field.command(pos, removed, added, self))

    # -- model → widget ------------------------------------------------------------------------

    def _on_model_changed(self, pos: int, removed: str, added: str, origin: object) -> None:
        if origin is self:
            return  # Our own edit, already on screen.
        self._applying = True
        try:
            cursor = QTextCursor(self._editor.document())
            cursor.setPosition(pos)
            cursor.setPosition(pos + len(removed), QTextCursor.MoveMode.KeepAnchor)
            # Splicing through a cursor (not setPlainText) lets Qt adjust every other
            # cursor — including the user's caret in this editor — around the change.
            cursor.insertText(added)
        finally:
            self._applying = False
        self._shadow = self._editor.toPlainText()


def exact_change(
    old_text: str, new_text: str, pos: int, removed_count: int, added_count: int
) -> tuple[int, str, str]:
    """The exact single span that turned ``old_text`` into ``new_text``.

    Qt's ``contentsChange`` occasionally over-reports its counts (block-separator
    accounting). Verify that the reported triple reconstructs reality; fall back to a
    prefix/suffix diff when it does not — correctness never depends on Qt's numbers.
    """
    removed = old_text[pos : pos + removed_count]
    added = new_text[pos : pos + added_count]
    if old_text[:pos] + added + old_text[pos + removed_count :] != new_text:
        return single_span_diff(old_text, new_text)
    return pos, removed, added


def single_span_diff(old: str, new: str) -> tuple[int, str, str]:
    """Minimal single-span difference between two strings (common prefix/suffix trimmed)."""
    prefix = 0
    limit = min(len(old), len(new))
    while prefix < limit and old[prefix] == new[prefix]:
        prefix += 1
    suffix = 0
    while suffix < limit - prefix and old[len(old) - 1 - suffix] == new[len(new) - 1 - suffix]:
        suffix += 1
    return prefix, old[prefix : len(old) - suffix], new[prefix : len(new) - suffix]
