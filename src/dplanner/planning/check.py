"""The check aspect: a step that stands for everything it waits on having been verified.

A check carries nothing at all — the marker entry is the whole shape. What it *covers* is
the graph's answer, not a stored list: the tests on every step in its ``requires`` cone,
recomputed on every read. Storing that list would make ``dplanner step link`` able to leave
a check claiming coverage it no longer has, with no window running to notice.

A release step is the same scope by a different name, which is why the walk lives in
``domain/ordering.py`` and the filtering in the module that owns tests, and neither knows
this file exists.
"""

from typing import Any

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Step

MODULE_ID = "step_check"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)


def read(step: Step) -> bool:
    """Whether the step is a check — presence of the entry, which carries nothing else."""
    return bool(step.module_data.get(MODULE_ID))


def write(on: bool) -> dict[str, Any]:
    """The entry to store. Off gives ``{}``, which removes the file."""
    if not on:
        return {}
    return stamped({"on": True}, DATA_FORMAT.version)


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when there is nothing to say."""
    return "check" if read(step) else ""


# Last, because it names the pieces above: the one declaration everything reads.
SPEC = AspectSpec(
    id=MODULE_ID,
    label="Check",
    summary=(
        "Marks a step as a check: it gathers every test it waits on, so a test run can be "
        "scoped to it."
    ),
    data_format=DATA_FORMAT,
    phrase=summary,
)
