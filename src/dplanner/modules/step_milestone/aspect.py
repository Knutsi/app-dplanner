"""The milestone aspect: its format, and the one place its shape is written down.

A milestone is a step like any other — it waits on what must ship and other work can wait on
it — that carries a label saying which milestone it is. The label is the whole entry: *when*
a milestone lands is the schedule's answer, derived from the graph and the estimates, and
storing a date here would be a second copy waiting to disagree with it.

This module was called ``step_release`` while the word for it was "release". The rename is a
:class:`~dplanner.core.module_data.Takeover`, not a format migration: the on-disk id is the
contract between the retired module and this one, so this package carries that id and a
converter, the data moves at open, and no other module learns anything. ``FORMAT.md``'s
*Retiring a module* has the three rules; the one that bites is that a takeover is **one-way**
— an older build opening the project afterwards sees no milestones at all.
"""

import re
from collections.abc import Iterable
from typing import Any

from dplanner.core.module_data import ModuleDataFormat, Takeover, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Project, Step, StepId

MODULE_ID = "step_milestone"

# What ``step_release`` last wrote. Frozen at format 1 forever, whatever this module does
# next: it is the retired schema's history, and history does not gain entries.
RETIRED_STEP_RELEASE = ModuleDataFormat("step_release")


def _label_in(entry: dict[str, Any]) -> str:
    """The readable ``label`` of an entry, or "". Shared by ``read`` and the takeover."""
    label = entry.get("label")
    return label if isinstance(label, str) else ""


def _from_step_release(retired: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    """A ``step_release`` entry as a ``step_milestone`` one — the label, renamed around it.

    The shapes are identical, so this is a rebuild rather than a conversion; it is written
    out anyway because the engine stamps the result with *this* module's version and does
    not run our own chain over it, so a shape change here has to be reflected here.

    An existing milestone entry wins: a project half-written by both builds keeps the newer
    answer rather than having the retired one overwrite it.
    """
    kept = dict(existing)
    label = _label_in(retired)
    return kept if _label_in(kept) or not label else kept | {"label": label}


DATA_FORMAT = ModuleDataFormat(
    MODULE_ID,
    takeovers=(Takeover(retired=RETIRED_STEP_RELEASE, convert=_from_step_release),),
)


def read(step: Step) -> str:
    """The milestone label, or "" when the step is not a milestone."""
    entry = step.module_data.get(MODULE_ID)
    return _label_in(entry) if entry else ""


def write(label: str) -> dict[str, Any]:
    """The entry to store. An empty label gives ``{}``, which removes the file."""
    label = label.strip()
    if not label:
        return {}
    return stamped({"label": label}, DATA_FORMAT.version)


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when there is nothing to say."""
    label = read(step)
    return "" if not label else f"milestone {label}"


# Any prefix, then a trailing dotted number: "v2", "v1.0", "milestone 4".
_NUMBERED = re.compile(r"^(?P<prefix>.*?)(?P<version>\d+(?:\.\d+)*)$")


def project_labels(project: Project, skip: StepId | None = None) -> list[str]:
    """Every milestone label in the project, in step order, optionally skipping one step."""
    return [read(step) for step in project.steps if step.id != skip and read(step)]


def next_milestone_label(existing: Iterable[str]) -> str:
    """The label the next milestone would naturally take, from the ones already in use.

    No labels yet gives ``v1``. Where labels end in a number, the highest is bumped in its
    own shape — ``v1, v2`` gives ``v3``, ``v1.0`` gives ``v2.0``, ``milestone 4`` gives
    ``milestone 5``. Labels that carry no number at all (``MVP``) are only counted, so
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


# Last, because it names the pieces above: the one declaration everything reads.
SPEC = AspectSpec(
    id=MODULE_ID,
    label="Milestone",
    summary="Marks a step as a milestone point, labelled: MVP, v1.0, v2.",
    data_format=DATA_FORMAT,
    phrase=summary,
)
