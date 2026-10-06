"""What the canvas knows about where things are, said in a terminal.

An agent planning through the CLI cannot see the graph. This file is its eyes and one of
its hands. The eyes: the geometry every surface agrees on — the stored positions with the
ambient layout filling the gaps (``placement.positions``), the card sizes
(``positions.node_size``), the waves (``ordering.depths``) — measured into a report an
agent can read (:func:`measure`, :func:`text`, :func:`as_json`) and a map it can look at
(:func:`map_text`), **derived on every read and never stored**: a second copy of where
things are is one that can disagree with the first. The hands: :func:`shift`, the canvas's
Divide as a function, and :func:`contract`, its Contract — each the one rule both the
gesture and the ``layout`` verb run, building the one command (:func:`divide_command`)
both surfaces push.

The columns and rows it reports are the sorts' lanes (``sorts.lanes``), so a gap the report
calls two pitches is a gap ``layout tidy`` keeps, and the map is drawn on the same lanes
rather than on pixels — a graph at an odd pitch still reads as the columns it has.

**It measures the picture, and in the picture a stack is one tall card**: the lanes, the
overlaps, the bounds and the waves are taken over the graph folded (``stack.fold``), each
stack its frame — what tidy acts on, and what a stack is in Wave view (N39), so a wave here
is not ``order show``'s. The cards are still every step at its own seat. Handed ``days_for``,
each wave also says when it runs — Wave view's ruler, in words, read off the one arrangement
(``sorts.arranged_in_waves``).

**Qt-free** — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

import math
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from dplanner.domain.commands import CompositeCommand
from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.ordering import depths
from dplanner.modules.canvas.layouts.named import Point, position_commands
from dplanner.modules.canvas.layouts.placement import positions
from dplanner.modules.canvas.layouts.positions import GRID, Size, node_size
from dplanner.modules.canvas.layouts.sorts import (
    DEFAULT_AIR,
    H_GAP,
    H_PITCH,
    V_GAP,
    V_PITCH,
    Lane,
    arranged_in_waves,
    hole,
    lanes,
    measured,
    span_words,
)
from dplanner.modules.canvas.stacks.stack import Rect, Stack, broken_reason, fold

type Axis = Literal["x", "y"]

# The labels both surfaces give the command: the undo menu's word for one side pushed away
# from a cut, and for one side pulled up to it.
DIVIDE_LABEL = "Divide Graph"
CONTRACT_LABEL = "Contract Graph"
# One map cell — a column pitch wide, a row pitch tall — is this many characters across.
CELL_W = 8


@dataclass(frozen=True)
class Card:
    """One step's body on the canvas, the wave the graph puts it in, and the stack it stands
    in ("" for none)."""

    id: StepId
    key: str
    title: str
    x: float
    y: float
    w: float
    h: float
    wave: int
    stack: str = ""


@dataclass(frozen=True)
class StackBox:
    """One stack as measured: its members in chain order, and its frame."""

    stack: Stack
    frame: Rect


@dataclass(frozen=True)
class Wave:
    """One wave's cards and their box — and, measured with ``days_for``, when it runs, in
    working days from the plan's start, as Wave view's ruler says it."""

    number: int
    steps: tuple[StepId, ...]
    bounds: Rect
    start: float | None = None
    finish: float | None = None


@dataclass(frozen=True)
class Geometry:
    """The graph as measured: every card, and — a stack counting as its frame — the box
    round them, the waves' boxes, every overlapping pair, and the lanes across each axis
    with the gaps between them. A stack is named in a lane or a pair by its first member."""

    cards: tuple[Card, ...]
    bounds: Rect | None
    waves: tuple[Wave, ...]
    overlaps: tuple[tuple[StepId, StepId], ...]
    columns: tuple[Lane, ...]
    rows: tuple[Lane, ...]
    stacks: tuple[StackBox, ...] = ()


# -- measuring ----------------------------------------------------------------------------------


def measure(
    library: Library,
    project: Project,
    *,
    key_of: Callable[[Step], str],
    days_for: Callable[[Step], float | None] | None = None,
) -> Geometry:
    """The geometry as it stands — with each wave's span when ``days_for`` is handed in."""
    steps = project.steps
    if not steps:
        return Geometry((), None, (), (), (), ())
    placed = positions(library, project)
    folded = fold(project)
    packing = folded.packing
    rects = {
        block: (*seat, *packing.sizes[block]) for block, seat in packing.blocks(placed).items()
    }
    by_depth = depths(library, folded.project)
    stack_of = {member: stack.id for stack in packing.stacks.values() for member in stack.members}
    cards = tuple(
        Card(
            step.id,
            key_of(step),
            step.title,
            *placed[step.id],
            *node_size(step),
            by_depth.get(packing.block_of(step.id), 0) + 1,
            stack_of.get(step.id, ""),
        )
        for step in steps
    )
    runs = () if days_for is None else arranged_in_waves(library, project, days_for=days_for).waves
    spans = {wave.depth: (wave.start, wave.finish) for wave in runs}
    waves = []
    for number in sorted({card.wave for card in cards}):
        members = tuple(card.id for card in cards if card.wave == number)
        blocks = dict.fromkeys(packing.block_of(step_id) for step_id in members)
        start, finish = spans.get(number - 1, (None, None))
        box = _bounds([rects[block] for block in blocks])
        waves.append(Wave(number, members, box, start, finish))
    ids = list(rects)

    def left(step_id: StepId) -> float:
        return rects[step_id][0]

    def top(step_id: StepId) -> float:
        return rects[step_id][1]

    def width(step_id: StepId) -> float:
        return rects[step_id][2]

    def height(step_id: StepId) -> float:
        return rects[step_id][3]

    return Geometry(
        cards,
        _bounds(list(rects.values())),
        tuple(waves),
        tuple(_overlaps(rects)),
        tuple(measured(lanes(ids, left, H_PITCH / 2), left, width)),
        tuple(measured(lanes(ids, top, V_PITCH / 2), top, height)),
        tuple(StackBox(stack, rects[stack.head]) for stack in packing.stacks.values()),
    )


