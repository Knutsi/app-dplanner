"""The feature marker: which catalogue record a step is the instance of.

A feature is a thing a person names, demos and tests. The **record** — title, description,
where in the spec it came from, its images — lives in the project's catalogue
(:mod:`.catalogue`); the step that realises it carries only the record's id. What the
step *gathers* is still nothing stored: ``domain/scope.py`` walks ``requires`` backwards
and stops at the previous feature, recomputed on every read, so ``dplanner step link``
cannot leave a feature claiming work it no longer has.

This module was ``step_feature`` while a feature was a bare ``{"on": true}`` marker. The
rename is a :class:`~dplanner.core.module_data.Takeover`, not a migration: the retired id
is carried here with a converter, and the data moves at open. A marker written by that
module names no record — no per-entry converter can mint one, because it cannot see the
project — so it reads as an **unregistered** feature step: still a feature to the graph,
listed as such by lint, and registered by the first ``feature set`` or Type toggle.
"""

from typing import Any

from dplanner.core.module_data import ModuleDataFormat, Takeover, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Step

MODULE_ID = "feature"

# What ``step_feature`` last wrote. Frozen at format 1 forever.
RETIRED_STEP_FEATURE = ModuleDataFormat("step_feature")

RECORD_KEY = "feature"


def _from_step_feature(retired: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    """A ``step_feature`` marker as a ``feature`` entry: still a marker, naming no record.

    An existing entry wins — a project half-written by both builds keeps the newer answer.
    The retired marker carried nothing, so there is nothing to carry over but the fact of
    it; ``{"on": true}`` stays readable as "unregistered" by :func:`read`.
    """
    return dict(existing) if existing else dict(retired)


DATA_FORMAT = ModuleDataFormat(
    MODULE_ID,
    takeovers=(Takeover(retired=RETIRED_STEP_FEATURE, convert=_from_step_feature),),
)


def read(step: Step) -> str | None:
    """The id of the record this step instantiates; ``""`` for a feature step naming no
    record (a marker the retired module wrote, or a hand edit); None for a plain step."""
    entry = step.module_data.get(MODULE_ID)
    if not entry:
        return None
    record = entry.get(RECORD_KEY)
    return record if isinstance(record, str) else ""


def is_feature(step: Step) -> bool:
    """Whether the graph reads this step as a feature — registered or not."""
    return read(step) is not None


def write(feature_id: str) -> dict[str, Any]:
    """The entry that makes a step the instance of ``feature_id``."""
    if not feature_id:
        raise ValueError("a feature step names the record it is the instance of")
    return stamped({RECORD_KEY: feature_id}, DATA_FORMAT.version)


def clear() -> dict[str, Any]:
    """The entry that makes a step plain again: ``{}`` removes the file."""
    return {}


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when there is nothing to say."""
    record = read(step)
    if record is None:
        return ""
    return f"feature {record}" if record else "feature (unregistered)"


# Last, because it names the pieces above: the one declaration everything reads.
SPEC = AspectSpec(
    id=MODULE_ID,
    label="Feature",
    summary=(
        "Makes a step the instance of one feature record from the project's catalogue "
        "(`dplanner feature list`); the work upstream of it flows into that feature, and "
        "its tests are read and run by it."
    ),
    data_format=DATA_FORMAT,
    phrase=summary,
)
