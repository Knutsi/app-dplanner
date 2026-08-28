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

from dataclasses import dataclass

from dplanner.domain.model import Product, Project, Step, StepId


def depths(product: Product, project: Project) -> dict[StepId, int]:
    """How many ``requires`` edges deep each step is — the length of its longest chain.

    Cycles cannot occur: the model refuses to create one, so the walk always terminates.
    An edge pointing at a step outside this project cannot occur either, for the same reason.
    """
    known: dict[StepId, int] = {}

    def depth_of(step_id: StepId, seen: frozenset[StepId]) -> int:
        if step_id in known:
            return known[step_id]
        if step_id in seen:  # Defensive: a hand-edited file could still contain one.
            return 0
        waiting = product.step(step_id).edges.get("requires", [])
        resolved = [t for t in waiting if project.step(t) is not None]
        found = 0 if not resolved else 1 + max(depth_of(t, seen | {step_id}) for t in resolved)
        known[step_id] = found
        return found

    for step in project.steps:
        depth_of(step.id, frozenset())
    return known


def waves(product: Product, project: Project) -> list[list[Step]]:
    """The steps grouped by depth: everything in ``waves[0]`` can be started now.

    Empty waves cannot occur — a step at depth *n* waits on one at depth *n-1* by
    definition — so the list is dense and its index is the wave number.
    """
    by_depth = depths(product, project)
    if not project.steps:
        return []
    grouped: list[list[Step]] = [[] for _ in range(max(by_depth.values(), default=0) + 1)]
    for step in project.steps:  # Project order is the tie-break, so the result is stable.
        grouped[by_depth.get(step.id, 0)].append(step)
    return grouped


def topological_order(product: Product, project: Project) -> list[Step]:
    """Every step, in an order that never puts a step before something it waits on."""
    return [step for wave in waves(product, project) for step in wave]


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


def placed(product: Product, project: Project) -> list[Placed]:
    """Every step in order, carrying its index and its wave.

    The shape a table wants and the shape the CLI prints, so neither has to number the rows
    itself and the two can never disagree about what step four is.
    """
    return [
        Placed(index=index, wave=wave_number + 1, step=step)
        for index, (wave_number, step) in enumerate(
            (
                (number, step)
                for number, wave in enumerate(waves(product, project))
                for step in wave
            ),
            start=1,
        )
    ]


def ready(product: Product, project: Project) -> list[Step]:
    """The steps with nothing left to wait on — the first wave, named for what it means."""
    found = waves(product, project)
    return found[0] if found else []