def pitches(lane: Lane, gap: float, pitch: float) -> float | None:
    """A lane's gap in pitches — one is neighbours at the sort's spacing, two is one empty
    column or row between. None for the first lane."""
    if lane.gap is None:
        return None
    return (lane.gap - gap) / pitch + 1


def _bounds(rects: Sequence[Rect]) -> Rect:
    left = min(x for x, _y, _w, _h in rects)
    top = min(y for _x, y, _w, _h in rects)
    right = max(x + w for x, _y, w, _h in rects)
    bottom = max(y + h for _x, y, _w, h in rects)
    return left, top, right - left, bottom - top


def _overlaps(rects: dict[StepId, Rect]) -> list[tuple[StepId, StepId]]:
    """Every pair whose bodies share interior — touching edges are not an overlap."""
    found = []
    boxes = list(rects.items())
    for index, (one, (x1, y1, w1, h1)) in enumerate(boxes):
        for other, (x2, y2, w2, h2) in boxes[index + 1 :]:
            apart = x1 + w1 <= x2 or x2 + w2 <= x1 or y1 + h1 <= y2 or y2 + h2 <= y1
            if not apart:
                found.append((one, other))
    return found


# -- saying it ----------------------------------------------------------------------------------


def as_json(geometry: Geometry) -> dict[str, Any]:
    """Every card by id; a lane lists a stack's members in order, and an overlap names a
    stack by its first member, which ``stacks`` maps to the rest."""
    members = _members(geometry)
    return {
        "steps": [
            {
                "id": card.id,
                "key": card.key,
                "title": card.title,
                "x": card.x,
                "y": card.y,
                "w": card.w,
                "h": card.h,
                "wave": card.wave,
                "stack": card.stack or None,
            }
            for card in geometry.cards
        ],
        "bounds": _rect_json(geometry.bounds),
        "waves": [
            {
                "wave": wave.number,
                "steps": list(wave.steps),
                "bounds": _rect_json(wave.bounds),
                "start": wave.start,
                "finish": wave.finish,
            }
            for wave in geometry.waves
        ],
        "overlaps": [list(pair) for pair in geometry.overlaps],
        "columns": _lanes_json(geometry.columns, H_GAP, H_PITCH, members),
        "rows": _lanes_json(geometry.rows, V_GAP, V_PITCH, members),
        "stacks": [
            {
                "id": box.stack.id,
                "steps": list(box.stack.members),
                "frame": _rect_json(box.frame),
                "gaps": [list(gap) for gap in box.stack.gaps],
            }
            for box in geometry.stacks
        ],
    }


