"""Running an agent on a step, as a change to the plan: the claim that the step is in
progress, and taking it back. ``dplanner agent run`` and the window's Run Agent both persist
the claim before the run starts — the start is the follow-up — and withdraw it when the
start fails.

The rest of a launch — the gate, the worktree, the briefing, the run's record, the process
— is outside the plan and is ``launch.py``'s, in the one order both surfaces follow.
"""

from collections.abc import Mapping
from datetime import date
from typing import Any

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.domain.workflow import Change
from dplanner.planning.status import MODULE_ID, STARTED_ORIGIN, Status, status_command, stored

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


def withdraw(step: Step, before: Mapping[str, Any] | None) -> Change:
    """The claim taken back after a start that failed: the status entry the step had
    before (``before``) — nothing when the step no longer reads in progress, which is
    somebody else's change since and stands."""
    if stored(step) is not Status.IN_PROGRESS:
        return Change(None, ())
    back = SetModuleDataCommand(
        step.id, MODULE_ID, dict(before or {}), view_origin=STARTED_ORIGIN, label=LABEL
    )
    return Change(back, ())
