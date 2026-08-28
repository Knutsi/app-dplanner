"""The release aspect: its format, and the one place its shape is written down.

A release is a step like any other — it waits on what must ship and other work can wait on
it — that carries a label saying which release it is. The label is the whole entry: *when*
a release lands is the schedule's answer, derived from the graph and the estimates, and
storing a date here would be a second copy waiting to disagree with it.
"""

import re
from collections.abc import Iterable
from typing import Any

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Project, Step, StepId

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


# Any prefix, then a trailing dotted number: "v2", "v1.0", "release 4".
_NUMBERED = re.compile(r"^(?P<prefix>.*?)(?P<version>\d+(?:\.\d+)*)$")


def project_labels(project: Project, skip: StepId | None = None) -> list[str]:
    """Every release label in the project, in step order, optionally skipping one step."""
    return [read(step) for step in project.steps if step.id != skip and read(step)]


def next_release_label(existing: Iterable[str]) -> str:
    """The label the next release would naturally take, from the ones already in use.

    No labels yet gives ``v1``. Where labels end in a number, the highest is bumped in its
    own shape — ``v1, v2`` gives ``v3``, ``v1.0`` gives ``v2.0``, ``release 4`` gives
    ``release 5``. Labels that carry no number at all (``MVP``) are only counted, so
    ``["MVP"]`` gives ``v2``. The result never collides with a label already in use: a
    label spelling the candidate would parse higher and have been the one bumped instead.
    """
    labels = [label.strip() for label in existing if label.strip()]
    if not labels:
        return "v1"
    numbered = [
        (tuple(int(part) for part in match["version"].split(".")), match["prefix"])
        for label in labels
        if (match := _NUMBERED.match(label))
    ]
    if not numbered:
        return f"v{len(labels) + 1}"
    version, prefix = max(numbered)
    bumped = (version[0] + 1, *(0 for _ in version[1:]))
    return prefix + ".".join(str(part) for part in bumped)
