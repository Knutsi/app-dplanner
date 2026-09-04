"""What a step gathers: the cone behind it, truncated at the collectors it hands off to.

`ordering.py` answers *in what order*; this answers *what belongs to what*. A **collector**
is a step that stands for everything behind it — a check, a feature, a milestone. What it
gathers is never stored: it is the ``requires`` cone, recomputed on every read, for the same
reason the topological order is (``dplanner step link`` relinks a graph with no window
running to notice a stored membership going stale).

The one idea here is that a collector's contents stop at the *next* collector. A milestone
gathers the features behind it, not the ones an earlier milestone already took; a feature
gathers its own work, not the work behind the feature it follows. So the walk takes a
``stops_at`` predicate: a step that satisfies it is recorded as a **boundary** and not
traversed through. With no predicate the walk is the whole cone, which is what a check means
and what ``ordering.upstream()`` is.

**Handed functions, never a schema** — the rule ``schedule()`` and ``progression()`` already
live by. Nothing in this file knows what a feature is; the composition root, the one place
allowed to name every aspect at once, writes the predicates.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from dplanner.domain.model import Library, Project, Step, StepId

StepPredicate = Callable[[Step], bool]


@dataclass(frozen=True)
class ScopeKind:
    """One kind of collector, described where every surface can read it.

    ``carried_by`` says whether a step declares a scope of this kind; ``stops_at`` says which
    collectors it hands off to — itself and anything above it, so a feature stops at features
    and milestones while a milestone stops only at milestones. A check stops at nothing: it
    stands for *everything* verified behind it, which is the point of declaring one.

    ``gathers`` names the kind whose carriers become headings **inside** this one's contents:
    a milestone is read as a list of features. It is not the same question as ``stops_at`` and
    must not be confused with it — what a walk stops at is deliberately *excluded* (an
    earlier milestone already took it), while what it gathers is what it is made of. Empty
    means a flat list, which is what a feature wants: it is the finest grain there is.
    """

    id: str  # == the aspect's module id.
    label: str  # What a person calls it: "Check", "Feature", "Milestone".
    carried_by: StepPredicate
    stops_at: StepPredicate
    gathers: str = ""  # A kind id, or "" for a flat list.


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
    """The cone behind ``step_id``, truncated at the collectors it hands off to.

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


def gatherers(
    library: Library,
    project: Project,
    *,
    carried_by: StepPredicate,
    stops_at: StepPredicate,
) -> dict[StepId, tuple[StepId, ...]]:
    """For every step, the collectors of one kind that gather it — ids in project order.

    The inverse of :func:`cone`, run once per collector: what "group these tests by feature"
    reads, and what tells lint that a step is gathered twice or not at all. A collector
    gathers itself, so a feature's own tests appear under its own name.

    A step reachable from two collectors, neither behind the other, is gathered by **both**.
    Any tie-break would be arbitrary — it genuinely feeds both — so the ambiguity is reported
    rather than resolved.
    """
    found: dict[StepId, list[StepId]] = {}
    for collector in project.steps:
        if not carried_by(collector):
            continue
        owned = cone(library, project, collector.id, stops_at=stops_at)
        for step in (collector, *owned.steps):
            found.setdefault(step.id, []).append(collector.id)
    return {step_id: tuple(owners) for step_id, owners in found.items()}


def kind_of(kinds: Sequence[ScopeKind], step: Step) -> ScopeKind | None:
    """Which kind of collector a step is read as, or ``None`` for a plain step.

    A step can carry two markers at once — nothing stops a milestone also being a feature —
    so the *listed* order decides, and that list is the composition root's. Three surfaces
    ask this question (the Covers tab, the scope selector, ``dplanner scope show``); asking
    it in one place is what keeps them agreeing.
    """
    return next((kind for kind in kinds if kind.carried_by(step)), None)


def leaders(kinds: Sequence[ScopeKind], kind: ScopeKind, reached: Sequence[Step]) -> list[Step]:
    """The sub-collectors inside a collector's contents — a milestone's features.

    Never the *boundaries* of the walk that found ``reached``: those are what it stopped at,
    because an earlier collector of the same rank already accounts for them. This is the
    other question — what the contents are made of — and ``ScopeKind.gathers`` names it.

    Both surfaces ask it, which is why it is here: the Covers tab and ``dplanner scope show``
    render the same groups, and two implementations of "what goes under a heading" would
    eventually put different things there.
    """
    if not kind.gathers:
        return []
    sub = next((found for found in kinds if found.id == kind.gathers), None)
    return [] if sub is None else [step for step in reached if sub.carried_by(step)]


def stops_for(kinds: Sequence[ScopeKind], step: Step) -> StepPredicate | None:
    """Where ``step``'s own cone stops, or ``None`` when it collects nothing.

    What a group heading is asked, so a feature under a milestone answers for its own work
    rather than for everything behind it.
    """
    kind = kind_of(kinds, step)
    return kind.stops_at if kind is not None else None
