"""A stack: a chain of steps the canvas draws as one tall card.

A stack is **presentation over a chain**, never a thing in the model (``ARCHITECTURE.md``'s
*A stack is presentation over a chain*). Each member carries ``"stack": "<id>"`` in its
``project_editor`` entry, the first member's seat is the stack's and the others store none,
and the order is read from the real ``requires`` chain — so ordering, the schedule and Ready
never learn a stack exists, and no stored order can disagree with the edges it would copy.

Every reader of positions treats a stack as one tall card, through the two halves of one
fold. :class:`Packing` is the geometry and knows no graph: card seats in, block seats out,
and back again — what a cut drag and ``layout shift`` hold. :func:`fold` adds the graph: a
scratch project with each stack one block under its first member's id, which every sort and
the geometry report run over unchanged.

**What may link to a stack is a rule the domain asks** (:func:`link_rule`, installed on the
library by the composition root): links arrive at the first member and leave from the last,
and the chain between is nobody else's. What another writer or a hand edit brings in anyway
is read, drawn and named (:func:`stray_links`, lint's ``stack.broken``), never repaired.

**Qt-free** — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

import math
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise

from dplanner.domain.model import Edge, Library, Project, Step, StepId
from dplanner.modules.project_editor.positions import GRID, Size, node_size, read_stack

type Point = tuple[float, float]
type Rect = tuple[float, float, float, float]
type Gap = tuple[StepId, StepId]

# The frame's margin round its column: room to take hold of it, and for the "+" set into its
# bottom edge. On the grid, so a stack whose first card sits on it has a frame on it too.
FRAME_PAD = 16.0
# The least room between one member's card and the next, for the connector drawn in place of
# an arrow. The next seat is rounded up onto the grid from there — the canvas snaps every card
# it places, and a default card's 76 plus 16 is not a multiple of 8 — so a column whose first
# card is on the grid is on it all the way down.
MEMBER_GAP = 16.0


def mint_id() -> str:
    """A new stack's id: opaque, and never a step id, so an import that mints fresh step ids
    keeps every stack without remapping one."""
    return uuid.uuid4().hex


@dataclass(frozen=True)
class Stack:
    """One stack: its members in chain order, and every neighbouring pair in that order the
    chain does not link — none, unless something outside broke it."""

    id: str
    members: tuple[StepId, ...]
    gaps: tuple[Gap, ...] = ()

    @property
    def head(self) -> StepId:
        """The first member, whose seat is the stack's."""
        return self.members[0]

    @property
    def broken(self) -> bool:
        return bool(self.gaps)


def chain(
    members: Sequence[StepId], requires_of: Callable[[StepId], Iterable[StepId]]
) -> tuple[tuple[StepId, ...], tuple[Gap, ...]]:
    """``members`` in chain order, and the gaps in it.

    Only a direct ``requires`` between two members counts. A run starts at each member with
    no predecessor among them, in the order given; then the earliest member not yet visited
    starts the next — a fork's second branch, a cycle a hand edit made — so every member
    lands in exactly one run, and a gap is where one run meets the next.
    """
    inside = set(members)
    after: dict[StepId, list[StepId]] = {member: [] for member in members}
    first: list[StepId] = []
    for member in members:
        before = [s for s in requires_of(member) if s in inside and s != member]
        for source in before:
            after[source].append(member)
        if not before:
            first.append(member)
    visited: set[StepId] = set()
    runs: list[list[StepId]] = []
    for start in (*first, *members):
        if start in visited:
            continue
        run = [start]
        visited.add(start)
        while (onward := next((m for m in after[run[-1]] if m not in visited), None)) is not None:
            run.append(onward)
            visited.add(onward)
        runs.append(run)
    order = tuple(member for run in runs for member in run)
    return order, tuple((one[-1], two[0]) for one, two in pairwise(runs))


def read_stacks(steps: Sequence[Step]) -> list[Stack]:
    """Every stack these steps make, in the order each one's first member comes."""
    grouped: dict[str, list[Step]] = {}
    for step in steps:
        if stack_id := read_stack(step):
            grouped.setdefault(stack_id, []).append(step)
    if not grouped:
        return []
    found = []
    for stack_id, group in grouped.items():
        waits = {step.id: step.edges.get("requires", []) for step in group}
        order, gaps = chain(list(waits), waits.__getitem__)
        found.append(Stack(stack_id, order, gaps))
    at = {step.id: index for index, step in enumerate(steps)}
    return sorted(found, key=lambda stack: at[stack.head])


def stack_of(steps: Sequence[Step], step_id: StepId) -> Stack | None:
    """The stack a step stands in, read with its order and its gaps — None for a loose step."""
    return next((stack for stack in read_stacks(steps) if step_id in stack.members), None)


