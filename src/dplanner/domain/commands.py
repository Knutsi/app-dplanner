"""Undoable changes to the library.

A command is the *only* way anything changes the library. Not because indirection is
virtuous, but because a command is the unit undo works in: pushing one is what makes an
action reversible, and the alternative — a view mutating the model directly — is a change
that Ctrl+Z cannot see and no other view hears about.

**This file is also the vocabulary the CLI shares with the GUI.** A menu action and a
``dplanner`` verb construct the *same* command object; the GUI pushes it onto the undo stack
and the CLI applies it and flushes. That is what keeps the two surfaces from drifting:
neither can grow a behaviour the other lacks without someone editing this file.

Two conventions carry through all of them:

**Origin flips after the first redo.** ``push()`` runs ``redo()`` once, and that first run
carries the originating view's token so the widget that already shows the change ignores its
own echo. Every later redo, and every undo, passes ``UNDO_ORIGIN``, which matches no view.

**Coalescing is bounded.** Typing is one undo step per burst, and setting the same field
twice in a row is one step — but a burst ends at a pause and whenever the application seals
the top of the stack.
"""

import time
from collections.abc import Iterable
from typing import Any, Protocol

from dplanner.domain.model import (
    FIELD_LABELS,
    Edge,
    Library,
    Node,
    NodeId,
    Project,
    Redirection,
    StepId,
    TextEdit,
)

# A pause longer than this starts a new undo step.
MERGE_WINDOW_SECONDS = 1.0

# Passed by undo and redo. It matches no view binding, so every view applies the change.
UNDO_ORIGIN: object = object()


class Command(Protocol):
    """One reversible change. See :mod:`dplanner.framework.undo`."""

    def text(self) -> str: ...

    def redo(self, library: Library) -> None: ...

    def undo(self, library: Library) -> None: ...

    def merge_with(self, other: "Command") -> bool: ...


class SetFieldCommand:
    """One of a node's value fields — a project's title or summary, a step's title.

    One command for every field on every level rather than a class each: they are edited the
    same way, undone the same way, and differ only in what the menu calls them.
    """

    def __init__(
        self, node_id: NodeId, field: str, value: object, view_origin: object | None = None
    ) -> None:
        self.node_id = node_id
        self.field = field
        self.value = value
        self._before: object = None
        self._captured = False
        self._next_origin = view_origin

    def text(self) -> str:
        return FIELD_LABELS.get(self.field, "Set Field")

    def redo(self, library: Library) -> None:
        if not self._captured:
            self._before = getattr(library.node(self.node_id), self.field)
            self._captured = True
        library.set_field(self.node_id, self.field, self.value, self._next_origin)
        self._next_origin = UNDO_ORIGIN

    def undo(self, library: Library) -> None:
        library.set_field(self.node_id, self.field, self._before, UNDO_ORIGIN)

    def merge_with(self, other: Command) -> bool:
        # Two different fields never merge, however fast they were typed: undoing a summary
        # should not silently undo a rename made a moment earlier.
        if (
            not isinstance(other, SetFieldCommand)
            or other.node_id != self.node_id
            or other.field != self.field
        ):
            return False
        self.value = other.value
        return True


