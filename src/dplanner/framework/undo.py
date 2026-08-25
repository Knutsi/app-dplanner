"""One undo stack for the whole application.

Not ``QUndoStack``: commands mutate your model, which Qt's stack cannot see, and the merge
rules need timestamps and sealing. Eighty lines of plain Python is easier to reason about
than bridging Qt's semantics, and it is directly testable without a window.

One stack, not one per view. A user who edits a title in a panel, types in an editor and
drags something in a tree expects Ctrl+Z to walk *back through what they did*, in that
order — which per-widget stacks cannot express. That is also why every change goes through
a command: a mutation made directly on the model is a change undo cannot see.

The stack is generic over your aggregate, and the concrete commands live in
:mod:`dplanner.domain.commands` — this file knows only that a command can be applied,
reversed, named and possibly merged.
"""

from typing import Protocol

from dplanner.core.signals import Signal


class Command[DocT](Protocol):
    """One reversible change to ``DocT``."""

    def text(self) -> str:
        """Human name for menu labels: "Typing", "Move Item"…"""
        ...

    def redo(self, document: DocT) -> None: ...

    def undo(self, document: DocT) -> None: ...

    def merge_with(self, other: "Command[DocT]") -> bool:
        """Try absorbing ``other`` (the newer command) into self; True when absorbed."""
        ...


class UndoService[DocT]:
    """The stack, plus the two rules that make it feel right: merging and sealing."""

    def __init__(self, document: DocT) -> None:
        self._document = document
        self._stack: list[Command[DocT]] = []
        self._applied = 0  # Commands 0.._applied-1 are applied; the rest are redoable.
        self._top_sealed = False
        self.changed: Signal[()] = Signal()

    def push(self, command: Command[DocT]) -> None:
        """Apply ``command`` and record it, merging into the top command when allowed."""
        command.redo(self._document)
        del self._stack[self._applied :]  # A new edit invalidates the redo tail.
        if self._stack and not self._top_sealed and self._stack[-1].merge_with(command):
            self.changed.emit()
            return
        self._stack.append(command)
        self._applied = len(self._stack)
        self._top_sealed = False
        self.changed.emit()

    def break_coalescing(self) -> None:
        """Seal the top command: the next edit starts a fresh undo step.

        Called on focus changes, tab switches and selection jumps — the moments a user
        would expect a new undoable chunk to begin. Without it, typing in one field and
        then in another an hour later would merge into a single step.
        """
        self._top_sealed = True

    def can_undo(self) -> bool:
        return self._applied > 0

    def can_redo(self) -> bool:
        return self._applied < len(self._stack)

    def undo_text(self) -> str:
        return self._stack[self._applied - 1].text() if self.can_undo() else ""

    def redo_text(self) -> str:
        return self._stack[self._applied].text() if self.can_redo() else ""

    def undo(self) -> None:
        if not self.can_undo():
            return
        self._applied -= 1
        self._stack[self._applied].undo(self._document)
        self._top_sealed = True  # Typing after an undo must never merge into old history.
        self.changed.emit()

    def redo(self) -> None:
        if not self.can_redo():
            return
        self._stack[self._applied].redo(self._document)
        self._applied += 1
        self._top_sealed = True
        self.changed.emit()
