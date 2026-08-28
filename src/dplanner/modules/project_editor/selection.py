"""What the user has picked on the canvas, and how it is addressed in the context.

A step has an id; an edge does not — it is a `(waiter, kind, source)` triple living in the
waiting step's ``edges`` map. The canvas needs that triple to be a *key*: an edge item has to
keep its identity across a sync so a selected edge survives an unrelated model change, and
the selection has to reach an action as a URI string like everything else in the context.

Qt-free and in its own file so ``verbs.py`` can act on selected edges without importing the
canvas that drew them, and so ``modes.py`` can report a selection without importing the scene.
"""

from dataclasses import dataclass

from dplanner.domain.model import StepId

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
