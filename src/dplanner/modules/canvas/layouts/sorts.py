"""The sort algorithms: five ways to arrange a step graph, as pure functions.

Every sort returns a position for every step and writes nothing — persisting the result is
the caller's gesture, pushed through the undo stack like any drag. Every sort is
**deterministic**: fixed sweep counts, and every tie broken by project order, so the same
graph always lands the same way (the ``ordering.py`` convention). And every sort is
**size-aware** through ``size_for``, which defaults to the card's stored size
(``positions.node_size``) — so a card somebody dragged larger keeps its room in every
arrangement without touching an algorithm — and **stack-aware** the same way: it arranges
the project folded (``stack.fold``), each stack one tall block under its first member's id,
and unfolds the result into every card's seat, so no sort can split a stack and none of the
algorithms below knows one exists.

The gaps are chosen so the default node lands on round pitches: ``NODE_W + H_GAP`` is the
300-point column pitch, ``NODE_H + V_GAP`` the 120-point row.

The sixth arrangement, :func:`tidy`, is a sort in kind but starts from where the cards
*are*: it keeps every cluster and the left-to-right, top-to-bottom order of what is there,
and only resolves overlaps, evens the spacing to the pitches and closes holes. The
**lanes** it reads the picture through — :func:`lanes`, :func:`measured` — are the one
clustering ``dplanner layout show`` reports gaps by and the map is drawn on, so what the
report says and what a tidy does can never disagree.

The seventh, :func:`waves`, is Wave view's arrangement — every card in the column of its
dependency depth — and is also shown **live**, derived on every sync while Wave view is on and
never saved; so where the others only have to be deterministic, it also has to hold still
(see its section below). Keep This Arrangement and ``dplanner layout sort waves`` write it.

**Qt-free** — ``dplanner layout sort`` and ``layout tidy`` run these where no graphics
stack exists.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import ceil, cos, sin, tau

from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.ordering import depths
from dplanner.modules.canvas.layouts.positions import GRID, NODE_H, NODE_W, node_size, snapped
from dplanner.modules.canvas.stacks.stack import FRAME_PAD, Folded, fold
from dplanner.planning.schedule import earliest_starts

type Point = tuple[float, float]
type SizeFor = Callable[[Step], tuple[float, float]]
type DaysFor = Callable[[Step], float | None]
# A card's edge or extent along one axis, by id — what the lanes read a picture through.
type Along = Callable[[StepId], float]

ORIGIN = 40.0
H_GAP = 80.0
V_GAP = 44.0  # NODE_H + V_GAP = the 120-point row pitch; NODE_H moves owe a look here.
# The pitches: one default card and its gap. What "a column apart" means in numbers, and
# what tidy and the geometry report count a gap in.
H_PITCH = NODE_W + H_GAP
V_PITCH = NODE_H + V_GAP
# Tidy's threshold, in pitches: the widest gap between neighbouring lanes that survives.
# One empty column or row of deliberate air is kept; wider is a hole and closes.
DEFAULT_AIR = 2
# The backward lean of a fishbone rib: how far left of its attachment a rib begins.
RIB_DX = 60.0
# One working day of timeline, in canvas points.
DAY_PX = 60.0
# The base distance between radial rings; a crowded ring pushes further out.
RING_GAP = 220.0


# -- layered -----------------------------------------------------------------------------------


def layered_flow(
    library: Library, project: Project, size_for: SizeFor = node_size
) -> dict[StepId, Point]:
    """Dependency depth left to right, crossings reduced, columns centred."""
    folded = fold(project, size_for)
    return folded.packing.unfold(_layered(library, folded.project, folded.size_for, vertical=False))


def layered_down(
    library: Library, project: Project, size_for: SizeFor = node_size
) -> dict[StepId, Point]:
    """The same layering flowing top to bottom."""
    folded = fold(project, size_for)
    return folded.packing.unfold(_layered(library, folded.project, folded.size_for, vertical=True))


def _layered(
    library: Library, project: Project, size_for: SizeFor, vertical: bool
) -> dict[StepId, Point]:
    steps = project.steps
    if not steps:
        return {}
    order = {step.id: index for index, step in enumerate(steps)}
    by_depth = depths(library, project)
    columns: dict[int, list[Step]] = {}
    for step in steps:
        columns.setdefault(by_depth.get(step.id, 0), []).append(step)
    keys = sorted(columns)

    waiters: dict[StepId, list[StepId]] = {step.id: [] for step in steps}
    for step in steps:
        for source in step.edges.get("requires", []):
            if source in waiters:
                waiters[source].append(step.id)

    # Barycenter sweeps, two in each direction. The count is fixed — more passes converge
    # a little further, but a fixed number is what keeps the result a pure function.
    position = {step.id: index for key in keys for index, step in enumerate(columns[key])}

    def sweep(over: list[int], neighbours_of: Callable[[Step], list[StepId]]) -> None:
        for key in over:
            column = columns[key]

            def barycenter(step: Step) -> float:
                indices = [position[n] for n in neighbours_of(step) if n in position]
                if not indices:
                    return float(position[step.id])
                return sum(indices) / len(indices)

            column.sort(key=lambda step: (barycenter(step), order[step.id]))
            for index, step in enumerate(column):
                position[step.id] = index

    def sources_of(step: Step) -> list[StepId]:
        return [s for s in step.edges.get("requires", []) if s in position]

    for _ in range(2):
        sweep(keys, sources_of)
        sweep(list(reversed(keys)), lambda step: waiters[step.id])

    # Coordinates: the flow axis advances a column at a time; each column is stacked on the
    # cross axis and centred against the tallest, so the graph reads symmetric.
    sizes = {step.id: size_for(step) for step in steps}

    def along(step: Step) -> float:
        return sizes[step.id][1] if vertical else sizes[step.id][0]

    def cross(step: Step) -> float:
        return sizes[step.id][0] if vertical else sizes[step.id][1]

    extents = {
        key: sum(cross(step) for step in columns[key]) + V_GAP * (len(columns[key]) - 1)
        for key in keys
    }
    deepest = max(extents.values())
    placed: dict[StepId, Point] = {}
    flow = ORIGIN
    for key in keys:
        at = ORIGIN + (deepest - extents[key]) / 2
        for step in columns[key]:
            placed[step.id] = (at, flow) if vertical else (flow, at)
            at += cross(step) + V_GAP
        flow += max(along(step) for step in columns[key]) + H_GAP
    return placed


# -- spine (fishbone) --------------------------------------------------------------------------


def spine(library: Library, project: Project, size_for: SizeFor = node_size) -> dict[StepId, Point]:
    """The longest dependency chain on a central line, feeder chains branching back-left
    above and below it — the tree fallen on its side."""
    folded = fold(project, size_for)
    return folded.packing.unfold(_spine(library, folded.project, folded.size_for))


def _spine(library: Library, project: Project, size_for: SizeFor) -> dict[StepId, Point]:
    steps = project.steps
    if not steps:
        return {}
    order = {step.id: index for index, step in enumerate(steps)}
    by_id = {step.id: step for step in steps}
    by_depth = depths(library, project)
    sizes = {step.id: size_for(step) for step in steps}
    lane_height = max(h for _w, h in sizes.values()) + V_GAP

    # The spine: walk back from the deepest step, always through a source one level up.
    tip = min(steps, key=lambda step: (-by_depth.get(step.id, 0), order[step.id]))
    chain = [tip]
    while by_depth.get(chain[-1].id, 0) > 0:
        wanted = by_depth[chain[-1].id] - 1
        sources = [
            by_id[s]
            for s in chain[-1].edges.get("requires", [])
            if s in by_id and by_depth.get(s, 0) == wanted
        ]
        if not sources:
            break
        chain.append(min(sources, key=lambda step: order[step.id]))
    chain.reverse()

    placed: dict[StepId, Point] = {}
    assigned = {step.id for step in chain}
    x = ORIGIN
    attach_x = {}
    for step in chain:
        placed[step.id] = (x, 0.0)
        attach_x[step.id] = x
        x += sizes[step.id][0] + H_GAP
    end_x = x

    def open_sources(step: Step) -> list[Step]:
        found = [
            by_id[s] for s in step.edges.get("requires", []) if s in by_id and s not in assigned
        ]
        return sorted(found, key=lambda source: order[source.id])

    # Ribs alternate above and below, each on its own lane per side — two ribs never share
    # a band, which is what makes the layout overlap-free whatever the sizes.
    lanes = {1.0: 0, -1.0: 0}
    side = -1.0  # the first rib goes above (negative y is up on the canvas)

    def place_rib(start: Step, from_x: float) -> None:
        nonlocal side
        rib: list[Step] = []
        node: Step | None = start
        while node is not None:
            assigned.add(node.id)
            rib.append(node)
            onward = open_sources(node)
            node = onward[0] if onward else None
        lanes[side] += 1
        y = side * lanes[side] * lane_height
        side = -side
        edge = from_x - RIB_DX
        starts = []
        for step in rib:
            edge -= sizes[step.id][0]
            placed[step.id] = (edge, y)
            starts.append(edge)
            edge -= H_GAP
        # A rib step's remaining sources fan out as ribs of their own, anchored where it sat.
        for step, at in zip(rib, starts, strict=True):
            for source in open_sources(step):
                place_rib(source, at)

    for step in chain:
        for source in open_sources(step):
            place_rib(source, attach_x[step.id])
    # Whatever no spine step reaches — disconnected work — hangs past the spine's end.
    for step in steps:
        if step.id not in assigned:
            place_rib(step, end_x)
    return placed


# -- timeline ----------------------------------------------------------------------------------


def timeline(
    library: Library,
    project: Project,
    size_for: SizeFor = node_size,
    days_for: DaysFor | None = None,
    default_days: float = 1.0,
) -> dict[StepId, Point]:
    """X is when a step can start — after everything it waits on — so the graph reads as a
    plan in time. Steps that would collide share the moment, not the lane. A stack lasts as
    long as its members together, since its chain runs one after another."""
    folded = fold(project, size_for)
    real = {step.id: step for step in project.steps}

    def days(step: Step) -> float:
        found = days_for(step) if days_for is not None else None
        return found if found is not None and found > 0 else default_days

    def duration(block: Step) -> float:
        return sum(days(real[member]) for member in folded.packing.members_of(block.id))

    return folded.packing.unfold(_timeline(library, folded.project, folded.size_for, duration))


def _timeline(
    library: Library, project: Project, size_for: SizeFor, duration: Callable[[Step], float]
) -> dict[StepId, Point]:
    steps = project.steps
    if not steps:
        return {}
    order = {step.id: index for index, step in enumerate(steps)}
    sizes = {step.id: size_for(step) for step in steps}
    lane_height = max(h for _w, h in sizes.values()) + V_GAP
    # A broken stack can fold into a cycle; the walk counts the step closing it as met.
    starts = earliest_starts(library, project, days_for=duration)

    placed: dict[StepId, Point] = {}
    lane_right: list[float] = []
    for step in sorted(steps, key=lambda step: (starts[step.id], order[step.id])):
        x = ORIGIN + starts[step.id] * DAY_PX
        lane = next((i for i, right in enumerate(lane_right) if right <= x), len(lane_right))
        if lane == len(lane_right):
            lane_right.append(0.0)
        lane_right[lane] = x + sizes[step.id][0] + H_GAP
        placed[step.id] = (x, ORIGIN + lane * lane_height)
    return placed


# -- waves -------------------------------------------------------------------------------------
#
# Wave view's arrangement: every card in the column of its dependency depth. Unlike the sorts
# above it is shown live — derived on every sync while Wave view is on, never saved — so its
# one extra duty is to hold still: a link added must move only the steps it changes the wave
# of, and nothing may reshuffle a column it did not touch (``docs/architecture/canvas.md``'s *Wave
# view derives positions; only Free view saves them*).


@dataclass(frozen=True)
class Wave:
    """One column: how deep its steps stand, where its cards stand across, and when its work
    runs — from its earliest start to its latest finish, in working days from the plan's
    start. ``steps`` is every card in it top to bottom, a stack's members included."""

    depth: int
    left: float
    right: float
    start: float
    finish: float
    steps: tuple[StepId, ...]

    @property
    def label(self) -> str:
        """What the ruler calls it — numbered as the Order tab numbers waves, so a step has
        one wave number everywhere; the first, what nothing waits before, is the start."""
        return "START" if self.depth == 0 else f"WAVE {self.depth + 1}"

    @property
    def span(self) -> str:
        return span_words(self.start, self.finish)