def text(geometry: Geometry) -> str:
    """The report a person or an agent reads: the box, a table of cards, the overlaps, the
    lanes with their gaps, the waves, and the stacks — a stack named ``[S5 S6 S7]`` wherever
    it counts as one card."""
    if geometry.bounds is None:
        return "no steps"
    keys = _keys(geometry)
    names = _names(geometry)
    x, y, w, h = geometry.bounds
    lines = [
        f"{len(geometry.cards)} steps in {len(geometry.columns)} columns x "
        f"{len(geometry.rows)} rows; bounds {x:g},{y:g} to {x + w:g},{y + h:g} ({w:g} x {h:g})",
        f"  {'key':<5} {'wave':>4} {'x':>6} {'y':>6} {'w':>5} {'h':>4}  title",
    ]
    for card in geometry.cards:
        lines.append(
            f"  {card.key:<5} {card.wave:>4} {card.x:>6g} {card.y:>6g} {card.w:>5g} "
            f"{card.h:>4g}  {card.title or 'Untitled step'}"
        )
    pairs = ", ".join(f"{names[a]} x {names[b]}" for a, b in geometry.overlaps)
    lines.append(f"overlaps: {pairs or 'none'}")
    lines += lane_lines(geometry, "x")
    lines += lane_lines(geometry, "y")
    lines.append("waves:")
    for wave in geometry.waves:
        bx, by, bw, bh = wave.bounds
        named = " ".join(keys[i] for i in wave.steps)
        runs = (
            ""
            if wave.start is None or wave.finish is None
            else "  " + span_words(wave.start, wave.finish)
        )
        lines.append(f"  {wave.number:>2}  at {bx:g},{by:g} size {bw:g} x {bh:g}{runs}  {named}")
    if geometry.stacks:
        lines.append("stacks:")
    for box in geometry.stacks:
        fx, fy, fw, fh = box.frame
        named = " ".join(keys[i] for i in box.stack.members)
        broken = broken_reason(box.stack, keys.__getitem__)
        lines.append(
            f"  {box.stack.id[:8]}  frame {fx:g},{fy:g} to {fx + fw:g},{fy + fh:g}  {named}"
            + (f" — broken: {broken}" if broken else "")
        )
    return "\n".join(lines)


def lane_lines(geometry: Geometry, axis: Axis) -> list[str]:
    """The lanes across one axis, each with the gap before it in units and in pitches."""
    names = _names(geometry)
    bands, gap, pitch, name = (
        (geometry.columns, H_GAP, H_PITCH, "columns")
        if axis == "x"
        else (geometry.rows, V_GAP, V_PITCH, "rows")
    )
    lines = [f"{name} (pitch {pitch:g}):"]
    for index, lane in enumerate(bands, 1):
        if lane.gap is not None:
            lines.append(f"      gap {lane.gap:g} ({_gap_words(lane, gap, pitch)})")
        named = " ".join(names[i] for i in lane.steps)
        lines.append(f"  {index:>2}  {axis} {lane.near:g}..{lane.far:g}  {named}")
    return lines


def _gap_words(lane: Lane, gap: float, pitch: float) -> str:
    if lane.gap is not None and lane.gap < 0:
        return "overlapping"
    count = pitches(lane, gap, pitch)
    assert count is not None
    words = f"{count:.1f} pitch{'' if abs(count - 1) < 0.05 else 'es'}"
    return f"{words} — wide" if hole(lane, gap, pitch) + 1 > DEFAULT_AIR else words


def _keys(geometry: Geometry) -> dict[StepId, str]:
    return {card.id: card.key or card.title or "Untitled step" for card in geometry.cards}


def _names(geometry: Geometry) -> dict[StepId, str]:
    """A card's key, or a stack's members' keys in brackets where it counts as one card."""
    keys = _keys(geometry)
    for head, members in _members(geometry).items():
        keys[head] = f"[{' '.join(keys[member] for member in members)}]"
    return keys


def _members(geometry: Geometry) -> dict[StepId, tuple[StepId, ...]]:
    return {box.stack.head: box.stack.members for box in geometry.stacks}


def _rect_json(rect: Rect | None) -> dict[str, float] | None:
    if rect is None:
        return None
    x, y, w, h = rect
    return {"x": x, "y": y, "w": w, "h": h}


