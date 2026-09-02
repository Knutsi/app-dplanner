"""The agent-run aspect: its vocabulary, and the one place its shape is written down.

Where a *status* is a claim about the work, an agent-run state is a claim about the shell:
Run Agent stamps ``launched`` the moment a terminal is spawned, and the agent inside it
moves the state along from the CLI as it works — ``needs-input`` is how it says it has a
question for the developer. Absence is the default — no agent run — and there is
deliberately no terminal state here: finishing is ``step_status``'s claim
(``status set … done``), so a finishing agent clears this entry instead, restoring absence;
and when the shell itself ends without clearing it, the window that launched it does
(:func:`record_exit`), because a chip on a step nobody is working on is a lie.
"""

from collections.abc import Sequence
from typing import Any, Final

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step, StepId, now_stamp

MODULE_ID = "step_agent_run"

# The lifecycle, in the order a run moves through it. Absence means no agent run.
STATES: Final = ("launched", "working", "plan-for-review", "pending-approval", "needs-input")

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


def record_launch(library: Library, step_id: StepId) -> None:
    """Stamp "an agent shell was launched on this step" — directly, off the undo stack.

    The stamp records an external fact: a detached shell now exists, and Ctrl+Z cannot
    un-launch it. An undo entry would make undo erase a true record instead of undoing the
    user's last edit, so the command is applied the way a background sync applies one.
    Autosave flushes on the store's dirty signal regardless of the stack.
    """
    SetModuleDataCommand(step_id, MODULE_ID, write("launched"), view_origin=LAUNCH_ORIGIN).redo(
        library
    )


def record_exit(library: Library, step_id: StepId) -> bool:
    """The shell ended: clear whatever state it left — the same way the launch was stamped.

    Nothing to do — and False — when the agent already cleared it from the CLI, which is
    the protocol; the write is only for the run that ended without saying so.
    """
    if not library.has(step_id) or not read(library.step(step_id)):
        return False
    SetModuleDataCommand(step_id, MODULE_ID, {}, view_origin=LAUNCH_ORIGIN).redo(library)
    return True


def forget_for_paste(_project: Project, steps: Sequence[Step]) -> None:
    """A copied step carries no agent run — the paste policy this module hands in.

    The state is a fact about a shell somebody launched on the *original*; a chip and a
    marching ring on a step nobody is working on would be a lie.
    """
    for step in steps:
        step.module_data.pop(MODULE_ID, None)


# Last, because it names the pieces above: the one declaration everything reads.
SPEC = AspectSpec(
    id=MODULE_ID,
    label="Agent run",
    summary=(
        "Where a launched agent stands: launched, working, plan-for-review,"
        " pending-approval, needs-input."
    ),
    data_format=DATA_FORMAT,
    phrase=summary,
)
