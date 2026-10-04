"""What a workflow hands back, who asked for it, and what it may read.

A workflow is one thing a person or an agent does — *set a status* — as a plain function in
the owning module's ``workflows.py``. Every surface calls it: the window's ``ActionSpec``
pushes the ``Change``'s command as one undo gesture, a CLI verb applies it and lets the store
flush, and both then perform its follow-ups. That is the rule that both surfaces build the
same object, moved up from the command to the whole workflow. ARCHITECTURE.md's *A workflow
is one function under both surfaces* has the reasoning.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol

from dplanner.domain.commands import Command
from dplanner.domain.model import (
    Edge,
    EdgeEnd,
    Node,
    NodeId,
    Project,
    ProjectId,
    Step,
    StepId,
)


@dataclass(frozen=True)
class Person:
    """Somebody at the window or in their own terminal: the director, who may finish a step."""


@dataclass(frozen=True)
class AgentRun:
    """An agent CLI working a step: its work ends at review."""


@dataclass(frozen=True)
class Daemon:
    """A process acting on the plan's own rules, with nobody at the keyboard."""


type Actor = Person | AgentRun | Daemon


@dataclass(frozen=True)
class EndClaim:
    """End the at-work claim an agent holds on ``step`` — the banner comes down."""

    project: ProjectId
    step: StepId


# What a caller performs once the change is accepted: effects outside the model. A new kind
# joins this union, and every performer's `match` then fails mypy until it handles it.
type FollowUp = EndClaim


@dataclass(frozen=True)
class Change:
    """A workflow's answer: ``command`` is None when the model would not change — the
    follow-ups still stand, so a repeated *ready for review* still ends the claim."""

    command: Command | None
    follow_ups: tuple[FollowUp, ...]
    label: str


class PlanView(Protocol):
    """The library's queries and nothing else: a workflow builds, it never mutates, and
    mypy refuses a mutator called on one of these."""

    def has(self, node_id: NodeId) -> bool: ...
    def node(self, node_id: NodeId) -> Node: ...
    def nodes(self) -> Iterator[Node]: ...
    def project(self, project_id: ProjectId) -> Project: ...
    def step(self, step_id: StepId) -> Step: ...
    def parent_of(self, node_id: NodeId) -> Node | None: ...
    def project_of(self, step_id: StepId) -> Project: ...
    def belongs_to(self, node_id: NodeId, project_id: ProjectId) -> bool: ...
    def text(self, node_id: NodeId, key: str) -> str: ...
    def link_refusal(self, step_id: StepId, kind: str, target: StepId) -> str | None: ...
    def requires(self, step_id: StepId) -> list[Step]: ...
    def dependents(self, step_id: StepId) -> list[Step]: ...
    def boundary_edges(self, step_ids: Iterable[StepId]) -> list[Edge]: ...
    def edges_of(self, step_ids: Iterable[StepId], end: EdgeEnd) -> list[Edge]: ...
