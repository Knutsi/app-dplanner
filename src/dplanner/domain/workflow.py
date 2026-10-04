"""What a workflow hands back, who asked for it, and what it may read.

A workflow is one thing a person or an agent does — *set a status* — as a plain function in
the owning module's ``workflows.py``. Every surface calls it: the window's ``ActionSpec``
pushes the ``Change``'s command as one undo gesture and a CLI verb applies it; each performs
the follow-ups once the change is accepted — the window once the push has succeeded, the CLI
once the whole invocation has been written. That is the rule that both surfaces build the
same object, moved up from the command to the whole workflow. `docs/architecture/core.md`'s *A
workflow is one function under both surfaces* has the reasoning.
"""

from dataclasses import dataclass
from typing import Protocol

from dplanner.domain.commands import Command
from dplanner.domain.model import Project, ProjectId, StepId


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


class PlanView(Protocol):
    """The queries a workflow reads, and no more: grown by a real reader, never ahead of
    one. It keeps the library's mutators out of a workflow's reach — a workflow builds a
    command and never applies one. It does not deep-freeze the model: the nodes it answers
    are the library's own objects, so a write through one would still type-check."""

    def project_of(self, step_id: StepId) -> Project: ...