# The dash between the ends of a range, spelled out: the lint would read the glyph as a hyphen.
EN_DASH = "\u2013"


def span_words(start: float, finish: float) -> str:
    """When a wave runs, in words — "day 0", or from one day to another, "1 to 2.5 d" with
    an en dash — the ruler's and ``layout show``'s alike, so the two cannot word one answer
    differently."""
    if start == finish:
        return f"day {start:g}"
    return f"{start:g} {EN_DASH} {finish:g} d"


@dataclass(frozen=True)
class WaveArrangement:
    """Every card's seat in Wave view, and the columns they stand in — what the ruler reads."""

    seats: dict[StepId, Point]
    waves: tuple[Wave, ...]


def waves(
    library: Library,
    project: Project,
    size_for: SizeFor = node_size,
    days_for: DaysFor | None = None,
) -> dict[StepId, Point]:
    """Every card in the column of its dependency depth — Wave view's seats, and what *Keep
    This Arrangement* and ``dplanner layout sort waves`` write."""
    return arranged_in_waves(library, project, size_for, days_for).seats


def arranged_in_waves(
    library: Library,
    project: Project,
    size_for: SizeFor = node_size,
    days_for: DaysFor | None = None,
) -> WaveArrangement:
    """The columns and every seat in them.

    A card's column is its dependency depth, over the folded graph: a stack is one block in
    the wave of its first member, and what follows it takes its depth from the stack as one
    node (N39). Down a column the blocks go by earliest start, then by where the highest of
    their sources stands in the column before, then by project order — one forward pass.
    Every rank there compares facts a new link changes only for the steps it moves, so no
    other card swaps places: that is why it is the *highest* source and not the mean of them
    (a mean can swap two cards whose sources never moved relative to each other), and why
    there is no second sweep.

    Columns start together at the top rather than centred, so a column changes only when
    its own cards do. Each is as wide as its widest card, and a stack's frame stands outside
    its cards' column, so a stack arriving never pushes the columns after it. Every seat is
    on the grid, where the canvas would have snapped it.
    """
    folded = fold(project, size_for)
    packing = folded.packing
    blocks = folded.project.steps
    if not blocks:
        return WaveArrangement({}, ())
    by_depth = depths(library, folded.project)
    starts, finishes = _block_times(library, project, folded, days_for)
    order = {block.id: index for index, block in enumerate(blocks)}
    columns: dict[int, list[Step]] = {}
    for block in blocks:
        columns.setdefault(by_depth.get(block.id, 0), []).append(block)

    rank: dict[StepId, int] = {}
    for depth in sorted(columns):

        def highest_source(block: Step, before: int = depth - 1) -> int:
            above = (
                rank[source]
                for source in block.edges.get("requires", [])
                if by_depth.get(source) == before and source in rank
            )
            return min(above, default=-1)

        column = columns[depth]
        column.sort(key=lambda block: (starts[block.id], highest_source(block), order[block.id]))
        rank.update((block.id, index) for index, block in enumerate(column))

    def inset(block: Step) -> float:
        return FRAME_PAD if block.id in packing.stacks else 0.0

    seats: dict[StepId, Point] = {}
    found: list[Wave] = []
    x = ORIGIN
    for depth in sorted(columns):
        column = columns[depth]
        y = ORIGIN
        for block in column:
            seats[block.id] = (x - inset(block), y)
            y = _up_to_grid(y + packing.sizes[block.id][1] + V_GAP)
        width = max(packing.sizes[block.id][0] - 2 * inset(block) for block in column)
        start, finish = _span(column, starts, finishes)
        members = tuple(member for block in column for member in packing.members_of(block.id))
        found.append(Wave(depth, x, x + width, start, finish, members))
        x = _up_to_grid(x + width + H_GAP)
    return WaveArrangement(packing.unfold(seats), tuple(found))


