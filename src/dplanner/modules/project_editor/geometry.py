"""What the canvas knows about where things are, said in a terminal.

An agent planning through the CLI cannot see the graph. This file is its eyes and one of
its hands. The eyes: the geometry every surface agrees on — the stored positions with the
ambient layout filling the gaps (``placement.positions``), the card sizes
(``positions.node_size``), the waves (``ordering.depths``) — measured into a report an
agent can read (:func:`measure`, :func:`text`, :func:`as_json`) and a map it can look at
(:func:`map_text`), **derived on every read and never stored**: a second copy of where
things are is one that can disagree with the first. The hand: :func:`shift`, the canvas's
Divide as a function — the same side rule, the same snapped distance, the same
``Divide Graph`` command (:func:`divide_command`) both surfaces push.

The columns and rows it reports are the sorts' lanes (``sorts.lanes``), so a gap the report
calls two pitches is a gap ``layout tidy`` keeps, and the map is drawn on the same lanes
rather than on pixels — a graph at an odd pitch still reads as the columns it has.

**Qt-free** — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from dplanner.domain.commands import CompositeCommand
from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.ordering import depths
from dplanner.modules.project_editor.named_layouts import Point, position_commands
from dplanner.modules.project_editor.placement import positions
from dplanner.modules.project_editor.positions import GRID, Size, node_size, snapped
from dplanner.modules.project_editor.sorts import (
    DEFAULT_AIR,
    H_GAP,
    H_PITCH,
    V_GAP,
    V_PITCH,
    Along,
    Lane,
    hole,
    lanes,
    measured,
)

type Rect = tuple[float, float, float, float]
type Axis = Literal["x", "y"]

# The label both surfaces give the command: the undo menu's word for one pushed side.
DIVIDE_LABEL = "Divide Graph"
# One map cell — a column pitch wide, a row pitch tall — is this many characters across.
CELL_W = 8


@dataclass(frozen=True)
class Card:
    """One step's body on the canvas, and the wave the graph puts it in."""

    id: StepId
    key: str
    title: str
    x: float
    y: float
    w: float
    h: float
    wave: int


@dataclass(frozen=True)
class Wave:
    number: int
    steps: tuple[StepId, ...]
    bounds: Rect


@dataclass(frozen=True)
class Geometry:
    """The graph as measured: every card, the box round them, the waves' boxes, every
    overlapping pair, and the lanes across each axis with the gaps between them."""

    cards: tuple[Card, ...]
    bounds: Rect | None
    waves: tuple[Wave, ...]
    overlaps: tuple[tuple[StepId, StepId], ...]
    columns: tuple[Lane, ...]
    rows: tuple[Lane, ...]


# -- measuring ----------------------------------------------------------------------------------


def measure(
    library: Library,
    project: Project,
    *,
    key_of: Callable[[Step], str],
    placed: dict[StepId, Point] | None = None,
) -> Geometry:
    """The geometry as it stands. ``placed`` lets a caller that already read the positions
    hand them over rather than derive them twice."""
    steps = project.steps
    if not steps:
        return Geometry((), None, (), (), (), ())
    if placed is None:
        placed = positions(library, project)
    by_depth = depths(library, project)
    cards = tuple(
        Card(
            step.id,
            key_of(step),
            step.title,
            *placed[step.id],
            *node_size(step),
            by_depth.get(step.id, 0) + 1,
        )
        for step in steps
    )
    rects = {card.id: (card.x, card.y, card.w, card.h) for card in cards}
    waves = []
    for number in sorted({card.wave for card in cards}):
        members = tuple(card.id for card in cards if card.wave == number)
        waves.append(Wave(number, members, _bounds([rects[i] for i in members])))
    ids = [card.id for card in cards]

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
        tuple(_overlaps(cards)),
        tuple(measured(lanes(ids, left, H_PITCH / 2), left, width)),
        tuple(measured(lanes(ids, top, V_PITCH / 2), top, height)),
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


def _overlaps(cards: Sequence[Card]) -> list[tuple[StepId, StepId]]:
    """Every pair whose bodies share interior — touching edges are not an overlap."""
    found = []
    for index, one in enumerate(cards):
        for other in cards[index + 1 :]:
            apart = (
                one.x + one.w <= other.x
                or other.x + other.w <= one.x
                or one.y + one.h <= other.y
                or other.y + other.h <= one.y
            )
            if not apart:
                found.append((one.id, other.id))
    return found


# -- saying it ----------------------------------------------------------------------------------


def as_json(geometry: Geometry) -> dict[str, Any]:
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
            }
            for card in geometry.cards
        ],
        "bounds": _rect_json(geometry.bounds),
        "waves": [
            {"wave": wave.number, "steps": list(wave.steps), "bounds": _rect_json(wave.bounds)}
            for wave in geometry.waves
        ],
        "overlaps": [list(pair) for pair in geometry.overlaps],
        "columns": _lanes_json(geometry.columns, H_GAP, H_PITCH),
        "rows": _lanes_json(geometry.rows, V_GAP, V_PITCH),
    }


