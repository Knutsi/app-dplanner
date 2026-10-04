"""Undoable changes to the library.

A command is the *only* way anything changes the library. Not because indirection is
virtuous, but because a command is the unit undo works in: pushing one is what makes an
action reversible, and the alternative — a view mutating the model directly — is a change
that Ctrl+Z cannot see and no other view hears about.

**This file is also the vocabulary the CLI shares with the GUI.** A menu action and a
``dplanner`` verb construct the *same* command object; the GUI pushes it onto the undo stack
and the CLI applies it and flushes. That is what keeps the two surfaces from drifting:
neither can grow a behaviour the other lacks without someone editing this file.

Three conventions carry through all of them:

**Origin flips after the first redo.** ``push()`` runs ``redo()`` once, and that first run
carries the originating view's token so the widget that already shows the change ignores its
own echo. Every later redo, and every undo, passes ``UNDO_ORIGIN``, which matches no view.

**Coalescing is bounded.** Typing is one undo step per burst, and setting the same field
twice in a row is one step — but a burst ends at a pause and whenever the application seals
the top of the stack.

**Nothing is overwritten that this command did not write.** A value command remembers what
its redo left behind, and its undo refuses — ``ValueError``, which the undo stack turns into
dropping the entry — when another writer has changed that value since: the store adopting
an outside edit, a background sync, the CLI. A replayed redo refuses the same way when the
value is no longer the one its undo put back. And a :class:`CompositeCommand` applies whole
or not at all, so a refusal never leaves half a gesture behind.
"""

import copy
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Protocol

