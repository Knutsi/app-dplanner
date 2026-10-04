"""Editing a stack: every gesture that builds or reshapes one, as one command each.

New, make, add, move, take out, dissolve — and the removal Delete, Cut and ``step remove``
run, which closes a stack's chain round a member that goes. The canvas and ``dplanner stack
…`` build the very same object, so neither surface can grow a stack edit the other lacks.

Every edit that moves links is a :func:`~dplanner.domain.commands.rewire_command`: the links
that go come off first, then the membership and the seat change, then the new links go on —
so no graph on the way is anything but a part of the one before or the one after, and the
cycle check cannot trip halfway. One relink (:func:`_relink`) rebuilds a line in its new
order for all of them: the chain in that order, the first member's outside inputs on
whoever is first now, the last member's dependents on whoever is last, and a step coming in
or going out left with no links at all. The seat is the first member's, so it is handed on
whenever the first member changes (``docs/architecture/canvas.md``'s *A stack is presentation over a
chain*).

**A builder refuses what it cannot keep one line** — make over steps with another step
between two of them, add, move and take out on a stack somebody broke — raising
``ValueError`` with the words; the
``*_refusal`` functions answer the same question without building, for a verb's greyed
state. Dissolve and the removal never refuse: a broken stack can always be taken apart, and
a Delete is never refused. ``docs/architecture/canvas.md``'s *One in, one out is a rule the domain
asks* has the reasoning.

**Qt-free** — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

import math
from collections.abc import Callable, Collection, Sequence
from itertools import pairwise
from typing import Any

from dplanner.domain.commands import (
    AddNodeCommand,
    Command,
    CompositeCommand,
    EdgeList,
    SetModuleDataCommand,
    edge_list,
    remove_steps_command,
    rewire_command,
)
from dplanner.domain.model import EDGE_KINDS, Edge, Library, NodeId, Step, StepId
from dplanner.domain.ordering import left_between
from dplanner.modules.canvas.geometry import shift
from dplanner.modules.canvas.layouts.named import position_commands
from dplanner.modules.canvas.layouts.placement import positions
from dplanner.modules.canvas.layouts.positions import (
    GRID,
    MODULE_ID,
    node_size,
    read_position,
    read_size,
    read_stack,
    write_member,
    write_position,
)
from dplanner.modules.canvas.layouts.sorts import H_GAP
from dplanner.modules.canvas.stacks.stack import (
    Point,
    Stack,
    broken_reason,
    mint_id,
    pack,
    read_stacks,
    stack_of,
    stray_links,
)

NEW_LABEL = "New Stack"
MAKE_LABEL = "Make Stack"
ADD_LABEL = "Add to Stack"
MOVE_LABEL = "Move in Stack"
TAKE_OUT_LABEL = "Take Out of Stack"
DISSOLVE_LABEL = "Dissolve Stack"


# -- refusals ----------------------------------------------------------------------------------


def make_refusal(library: Library, step_ids: Sequence[StepId]) -> str | None:
    """Why these steps cannot become one stack, or None.

    Any steps of one project can, linked or not — :func:`make_command` links them into one
    line — unless one already stands in a stack, or a step left out comes between two of
    them: a line through both would have to wait on it and be waited on by it at once.
    """
    chosen = list(dict.fromkeys(step_ids))
    if not chosen:
        return "pick the steps to stack"
    steps = [library.step(step_id) for step_id in chosen]
    project = library.project_of(chosen[0])
    if any(library.project_of(step.id) is not project for step in steps):
        return "a stack's steps are all in one project"
    for step in steps:
        if read_stack(step):
            return f"{step.title!r} is already in a stack"
    between = left_between(project, set(chosen))
    if between is not None:
        return f"{between.title!r} comes between them — pick it too, or leave a step out"
    return None


def line_refusal(library: Library, stack: Stack) -> str | None:
    """Why this stack cannot be edited, or None: it is no longer one line — a gap, or a link
    into or out of its middle that another writer or a hand edit brought in."""
    steps = library.project_of(stack.head).steps
    reason = broken_reason(stack, _title(library), stray_links(stack, steps))
    if reason is None:
        return None
    return f"the stack is not one line: {reason} — link or unlink to mend it, or dissolve it first"


def join_refusal(library: Library, step: Step, stack: Stack) -> str | None:
    """Why ``step`` cannot join ``stack``, or None. A step born for it can always join."""
    if not library.has(step.id):
        return None
    if step.id in stack.members:
        return f"{step.title!r} is already in this stack — move it instead"
    if read_stack(step):
        return f"{step.title!r} is already in a stack — take it out first"
    if library.project_of(step.id) is not library.project_of(stack.head):
        return f"{step.title!r} is in another project"
    return None


# -- builders ----------------------------------------------------------------------------------


def new_stack_command(
    project_id: NodeId, step: Step, seat: Point | None = None, label: str = NEW_LABEL
) -> CompositeCommand:
    """A step born as a stack of one, at ``seat`` when a gesture pointed at one — a CLI verb
    has no gesture, and the ambient layout places it."""
    stack = mint_id()
    entry = write_position(*seat, stack=stack) if seat is not None else write_member(stack)
    return CompositeCommand(
        label,
        [
            AddNodeCommand(project_id, step),
            SetModuleDataCommand(step.id, MODULE_ID, entry, label=label),
        ],
    )


def make_command(
    library: Library, step_ids: Sequence[StepId], label: str = MAKE_LABEL
) -> CompositeCommand:
    """Stack these steps where they stand, linked into one line.

    The order is the links' where there are any, and the canvas's left to right, top to
    bottom where there are none (:func:`line_order`). Each step waits on the one before it
    and nothing else among them — a link between two of them the line does not keep is one
    it implies. What any of them waited on from outside, the first waits on now, and what
    waited on any of them waits on the last: the stack takes its links in at its first step
    and sends them out from its last, and no step waits on less than it did. A line already
    one keeps every link. The first keeps its seat, which is the stack's, and the others'
    seats go — the column derives them; nothing moves out of the way, and the room the
    steps took is left as it was.
    """
    if (refusal := make_refusal(library, step_ids)) is not None:
        raise ValueError(refusal)
    order = line_order(library, list(dict.fromkeys(step_ids)))
    lists: dict[EdgeList, list[StepId]] = {}
    _link_line(library, order, lists)
    stack = mint_id()
    commands: list[Command] = []
    for index, member in enumerate(order):
        step = library.step(member)
        seat = read_position(step) if index == 0 else None
        entry = (
            write_position(*seat, read_size(step), stack=stack)
            if seat is not None
            else write_member(stack, read_size(step))
        )
        commands.append(SetModuleDataCommand(member, MODULE_ID, entry, label=label))
    return rewire_command(library, lists, label, commands)


def line_order(library: Library, step_ids: Sequence[StepId]) -> list[StepId]:
    """The order a stack made of these steps runs in: every link among them runs forward,
    and among steps no link orders, the one further left comes first, then the higher."""
    project = library.project_of(step_ids[0])
    seats = positions(library, project)
    inside = set(step_ids)
    waits = {
        step_id: [s for s in library.step(step_id).edges.get("requires", []) if s in inside]
        for step_id in step_ids
    }
    rank = {step_id: (*seats[step_id], index) for index, step_id in enumerate(step_ids)}
    order: list[StepId] = []
    while len(order) < len(step_ids):
        left = [step_id for step_id in step_ids if step_id not in order]
        ready = [step_id for step_id in left if all(s in order for s in waits[step_id])]
        order.append(min(ready or left, key=rank.__getitem__))
    return order


def add_command(
    library: Library,
    step: Step,
    stack: Stack,
    slot: int | None = None,
    *,
    carrying: Sequence[Command] = (),
    label: str = ADD_LABEL,
) -> CompositeCommand:
    """``step`` into ``stack`` at ``slot`` (a member index; the end when None).

    A step born for it arrives with ``carrying`` — the commands that make it what it is; an
    existing one is **disconnected first** and arrives with no links of its own. Put in
    front, it takes over the stack's inputs and its seat; put at the end, the old last's
    dependents wait on it instead.
    """
    if (refusal := line_refusal(library, stack) or join_refusal(library, step, stack)) is not None:
        raise ValueError(refusal)
    at = len(stack.members) if slot is None else slot
    if not 0 <= at <= len(stack.members):
        raise ValueError(f"a stack of {len(stack.members)} has no slot {at + 1}")
    new = (*stack.members[:at], step.id, *stack.members[at:])
    if library.has(step.id):
        return _restack(library, stack, new, label, joining=step.id)
    project_id = library.project_of(stack.head).id
    born = [AddNodeCommand(project_id, step), *carrying]
    return _restack(library, stack, new, label, born=(step, born))


def move_command(
    library: Library, stack: Stack, member: StepId, slot: int, label: str = MOVE_LABEL
) -> CompositeCommand:
    """A member to another slot in its stack. The chain follows the new order, and whoever
    ends up first and last carry the stack's inputs, dependents and seat."""
    if (refusal := _member_refusal(library, stack, member)) is not None:
        raise ValueError(refusal)
    if not 0 <= slot < len(stack.members):
        raise ValueError(f"a stack of {len(stack.members)} has no slot {slot + 1}")
    rest = [one for one in stack.members if one != member]
    new = (*rest[:slot], member, *rest[slot:])
    return _restack(library, stack, new, label)


