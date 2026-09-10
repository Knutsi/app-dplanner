"""The application's Undo and Redo keys, carried into a window of its own.

The menu bar owns Ctrl+Z: its QAction lives on the main window and fires while that window
is the active one. A dialog is another window, so inside one the key reaches nobody — and a
bound editor makes that silence complete, because :class:`~dplanner.framework.text_binding.
TextBinding` switches the widget's own history off and gives the shortcut up on purpose
(there is one undo stack and it is the application's). The description editor in the step
details dialog therefore had no undo at all: the widget's answer was disabled and the
application's was out of context.

**A dialog handed the ``UndoService`` is a surface that edits the document** — that is what
the argument means — so it carries the document's keys. Two QActions on the dialog, bound to
the same standard sequences the menu bar binds. A window shortcut in a window of its own can
never be ambiguous with the menu bar's: only one of the two windows is ever active, and an
ambiguous shortcut fires neither of its claimants.

It goes to the stack rather than through the action registry because a verb's id belongs to
a module and the framework knows none of them; ``UndoService`` opens the same telemetry span
either way, and undoing nothing is already a no-op there.
"""

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QWidget

from dplanner.framework.action_registry import key_sequences
from dplanner.framework.undo import UndoService


def install_undo_keys(window: QWidget, undo: UndoService[Any]) -> None:
    """Give ``window`` Undo and Redo, acting on the application's one stack."""
    for label, standard, run in (
        ("Undo", QKeySequence.StandardKey.Undo, undo.undo),
        ("Redo", QKeySequence.StandardKey.Redo, undo.redo),
    ):
        action = QAction(label, window)
        action.setShortcuts(key_sequences(standard))
        # Explicit because the no-ambiguity argument above rests on it: these keys answer
        # in this window only, and the menu bar's answer in its own.
        action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        action.triggered.connect(lambda _checked=False, run=run: run())
        window.addAction(action)
