"""What a playbook's pass does to the plan: the one change it makes itself.

Everything else a pass changes is somebody else's — the agent sets its step Ready for review,
``progress`` accepts it through the merge's own path. A playbook with nothing to merge (a
*Spike*: plan, then a person) is finished by the person's approval, and that is this change.
"""

from datetime import date

from dplanner.domain.model import Step
from dplanner.domain.workflow import Change
from dplanner.planning.status import Status, status_command, stored

LABEL = "Playbook approved"


def approved(step: Step, *, today: date) -> Change:
    """The step done, its playbook's last gate having approved it — no command when it
    already reads done."""
    if stored(step) is Status.DONE:
        return Change(None, ())
    return Change(status_command(step, Status.DONE, today=today, label=LABEL), ())