def take_out_command(
    library: Library,
    stack: Stack,
    member: StepId,
    seat: Point | None = None,
    label: str = TAKE_OUT_LABEL,
) -> CompositeCommand:
    """A member out of its stack, **with no links at all**: the chain closes round the gap,
    and the stack's inputs, dependents and seat stay with whoever is first and last now.
    The step lands at ``seat`` when a gesture dropped it somewhere; with none, the ambient
    layout places it, as it places any step nobody put down."""
    if (refusal := _member_refusal(library, stack, member)) is not None:
        raise ValueError(refusal)
    new = tuple(one for one in stack.members if one != member)
    return _restack(library, stack, new, label, leaving=(member, seat))


def insert_before_command(
    library: Library,
    step: Step,
    before: StepId,
    label: str,
    *,
    carrying: Sequence[Command] = (),
    seat: Point | None = None,
) -> CompositeCommand:
    """A step born in front of ``before``: it takes over everything ``before`` waited on,
    and ``before`` waits on it alone.

    A stacked ``before`` makes the new step a member in its slot — in front of the first, it
    takes the stack's seat as well — and a lone one is a line of one, the new step landing
    at ``seat``. Never refused: over a stack somebody broke the splice keeps it no more
    broken than it was. Links that no longer resolve stay where they are.
    """
    project = library.project_of(before)
    waiting = library.step(before)
    taken = [source for source in waiting.edges.get("requires", []) if library.has(source)]
    kept = [source for source in waiting.edges.get("requires", []) if source not in taken]
    lists: dict[EdgeList, list[StepId]] = {
        (step.id, "requires"): taken,
        (before, "requires"): [*kept, step.id],
    }
    between: list[Command] = [AddNodeCommand(project.id, step), *carrying]
    stack = stack_of(project.steps, before)
    if stack is None:
        if seat is not None:
            between.append(
                SetModuleDataCommand(step.id, MODULE_ID, write_position(*seat), label=label)
            )
    else:
        slot = stack.members.index(before)
        new = (*stack.members[:slot], step.id, *stack.members[slot:])
        between += _membership(library, stack, new, label, born=step)
    return rewire_command(library, lists, label, between)


