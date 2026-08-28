"""The spec aspect: which requirements a step implements, and the figures it carries.

One module id, two shapes — the pattern ``estimation`` set. Beside a *project*, ``spec``
keeps the document index, the requirements and the assets (see :mod:`.documents`); beside a
*step* it keeps the requirement ids the step answers for and the spec figures copied next
to it (``attach-to-step``). The step half is the aspect: it is what ``dplanner aspect
list`` and the generated skill describe, and it is how an agent records *why* a step
exists and what it should look at.

A link is a plain id, resolved tolerantly: a requirement that has since been unmarked
reads as a dangling id, not an error — the same philosophy as an edge naming a deleted
step, and for the same reason (undo must be able to restore either side independently).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.assets import assets
from dplanner.domain.model import NodeId, Step
from dplanner.domain.store import ModuleFileArea

MODULE_ID = "spec"


def _to_format_2(data: dict[str, Any]) -> dict[str, Any]:
    """Format 1 shapes are valid format 2 shapes — for the project index *and* the step
    entry, since one format covers both. The bump exists so an older build refuses to
    rewrite the entry (its tolerant reader drops the keys format 2 added: ``page`` on a
    requirement, the ``assets`` list, a step's ``attachments``) rather than losing them."""
    return dict(data)


DATA_FORMAT = ModuleDataFormat(MODULE_ID, 2, (_to_format_2,))

LINKS_KEY = "requirements"
ATTACHMENTS_KEY = "attachments"

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


@dataclass(frozen=True)
class SpecAttachment:
    """A spec figure copied beside a step, with where it came from."""

    file: str  # assets/<sha256[:16]><suffix> in the *step's* spec file area.
    document: str = ""  # The SpecDocument.name it was rendered from, when known.
    page: int | None = None
    asset: str = ""  # The project index's asset id it was copied from.


def read_attachments(step: Step) -> list[SpecAttachment]:
    """The spec figures beside this step. Unreadable data reads as none."""
    raw = step.module_data.get(MODULE_ID, {}).get(ATTACHMENTS_KEY)
    if not isinstance(raw, list):
        return []
    return [
        SpecAttachment(
            file=entry["file"],
            document=entry.get("document", ""),
            page=entry.get("page") if isinstance(entry.get("page"), int) else None,
            asset=entry.get("asset", ""),
        )
        for entry in raw
        if isinstance(entry, dict) and isinstance(entry.get("file"), str)
    ]


def write_step_entry(
    ids: Sequence[str], attachments: Sequence[SpecAttachment] = ()
) -> dict[str, Any]:
    """The whole step entry — links *and* attachments, because writing one from the other's
    reader is how an edit erases what it never looked at. ``{}`` (remove the file) when
    both are empty."""
    data: dict[str, Any] = {}
    unique = sorted(set(ids))
    if unique:
        data[LINKS_KEY] = unique
    if attachments:
        data[ATTACHMENTS_KEY] = [
            {
                "file": attachment.file,
                **({"document": attachment.document} if attachment.document else {}),
                **({"page": attachment.page} if attachment.page is not None else {}),
                **({"asset": attachment.asset} if attachment.asset else {}),
            }
            for attachment in attachments
        ]
    return stamped(data, DATA_FORMAT.version)


def attachment_paths(
    files: Callable[[NodeId, str], ModuleFileArea], step_id: NodeId
) -> tuple[str, ...]:
    """A step's spec figures as workspace-relative paths — what a briefing lists and the
    launcher stages. A step the store has never flushed has no directory, and no files."""
    try:
        area = files(step_id, MODULE_ID)
    except KeyError:
        return ()
    return tuple(f"{area.directory}/{name}" for name in assets(area))


def summary(step: Step) -> str:
    """One short phrase for a step's row, empty when the aspect has nothing to say."""
    count = len(read_links(step))
    if count == 0:
        return ""
    return "meets 1 requirement" if count == 1 else f"meets {count} requirements"
