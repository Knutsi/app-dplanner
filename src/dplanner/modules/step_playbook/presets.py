"""The built-in playbooks: a list of stages each, chosen per step.

A playbook is the alternative to Run Agent on one step — stages that plan the work, do it and
decide whether it is good enough — and the step stays one card whatever its stages are. The
stages are a list, never a graph: their order is the order they run in, and a gate's *changes*
goes back to the nearest earlier work stage. There are no playbook files yet; these ten are
the whole vocabulary (``docs/architecture/playbooks.md``'s *The presets*).
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from dplanner.domain.headless import StageKind

ROUNDS = 2  # Verdicts a gate may give in a pass before it escalates to somebody.
MAX_ROUNDS = 5

Reviewer = Literal["same", "other"]


class StageRole(StrEnum):
    """What a stage of a playbook does — and who acts in it."""

    PLAN = "plan"
    EXECUTE = "execute"
    REVIEW = "review"
    PERSON = "person"
    COORDINATOR = "coordinator"
    PROGRESS = "progress"

    @property
    def is_gate(self) -> bool:
        """Whether the stage ends in a verdict: pass, or changes."""
        return self in (StageRole.REVIEW, StageRole.PERSON, StageRole.COORDINATOR)

    @property
    def agent_stage(self) -> StageKind | None:
        """The headless turn a harness runs for this stage; None where nobody's agent acts."""
        return {
            StageRole.PLAN: StageKind.PLAN,
            StageRole.EXECUTE: StageKind.EXECUTE,
            StageRole.REVIEW: StageKind.REVIEW,
        }.get(self)


@dataclass(frozen=True)
class Stage:
    role: StageRole
    reviewer: Reviewer | None = None  # A review's agent: the implementer's, fresh, or another.

    @property
    def label(self) -> str:
        if self.reviewer is not None:
            return f"{self.role.value} ({self.reviewer} agent)"
        return self.role.value


@dataclass(frozen=True)
class Playbook:
    id: str
    name: str
    # Raised whenever the stage list changes, so a pass pinned to an older list says so.
    revision: int
    stages: tuple[Stage, ...]
    summary: str  # What the stage list alone does not say.

    def stage_ids(self) -> tuple[str, ...]:
        """Each stage's id in this playbook — its role, numbered when the role repeats
        (``review``, ``review-2``) — which is what a run's ``stage`` names."""
        seen: dict[StageRole, int] = {}
        ids = []
        for stage in self.stages:
            seen[stage.role] = seen.get(stage.role, 0) + 1
            count = seen[stage.role]
            ids.append(stage.role.value if count == 1 else f"{stage.role.value}-{count}")
        return tuple(ids)

    def has_gate(self) -> bool:
        return any(stage.role.is_gate for stage in self.stages)

    def reviews_with_other(self) -> bool:
        return any(stage.reviewer == "other" for stage in self.stages)

    def stage_words(self) -> str:
        return ", ".join(stage.label for stage in self.stages)


PLAN = Stage(StageRole.PLAN)
EXECUTE = Stage(StageRole.EXECUTE)
PERSON = Stage(StageRole.PERSON)

LAND = Playbook(
    "land",
    "Land: execute ⇄ review (other agent) → human review",
    1,
    (EXECUTE, Stage(StageRole.REVIEW, "other"), PERSON),
    "The landing's own work — the mainline merged in, the checks, the PR into it — reviewed "
    "cross-vendor, then a person merges: DPlanner never merges into the mainline.",
)
LANDING_DEFAULT = LAND  # What a branch landing runs when nobody chose.

PRESETS: tuple[Playbook, ...] = (
    Playbook(
        "execute",
        "Execute",
        1,
        (EXECUTE,),
        "Run Agent, headless: works in the auto-approving mode and stops at Ready for review.",
    ),
    Playbook(
        "plan-execute-coordinator",
        "Plan → execute → coordinator review",
        1,
        (PLAN, EXECUTE, Stage(StageRole.COORDINATOR)),
        "The coordinator driving the run judges the work, or a person when none does.",
    ),
    Playbook(
        "plan-execute-person",
        "Plan → execute → human review",
        1,
        (PLAN, EXECUTE, PERSON),
        "The step's owner judges the work.",
    ),
    Playbook(
        "plan-execute-progress",
        "Plan → execute → progress",
        1,
        (PLAN, EXECUTE, Stage(StageRole.PROGRESS)),
        "Accepts the work on its feature branch so what waits on it may start; on the "
        "mainline a person approves instead.",
    ),
    Playbook(
        "plan-execute-review-self",
        "Plan → execute ⇄ review (same agent)",
        1,
        (PLAN, EXECUTE, Stage(StageRole.REVIEW, "same")),
        "The implementer's agent reviews the work in a fresh session.",
    ),
    Playbook(
        "plan-execute-review-other",
        "Plan → execute ⇄ review (other agent)",
        1,
        (PLAN, EXECUTE, Stage(StageRole.REVIEW, "other")),
        "Another vendor's agent reviews the work; the same vendor, fresh, when only one is "
        "usable here.",
    ),
    Playbook(
        "plan-person-execute",
        "Plan → human review → execute",
        1,
        (PLAN, PERSON, EXECUTE),
        "A person approves the plan before any code is written: plan mode, headless.",
    ),
    LAND,
    Playbook(
        "review-only",
        "Review only",
        1,
        (Stage(StageRole.REVIEW, "other"), PERSON),
        "Reviews an existing PR against its base, cross-vendor, then a person decides.",
    ),
    Playbook(
        "spike",
        "Spike",
        1,
        (PLAN, PERSON),
        "Research or design, read-only: the plan is the output, and a person's approval "
        "sets the step done.",
    ),
)


def preset(playbook_id: str) -> Playbook | None:
    return next((playbook for playbook in PRESETS if playbook.id == playbook_id), None)
