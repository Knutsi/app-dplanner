"""What a playbook's pass does to the plan: the changes it makes itself.

Everything else a pass changes is somebody else's — the agent sets its step Ready for review,
``progress`` accepts it through the merge's own path. A playbook with nothing to merge (a
*Spike*: plan, then a person) is finished by the person's approval, and that is one change;
a pass stopped by a person is the other.
"""

from datetime import date

from dplanner.domain.model import Step
from dplanner.domain.workflow import Change, EndClaim, PlanView, Release
from dplanner.planning.status import Status, status_command, stored

LABEL = "Playbook approved"
STOP_LABEL = "Stop Playbook"


def approved(step: Step, *, today: date) -> Change:
    """The step done, its playbook's last gate having approved it — no command when it
    already reads done."""
    if stored(step) is Status.DONE:
        return Change(None, ())
    return Change(status_command(step, Status.DONE, today=today, label=LABEL), ())


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