def dissolve_command(
    library: Library, stack: Stack, label: str = DISSOLVE_LABEL
) -> CompositeCommand:
    """The stack taken apart into the line it stands for.

    A placed stack lays its members out in a row from its seat, at the sorts' gap, and pushes
    everything past its frame out of the way by the room the row needs over the column — the
    Divide gesture's rule, so a stack beyond it travels whole. Nothing contracts: the room
    the column left below stays. A stack nobody placed only loses its membership, and the
    ambient layout lays the line out as it lays out any other. No link changes.
    """
    project = library.project_of(stack.head)
    steps = {step.id: step for step in project.steps}
    seat = read_position(steps[stack.head])
    if seat is None:
        return CompositeCommand(
            label,
            [
                SetModuleDataCommand(
                    m, MODULE_ID, write_member("", read_size(steps[m])), label=label
                )
                for m in stack.members
            ],
        )
    x, y = seat
    row: dict[StepId, Point] = {}
    across = 0.0
    for member in stack.members:
        row[member] = (x + across, y)
        across = math.ceil((across + node_size(steps[member])[0] + H_GAP) / GRID) * GRID
    last = stack.members[-1]
    row_right = row[last][0] + node_size(steps[last])[0]
    column_right = x + max(node_size(steps[member])[0] for member in stack.members)
    commands: list[Command] = [
        SetModuleDataCommand(
            member, MODULE_ID, write_position(*row[member], read_size(steps[member])), label=label
        )
        for member in stack.members
    ]
    by = math.ceil((row_right - column_right) / GRID) * GRID
    if by > 0:
        packing = pack(project)
        placed = packing.blocks(positions(library, project))
        left, _top = placed.pop(stack.head)
        cut = left + packing.sizes[stack.head][0]
        moved = packing.unfold(shift(placed, packing.sizes, "x", cut, by))
        commands += position_commands(project, moved, label)
    return CompositeCommand(label, commands)