def _block_times(
    library: Library, project: Project, folded: Folded, days_for: DaysFor | None
) -> tuple[dict[StepId, float], dict[StepId, float]]:
    """Each block's earliest start and finish. A stack lasts as long as its members
    together, since its chain runs one after another; an unestimated step takes no days."""
    real = {step.id: step for step in project.steps}

    def own(step: Step) -> float:
        return (days_for(step) if days_for is not None else None) or 0.0

    lasting = {
        block.id: sum(own(real[member]) for member in folded.packing.members_of(block.id))
        for block in folded.project.steps
    }
    starts = earliest_starts(library, folded.project, days_for=lambda block: lasting[block.id])
    return starts, {block: start + lasting[block] for block, start in starts.items()}


def _span(
    column: Sequence[Step], starts: dict[StepId, float], finishes: dict[StepId, float]
) -> tuple[float, float]:
    return min(starts[block.id] for block in column), max(finishes[block.id] for block in column)


def _up_to_grid(value: float) -> float:
    """The next seat on the grid at or past ``value`` — never nearer than the gap asked."""
    return float(ceil(value / GRID) * GRID)


# -- radial ------------------------------------------------------------------------------------


def most_connected(library: Library, project: Project) -> StepId | None:
    """The step with the most links either way — radial's centre when none is chosen."""
    steps = project.steps
    if not steps:
        return None
    order = {step.id: index for index, step in enumerate(steps)}
    degree = {step.id: 0 for step in steps}
    for step in steps:
        for source in step.edges.get("requires", []):
            if source in degree:
                degree[step.id] += 1
                degree[source] += 1
    return min(steps, key=lambda step: (-degree[step.id], order[step.id])).id


