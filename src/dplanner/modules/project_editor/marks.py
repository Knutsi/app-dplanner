"""Marks: a way of looking at the graph, and the socket facts they colour.

A mark is a per-user preference — *show me where the graph starts, where it ends, what
floats free* — not a fact about a project, so nothing here reaches disk beside the plan
(the module keeps it in ``user_config``). Which sockets a node has connected is derived
every sync from the edges the canvas draws, exactly like the ordering: stored, it could
disagree with the graph it came from the moment ``dplanner step link`` ran.

Qt-free, so the derivation and the value can be tested with plain ``Step``s.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace

from dplanner.domain.model import Step, StepId

MARK_NAMES = ("starts", "ends", "orphans")


@dataclass(frozen=True)
class Marks:
    """Which marks are on. ``starts`` colours a socket nothing arrives at, ``ends`` one
    nothing leaves from, and ``orphans`` rings a node with neither."""

    starts: bool = False
    ends: bool = False
    orphans: bool = False

    def is_on(self, name: str) -> bool:
        return bool(getattr(self, name))

    def with_(self, name: str, on: bool) -> "Marks":
        if name not in MARK_NAMES:
            raise KeyError(name)
        return replace(self, **{name: on})

    def to_json(self) -> dict[str, bool]:
        return {name: self.is_on(name) for name in MARK_NAMES}

    @classmethod
    def from_json(cls, data: object) -> "Marks":
        """Tolerant: anything that is not a mapping of the known names reads as all off."""
        if not isinstance(data, dict):
            return cls()
        return cls(**{name: bool(data.get(name, False)) for name in MARK_NAMES})


def ports(steps: Sequence[Step]) -> dict[StepId, tuple[bool, bool]]:
    """``(has incoming, has outgoing)`` per step, over every edge kind whose both ends are
    among ``steps`` — the edges the canvas draws, and no others."""
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