def _lanes_json(
    bands: Sequence[Lane], gap: float, pitch: float, members: dict[StepId, tuple[StepId, ...]]
) -> dict[str, Any]:
    return {
        "pitch": pitch,
        "gap": gap,
        "lanes": [
            {
                "steps": [card for i in lane.steps for card in members.get(i, (i,))],
                "from": lane.near,
                "to": lane.far,
                "gap": lane.gap,
                "pitches": None
                if (count := pitches(lane, gap, pitch)) is None
                else round(count, 2),
                "holes": hole(lane, gap, pitch),
            }
            for lane in bands
        ],
    }


# -- the map ------------------------------------------------------------------------------------


def map_text(geometry: Geometry) -> str:
    """The graph as text: one line per row lane, one cell per column lane, a step's key in
    its cell. A card wider than a pitch spans cells and is filled with ``-``; a card taller
    than one drops a ``|`` through the rows below; two cards in one cell share it as
    ``S2/S4``; a stack is its members' keys down its frame's column, a row each. Cells are
    the lanes, so a hole reads as an empty cell whatever its width in units. Plain ASCII,
    so it pastes into any code fence."""
    if not geometry.cards:
        return ""
    keys = {card.id: card.key for card in geometry.cards}
    members = _members(geometry)
    stacked = {member for column in members.values() for member in column}
    rects: dict[StepId, Rect] = {
        card.id: (card.x, card.y, card.w, card.h)
        for card in geometry.cards
        if card.id not in stacked
    }
    rects.update((box.stack.head, box.frame) for box in geometry.stacks)
    spans = {
        block: (
            _span(w, H_GAP, H_PITCH),
            max(_span(h, V_GAP, V_PITCH), len(members.get(block, ()))),
        )
        for block, (_x, _y, w, h) in rects.items()
    }
    column_at = _cell_index(geometry.columns, lambda i: spans[i][0], H_GAP, H_PITCH)
    row_at = _cell_index(geometry.rows, lambda i: spans[i][1], V_GAP, V_PITCH)
    width = max(column_at[i] + spans[i][0] for i in rects)
    height = max(row_at[i] + spans[i][1] for i in rects)
    grid = [[" "] * (width * CELL_W) for _ in range(height)]
    for block in rects:
        column, row = column_at[block], row_at[block]
        across, down = spans[block]
        start, room = column * CELL_W, across * CELL_W - 1
        labels = [keys[member] for member in members.get(block, (block,))]
        for line, key in enumerate(labels):
            held = "".join(grid[row + line][start : start + room]).strip(" -|")
            label = (f"{held}/{key}" if held else key)[:room]
            grid[row + line][start : start + room] = list(
                label.ljust(room, "-" if across > 1 else " ")
            )
        for below in range(len(labels), down):
            grid[row + below][start] = "|"
    return "\n".join("".join(line).rstrip() for line in grid)


def _cell_index(
    bands: Sequence[Lane], cells: Callable[[StepId], int], gap: float, pitch: float
) -> dict[StepId, int]:
    """Each lane's first cell: the lanes in order, a hole kept as empty cells, a lane as
    many cells deep as its deepest card. A lane that starts inside the reach of the ones
    before it — beside a card taller than a pitch, or a stack — starts as many cells down
    from the lane before it as it lies pitches below that lane, so what stands beside a tall
    card is drawn beside it rather than under it."""
    found: dict[StepId, int] = {}
    reach = 0  # The first cell past every lane so far.
    before: tuple[int, float] | None = None  # The last lane's first cell and near edge.
    for lane in bands:
        if before is not None and lane.gap is not None and lane.gap < 0:
            cell, near = before
            at = min(reach, cell + max(1, round((lane.near - near) / pitch)))
        else:
            at = reach + hole(lane, gap, pitch)
        for step_id in lane.steps:
            found[step_id] = at
        reach = max(reach, at + max(cells(step_id) for step_id in lane.steps))
        before = (at, lane.near)
    return found


def _span(extent: float, gap: float, pitch: float) -> int:
    return max(1, round((extent + gap) / pitch))


# -- shifting and contracting ------------------------------------------------------------------


def shift(
    placed: dict[StepId, Point],
    sizes: dict[StepId, Size],
    axis: Axis,
    cut: float,
    by: float,
    only: Collection[StepId] | None = None,
) -> dict[StepId, Point]:
    """The Divide gesture's rule as a function: which side a card is on is its body's
    centre against the cut, a positive distance pushes the far side and a negative one
    brings the near side back. Only the seats that move are returned. ``only`` names the
    movers outright — the cut then says nothing but the axis. The distance is taken as
    given: the drag snaps it through the scene, the verb onto the grid."""
    if only is not None:
        moving = [step_id for step_id in placed if step_id in only]
    elif by == 0:
        moving = []
    else:
        moving = [s for s in placed if _beyond(placed, sizes, axis, cut, s) == (by > 0)]
    return _moved(placed, moving, axis, by)