def radial(
    library: Library,
    project: Project,
    size_for: SizeFor = node_size,
    center: StepId | None = None,
) -> dict[StepId, Point]:
    """The chosen step at the middle, everything else fanned out on rings by how many
    links away it is, each branch keeping an angular sector sized to what hangs off it. A
    member of a stack chosen as the middle puts its whole stack there."""
    folded = fold(project, size_for)
    middle = None if center is None else folded.packing.block_of(center)
    return folded.packing.unfold(_radial(library, folded.project, folded.size_for, middle))


def _radial(
    library: Library, project: Project, size_for: SizeFor, center: StepId | None
) -> dict[StepId, Point]:
    steps = project.steps
    if not steps:
        return {}
    order = {step.id: index for index, step in enumerate(steps)}
    sizes = {step.id: size_for(step) for step in steps}
    if center is None or all(step.id != center for step in steps):
        center = most_connected(library, project)
        assert center is not None

    neighbours: dict[StepId, list[StepId]] = {step.id: [] for step in steps}
    for step in steps:
        for source in step.edges.get("requires", []):
            if source in neighbours:
                neighbours[step.id].append(source)
                neighbours[source].append(step.id)
    for key in neighbours:
        neighbours[key] = sorted(set(neighbours[key]), key=lambda n: order[n])

    ring: dict[StepId, int] = {center: 0}
    children: dict[StepId, list[StepId]] = {step.id: [] for step in steps}
    queue = [center]
    while queue:
        node = queue.pop(0)
        for near in neighbours[node]:
            if near not in ring:
                ring[near] = ring[node] + 1
                children[node].append(near)
                queue.append(near)
    # Steps the centre cannot reach still deserve a seat: an outermost ring of their own.
    unreachable = sorted((step.id for step in steps if step.id not in ring), key=lambda n: order[n])
    outermost = max(ring.values()) + 1
    for step_id in unreachable:
        ring[step_id] = outermost

    weight: dict[StepId, int] = {}

    def weigh(node: StepId) -> int:
        weight[node] = 1 + sum(weigh(child) for child in children[node])
        return weight[node]

    weigh(center)

    angle: dict[StepId, float] = {center: 0.0}

    def fan(node: StepId, low: float, high: float) -> None:
        angle[node] = (low + high) / 2
        total = sum(weight[child] for child in children[node])
        at = low
        for child in children[node]:
            share = (high - low) * weight[child] / total
            fan(child, at, at + share)
            at += share

    fan(center, 0.0, tau)
    for index, step_id in enumerate(unreachable):
        angle[step_id] = tau * index / len(unreachable)

    # Ring radii: far enough out for the ring's population to keep a node width of chord
    # between neighbours on average, and always past the ring before it.
    population: dict[int, int] = {}
    for level in ring.values():
        population[level] = population.get(level, 0) + 1
    widest = max(w for w, _h in sizes.values())
    tallest = max(h for _w, h in sizes.values())
    radius = {0: 0.0}
    for level in sorted(population):
        if level == 0:
            continue
        wanted = max(level * RING_GAP, population[level] * (widest + H_GAP) / tau)
        radius[level] = max(wanted, radius.get(level - 1, 0.0) + tallest + V_GAP)

    placed: dict[StepId, Point] = {}
    for step_id, level in ring.items():
        w, h = sizes[step_id]
        r = radius[level]
        placed[step_id] = (r * cos(angle[step_id]) - w / 2, r * sin(angle[step_id]) - h / 2)
    return placed