class EditTextCommand:
    """A positioned edit to one module's prose on one node, coalescing consecutive typing.

    ``label`` is what the Edit menu says. A burst of typing is "Typing"; a whole document
    replaced at once — which is what the CLI does — says so instead, and the differing label
    is also what stops the two from merging into one undo step.
    """

    def __init__(
        self, edit: TextEdit, view_origin: object | None = None, label: str = "Typing"
    ) -> None:
        self.edit = edit
        self.label = label
        self._next_origin = view_origin
        self._at = time.monotonic()

    def text(self) -> str:
        return self.label

    def redo(self, library: Library) -> None:
        library.apply_text_edit(self.edit, self._next_origin)
        self._next_origin = UNDO_ORIGIN

    def undo(self, library: Library) -> None:
        library.apply_text_edit(self.edit.inverted(), UNDO_ORIGIN)

    def merge_with(self, other: Command) -> bool:
        if not isinstance(other, EditTextCommand) or other.label != self.label:
            return False
        mine, theirs = self.edit, other.edit
        if (mine.node_id, mine.key) != (theirs.node_id, theirs.key):
            return False
        if time.monotonic() - self._at > MERGE_WINDOW_SECONDS:
            return False
        # Only the shapes a person actually produces by typing: adding at the end of what
        # was added, and backspacing into it.
        appending = (
            not mine.removed and not theirs.removed and theirs.pos == mine.pos + len(mine.added)
        )
        backspacing = not theirs.added and theirs.pos + len(theirs.removed) == mine.pos + len(
            mine.added
        )
        if appending:
            added = mine.added + theirs.added
        elif backspacing and len(mine.added) >= len(theirs.removed):
            added = mine.added[: -len(theirs.removed)]
        else:
            return False
        self.edit = TextEdit(mine.node_id, mine.key, mine.pos, mine.removed, added)
        self._at = time.monotonic()
        return True


class SetEdgesCommand:
    """Replace one kind of incoming edge on one step."""

    def __init__(
        self, step_id: StepId, kind: str, targets: list[StepId], view_origin: object | None = None
    ) -> None:
        self.step_id = step_id
        self.kind = kind
        self.targets = list(targets)
        self._before: list[StepId] | None = None
        self._next_origin = view_origin

    def text(self) -> str:
        return "Change Links"

    def redo(self, library: Library) -> None:
        if self._before is None:
            self._before = list(library.step(self.step_id).edges.get(self.kind, []))
        library.set_edges(self.step_id, self.kind, self.targets, self._next_origin)
        self._next_origin = UNDO_ORIGIN

    def undo(self, library: Library) -> None:
        assert self._before is not None
        library.set_edges(self.step_id, self.kind, self._before, UNDO_ORIGIN)

    def merge_with(self, other: Command) -> bool:
        return False


class AddNodeCommand:
    """Add a step to a project.

    Generic over the node kinds the model holds, but in practice steps only: project
    membership is a library operation (git plus the library file), performed off the undo
    stack by the library module — undo cannot re-initialise a repository.
    """

    def __init__(self, parent_id: NodeId, node: Node, index: int | None = None) -> None:
        self.parent_id = parent_id
        self.node = node
        self.index = index
        self._mark_before: int | None = None

    def text(self) -> str:
        return f"Add {self.node.kind.title()}"

    def redo(self, library: Library) -> None:
        parent = library.node(self.parent_id)
        if self._mark_before is None:
            self._mark_before = getattr(parent, "last_number", 0)
        library.add_child(self.parent_id, self.node, self.index)

    def undo(self, library: Library) -> None:
        _, self.index = library.remove_child(self.node.id)
        # Undoing a birth hands the number back: the step never was, so nothing can
        # carry its key, and undo has to leave the workspace exactly as it found it.
        parent = library.node(self.parent_id)
        if isinstance(parent, Project) and self._mark_before is not None:
            parent.last_number = self._mark_before

    def merge_with(self, other: Command) -> bool:
        return False


class RemoveNodeCommand:
    """Remove a project or a step, keeping it so undo can put it back where it was."""

    def __init__(self, node_id: NodeId) -> None:
        self.node_id = node_id
        self._node: Node | None = None
        self._parent_id = ""
        self._index = 0

    def text(self) -> str:
        return "Delete" if self._node is None else f"Delete {self._node.kind.title()}"

    def redo(self, library: Library) -> None:
        self._node = library.node(self.node_id)
        self._parent_id, self._index = library.remove_child(self.node_id)

    def undo(self, library: Library) -> None:
        assert self._node is not None
        library.restore_child(self._parent_id, self._node, self._index)

    def merge_with(self, other: Command) -> bool:
        return False


