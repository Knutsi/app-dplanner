"""What the user has picked on the canvas, how it is addressed in the context, and what it
touches.

A step has an id; an edge does not — it is a `(waiter, kind, source)` triple living in the
waiting step's ``edges`` map. The canvas needs that triple to be a *key*: an edge item has to
keep its identity across a sync so a selected edge survives an unrelated model change, and
the selection has to reach an action as a URI string like everything else in the context.

Qt-free and in its own file so ``verbs.py`` can act on selected edges without importing the
canvas that drew them, and so ``modes.py`` can report a selection without importing the scene.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from dplanner.domain.model import Edge, StepId

# The URI's entity kinds, beside "step" and "project".
EDGE_KIND = "edge"
REGION_KIND = "region"
_SEPARATOR = "|"


@dataclass(frozen=True, order=True)
class EdgeRef:
    """One edge, as the model states it: ``waiter`` waits on ``source``."""

    waiter: StepId
    kind: str
    source: StepId

    def entity_id(self) -> str:
        """The id half of ``app://selection/edge/<id>``."""
        return _SEPARATOR.join((self.waiter, self.kind, self.source))

    def as_edge(self) -> Edge:
        """The same arrow as the domain states it — what every edge verb hands over."""
        return (self.waiter, self.kind, self.source)


def parse_edge_id(entity_id: str) -> EdgeRef | None:
    """An :class:`EdgeRef` back from a context URI's id, or None if it is not one."""
    parts = entity_id.split(_SEPARATOR)
    if len(parts) != 3 or not all(parts):
        return None
    waiter, kind, source = parts
    return EdgeRef(waiter=waiter, kind=kind, source=source)


@dataclass(frozen=True)
class CanvasSelection:
    """Both kinds at once, as the canvas reports them.

    Steps stay in click order — ``steps.link`` reads it as "the second waits on the first" —
    which is why this is a tuple and not the set Qt hands back.
    """

    steps: tuple[StepId, ...] = ()
    edges: tuple[EdgeRef, ...] = ()
    regions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Neighbourhood:
    """What a picked set of steps touches: the arrows hanging off it, and every step one of
    them reaches — the picked ones included, since a step is its own neighbour.

    Two readers of the one derivation: an arrow in ``edges`` is lit whatever the look says,
    and the spotlight fades every node and arrow these two sets do not name.
    """

    steps: frozenset[StepId] = frozenset()
    edges: frozenset[EdgeRef] = frozenset()


def neighbourhood(edges: Iterable[EdgeRef], picked: Iterable[StepId]) -> Neighbourhood:
    """The neighbourhood of ``picked`` among the arrows the canvas is drawing.

    Derived on every selection change and every sync from the edges in front of the user,
    exactly like ``ordering.ports()`` — written down, it could disagree with the graph the
    moment ``dplanner step link`` ran with no window open to notice.

    **Nothing picked has no neighbourhood**, and that empty answer is what keeps a spotlight
    over an empty selection from dimming the whole canvas to say nothing at all.
    """
    steps = set(picked)
    if not steps:
        return Neighbourhood()
    touching = frozenset(ref for ref in edges if ref.waiter in steps or ref.source in steps)
    steps.update(ref.waiter for ref in touching)
    steps.update(ref.source for ref in touching)
    return Neighbourhood(steps=frozenset(steps), edges=touching)