def stray_links(stack: Stack, steps: Sequence[Step]) -> tuple[Edge, ...]:
    """Every ``requires`` link that makes a stack more than one line besides its gaps: into a
    member below the first from anywhere but the member before it, and out of a member above
    the last to anywhere but the member after it. The first member's inputs and the last's
    dependents are the stack's own; a ``relates`` link is nobody's business here, and an id
    that no longer resolves is a ghost lint names elsewhere."""
    members = stack.members
    after = dict(pairwise(members))
    before = {then: first for first, then in after.items()}
    ids = {step.id for step in steps}
    found: dict[Edge, None] = {}
    for step in steps:
        for source in step.edges.get("requires", []):
            if source not in ids:
                continue
            into = step.id in before and source != before[step.id]
            out_of = source in after and step.id != after[source]
            if into or out_of:
                found[(step.id, "requires", source)] = None
    return tuple(found)


def broken_reason(
    stack: Stack, name: Callable[[StepId], str], strays: Sequence[Edge] = ()
) -> str | None:
    """What breaks a stack, in words — None for one that is a single line. ``strays`` are
    :func:`stray_links`' answer, for a reader that asked it."""
    words = [f"{name(then)} does not wait on {name(before)}" for before, then in stack.gaps]
    for waiter, _kind, source in strays:
        into = waiter in stack.members[1:]
        end = "first step takes links in" if into else "last step sends links out"
        words.append(f"{name(waiter)} waits on {name(source)}, though only the stack's {end}")
    return "; ".join(words) or None


def link_rule(library: Library, waiter: StepId, kind: str, source: StepId) -> str | None:
    """One in, one out: why ``waiter`` may not wait on ``source`` because of a stack, or None.

    A stack takes its links in at its first member and sends them out from its last, and
    the chain between is its own. Refused:

    - a link into a member that already waits on one of its own stack — it is below the
      first;
    - a link out of a member one of its own stack already waits on — it is above the last;
    - a link between two members of one stack while the waiter waits on anything or the
      source has any dependent — a chain link joins two free ends.

    Only ``requires`` counts, and only links that resolve. It reads membership and link
    counts, never positions, and every condition says *some other link exists* — so a link
    legal in a graph is legal in every part of it, which is why one gesture at a time can
    never break a stack that is one line (``ARCHITECTURE.md``'s *One in, one out is a rule
    the domain asks*). A run head in a stack somebody broke counts as a first member.
    Each refusal names what fixes it.
    """
    if kind != "requires":
        return None
    here, there = library.step(waiter), library.step(source)
    own, theirs = read_stack(here), read_stack(there)
    if not own and not theirs:
        return None
    if own:
        waits_on = library.requires(waiter)
        if any(read_stack(step) == own for step in waits_on):
            first = _end_title(library, waiter, own, last=False)
            return (
                f"{here.title!r} is inside a stack: a link into it arrives at its first step, "
                f"{first!r} — or take {here.title!r} out of the stack first"
            )
        if theirs == own and waits_on:
            return (
                f"{here.title!r} also waits on steps outside its stack, and only a stack's "
                "first step may — unlink them first"
            )
    if theirs:
        waited_by = library.dependents(source)
        if any(read_stack(step) == theirs for step in waited_by):
            last = _end_title(library, source, theirs, last=True)
            return (
                f"{there.title!r} is inside a stack: a link out of it leaves from its last "
                f"step, {last!r} — or take {there.title!r} out of the stack first"
            )
        if own == theirs and waited_by:
            return (
                f"{there.title!r} also has steps outside its stack waiting on it, and only a "
                "stack's last step may — unlink them first"
            )
    return None


def _end_title(library: Library, member: StepId, stack_id: str, *, last: bool) -> str:
    """The title of the first or last member of the stack ``member`` stands in — read only
    when a refusal has to name it."""
    steps = library.project_of(member).steps
    found = next(stack for stack in read_stacks(steps) if stack.id == stack_id)
    end = found.members[-1] if last else found.head
    return library.step(end).title


def member_seats(
    stack: Stack, head_seat: Point, size_of: Callable[[StepId], Size]
) -> dict[StepId, Point]:
    """Every member's top-left: a column under the first one's seat, left-aligned, each card
    at its own height and at least ``MEMBER_GAP`` from the next, a whole number of grid
    steps below the first."""
    x, y = head_seat
    seats, down = {}, 0.0
    for member in stack.members:
        seats[member] = (x, y + down)
        down = math.ceil((down + size_of(member)[1] + MEMBER_GAP) / GRID) * GRID
    return seats