# -- tidy ---------------------------------------------------------------------------------------
#
# Where the five sorts read the graph, tidy reads the picture: the cards as they sit, in
# lanes. Every rule below is there because a simpler one broke an invariant — the lanes
# cluster on *edges* (centres split a column of mixed widths on the second run), the join is
# *inclusive* (the flow sort centres a column by whole half-pitches), an overlap becomes a
# *sub-row* of its own (a stack inside a cell beside a taller neighbour was not idempotent),
# and a hole is measured against the *reach* of everything before it and *rounded* (snap
# noise of eight points must never collapse a kept empty row).


@dataclass(frozen=True)
class Lane:
    """One band of cards across an axis, and the air before it.

    ``near`` and ``far`` are the band's nearest and furthest edges; ``gap`` is measured from
    the reach of every lane before it — a tall card two lanes back still counts — and is
    None for the first lane.
    """

    steps: tuple[StepId, ...]
    near: float
    far: float
    gap: float | None


def lanes(ids: Sequence[StepId], edge: Along, half: float) -> list[list[StepId]]:
    """Greedy bands along one axis: the first card anchors a lane, a card joins while its
    edge is within ``half`` of the anchor (inclusive), else it anchors the next. Ties keep
    the order ``ids`` arrive in — project order, for every caller."""
    found: list[list[StepId]] = []
    anchor: float | None = None
    for step_id in sorted(ids, key=edge):
        if anchor is None or edge(step_id) - anchor > half:
            found.append([])
            anchor = edge(step_id)
        found[-1].append(step_id)
    return found


