"""What the plan made due, and the claim that says it was launched — with no window in sight.

A step is *due* when nobody needs to decide to start it: a collector whose last source, or a
review whose subject, just reached review across an auto-progress link, or a side of a
review's conversation whose turn it is and whose agent has gone. This is the one derivation
every surface reads — ``progression show`` marks it, the status verbs say what they made due,
and the window's ``AutoLauncher`` launches it — and it is headless so that a process with no
window can launch the same steps by the same rule.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.modules.auto_progress.aspect import auto_progresses
from dplanner.modules.step_agent_run.aspect import read as run_state
from dplanner.modules.step_review.aspect import TurnDue, due_turns, record_turn_launched
from dplanner.planning import progression
from dplanner.planning.agent import enabled as is_agent
from dplanner.planning.kinds import works_nobody
from dplanner.planning.schedule import status_on
from dplanner.planning.status import Status, readiness_of, record_started


@dataclass(frozen=True)
class Due:
    """A step due to be launched — for its conversation's ``turn`` when it has one, since
    that claim is a stamp on the round rather than its status."""

    step: Step
    turn: TurnDue | None = None

    @property
    def step_id(self) -> StepId:
        return self.step.id


def has_run(step: Step) -> bool:
    """Whether the plan records an agent run on the step — the launch's own stamp."""
    return bool(run_state(step))


def _counts_as_work(step: Step) -> bool:
    return not works_nobody(step)


def due_now(
    library: Library,
    project: Project,
    status_for: Callable[[Step], Status],
    running: Callable[[Step], bool] = has_run,
) -> list[Due]:
    """Every step of ``project`` due to be launched, in project order: what auto-progress made
    due (``progression.due``), and a side of a conversation whose turn it is and whose agent
    has gone (``due_turns``). One step due both ways is due for its turn: that claim is the
    one a later pass must read.

    ``running`` is the plan's run stamp; a window widens it to the runs it is watching, which
    a claim not yet on disk cannot hide.
    """
    found: dict[StepId, Due] = {
        turn.step.id: Due(turn.step, turn)
        for turn in due_turns(library, project, is_agent, running, status_for)
    }
    for step in progression.due(
        library, project, status_for, auto_progresses, is_agent, running, _counts_as_work
    ):
        found.setdefault(step.id, Due(step))
    place = {step.id: index for index, step in enumerate(project.steps)}
    return sorted(found.values(), key=lambda each: place[each.step_id])


def due_in(library: Library, today: date, running: Callable[[Step], bool] = has_run) -> list[Due]:
    """Every step due across the library on ``today``, project by project."""
    status_for = readiness_of(status_on(library, today))
    return [
        each
        for project in library.projects
        for each in due_now(library, project, status_for, running)
    ]


def claim(library: Library, due: Due, today: date) -> None:
    """Write the claim that says ``due`` was launched — in progress for what auto-progress
    made due, the round's stamp for a turn — so the next derivation reads it as not due."""
    if due.turn is not None:
        record_turn_launched(library, due.turn.asker, due.turn.party)
    else:
        record_started(library, due.step_id, today)