def frame(stack: Stack, head_seat: Point, size_of: Callable[[StepId], Size]) -> Rect:
    """The tall card: the column of member cards, as wide as its widest, and the pad round
    it."""
    x, y = head_seat
    last = stack.members[-1]
    height = member_seats(stack, head_seat, size_of)[last][1] + size_of(last)[1] - y
    width = max(size_of(member)[0] for member in stack.members)
    return x - FRAME_PAD, y - FRAME_PAD, width + 2 * FRAME_PAD, height + 2 * FRAME_PAD


class Packing:
    """The geometry of a fold: each stack one block under its first member's id, as big as
    its frame, and every other card as it is.

    Card seats go in and block seats come out (:meth:`blocks`); whatever moves blocks — a
    sort, a tidy, a shift, a contract — hands them back to :meth:`unfold` for every card's
    seat. A stack is packed only when every member has a card, so a view a moment behind the
    model never asks for a card it does not have.
    """

    def __init__(self, stacks: Sequence[Stack], cards: Mapping[StepId, Size]) -> None:
        self._cards = cards
        self.stacks = {s.head: s for s in stacks if all(m in cards for m in s.members)}
        self._stack_of = {m: s for s in self.stacks.values() for m in s.members}
        # Every block's footprint: a card's own, or its stack's frame.
        self.sizes: dict[StepId, Size] = {}
        for step_id, size in cards.items():
            stack = self._stack_of.get(step_id)
            if stack is None:
                self.sizes[step_id] = size
            elif step_id == stack.head:
                _x, _y, width, height = frame(stack, (0.0, 0.0), self._card)
                self.sizes[step_id] = (width, height)

    def _card(self, step_id: StepId) -> Size:
        return self._cards[step_id]

    def block_of(self, step_id: StepId) -> StepId:
        """The block a card is part of: its stack's first member, or itself."""
        stack = self._stack_of.get(step_id)
        return step_id if stack is None else stack.head

    def members_of(self, block: StepId) -> tuple[StepId, ...]:
        """The cards a block stands for, in chain order."""
        stack = self.stacks.get(block)
        return (block,) if stack is None else stack.members

    def blocks(self, placed: Mapping[StepId, Point]) -> dict[StepId, Point]:
        """Card seats → block seats: a stack's is its frame's corner, taken from its first
        member's seat, and its other members say nothing."""
        found: dict[StepId, Point] = {}
        for step_id, (x, y) in placed.items():
            stack = self._stack_of.get(step_id)
            if stack is None:
                found[step_id] = (x, y)
            elif step_id == stack.head:
                found[step_id] = (x - FRAME_PAD, y - FRAME_PAD)
        return found

    def unfold(self, blocks: Mapping[StepId, Point]) -> dict[StepId, Point]:
        """Block seats → every card's seat: a frame's corner becomes its column."""
        found: dict[StepId, Point] = {}
        for block, (x, y) in blocks.items():
            stack = self.stacks.get(block)
            if stack is None:
                found[block] = (x, y)
            else:
                found.update(member_seats(stack, (x + FRAME_PAD, y + FRAME_PAD), self._card))
        return found


def pack(project: Project, size_for: Callable[[Step], Size] = node_size) -> Packing:
    """The project's stacks packed over its cards' footprints."""
    return Packing(read_stacks(project.steps), {step.id: size_for(step) for step in project.steps})


@dataclass(frozen=True)
class Folded:
    """A project as an arrangement sees it: each stack one block under its first member's
    id, carrying no module data — so folding it again changes nothing — and the packing
    that turns the blocks' seats back into the cards'."""

    project: Project
    packing: Packing

    def size_for(self, step: Step) -> Size:
        return self.packing.sizes[step.id]


def fold(project: Project, size_for: Callable[[Step], Size] = node_size) -> Folded:
    """The project with every stack folded into one block.

    A block waits on what its first member waits on — the stack stands in that member's
    wave — and a step that waits on any member waits on the block, so what comes after a
    stack takes its depth from the stack as one node. A stack broken from outside can fold
    into a cycle the real graph does not have; every walk over a graph guards against one.
    With no stacks the project comes back as it is.
    """
    packing = pack(project, size_for)
    if not packing.stacks:
        return Folded(project, packing)
    folded = Project(node_id=project.id, title=project.title, created=project.created)
    for step in project.steps:
        if packing.block_of(step.id) != step.id:
            continue  # A member below its stack's first: the block stands for it.
        waits = (packing.block_of(source) for source in step.edges.get("requires", []))
        requires = list(dict.fromkeys(source for source in waits if source != step.id))
        folded.steps.append(
            Step(
                node_id=step.id,
                title=step.title,
                edges={"requires": requires},
                created=step.created,
            )
        )
    return Folded(folded, packing)