def measured(bands: Sequence[Sequence[StepId]], low: Along, size: Along) -> list[Lane]:
    """The lanes with their edges and the gap before each, in the order given."""
    found: list[Lane] = []
    reach: float | None = None
    for band in bands:
        near = min(low(step_id) for step_id in band)
        far = max(low(step_id) + size(step_id) for step_id in band)
        found.append(Lane(tuple(band), near, far, None if reach is None else near - reach))
        reach = far if reach is None else max(reach, far)
    return found


def hole(lane: Lane, gap: float, pitch: float) -> int:
    """How many empty whole pitches lie before a lane — none for the first, and never
    fewer than none for one that is cramped or overlapping. Rounded: ``round`` is Python's,
    which takes an exact half-pitch to the even count — deterministic, so acceptable."""
    if lane.gap is None:
        return 0
    return max(0, round((lane.gap - gap) / pitch))


def _spread(
    bands: Sequence[Lane], size: Along, gap: float, pitch: float, air: int
) -> dict[StepId, float]:
    """Seats along one axis: lanes laid from ``ORIGIN`` at the pitch, a kept hole carried,
    a hole wider than ``air`` closed to one gap. Accumulated exactly and snapped per lane, so
    nothing drifts."""
    seats: dict[StepId, float] = {}
    at = ORIGIN
    for lane in bands:
        if lane.gap is not None:
            kept = hole(lane, gap, pitch)
            at += gap + (kept if kept + 1 <= air else 0) * pitch
        for step_id in lane.steps:
            seats[step_id] = snapped(at, GRID)
        at += max(size(step_id) for step_id in lane.steps)
    return seats


