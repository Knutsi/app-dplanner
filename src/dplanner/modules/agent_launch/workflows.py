"""Running an agent on a step, as a change to the plan: the claim that the step is in
progress. ``dplanner agent run`` and the window's Run Agent both apply it, once the run
``launch.py`` started is under way — never for a run that did not start.

The rest of a launch — the worktree, the briefing, the run's record, the process — is
outside the plan and is ``launch.py``'s, in the one order both surfaces follow.
"""

from datetime import date

from dplanner.domain.model import Step
from dplanner.domain.workflow import Change
from dplanner.planning.status import STARTED_ORIGIN, Status, status_command, stored

LABEL = "Run Agent"


def run_agent(step: Step, *, today: date) -> Change:
    """The step claimed in progress — no command when it already says so. Under the
    launch's origin, which no view claims, so every view repaints it as a change from
    outside; the window applies it off the undo stack, since the agent it records cannot
    be undone."""
    if stored(step) is Status.IN_PROGRESS:
        return Change(None, ())
    claim = status_command(
        step, Status.IN_PROGRESS, today=today, view_origin=STARTED_ORIGIN, label=LABEL
    )
    return Change(claim, ())
