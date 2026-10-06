"""Marks: a way of looking at the graph, and the socket facts they colour.

A mark is a per-user preference — *show me where the graph starts, where it ends, what
floats free* — not a fact about a project, so nothing here reaches disk beside the plan
(the module keeps it in ``user_config``). Which sockets a node has connected is derived
every sync by :func:`dplanner.domain.ordering.ports`, exactly like the ordering: stored, it
could disagree with the graph it came from the moment ``dplanner step link`` ran. That walk
lives in the domain because ``graph.orphan`` lint asks the same question, and a module may
not import another module's copy of an answer.

Qt-free, so the derivation and the value can be tested with plain ``Step``s.
"""

from dataclasses import dataclass, replace

MARK_NAMES = ("starts", "ends")


@dataclass(frozen=True)
class Marks:
    """Which marks are on. ``starts`` colours a socket nothing arrives at, ``ends`` one
    nothing leaves from.

    **Both are on by default.** A socket with nothing on it is what a graph can be wrong
    about, and it is invisible until somebody thinks to look — a preference that has to be
    found before it can help is one that helps nobody. Switching one off is the deliberate
    act, and it is remembered.

    There was a third, ``orphans``, which rang a node with no links at all in the refusal
    red. It is gone: a node nothing touches is what ``graph.orphan`` reports, and a step a
    lint finding is about now wears the squiggle — so the ring was a second red vocabulary
    for a fact the general mark already covers, and a *preference* that could hide a
    problem, which is not a way of looking. A stored ``orphans`` is ignored, as
    ``from_json`` ignores any name it does not know.
    """

    starts: bool = True
    ends: bool = True

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
        """Tolerant: anything that is not a mapping of the known names reads as the default.

        A name the stored value does not mention takes the default rather than False —
        ``FORMAT.md``'s absence rule, and what lets a default change reach somebody who
        never touched that switch.
        """
        if not isinstance(data, dict):
            return cls()
        return cls(**{name: bool(data[name]) for name in MARK_NAMES if name in data})
