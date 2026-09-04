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

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol

from dplanner.core.signals import Signal
from dplanner.core.telemetry import current


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


class _Gesture[DocT]:
    """Several already-applied commands as one undo step — what :meth:`gesture` records."""

    def __init__(self, label: str, commands: list[Command[DocT]]) -> None:
        self._label = label
        self._commands = commands

    def text(self) -> str:
        return self._label

    def redo(self, document: DocT) -> None:
        for command in self._commands:
            command.redo(document)

    def undo(self, document: DocT) -> None:
        for command in reversed(self._commands):
            command.undo(document)

    def merge_with(self, other: Command[DocT]) -> bool:
        return False


class UndoService[DocT]:
    """The stack, plus the two rules that make it feel right: merging and sealing."""

    def __init__(self, document: DocT) -> None:
        self._document = document
        self._stack: list[Command[DocT]] = []
        self._applied = 0  # Commands 0.._applied-1 are applied; the rest are redoable.
        self._top_sealed = False
        self._gesture: list[Command[DocT]] | None = None
        self.changed: Signal[()] = Signal("undo.changed")

    def push(self, command: Command[DocT]) -> None:
        """Apply ``command`` and record it, merging into the top command when allowed.

        Timed as a ``command`` span: typing never passes through an action, so this is
        where a keystroke's whole cost — the mutation and every view's reaction — is read.
        """
        with current().span("command", command.text(), verb="push"):
            command.redo(self._document)
            if self._gesture is not None:
                self._gesture.append(command)  # Placed as one step when the gesture ends.
                return
            self._place(command)

    @contextmanager
    def gesture(self, label: str) -> Iterator[None]:
        """Every push inside the block lands on the stack as **one** step named ``label``.

        For a gesture that runs several verbs — a template that flips five toggles, each
        the owning module's own command — where the alternative is every verb learning to
        build a composite for a caller it cannot see. Each command is applied as it is
        pushed, so the verbs in the block see each other's effects; the stack only hears
        about the whole at the end. A gesture inside a gesture belongs to the outer one.
        """
        if self._gesture is not None:
            yield
            return
        self._gesture = []
        try:
            yield
        finally:
            commands, self._gesture = self._gesture, None
            if len(commands) == 1:
                self._place(commands[0])
            elif commands:
                self._place(_Gesture(label, commands))

    def _place(self, command: Command[DocT]) -> None:
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
        command = self._stack[self._applied - 1]
        with current().span("command", command.text(), verb="undo"):
            try:
                command.undo(self._document)
            except (KeyError, ValueError):
                self._drop_from(self._applied - 1)
                return
            self._applied -= 1
            self._top_sealed = True  # Typing after an undo must never merge into old history.
            self.changed.emit()

    def redo(self) -> None:
        if not self.can_redo():
            return
        command = self._stack[self._applied]
        with current().span("command", command.text(), verb="redo"):
            try:
                command.redo(self._document)
            except (KeyError, ValueError):
                self._drop_from(self._applied)
                return
            self._applied += 1
            self._top_sealed = True
            self.changed.emit()

    def _drop_from(self, index: int) -> None:
        """The document refused a command: it names what is no longer there — a step
        another writer removed, prose whose positions moved under an adopted edit. That
        entry and everything after it describe a document that no longer exists, so they
        go; the history before it is still true."""
        del self._stack[index:]
        self._applied = min(self._applied, len(self._stack))
        self._top_sealed = True
        self.changed.emit()

    def clear(self) -> None:
        """Forget the history: the document it was recorded over has been replaced
        wholesale — a branch switch, a pull — and undoing into it would replay stale edits."""
        self._stack.clear()
        self._applied = 0
        self._top_sealed = False
        self.changed.emit()
