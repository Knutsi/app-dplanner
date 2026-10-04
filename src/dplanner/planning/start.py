"""The start aspect: the one step a plan begins from.

A start carries nothing — the marker entry is the whole shape. What it *means* is the
composition root's to wire: a feature's walk and a milestone's walk both stop at it
(``_scope_kinds()``), so the origin every parallel branch traces back to is nobody's work,
and a plan fanning out from it is not a step gathered by every feature at once.

It is a marker rather than "the step nothing precedes" because a plan being built has
several of those, and one of them is usually work somebody forgot to link: inferring the
origin would make that step quietly nobody's too.
"""

from typing import Any

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Step

MODULE_ID = "step_start"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)


def read(step: Step) -> bool:
    """Whether the step is the start — presence of the entry, which carries nothing else."""
    return bool(step.module_data.get(MODULE_ID))


def write(on: bool) -> dict[str, Any]:
    """The entry to store. Off gives ``{}``, which removes the file."""
    if not on:
        return {}
    return stamped({"on": True}, DATA_FORMAT.version)


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when there is nothing to say."""
    return "start" if read(step) else ""


# Last, because it names the pieces above: the one declaration everything reads.
SPEC = AspectSpec(
    id=MODULE_ID,
    label="Start",
    summary=(
        "Marks the step the plan begins from: no feature or milestone gathers it, so work "
        "fanning out from it in parallel belongs to each branch alone."
    ),
    data_format=DATA_FORMAT,
    phrase=summary,
)
