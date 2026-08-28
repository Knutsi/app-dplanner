"""The sort algorithms: five ways to arrange a step graph, as pure functions.

Every sort returns a position for every step and writes nothing — persisting the result is
the caller's gesture, pushed through the undo stack like any drag. Every sort is
**deterministic**: fixed sweep counts, and every tie broken by project order, so the same
graph always lands the same way (the ``ordering.py`` convention). And every sort is
**size-aware** through ``size_for``, so when nodes grow beyond one fixed footprint — a step
kind that packs more inside itself — the spacing follows without touching an algorithm.

The gaps are chosen so the default node lands on round pitches: ``NODE_W + H_GAP`` is the
300-point column pitch, ``NODE_H + V_GAP`` the 120-point row.

**Qt-free** — ``dplanner layout sort`` runs these where no graphics stack exists.
"""

from collections.abc import Callable
from math import cos, sin, tau

from dplanner.domain.model import Product, Project, Step, StepId
from dplanner.domain.ordering import depths
from dplanner.modules.project_editor.positions import NODE_H, NODE_W

type Point = tuple[float, float]
type SizeFor = Callable[[Step], tuple[float, float]]
type DaysFor = Callable[[Step], float | None]

ORIGIN = 40.0
H_GAP = 80.0
V_GAP = 44.0  # NODE_H + V_GAP = the 120-point row pitch; NODE_H moves owe a look here.
# The backward lean of a fishbone rib: how far left of its attachment a rib begins.
RIB_DX = 60.0
# One working day of timeline, in canvas points.
DAY_PX = 60.0
# The base distance between radial rings; a crowded ring pushes further out.
RING_GAP = 220.0


def node_size(_step: Step) -> tuple[float, float]:
    """The default footprint — today every node is the same size."""
    return (NODE_W, NODE_H)


# -- layered -----------------------------------------------------------------------------------


def layered_flow(
    product: Product, project: Project, size_for: SizeFor = node_size
) -> dict[StepId, Point]:
    """Dependency depth left to right, crossings reduced, columns centred."""
    return _layered(product, project, size_for, vertical=False)


def layered_down(
    product: Product, project: Project, size_for: SizeFor = node_size
) -> dict[StepId, Point]:
    """The same layering flowing top to bottom."""
    return _layered(product, project, size_for, vertical=True)


def _layered(
    product: Product, project: Project, size_for: SizeFor, vertical: bool
) -> dict[StepId, Point]:
    steps = project.steps
    if not steps:
        return {}
    order = {step.id: index for index, step in enumerate(steps)}
    by_depth = depths(product, project)
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


def spine(
    product: Product, project: Project, size_for: SizeFor = node_size
) -> dict[StepId, Point]:
    """The longest dependency chain on a central line, feeder chains branching back-left
    above and below it — the tree fallen on its side."""
    steps = project.steps
    if not steps:
        return {}
    order = {step.id: index for index, step in enumerate(steps)}
    by_id = {step.id: step for step in steps}
    by_depth = depths(product, project)
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
            by_id[s]
            for s in step.edges.get("requires", [])
            if s in by_id and s not in assigned
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
    product: Product,
    project: Project,
    size_for: SizeFor = node_size,
    days_for: DaysFor | None = None,
    default_days: float = 1.0,
) -> dict[StepId, Point]:
    """X is when a step can start — after everything it waits on — so the graph reads as a
    plan in time. Steps that would collide share the moment, not the lane."""
    steps = project.steps
    if not steps:
        return {}
    order = {step.id: index for index, step in enumerate(steps)}
    by_id = {step.id: step for step in steps}
    sizes = {step.id: size_for(step) for step in steps}
    lane_height = max(h for _w, h in sizes.values()) + V_GAP

    def duration(step: Step) -> float:
        days = days_for(step) if days_for is not None else None
        return days if days is not None and days > 0 else default_days

    earliest: dict[StepId, float] = {}

    def start_of(step: Step) -> float:
        if step.id not in earliest:
            sources = [by_id[s] for s in step.edges.get("requires", []) if s in by_id]
            earliest[step.id] = max(
                (start_of(source) + duration(source) for source in sources), default=0.0
            )
        return earliest[step.id]

    placed: dict[StepId, Point] = {}
    lane_right: list[float] = []
    for step in sorted(steps, key=lambda step: (start_of(step), order[step.id])):
        x = ORIGIN + start_of(step) * DAY_PX
        lane = next((i for i, right in enumerate(lane_right) if right <= x), len(lane_right))
        if lane == len(lane_right):
            lane_right.append(0.0)
        lane_right[lane] = x + sizes[step.id][0] + H_GAP
        placed[step.id] = (x, ORIGIN + lane * lane_height)
    return placed


# -- radial ------------------------------------------------------------------------------------


def most_connected(product: Product, project: Project) -> StepId | None:
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
    product: Product,
    project: Project,
    size_for: SizeFor = node_size,
    center: StepId | None = None,
) -> dict[StepId, Point]:
    """The chosen step at the middle, everything else fanned out on rings by how many
    links away it is, each branch keeping an angular sector sized to what hangs off it."""
    steps = project.steps
    if not steps:
        return {}
    order = {step.id: index for index, step in enumerate(steps)}
    sizes = {step.id: size_for(step) for step in steps}
    if center is None or all(step.id != center for step in steps):
        center = most_connected(product, project)
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
    unreachable = sorted(
        (step.id for step in steps if step.id not in ring), key=lambda n: order[n]
    )
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
