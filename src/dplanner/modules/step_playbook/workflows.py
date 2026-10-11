"""What a playbook's pass does to the plan: the changes it makes itself.

Everything else a pass changes is somebody else's — the agent sets its step Ready for review,
``progress`` accepts it through the merge's own path. A playbook with nothing to merge (a
*Spike*: plan, then a person) is finished by the person's approval; one whose last gate
accepted work with a PR open leaves it ready to merge, so the merge finishes it; work sent
back for another round is in progress again; and a pass stopped by a person is the last.
"""

from datetime import date

from dplanner.domain.model import Step
from dplanner.domain.workflow import Change, EndClaim, PlanView, Release
from dplanner.planning.status import Status, status_command, stored

LABEL = "Playbook approved"
# The decision note a person's *Accept* of a pass that is through is kept as.
ACCEPTED = "Accepted after its playbook"
STOP_LABEL = "Stop Playbook"
REOPEN_LABEL = "Playbook sent back"


def acceptance(pass_id: str, playbook: str, because: str = "") -> str:
    """The reason a person's *Accept* of a pass is kept as, on both surfaces."""
    return f"Accepted after pass {pass_id} of {playbook}" + (
        f": {because.strip()}" if because.strip() else "."
    )


def approved(step: Step, *, today: date) -> Change:
    """The step done, its playbook's last gate having approved it — no command when it
    already reads done."""
    if stored(step) is Status.DONE:
        return Change(None, ())
    return Change(status_command(step, Status.DONE, today=today, label=LABEL), ())


def awaiting_merge(step: Step, *, today: date) -> Change:
    """The step ready to merge: its playbook's last gate accepted the work, and the PR it
    made is what is left — whose merge then makes it done (``github refresh``, the window's
    refresher). No command when it already says so, or says done."""
    if stored(step) in (Status.READY_TO_MERGE, Status.DONE):
        return Change(None, ())
    return Change(status_command(step, Status.READY_TO_MERGE, today=today, label=LABEL), ())


def reopened(step: Step, *, today: date) -> Change:
    """The step in progress again: its pass sent the work back for another round, so what it
    said was finished — Ready for review, or accepted as ready to merge — no longer is, and a
    merge must not finish it meanwhile. No command for any other status."""
    if stored(step) not in (Status.READY_FOR_REVIEW, Status.READY_TO_MERGE):
        return Change(None, ())
    return Change(status_command(step, Status.IN_PROGRESS, today=today, label=REOPEN_LABEL), ())


def stopped(view: PlanView, step: Step, *, today: date) -> Change:
    """The plan once a person has stopped the step's pass (``engine.stop``): a step that read
    in progress — the pass's own claim, since nobody works it now — back to pending, any other
    status standing; the agent's at-work claim ended, and the step released from the squad
    claim holding it."""
    project = view.project_of(step.id).id
    follow_ups = (EndClaim(project, step.id), Release(project, step.id, "playbook stopped"))
    if stored(step) is not Status.IN_PROGRESS:
        return Change(None, follow_ups)
    back = status_command(step, Status.PENDING, today=today, label=STOP_LABEL)
    return Change(back, follow_ups)