@dataclass(frozen=True)
class Contraction:
    """What a contract did: the seats that moved, how far the side travelled (signed,
    along the axis), and the pair that stopped it — the card that moved and the card it
    stopped a gap short of — or None when the distance asked for ran out first."""

    moved: dict[StepId, Point]
    by: float
    stopped: tuple[StepId, StepId] | None


def contract(
    placed: dict[StepId, Point],
    sizes: dict[StepId, Size],
    axis: Axis,
    cut: float,
    by: float,
) -> Contraction:
    """The Contract gesture's rule as a function — Divide's other half. The side *behind*
    the travel is pulled along it as one block, closing the gap at the cut: the far side
    for a negative distance, the near side for a positive one, each card's side decided by
    its centre as :func:`shift` decides it.

    It stops the sorts' gap (``H_GAP`` across an upright cut, ``V_GAP`` across a level one)
    short of the first card ahead of it that shares its band — whose extent across the
    travel overlaps a mover's — so it never makes an overlap; a card in another band can
    never meet it, and a pair that already overlaps is ignored. The room is rounded towards
    the cut onto the grid, so a side on the grid stays on it. An infinite distance closes
    as far as that allows, and moves nothing when no card ahead shares a band."""
    if by == 0:
        return Contraction({}, 0.0, None)
    along = 0 if axis == "x" else 1
    gap = H_GAP if axis == "x" else V_GAP
    pulled = [s for s in placed if _beyond(placed, sizes, axis, cut, s) == (by < 0)]
    block = set(pulled)

    def extent(step_id: StepId, index: int) -> tuple[float, float]:
        low = placed[step_id][index]
        return low, low + sizes[step_id][index]

    room, stopped = math.inf, None
    for mover in pulled:
        (low, high), (side_low, side_high) = extent(mover, along), extent(mover, 1 - along)
        for other in placed:
            other_low, other_high = extent(other, 1 - along)
            if other in block or other_high <= side_low or side_high <= other_low:
                continue  # Moving with it, or in another band: it can never be met.
            ahead_low, ahead_high = extent(other, along)
            distance = low - ahead_high if by < 0 else ahead_low - high
            if distance < 0:
                continue  # Behind the mover, or already overlapping it.
            free = max(0.0, math.floor((distance - gap) / GRID) * GRID)
            if free < room:
                room, stopped = free, (mover, other)
    travel = min(abs(by), room)
    if abs(by) < room:
        stopped = None
    if travel == 0 or math.isinf(travel):
        return Contraction({}, 0.0, stopped)
    signed = math.copysign(travel, by)
    return Contraction(_moved(placed, pulled, axis, signed), signed, stopped)


def direction(axis: Axis, by: float) -> str:
    """Which way a signed distance along an axis goes, in the words both surfaces say."""
    return ("right" if by > 0 else "left") if axis == "x" else ("down" if by > 0 else "up")


def _beyond(
    placed: dict[StepId, Point], sizes: dict[StepId, Size], axis: Axis, cut: float, step_id: StepId
) -> bool:
    """Whether a card's body centre lies past the cut — the side rule both hands share."""
    along = 0 if axis == "x" else 1
    return placed[step_id][along] + sizes[step_id][along] / 2 > cut


def _moved(
    placed: dict[StepId, Point], moving: Sequence[StepId], axis: Axis, by: float
) -> dict[StepId, Point]:
    return {
        step_id: (placed[step_id][0] + by, placed[step_id][1])
        if axis == "x"
        else (placed[step_id][0], placed[step_id][1] + by)
        for step_id in moving
    }


def divide_command(
    project: Project,
    moved: dict[StepId, Point],
    view_origin: object = None,
    *,
    label: str = DIVIDE_LABEL,
) -> CompositeCommand:
    """One moved side as one undo step — what the canvas's Divide and Contract push and
    what ``dplanner layout shift`` and ``layout contract`` apply."""
    return CompositeCommand(
        label, position_commands(project, moved, label, view_origin=view_origin)
    )
