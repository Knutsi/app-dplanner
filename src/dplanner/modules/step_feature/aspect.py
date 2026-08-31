"""The feature aspect: the unit between a step and a milestone.

A feature is the thing a person names, demos and tests — it collects the work behind it,
stopping at the previous feature. Like a check it carries **nothing at all**: the marker
entry is the whole shape, and what it gathers is ``domain/scope.py``'s answer, recomputed on
every read. Storing that membership would let ``dplanner step link`` leave a feature
claiming work it no longer has, with no window running to notice.

What separates it from a check is only the predicate the composition root hands the walk: a
check stops at nothing and stands for the whole cone behind it, a feature stops at the next
feature or milestone and owns only what is new. Neither this file nor the walk knows that —
see ``ScopeKind`` in ``domain/scope.py``.
"""

from typing import Any

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Step

MODULE_ID = "step_feature"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)


def read(step: Step) -> bool:
    """Whether the step is a feature — presence of the entry, which carries nothing else."""
    return bool(step.module_data.get(MODULE_ID))


def write(on: bool) -> dict[str, Any]:
    """The entry to store. Off gives ``{}``, which removes the file."""
    if not on:
        return {}
    return stamped({"on": True}, DATA_FORMAT.version)


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when there is nothing to say."""
    return "feature" if read(step) else ""


# Last, because it names the pieces above: the one declaration everything reads.
SPEC = AspectSpec(
    id=MODULE_ID,
    label="Feature",
    summary=(
        "Marks a step as a feature: it collects the work and tests behind it, stopping at "
        "the previous feature, so tests can be read and run by the thing they belong to."
    ),
    data_format=DATA_FORMAT,
    phrase=summary,
)
