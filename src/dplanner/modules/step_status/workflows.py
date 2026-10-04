"""Setting a status, once, for every surface: the window's Status verbs, ``dplanner status
set`` and the review verbs all call :meth:`StatusWorkflow.set_status` and perform the
``Change`` it returns. ``domain/workflow.py`` says what a workflow is.

**An agent's run ends at ready-for-review.** An :class:`AgentRun` setting an agent step done
before anybody reviewed it is refused, naming ``ready-for-review`` — unless ``because`` says
why nothing needs reviewing, which is kept as a ``decision`` note on the step in the same
change. A :class:`Person` is never asked: the director has authority over the worker.
ARCHITECTURE.md's *An agent finishes at Ready for review* has the reasoning.

**A status that says nobody is working the step ends the claim on it**, whoever sets it —
so a director marking a step done in the window takes the agent's banner down. Ending the
claim is all it does: nothing yet tells the agent to stand down.
"""

import shlex
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import assert_never

from dplanner.domain.commands import Command, CompositeCommand
from dplanner.domain.model import Step
from dplanner.domain.workflow import (
    Actor,
    AgentRun,
    Change,
    Daemon,
    EndClaim,
    FollowUp,
    Person,
    PlanView,
)
from dplanner.planning.status import (
    MODULE_ID,
    REVIEW_AND_MERGE,
    Status,
    no_status,
    status_command,
    stored,
    write,
)

# The statuses that say nobody is working a step any more: setting one ends its claim.
STOPPED = frozenset({*REVIEW_AND_MERGE, Status.DONE, Status.BLOCKED})

LABEL = "Set Status"


@dataclass(frozen=True)
class Kept:
    """The decision note a ``because`` was kept as; ``added`` is False when the step already
    carried it, which then stands as it was."""

    note: str
    added: bool


@dataclass(frozen=True)
class StatusWorkflow:
    """The facts the composition root knows and this module does not: ``works_nobody``
    names a step nobody works — "a wait" — which has no status but pending; ``is_agent``
    says an agent executes a step; ``keep_reason`` builds the decision note a ``because``
    is kept as, answering its id and the command that adds it — None when the step already
    carries that note."""

    works_nobody: Callable[[Step], str]
    is_agent: Callable[[Step], bool]
    keep_reason: Callable[[PlanView, Step, str, date], tuple[str, Command | None]]

    def refusal(
        self, steps: Sequence[Step], status: Status, actor: Actor, because: str = ""
    ) -> str:
        """Why ``actor`` may not set ``steps`` to ``status``; "" when it may. Reads only the
        steps it is handed — it runs in an action state, on every announce."""
        if because and status is not Status.DONE:
            return "--because says why a step is done without review; it goes with done"
        for step in steps:
            if (kind := self.works_nobody(step)) and status is not Status.PENDING:
                return f"{step.title!r} is {kind}: {no_status(kind)}"
            match actor:
                case AgentRun():
                    if (
                        status is Status.DONE
                        and not because
                        and stored(step) not in REVIEW_AND_MERGE  # A reviewer may finish it.
                        and self.is_agent(step)
                    ):
                        return _review_first(step)
                case Person() | Daemon():
                    pass
                case _:
                    assert_never(actor)
        return ""

    def set_status(
        self,
        view: PlanView,
        step: Step,
        status: Status,
        *,
        actor: Actor,
        today: date,
        because: str = "",
    ) -> tuple[Change, Kept | None]:
        """Set ``step`` to ``status``: the note a ``because`` is kept as and the status, as
        one command, and the claim to end when the work has stopped — with the note it kept,
        for a surface that says so. Raises ``ValueError`` on a refusal — the model's word
        for a change that cannot be true."""
        if why := self.refusal([step], status, actor, because):
            raise ValueError(why)
        commands: list[Command] = []
        kept = None
        if because:
            note, command = self.keep_reason(view, step, because, today)
            kept = Kept(note, added=command is not None)
            commands.extend([command] if command is not None else [])
        previous = step.module_data.get(MODULE_ID)
        if write(status, today=today, previous=previous) != (previous or {}):
            commands.append(status_command(step, status, today=today, label=LABEL))
        follow_ups = (EndClaim(view.project_of(step.id).id, step.id),) if status in STOPPED else ()
        command = CompositeCommand(LABEL, commands) if commands else None
        return Change(command, follow_ups), kept


@dataclass(frozen=True)
class Performed:
    """What came of the follow-ups: the claims that stood and were ended, and the ones that
    could not be, each with why."""

    ended: tuple[EndClaim, ...] = ()
    failed: tuple[tuple[EndClaim, str], ...] = ()


def perform(follow_ups: Iterable[FollowUp], end_claim: Callable[[EndClaim], bool]) -> Performed:
    """Perform follow-ups once their change is accepted, each on its own: one that fails is
    reported and the rest are still attempted. The model is never rolled back for an effect —
    the change is true, and releasing a claim again is safe, so a retry is the remedy."""
    ended: list[EndClaim] = []
    failed: list[tuple[EndClaim, str]] = []
    for follow_up in follow_ups:
        match follow_up:
            case EndClaim():
                try:
                    if end_claim(follow_up):
                        ended.append(follow_up)
                except OSError as error:
                    failed.append((follow_up, str(error)))
            case _:
                assert_never(follow_up)
    return Performed(tuple(ended), tuple(failed))


def _review_first(step: Step) -> str:
    ref = shlex.quote(step.title)
    return (
        f"{step.title!r} is an agent step, and an agent's work ends at ready-for-review:"
        f" `dplanner status set {ref} ready-for-review` — a person or a reviewing agent"
        f" sets it done. If nothing needs reviewing, say why:"
        f" `dplanner status set {ref} done --because '<reason>'`."
    )