def bridged_removal(
    library: Library, step_ids: Sequence[StepId], verb: str, *, links: Sequence[Edge] = ()
) -> CompositeCommand:
    """:func:`~dplanner.domain.commands.remove_steps_command`, closing every stack's chain
    round the members that go — what Delete, Cut, ``step remove`` and ``project
    clear-steps`` run.

    Over a stack that is one line, the member after a gap waits on the member before it, and
    a first or last member going hands the stack's inputs or dependents to the next one in
    line. A stack somebody broke loses its members plainly. Either way a first member going
    hands the seat on. A link picked beside the steps is removed, never moved.
    """
    doomed = set(step_ids)
    dropped = set(links)
    lists: dict[EdgeList, list[StepId]] = {}
    seats: list[Command] = []
    projects = {library.project_of(step_id).id: None for step_id in step_ids}
    for project_id in projects:
        steps = library.project(project_id).steps
        for stack in read_stacks(steps):
            survivors = tuple(one for one in stack.members if one not in doomed)
            if not survivors or len(survivors) == len(stack.members):
                continue
            if not stack.gaps and not stray_links(stack, steps):
                _relink(library, stack.members, survivors, lists, gone=doomed, dropped=dropped)
            seats += _membership(library, stack, survivors, verb)
    bridges = [
        (waiter, kind, source)
        for (waiter, kind), final in lists.items()
        for source in final
        if source not in library.step(waiter).edges.get(kind, [])
    ]
    return remove_steps_command(
        library, list(step_ids), verb, links=links, bridges=bridges, between=seats
    )


# -- the pieces --------------------------------------------------------------------------------


def _link_line(
    library: Library, order: Sequence[StepId], lists: dict[EdgeList, list[StepId]]
) -> None:
    """Plan, into ``lists``, the ``requires`` lists that make ``order`` one line: each step
    waits on the one before it alone, the first on everything any of them waited on from
    outside, and whatever waited on any of them on the last instead. Links that no longer
    resolve stay where they are."""
    inside = set(order)
    first, last = order[0], order[-1]
    inputs: list[StepId] = []
    for member in order:
        for source in library.step(member).edges.get("requires", []):
            if library.has(source) and source not in inside and source not in inputs:
                inputs.append(source)
    for index, member in enumerate(order):
        held = edge_list(lists, library, member, "requires")
        ghosts = [source for source in held if not library.has(source)]
        wanted = inputs if member == first else [order[index - 1]]
        if [s for s in held if library.has(s)] != wanted:
            held[:] = [*wanted, *ghosts]
    project = library.project_of(first)
    for step in project.steps:
        if step.id in inside:
            continue
        waits = step.edges.get("requires", [])
        if any(source in inside and source != last for source in waits):
            held = edge_list(lists, library, step.id, "requires")
            for member in order[:-1]:
                if member in held:
                    _replace(held, member, last)


def _member_refusal(library: Library, stack: Stack, member: StepId) -> str | None:
    if member not in stack.members:
        return f"{library.step(member).title!r} is not in this stack"
    return line_refusal(library, stack)


def _restack(
    library: Library,
    stack: Stack,
    new: Sequence[StepId],
    label: str,
    *,
    joining: StepId | None = None,
    born: tuple[Step, Sequence[Command]] | None = None,
    leaving: tuple[StepId, Point | None] | None = None,
) -> CompositeCommand:
    """The stack rebuilt in ``new`` order as one rewire: the links, then a step born and the
    membership and seats, then the new links."""
    lists: dict[EdgeList, list[StepId]] = {}
    _relink(
        library,
        stack.members,
        new,
        lists,
        joining=() if joining is None else (joining,),
        leaving=() if leaving is None else (leaving[0],),
    )
    between: list[Command] = [] if born is None else list(born[1])
    between += _membership(
        library,
        stack,
        new,
        label,
        born=None if born is None else born[0],
        leaving=leaving,
    )
    return rewire_command(library, lists, label, between)