def text(geometry: Geometry) -> str:
    """The report a person or an agent reads: the box, a table of cards, the overlaps, the
    lanes with their gaps, and the waves."""
    if geometry.bounds is None:
        return "no steps"
    keys = _keys(geometry)
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
    pairs = ", ".join(f"{keys[a]} x {keys[b]}" for a, b in geometry.overlaps)
    lines.append(f"overlaps: {pairs or 'none'}")
    lines += lane_lines(geometry, "x")
    lines += lane_lines(geometry, "y")
    lines.append("waves:")
    for wave in geometry.waves:
        bx, by, bw, bh = wave.bounds
        named = " ".join(keys[i] for i in wave.steps)
        lines.append(f"  {wave.number:>2}  at {bx:g},{by:g} size {bw:g} x {bh:g}  {named}")
    return "\n".join(lines)


def lane_lines(geometry: Geometry, axis: Axis) -> list[str]:
    """The lanes across one axis, each with the gap before it in units and in pitches."""
    keys = _keys(geometry)
    bands, gap, pitch, name = (
        (geometry.columns, H_GAP, H_PITCH, "columns")
        if axis == "x"
        else (geometry.rows, V_GAP, V_PITCH, "rows")
    )
    lines = [f"{name} (pitch {pitch:g}):"]
    for index, lane in enumerate(bands, 1):
        if lane.gap is not None:
            lines.append(f"      gap {lane.gap:g} ({_gap_words(lane, gap, pitch)})")
        named = " ".join(keys[i] for i in lane.steps)
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


def _rect_json(rect: Rect | None) -> dict[str, float] | None:
    if rect is None:
        return None
    x, y, w, h = rect
    return {"x": x, "y": y, "w": w, "h": h}


def _lanes_json(bands: Sequence[Lane], gap: float, pitch: float) -> dict[str, Any]:
    return {
        "pitch": pitch,
        "gap": gap,
        "lanes": [
            {
                "steps": list(lane.steps),
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
    ``S2/S4``. Cells are the lanes, so a hole reads as an empty cell whatever its width in
    units. Plain ASCII, so it pastes into any code fence."""
    cards = {card.id: card for card in geometry.cards}
    if not cards:
        return ""
    column_at = _cell_index(geometry.columns, lambda i: cards[i].w, H_GAP, H_PITCH)
    row_at = _cell_index(geometry.rows, lambda i: cards[i].h, V_GAP, V_PITCH)
    spans = {
        i: (_span(card.w, H_GAP, H_PITCH), _span(card.h, V_GAP, V_PITCH))
        for i, card in cards.items()
    }
    width = max(column_at[i] + spans[i][0] for i in cards)
    height = max(row_at[i] + spans[i][1] for i in cards)
    grid = [[" "] * (width * CELL_W) for _ in range(height)]
    for step_id, card in cards.items():
        column, row = column_at[step_id], row_at[step_id]
        across, down = spans[step_id]
        start, room = column * CELL_W, across * CELL_W - 1
        held = "".join(grid[row][start : start + room]).strip(" -")
        label = (f"{held}/{card.key}" if held else card.key)[:room]
        grid[row][start : start + room] = list(label.ljust(room, "-" if across > 1 else " "))
        for below in range(1, down):
            grid[row + below][start] = "|"
    return "\n".join("".join(line).rstrip() for line in grid)


def _cell_index(bands: Sequence[Lane], size: Along, gap: float, pitch: float) -> dict[StepId, int]:
    """Each lane's first cell: the lanes in order, a hole kept as empty cells, a lane as
    wide as its widest card."""
    found: dict[StepId, int] = {}
    at = 0
    for lane in bands:
        at += hole(lane, gap, pitch)
        for step_id in lane.steps:
            found[step_id] = at
        at += _span(max(size(step_id) for step_id in lane.steps), gap, pitch)
    return found


def _span(extent: float, gap: float, pitch: float) -> int:
    return max(1, round((extent + gap) / pitch))


# -- shifting -----------------------------------------------------------------------------------


def shift(
    placed: dict[StepId, Point],
    sizes: dict[StepId, Size],
    axis: Axis,
    cut: float,
    by: float,
    only: Collection[StepId] | None = None,
) -> dict[StepId, Point]:
    """The Divide gesture's rule as a function: which side a card is on is its body's
    centre against the cut, a positive distance pushes the far side, a negative one
    brings the near side back, and the distance snaps to the grid as the drag does. Only
    the seats that move are returned. ``only`` names the movers outright — the cut then
    says nothing but the axis."""
    delta = snapped(by, GRID)
    along = 0 if axis == "x" else 1

    def beyond(step_id: StepId) -> bool:
        x, y = placed[step_id]
        w, h = sizes[step_id]
        return (x + w / 2, y + h / 2)[along] > cut

    if only is not None:
        moving = [step_id for step_id in placed if step_id in only]
    elif delta > 0:
        moving = [step_id for step_id in placed if beyond(step_id)]
    elif delta < 0:
        moving = [step_id for step_id in placed if not beyond(step_id)]
    else:
        moving = []
    return {
        step_id: (placed[step_id][0] + delta, placed[step_id][1])
        if along == 0
        else (placed[step_id][0], placed[step_id][1] + delta)
        for step_id in moving
    }


def divide_command(
    project: Project, moved: dict[StepId, Point], view_origin: object = None
) -> CompositeCommand:
    """One pushed side as one undo step — what the canvas's Divide pushes and what
    ``dplanner layout shift`` applies."""
    return CompositeCommand(
        DIVIDE_LABEL, position_commands(project, moved, DIVIDE_LABEL, view_origin=view_origin)
    )