class SetModuleDataCommand:
    """Replace one module's entry on one node — how an aspect is written.

    An aspect is edited through the undo stack like everything else, which is what lets the
    CLI set an estimate and the GUI undo it.

    ``label`` is what the Edit menu says, the way :class:`EditTextCommand` has one: "Set
    Estimate" and "Move Step" are the same mechanism and should not both read "Edit".
    """

    def __init__(
        self,
        node_id: NodeId,
        module_id: str,
        data: dict[str, Any],
        view_origin: object | None = None,
        label: str = "",
    ) -> None:
        self.node_id = node_id
        self.module_id = module_id
        self.data = dict(data)
        self.label = label
        self._before: dict[str, Any] | None = None
        self._next_origin = view_origin

    def text(self) -> str:
        if self.label:
            return self.label
        return "Clear" if not self.data else "Edit"

    def redo(self, library: Library) -> None:
        if self._before is None:
            self._before = dict(library.node(self.node_id).module_data.get(self.module_id, {}))
        library.set_module_data(self.node_id, self.module_id, self.data, self._next_origin)
        self._next_origin = UNDO_ORIGIN

    def undo(self, library: Library) -> None:
        assert self._before is not None
        library.set_module_data(self.node_id, self.module_id, self._before, UNDO_ORIGIN)

    def merge_with(self, other: Command) -> bool:
        if (
            not isinstance(other, SetModuleDataCommand)
            or other.node_id != self.node_id
            or other.module_id != self.module_id
            or other.label != self.label
        ):
            return False
        self.data = other.data
        return True


class CompositeCommand:
    """Several commands as one undo step — "Delete 5 steps" must undo as one gesture."""

    def __init__(self, label: str, commands: list[Command]) -> None:
        self.label = label
        self.commands = commands

    def text(self) -> str:
        return self.label

    def redo(self, library: Library) -> None:
        for command in self.commands:
            command.redo(library)

    def undo(self, library: Library) -> None:
        for command in reversed(self.commands):
            command.undo(library)

    def merge_with(self, other: Command) -> bool:
        return False


def remove_edges_command(library: Library, edges: Iterable[Edge], label: str) -> CompositeCommand:
    """Remove these ``(waiter, kind, source)`` edges as one undo step.

    One :class:`SetEdgesCommand` per ``(waiter, kind)``, because it replaces the list: two
    commands on the same list would each be built from the state before either ran, and
    the second would put back what the first removed. Always a composite, so the undo
    entry says what was done rather than "Change Links".
    """
    by_list: dict[tuple[StepId, str], set[StepId]] = {}
    for waiter, kind, source in edges:
        by_list.setdefault((waiter, kind), set()).add(source)
    commands: list[Command] = [
        SetEdgesCommand(
            waiter,
            kind,
            [t for t in library.step(waiter).edges.get(kind, []) if t not in gone],
        )
        for (waiter, kind), gone in sorted(by_list.items())
    ]
    return CompositeCommand(label, commands)


def redirect_edges_command(
    library: Library, redirection: Redirection, label: str
) -> CompositeCommand:
    """Move one end of :attr:`Redirection.moving` onto its anchor as one undo step.

    One :class:`SetEdgesCommand` per affected ``(waiter, kind)`` list carrying that list's
    *final* content — computed here rather than per edge, because a redirect takes an edge
    off one list and puts it on another, and moving the source end is both on the same
    list. Which order the commands run in cannot matter: every edge the redirect adds hangs
    off the anchor at the moving end, so no half-applied state can hold a cycle the finished
    one does not (:meth:`Library.redirection` has the argument).
    """
    lists: dict[tuple[StepId, str], list[StepId]] = {}

    def held(waiter: StepId, kind: str) -> list[StepId]:
        return lists.setdefault((waiter, kind), list(library.step(waiter).edges.get(kind, [])))

    for waiter, kind, source in redirection.moving:
        held(waiter, kind).remove(source)
    for edge in redirection.moving:
        new_waiter, kind, new_source = redirection.moved(edge)
        targets = held(new_waiter, kind)
        if new_source not in targets:
            targets.append(new_source)
    commands: list[Command] = [
        SetEdgesCommand(waiter, kind, targets)
        for (waiter, kind), targets in sorted(lists.items())
        if targets != library.step(waiter).edges.get(kind, [])
    ]
    return CompositeCommand(label, commands)
