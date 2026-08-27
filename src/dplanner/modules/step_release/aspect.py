"""The release aspect: its format, and the one place its shape is written down.

A release is a step like any other — it waits on what must ship and other work can wait on
it — that carries a label saying which release it is. The label is the whole entry: *when*
a release lands is the schedule's answer, derived from the graph and the estimates, and
storing a date here would be a second copy waiting to disagree with it.
"""

from typing import Any

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Step

MODULE_ID = "step_release"

DATA_FORMAT = ModuleDataFormat(MODULE_ID)

SPEC = AspectSpec(
    id=MODULE_ID,
    label="Release",
    summary="Marks a step as a release point, labelled: MVP, v1.0, v2.",
    data_format=DATA_FORMAT,
)


def read(step: Step) -> str:
    """The release label, or "" when the step is not a release."""
    entry = step.module_data.get(MODULE_ID)
    label = entry.get("label") if entry else None
    return label if isinstance(label, str) else ""


def write(label: str) -> dict[str, Any]:
    """The entry to store. An empty label gives ``{}``, which removes the file."""
    label = label.strip()
    if not label:
        return {}
    return stamped({"label": label}, DATA_FORMAT.version)


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when there is nothing to say."""
    label = read(step)
    return "" if not label else f"release {label}"