def tidy(
    project: Project,
    placed: dict[StepId, Point],
    size_for: SizeFor = node_size,
    *,
    air: int = DEFAULT_AIR,
) -> dict[StepId, Point]:
    """Keep every cluster and its order; resolve overlaps, even the spacing to the pitches,
    close any hole wider than ``air`` pitches to one, snap to the grid and start at the
    origin. Idempotent: a tidied graph tidies to itself, and a sorted one to itself snapped.

    ``placed`` is where every step sits now (``placement.positions``); this file cannot
    import that one, so the caller hands the picture in. A stack is read and tidied as its
    frame, one tall card, and its members follow.
    """
    folded = fold(project, size_for)
    blocks = folded.packing.blocks(placed)
    return folded.packing.unfold(_tidy(folded.project, blocks, folded.size_for, air))


def _tidy(
    project: Project, placed: dict[StepId, Point], size_for: SizeFor, air: int
) -> dict[StepId, Point]:
    steps = project.steps
    if not steps:
        return {}
    rects = {step.id: (*placed[step.id], *size_for(step)) for step in steps}
    ids = [step.id for step in steps]

    def left(step_id: StepId) -> float:
        return rects[step_id][0]

    def top(step_id: StepId) -> float:
        return rects[step_id][1]

    def width(step_id: StepId) -> float:
        return rects[step_id][2]

    def height(step_id: StepId) -> float:
        return rects[step_id][3]

    columns = lanes(ids, left, H_PITCH / 2)
    column_of = {step_id: index for index, band in enumerate(columns) for step_id in band}
    # Two cards in one column and one row overlap; the lower one takes a sub-row of its
    # own, inserted after the row — the same line count as stacking, and stable on re-run.
    rows: list[list[StepId]] = []
    for band in lanes(ids, top, V_PITCH / 2):
        taken: dict[int, int] = {}
        sub: list[list[StepId]] = []
        for step_id in sorted(band, key=lambda step_id: (top(step_id), left(step_id))):
            depth = taken.get(column_of[step_id], 0)
            taken[column_of[step_id]] = depth + 1
            if depth == len(sub):
                sub.append([])
            sub[depth].append(step_id)
        rows.extend(sub)
    xs = _spread(measured(columns, left, width), width, H_GAP, H_PITCH, air)
    ys = _spread(measured(rows, top, height), height, V_GAP, V_PITCH, air)
    return {step_id: (xs[step_id], ys[step_id]) for step_id in ids}
