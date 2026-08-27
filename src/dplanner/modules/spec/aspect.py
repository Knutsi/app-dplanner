"""The spec aspect: which requirements a step implements.

One module id, two shapes — the pattern ``estimation`` set. Beside a *project*, ``spec``
keeps the document index and the requirements (see :mod:`.documents`); beside a *step* it
keeps the list of requirement ids the step answers for. The step half is the aspect: it is
what ``dplanner aspect list`` and the generated skill describe, and it is how an agent
records *why* a step exists.

A link is a plain id, resolved tolerantly: a requirement that has since been unmarked
reads as a dangling id, not an error — the same philosophy as an edge naming a deleted
step, and for the same reason (undo must be able to restore either side independently).
"""

from collections.abc import Sequence
from typing import Any

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Step

MODULE_ID = "spec"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)

LINKS_KEY = "requirements"

SPEC = AspectSpec(
    id=MODULE_ID,
    label="Spec requirements",
    summary="Which spec requirements a step implements; link with `dplanner spec link`.",
    data_format=DATA_FORMAT,
)


def read_links(step: Step) -> list[str]:
    """The requirement ids this step is linked to. Unreadable data reads as no links."""
    ids = step.module_data.get(MODULE_ID, {}).get(LINKS_KEY)
    if not isinstance(ids, list):
        return []
    return [entry for entry in ids if isinstance(entry, str)]


def write_links(ids: Sequence[str]) -> dict[str, Any]:
    """The module_data entry for these links — ``{}`` (remove the file) when there are none."""
    unique = sorted(set(ids))
    return stamped({LINKS_KEY: unique} if unique else {}, DATA_FORMAT.version)


def summary(step: Step) -> str:
    """One short phrase for a step's row, empty when the aspect has nothing to say."""
    count = len(read_links(step))
    if count == 0:
        return ""
    return "meets 1 requirement" if count == 1 else f"meets {count} requirements"
