"""The agent-run aspect: its vocabulary, and the one place its shape is written down.

Where a *status* is a claim about the work, an agent-run state is a claim about the shell:
Run Agent stamps ``launched`` the moment a terminal is spawned, and the agent inside it
moves the state along from the CLI as it works. Absence is the default — no agent run —
and there is deliberately no terminal state here: finishing is ``step_status``'s claim
(``status set … done``), so a finishing agent clears this entry instead, restoring absence.
"""

from typing import Any, Final

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Product, Step, StepId, now_stamp

MODULE_ID = "step_agent_run"

# The lifecycle, in the order a run moves through it. Absence means no agent run.
STATES: Final = ("launched", "working", "plan-for-review", "pending-approval")

DATA_FORMAT = ModuleDataFormat(MODULE_ID)


# The launch stamp's origin: no view claims it, so every surface treats the write as
# foreign and repaints — the github refresher's pattern.
LAUNCH_ORIGIN: Final[object] = object()


def read(step: Step) -> str:
    """The run state, or "" when no agent run is recorded.

    An unknown word — perhaps written by a newer build — also reads as "": this build
    cannot act on a state it does not know, but it must not crash over one either. The
    unknown entry itself is left on disk untouched.
    """
    entry = step.module_data.get(MODULE_ID)
    state = entry.get("state") if entry else None
    return state if state in STATES else ""


def launched(step: Step) -> str:
    """When the shell was launched (an ISO stamp), or "" when no run is recorded."""
    entry = step.module_data.get(MODULE_ID)
    stamp = entry.get("launched") if entry else None
    return stamp if isinstance(stamp, str) else ""


def write(state: str, launched: str = "") -> dict[str, Any]:
    """The entry to store. An empty state gives ``{}``, which removes the file.

    Pass the step's existing ``launched`` stamp to keep the spawn time as the state moves
    along; without one, now is stamped — truthful enough for an agent driven outside
    Run Agent.
    """
    if not state:
        return {}
    if state not in STATES:
        raise ValueError(f"unknown agent-run state {state!r} (one of {', '.join(STATES)})")
    return stamped({"state": state, "launched": launched or now_stamp()}, DATA_FORMAT.version)


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when there is nothing to say."""
    state = read(step)
    return "" if not state else f"agent: {state.replace('-', ' ')}"


def record_launch(product: Product, step_id: StepId) -> None:
    """Stamp "an agent shell was launched on this step" — directly, off the undo stack.

    The stamp records an external fact: a detached shell now exists, and Ctrl+Z cannot
    un-launch it. An undo entry would make undo erase a true record instead of undoing the
    user's last edit, so the command is applied the way a background sync applies one.
    Autosave flushes on the store's dirty signal regardless of the stack.
    """
    SetModuleDataCommand(step_id, MODULE_ID, write("launched"), view_origin=LAUNCH_ORIGIN).redo(
        product
    )


# Last, because it names the pieces above: the one declaration everything reads.
SPEC = AspectSpec(
    id=MODULE_ID,
    label="Agent run",
    summary="Where a launched agent stands: launched, working, plan-for-review, pending-approval.",
    data_format=DATA_FORMAT,
    phrase=summary,
)
