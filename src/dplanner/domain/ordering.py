"""In what order can a project's steps be done, and what can be started now.

A project is a graph, and this is the question the graph is *for*. The answer is a
topological sort, arranged in waves: everything in wave one has nothing left to wait on and
can be started today; everything in wave two waits only on wave one.

**Plain functions over the model, with no Qt**, so the canvas layout, the order view and the
CLI all read the same walk — and so the interesting part is testable without a widget in
sight. `project_editor/placement.py` is the other file that works this way, for the same reason.

**Deterministic by construction.** A topological sort has many valid answers; this one breaks
every tie by the project's own step order, so the result changes when the graph changes and
not otherwise. An order that reshuffled between two reads would be useless in a diff and
worse to a person watching it.

**Nothing here is written to disk.** The order is derived, and derived data that is also
stored is data that can disagree with itself — the CLI would be the one to catch it out, since
``dplanner step link`` changes a graph with no window running to notice. Availability comes
from exposing this function everywhere instead: the activity, ``dplanner order show``, and
``--json`` for anything reading programmatically.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from dplanner.domain.model import Library, Project, Step, StepId


def depths(library: Library, project: Project) -> dict[StepId, int]:
    """How many ``requires`` edges deep each step is — the length of its longest chain.

    The edges are read off the steps this project holds, never looked up in the library, so
    a project built as a view of another — the graph editor folding a stack into one block —
    is measured as itself. The model refuses to create a cycle, but a hand-edited file or
    such a view can hold one, so the walk guards against it and places the step it closes
    at depth zero. An edge to a step outside the project is skipped.
    """
    known: dict[StepId, int] = {}
    by_id = {step.id: step for step in project.steps}  # Once per walk: Project.step() is a scan.

    def depth_of(step_id: StepId, seen: frozenset[StepId]) -> int:
        if step_id in known:
            return known[step_id]
        if step_id in seen:
            return 0
        waiting = by_id[step_id].edges.get("requires", [])
        resolved = [t for t in waiting if t in by_id]

        found = 0 if not resolved else 1 + max(depth_of(t, seen | {step_id}) for t in resolved)
        known[step_id] = found
        return found

    for step in project.steps:
        depth_of(step.id, frozenset())
    return known


def cyclic(library: Library, project: Project) -> list[Step]:
    """The steps that wait on themselves, directly or through others — in project order.

    The model refuses to *create* a cycle, so this answers for a file edited by hand: every
    other walk here guards itself and quietly places such a step at depth zero, which is a
    plan that cannot be timed pretending it can. A surface that dates the plan asks this
    first and says what it found instead. Empty is the normal answer.

    Kahn's peeling: shed every step whose requirements are all shed; whatever remains sits
    on a cycle or behind one, and both are named — a step behind a loop is as undatable
    as the loop itself.
    """
    ids = {step.id for step in project.steps}
    pending: dict[StepId, set[StepId]] = {
        step.id: {target for target in step.edges.get("requires", []) if target in ids}
        for step in project.steps
    }

    shed = True
    while shed:
        shed = False
        for step_id, waiting in tuple(pending.items()):
            if not waiting:
                del pending[step_id]
                for others in pending.values():
                    others.discard(step_id)
                shed = True
    return [step for step in project.steps if step.id in pending]


def waves(library: Library, project: Project) -> list[list[Step]]:
    """The steps grouped by depth: everything in ``waves[0]`` can be started now.

    Empty waves cannot occur — a step at depth *n* waits on one at depth *n-1* by
    definition — so the list is dense and its index is the wave number.
    """
    by_depth = depths(library, project)
    if not project.steps:
        return []
    grouped: list[list[Step]] = [[] for _ in range(max(by_depth.values(), default=0) + 1)]
    for step in project.steps:  # Project order is the tie-break, so the result is stable.
        grouped[by_depth.get(step.id, 0)].append(step)
    return grouped


def topological_order(library: Library, project: Project) -> list[Step]:
    """Every step, in an order that never puts a step before something it waits on."""
    return [step for wave in waves(library, project) for step in wave]


@dataclass(frozen=True)
class Placed:
    """One step's place in the order: where it comes, and what it can go alongside.

    ``index`` is the topological index — the step's position in an order that never puts
    anything before what it waits on. ``wave`` is which group of steps it can be started
    with. Both are 1-based, because both are shown to people.
    """

    index: int
    wave: int
    step: Step


def placed(library: Library, project: Project) -> list[Placed]:
    """Every step in order, carrying its index and its wave.

    The shape a table wants and the shape the CLI prints, so neither has to number the rows
    itself and the two can never disagree about what step four is.
    """
    return [
        Placed(index=index, wave=wave_number + 1, step=step)
        for index, (wave_number, step) in enumerate(
            (
                (number, step)
                for number, wave in enumerate(waves(library, project))
                for step in wave
            ),
            start=1,
        )
    ]


def ready(library: Library, project: Project) -> list[Step]:
    """The steps with nothing left to wait on — the first wave, named for what it means."""
    found = waves(library, project)
    return found[0] if found else []


StepPredicate = Callable[[Step], bool]


@dataclass(frozen=True)
class Cone:
    """What one walk found: the steps a collector owns, and the collectors it gathers.

    ``steps`` excludes the origin — a caller that wants a step's own aspects counted adds it
    back, as ``testing.covered()`` does — and excludes the boundaries, which are the thing
    they were stopped at rather than part of what stopped there. Both are in project order,
    so an answer never reshuffles between two reads.
    """

    steps: tuple[Step, ...]
    boundaries: tuple[Step, ...]


def cone(
    library: Library,
    project: Project,
    step_id: StepId,
    *,
    stops_at: StepPredicate | None = None,
) -> Cone:
    """The cone behind ``step_id``, truncated at the boundaries ``stops_at`` names.

    A step is in ``steps`` exactly when some path of ``requires`` edges reaches it from the
    origin without crossing a boundary — so a step behind an earlier feature *and* reachable
    around it still belongs to both, which is the honest answer and the one lint reports.

    The visited set is also the cycle guard, the same defensive stance ``depths()`` takes
    against a hand-edited file. Boundaries are never recursed into, so a graph with a hundred
    milestones costs one pass, not a hundred.
    """
    reached: set[StepId] = set()
    stopped: set[StepId] = set()
    ids = {step.id for step in project.steps}  # Once per walk: Project.step() is a scan.

    def visit(current: StepId) -> None:
        for target in library.requires(current):
            if target.id in reached or target.id in stopped:
                continue
            if target.id not in ids:
                continue

            if stops_at is not None and stops_at(target):
                stopped.add(target.id)
                continue
            reached.add(target.id)
            visit(target.id)

    visit(step_id)
    return Cone(
        steps=tuple(step for step in project.steps if step.id in reached),
        boundaries=tuple(step for step in project.steps if step.id in stopped),
    )


def upstream(library: Library, project: Project, step_id: StepId) -> list[Step]:
    """Every step this one waits on, directly or through others, in project order.

    ``Library.requires()`` answers one edge out; this answers the whole cone behind a step.
    It is :func:`cone` with nothing to stop it — the untruncated case, named for the
    question most callers are asking. What a *collector* gathers, which stops at the next
    collector, is ``planning/scope.py``'s.
    """
    return list(cone(library, project, step_id).steps)


def dependents_index(project: Project) -> dict[StepId, list[Step]]:
    """Who waits on each step, built once: ``Library.dependents`` answers one step and scans
    the project to do it, so a walk forwards reads this instead."""
    index: dict[StepId, list[Step]] = {}
    for step in project.steps:
        for source in step.edges.get("requires", []):
            index.setdefault(source, []).append(step)
    return index


def downstream(
    project: Project, step_id: StepId, index: dict[StepId, list[Step]] | None = None
) -> list[Step]:
    """Every step that waits on this one, directly or through others, in project order —
    :func:`upstream` walked the other way. ``index`` is :func:`dependents_index`, handed in
    by a caller that walks from several steps."""
    index = dependents_index(project) if index is None else index
    reached: set[StepId] = set()
    pending = [step_id]
    while pending:
        for dependent in index.get(pending.pop(), []):
            if dependent.id not in reached:  # Also the cycle guard.
                reached.add(dependent.id)
                pending.append(dependent.id)
    return [step for step in project.steps if step.id in reached and step.id != step_id]


def left_between(project: Project, chosen: set[StepId]) -> Step | None:
    """A step outside ``chosen`` on a path from one of them to another, or None — the one
    that would have to wait on the picked steps and be waited on by them at once, which is
    why neither a line (a stack) nor a bracket (a branch) can be drawn round them."""
    index = dependents_index(project)
    seen: set[StepId] = set()
    reached = [d for c in chosen for d in index.get(c, []) if d.id not in chosen]
    while reached:
        step = reached.pop()
        if step.id in seen:
            continue
        seen.add(step.id)
        for onward in index.get(step.id, []):
            if onward.id in chosen:
                return step
            reached.append(onward)
    return None


def ports(steps: Sequence[Step]) -> dict[StepId, tuple[bool, bool]]:
    """``(has incoming, has outgoing)`` per step, over every edge kind whose both ends are
    among ``steps`` — the edges the canvas draws, and no others.

    Two readers of the one walk: the canvas's orphan, start and end marks, and
    ``graph.orphan`` lint. A step with neither is on no graph at all, and the window
    already says so in the refusal red.
    """
    ids = {step.id for step in steps}
    incoming: set[StepId] = set()
    outgoing: set[StepId] = set()
    for waiter in steps:
        for sources in waiter.edges.values():
            for source in sources:
                if source in ids:
                    incoming.add(waiter.id)
                    outgoing.add(source)
    return {step.id: (step.id in incoming, step.id in outgoing) for step in steps}