def _relink(
    library: Library,
    old: Sequence[StepId],
    new: Sequence[StepId],
    lists: dict[EdgeList, list[StepId]],
    *,
    joining: Collection[StepId] = (),
    leaving: Collection[StepId] = (),
    gone: Collection[StepId] = (),
    dropped: Collection[Edge] = (),
) -> None:
    """Plan, into ``lists``, the ``requires`` lists that make ``old`` the line ``new``.

    In this order, each over the lists as the step before left them:

    1. A **joining** step loses every link it has — both kinds, as Isolate takes them.
    2. The **ends**: the old first member's inputs from outside the line go to the new first,
       and the old last's dependents outside it wait on the new last instead, in the place
       in their list where the old last stood. A step joining, a step being deleted
       (``gone``), a link picked for removal (``dropped``) and an id that no longer resolves
       are never moved.
    3. The **chain**: each member of ``new`` waits on the one before it, in the place of the
       one it waited on, so a list whose neighbour did not change is left as it was.
    4. A **leaving** step loses whatever links it still has.

    A ``gone`` step's own lists are left alone — they go with it, and come back with it.
    """
    first, last = old[0], old[-1]
    inside = {*old, *new}
    shut = {*joining, *gone}
    for waiter, kind, source in _links_of(library, joining):
        _drop(lists, library, waiter, kind, source)
    head = library.step(first).edges.get("requires", [])
    inputs = [
        source
        for source in head
        if library.has(source)
        and source not in inside
        and source not in shut
        and (first, "requires", source) not in dropped
    ]
    dependents = [
        step.id
        for step in library.dependents(last)
        if step.id not in inside
        and step.id not in shut
        and (step.id, "requires", last) not in dropped
    ]
    new_first = new[0] if new else None
    new_last = new[-1] if new else None
    if new_first != first:
        if first not in gone and first not in leaving:
            held = edge_list(lists, library, first, "requires")
            held[:] = [source for source in held if source not in inputs]
        if new_first is not None:
            held = edge_list(lists, library, new_first, "requires")
            held += [source for source in inputs if source not in held]
    if new_last != last:
        for waiter in dependents:
            _replace(edge_list(lists, library, waiter, "requires"), last, new_last)
    before = {then: one for one, then in pairwise(old)}
    for index, member in enumerate(new):
        wanted = new[index - 1] if index else None
        had = before.get(member)
        if wanted == had:
            continue
        held = edge_list(lists, library, member, "requires")
        if had is not None and had in held:
            _replace(held, had, wanted)
        elif wanted is not None and wanted not in held:
            held.append(wanted)
    for waiter, kind, source in _links_of(library, leaving):
        _drop(lists, library, waiter, kind, source)


def _membership(
    library: Library,
    stack: Stack,
    new: Sequence[StepId],
    label: str,
    *,
    born: Step | None = None,
    leaving: tuple[StepId, Point | None] | None = None,
) -> list[Command]:
    """The entries that make ``new`` the stack's members: a step joining gains the key, the
    first member holds the stack's seat — handed on when the first changes, and only when
    one was stored — and a step leaving keeps its size, the seat a gesture dropped it at,
    and no key. An entry that would not change is not written."""
    seat = read_position(library.step(stack.head))
    new_first = new[0] if new else None
    wanted: dict[StepId, dict[str, Any]] = {}
    for member in new:
        joined = member not in stack.members
        size = None if born is not None and member == born.id else read_size(library.step(member))
        if member == new_first:
            if joined or member != stack.head:
                wanted[member] = (
                    write_position(*seat, size, stack=stack.id)
                    if seat is not None
                    else write_member(stack.id, size)
                )
        elif joined or member == stack.head:
            wanted[member] = write_member(stack.id, size)
    if leaving is not None:
        step_id, dropped_at = leaving
        size = read_size(library.step(step_id))
        wanted[step_id] = (
            write_position(*dropped_at, size) if dropped_at is not None else write_member("", size)
        )
    return [
        SetModuleDataCommand(step_id, MODULE_ID, entry, label=label)
        for step_id, entry in wanted.items()
        if not library.has(step_id) or library.step(step_id).module_data.get(MODULE_ID, {}) != entry
    ]


def _links_of(library: Library, step_ids: Collection[StepId]) -> list[Edge]:
    """Every link, of a kind this build knows, with one end among steps already in the
    library — what disconnecting them takes."""
    present = [step_id for step_id in step_ids if library.has(step_id)]
    if not present:
        return []
    return [edge for edge in library.boundary_edges(present) if edge[1] in EDGE_KINDS]


def _drop(
    lists: dict[EdgeList, list[StepId]], library: Library, waiter: StepId, kind: str, source: StepId
) -> None:
    held = edge_list(lists, library, waiter, kind)
    if source in held:
        held.remove(source)


def _replace(held: list[StepId], old: StepId, new: StepId | None) -> None:
    """``old`` in ``held`` becomes ``new`` where it stood — or goes, when there is no ``new``
    or it is there already."""
    at = held.index(old)
    if new is None or new in held:
        del held[at]
    else:
        held[at] = new


def _title(library: Library) -> Callable[[StepId], str]:
    return lambda step_id: repr(library.step(step_id).title)
