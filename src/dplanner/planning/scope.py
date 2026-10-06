"""What a step gathers: the collector kinds, and the cones they read as.

``domain/ordering.py`` walks the graph — :func:`~dplanner.domain.ordering.cone` is the
``requires`` cone behind a step, truncated at the boundaries a predicate names. This file says
what those walks *mean*. A **collector** is a step that stands for everything behind it — a
check, a feature, a milestone. What it gathers is never stored: it is the cone, recomputed on
every read, for the same reason the topological order is (``dplanner step link`` relinks a
graph with no window running to notice a stored membership going stale).

The one idea here is that a collector's contents stop at the *next* collector. A milestone
gathers the features behind it, not the ones an earlier milestone already took; a feature
gathers its own work, not the work behind the feature it follows. A boundary is usually a
collector, but not always — the plan's start stops a feature's walk too, and
:func:`handoffs` tells the two apart.

**The markers are still handed in.** What makes a step a feature, a milestone or a check is
not yet a planning fact, so a :class:`ScopeKind` carries predicates the composition root
writes; once those markers move into this tier they become imports here.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.ordering import Cone, StepPredicate, cone


@dataclass(frozen=True)
class ScopeKind:
    """One kind of collector, described where every surface can read it.

    ``carried_by`` says whether a step declares a scope of this kind; ``stops_at`` says where
    its walk stops — the collectors it hands off to, itself and anything above it, so a
    feature stops at features and milestones while a milestone stops only at milestones, and
    the plan's start, which is nobody's (:func:`handoffs` keeps the collectors apart from it).
    A check stops at nothing: it stands for *everything* verified behind it, which is the
    point of declaring one.

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


def handoffs(kinds: Sequence[ScopeKind], walked: Cone) -> tuple[Step, ...]:
    """The collectors a walk handed off to: the boundaries some kind carries.

    A walk can also stop at a step that collects nothing — the plan's start, which the
    composition root has a feature's and a milestone's walk stop at so that the origin is
    nobody's. That is where the graph ends, not an earlier collector that already took
    something, so it is no *after* to name and no second reading to offer. Both surfaces
    that offer one ask this rather than ``boundaries``: ``dplanner scope show`` and the
    Covers tab's switch.
    """
    return tuple(step for step in walked.boundaries if kind_of(kinds, step) is not None)


def stops_for(kinds: Sequence[ScopeKind], step: Step) -> StepPredicate | None:
    """Where ``step``'s own cone stops, or ``None`` when it collects nothing.

    What a group heading is asked, so a feature under a milestone answers for its own work
    rather than for everything behind it.
    """
    kind = kind_of(kinds, step)
    return kind.stops_at if kind is not None else None
