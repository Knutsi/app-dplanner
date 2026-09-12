"""The status aspect: its vocabulary, and the one place its shape is written down.

A step's status is a claim only a person or an agent can make — the graph can say what is
*ready*, but not what is finished or stuck, which is why this is stored rather than derived.
The vocabulary is deliberately small: ``pending`` is the default and encoded as absence
(FORMAT.md: absence encodes the default), so ``write("pending")`` returns ``{}`` and the
file disappears. ``blocked`` earns its place as the one state the graph cannot see —
an external blockage is a fact from outside the plan.
"""

from typing import Any, Final

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Step, StepId

MODULE_ID = "step_status"

IN_PROGRESS: Final = "in-progress"

# In the order work moves through them. "pending" first because it is the default.
STATUSES: Final = ("pending", IN_PROGRESS, "done", "blocked")

DATA_FORMAT = ModuleDataFormat(MODULE_ID)

# The origin the window's own "work started here" claim carries: no view claims it, so
# every surface treats the write as foreign and repaints — the launch stamp's pattern.
STARTED_ORIGIN: Final[object] = object()


def read(step: Step) -> str:
    """The step's status. Absent or unreadable data reads as ``pending``, never as an error.

    An unknown word — perhaps written by a newer build — is also read as ``pending``: this
    build cannot act on a state it does not know, but it must not crash over one either.
    The unknown entry itself is left on disk untouched.
    """
    entry = step.module_data.get(MODULE_ID)
    status = entry.get("status") if entry else None
    return status if status in STATUSES else "pending"


def write(status: str) -> dict[str, Any]:
    """The entry to store. ``pending`` gives ``{}``, which removes the file."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r} (one of {', '.join(STATUSES)})")
    if status == "pending":
        return {}
    return stamped({"status": status}, DATA_FORMAT.version)


def record_started(library: Library, step_id: StepId) -> bool:
    """Work on the step just began: claim ``in-progress`` — directly, off the undo stack.

    The claim rides on something nobody can undo — a detached agent shell now exists — so
    it is applied the way that launch is stamped (``step_agent_run``'s ``record_launch``
    has the reasoning): an undo entry here would let Ctrl+Z file the step as pending while
    an agent is still working in it. False, and no write, when the step is gone or already
    claims to be in progress.
    """
    if not library.has(step_id) or read(library.step(step_id)) == IN_PROGRESS:
        return False
    SetModuleDataCommand(step_id, MODULE_ID, write(IN_PROGRESS), view_origin=STARTED_ORIGIN).redo(
        library
    )
    return True


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when the step is simply pending."""
    status = read(step)
    return "" if status == "pending" else status.replace("-", " ")


# Last, because it names the pieces above: the one declaration everything reads.
SPEC = AspectSpec(
    id=MODULE_ID,
    label="Status",
    summary="Where a step stands: pending, in-progress, done, or blocked.",
    data_format=DATA_FORMAT,
    phrase=summary,
)