from dplanner.domain.model import (
    EDGE_KINDS,
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

# One list an edge lives on: the step that waits, and the kind. A command that rewrites edges
# replaces whole lists, so this is the unit it plans in.
type EdgeList = tuple[StepId, str]


def _unchanged(current: object, expected: object, what: str) -> None:
    """Refuse to write over ``what`` when it is no longer the value this command left."""
    if current != expected:
        raise ValueError(f"{what} changed since; another writer's change is kept")


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
        self._after: object = None
        self._captured = False
        self._next_origin = view_origin

    def text(self) -> str:
        return FIELD_LABELS.get(self.field, "Set Field")

    def _current(self, library: Library) -> object:
        return getattr(library.node(self.node_id), self.field)

    def redo(self, library: Library) -> None:
        if not self._captured:
            self._before = self._current(library)
            self._captured = True
        else:
            _unchanged(self._current(library), self._before, self.text())
        library.set_field(self.node_id, self.field, self.value, self._next_origin)
        self._after = self._current(library)
        self._next_origin = UNDO_ORIGIN

    def undo(self, library: Library) -> None:
        _unchanged(self._current(library), self._after, self.text())
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
        self._after = other._after
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
    """Replace one kind of incoming edge on one step.

    The library's :attr:`~Library.link_rules` judge the **first** redo only, and only while
    ``rules`` is on: that is the moment somebody chose the link. An undo puts back what was
    there and a later redo replays what was judged already, so neither asks again — judged,
    either could refuse halfway through a composite over a stack another writer broke
    since, and the undo stack would drop the entry half applied. A command that copies or
    moves links which already exist passes ``rules=False`` outright (:meth:`Library.set_edges`
    names who).
    """

    def __init__(
        self,
        step_id: StepId,
        kind: str,
        targets: list[StepId],
        view_origin: object | None = None,
        *,
        rules: bool = True,
    ) -> None:
        self.step_id = step_id
        self.kind = kind
        self.targets = list(targets)
        self.rules = rules
        self._before: list[StepId] | None = None
        self._after: list[StepId] = []
        self._next_origin = view_origin

    def text(self) -> str:
        return "Change Links"

    def _current(self, library: Library) -> list[StepId]:
        return list(library.step(self.step_id).edges.get(self.kind, []))

    def redo(self, library: Library) -> None:
        first = self._before is None
        if self._before is None:
            self._before = self._current(library)
        else:
            _unchanged(self._current(library), self._before, self.text())
        library.set_edges(
            self.step_id, self.kind, self.targets, self._next_origin, rules=self.rules and first
        )
        self._after = self._current(library)
        self._next_origin = UNDO_ORIGIN

    def undo(self, library: Library) -> None:
        assert self._before is not None
        _unchanged(self._current(library), self._after, self.text())
        library.set_edges(self.step_id, self.kind, self._before, UNDO_ORIGIN, rules=False)

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
        self._after: dict[str, Any] = {}
        self._next_origin = view_origin

    def text(self) -> str:
        if self.label:
            return self.label
        return "Clear" if not self.data else "Edit"

    def _current(self, library: Library) -> dict[str, Any]:
        # A deep copy: the model keeps the dict it was handed, and a nested value edited in
        # place there would otherwise change the remembered one along with it.
        return copy.deepcopy(library.node(self.node_id).module_data.get(self.module_id, {}))

    def redo(self, library: Library) -> None:
        if self._before is None:
            self._before = self._current(library)
        else:
            _unchanged(self._current(library), self._before, self.text())
        library.set_module_data(self.node_id, self.module_id, self.data, self._next_origin)
        self._after = self._current(library)
        self._next_origin = UNDO_ORIGIN

    def undo(self, library: Library) -> None:
        assert self._before is not None
        _unchanged(self._current(library), self._after, self.text())
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
        self._after = other._after
        return True


class CompositeCommand:
    """Several commands as one undo step — "Delete 5 steps" must undo as one gesture.

    Whole or not at all, both ways: when one command refuses, the ones already applied are
    reversed before the refusal goes on, so the model is never left half way.
    """

    def __init__(self, label: str, commands: list[Command]) -> None:
        self.label = label
        self.commands = commands

    def text(self) -> str:
        return self.label

    def redo(self, library: Library) -> None:
        _all_or_nothing(self.commands, lambda c: c.redo(library), lambda c: c.undo(library))

    def undo(self, library: Library) -> None:
        _all_or_nothing(
            reversed(self.commands), lambda c: c.undo(library), lambda c: c.redo(library)
        )

    def merge_with(self, other: Command) -> bool:
        return False


def _all_or_nothing(
    commands: Iterable[Command],
    apply: Callable[[Command], None],
    revert: Callable[[Command], None],
) -> None:
    """``apply`` each command in turn; if one raises, ``revert`` those done, then re-raise.
    The undo stack's gestures keep a copy (``framework/undo.py``), which this layer is below."""
    done: list[Command] = []
    try:
        for command in commands:
            apply(command)
            done.append(command)
    except Exception:
        for command in reversed(done):
            revert(command)
        raise


def rewire_command(
    library: Library,
    lists: Mapping[EdgeList, Sequence[StepId]],
    label: str,
    between: Sequence[Command] = (),
) -> CompositeCommand:
    """Rewrite these edge lists to their final content, with ``between`` in the middle, as
    one undo step: **every removal first, then** ``between``, **then every addition.**

    A list that loses some ids and gains others is two writes — what it keeps, then what it
    ends as — so every graph a redo passes through is a subset of the graph before or the
    graph after, and so is every graph the undo passes through, run in reverse. A subset of
    an acyclic graph is acyclic: the cycle check cannot trip halfway, whatever order the
    lists come in. ``between`` is where what the links depend on changes — a stack's
    membership and seat, a node born or removed — so the additions land on the finished
    membership and the undo's re-additions on the one they came from. A waiter not yet in
    the library reads as an empty list, which lets a node born in ``between`` gain its own
    among the additions.

    Written with ``rules=False``: what a rewire adds is a line its builder already refused
    or allowed as a whole, plus links that existed before and are only moving — judged
    again, a moved link whose far end sits in *another* stack somebody broke would refuse
    and strand the composite. A kind this build does not know is carried, never rewritten.
    ``docs/architecture/canvas.md``'s *One in, one out is a rule the domain asks* has the argument.
    """
    removals: list[Command] = []
    additions: list[Command] = []
    for (waiter, kind), final in sorted(lists.items()):
        if kind not in EDGE_KINDS:
            continue
        current = library.step(waiter).edges.get(kind, []) if library.has(waiter) else []
        wanted = list(dict.fromkeys(final))
        kept = [target for target in current if target in wanted]
        if kept != current:
            removals.append(SetEdgesCommand(waiter, kind, kept, rules=False))
        if wanted != kept:
            additions.append(SetEdgesCommand(waiter, kind, wanted, rules=False))
    return CompositeCommand(label, [*removals, *between, *additions])


def edge_list(
    lists: dict[EdgeList, list[StepId]], library: Library, waiter: StepId, kind: str
) -> list[StepId]:
    """The list being planned for ``(waiter, kind)``, started from the model's the first time
    it is named — how a builder edits many edges over one list each before a rewire writes
    them, so two changes to one list never overwrite each other. A step not yet in the
    library starts empty, as :func:`rewire_command` reads it."""
    if (waiter, kind) not in lists:
        current = library.step(waiter).edges.get(kind, []) if library.has(waiter) else []
        lists[(waiter, kind)] = list(current)
    return lists[(waiter, kind)]


def remove_edges_command(library: Library, edges: Iterable[Edge], label: str) -> CompositeCommand:
    """Remove these ``(waiter, kind, source)`` edges as one undo step.

    One :class:`SetEdgesCommand` per ``(waiter, kind)``, because it replaces the list: two
    commands on the same list would each be built from the state before either ran, and
    the second would put back what the first removed. Always a composite, so the undo
    entry says what was done rather than "Change Links".
    """
    lists: dict[EdgeList, list[StepId]] = {}
    for waiter, kind, source in edges:
        held = edge_list(lists, library, waiter, kind)
        if source in held:
            held.remove(source)
    return rewire_command(library, lists, label)


def remove_steps_command(
    library: Library,
    step_ids: Sequence[StepId],
    verb: str,
    *,
    links: Sequence[Edge] = (),
    bridges: Iterable[Edge] = (),
    between: Sequence[Command] = (),
) -> CompositeCommand:
    """Remove these steps and every link into them as one undo step, named for the verb
    that asked — "Delete Step", "Cut 3 Steps" — and ``links`` besides: the arrows a Delete
    found picked beside the steps, "Delete 3 Items".

    :meth:`Library.remove_child` leaves the survivors' lists alone so that undo can put the
    graph back exactly. The tidying belongs here instead: a composite undoes in reverse, so
    the steps come back before the lists that named them and the undo is just as exact —
    and no ghost id reaches disk to freeze a survivor's list later. Links *among* the
    doomed live on the doomed nodes and travel with them; only the ones crossing in go,
    and a picked link joins them in the **one** removal, so a list that loses both is
    rewritten once (:func:`remove_edges_command` says why that matters).

    ``bridges`` are links the removal makes across the gap it leaves — a stack closing its
    chain round a deleted member — added once the steps are gone, and ``between`` runs with
    the steps' removal (the stack's seat handed on). It is a :func:`rewire_command`, so no
    graph on the way is anything but a subset of the one before or the one after.
    """
    doomed = list(step_ids)
    chosen = set(doomed)
    incoming = [edge for edge in library.boundary_edges(doomed) if edge[0] not in chosen]
    incoming += [edge for edge in links if edge[0] not in chosen]
    if links:
        label = f"{verb} {len(doomed) + len(links)} Items"
    else:
        label = f"{verb} Step" if len(doomed) == 1 else f"{verb} {len(doomed)} Steps"
    lists: dict[EdgeList, list[StepId]] = {}
    for waiter, kind, source in incoming:
        held = edge_list(lists, library, waiter, kind)
        if source in held:
            held.remove(source)
    for waiter, kind, source in bridges:
        held = edge_list(lists, library, waiter, kind)
        if source not in held:
            held.append(source)
    removing = [RemoveNodeCommand(step_id) for step_id in doomed]
    return rewire_command(library, lists, label, [*removing, *between])


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
    lists: dict[EdgeList, list[StepId]] = {}
    for waiter, kind, source in redirection.moving:
        edge_list(lists, library, waiter, kind).remove(source)
    for edge in redirection.moving:
        new_waiter, kind, new_source = redirection.moved(edge)
        targets = edge_list(lists, library, new_waiter, kind)
        if new_source not in targets:
            targets.append(new_source)
    commands: list[Command] = [
        SetEdgesCommand(waiter, kind, targets)
        for (waiter, kind), targets in sorted(lists.items())
        if targets != library.step(waiter).edges.get(kind, [])
    ]
    return CompositeCommand(label, commands)
