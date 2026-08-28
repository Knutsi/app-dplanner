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
from dplanner.domain.model import Step

MODULE_ID = "step_status"

# In the order work moves through them. "pending" first because it is the default.
STATUSES: Final = ("pending", "in-progress", "done", "blocked")

DATA_FORMAT = ModuleDataFormat(MODULE_ID)

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
