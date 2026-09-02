"""The spec aspect: the figures a step carries, and the project's topology.

One module id, three shapes — the pattern ``estimation`` set. Beside a *project*, ``spec``
keeps the document index and the assets in ``module_data`` (see :mod:`.documents`) and
the **topology** in ``module_text``: the prose that says how this project's graph is
shaped — what counts as a feature here, what follows one, where the milestones fall. Beside
a *step* it keeps the spec figures copied next to it (``attach-to-step``). The step half is
the aspect: it is what ``dplanner aspect list`` and the generated skill describe.

What a step *answers for* in the spec is no longer stored here. A spec is read into
**features** (``modules/feature``), each pointing back at the passage it came from, and a
work step reaches the spec through the feature it flows into — the graph's answer, not a
link.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.assets import assets
from dplanner.domain.model import NodeId, Project, Step, TextEdit
from dplanner.domain.store import FilesFor

MODULE_ID = "spec"


def _to_format_2(data: dict[str, Any]) -> dict[str, Any]:
    """Format 1 shapes are valid format 2 shapes — for the project index *and* the step
    entry, since one format covers both. The bump exists so an older build refuses to
    rewrite the entry (its tolerant reader drops the keys format 2 added: ``page`` on a
    requirement, the ``assets`` list, a step's ``attachments``) rather than losing them."""
    return dict(data)


def _to_format_3(data: dict[str, Any]) -> dict[str, Any]:
    """Requirements became features, kept by their own module. The ``requirements`` key —
    the project's record list and a step's link list alike — is dropped; what it said is
    not converted, because a requirement was a citation and a feature is a thing, and
    only a person reading the spec again can say which citations were features."""
    return {key: value for key, value in data.items() if key != "requirements"}


DATA_FORMAT = ModuleDataFormat(MODULE_ID, 3, (_to_format_2, _to_format_3))

ATTACHMENTS_KEY = "attachments"


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


def write_step_entry(attachments: Sequence[SpecAttachment] = ()) -> dict[str, Any]:
    """The whole step entry — ``{}`` (remove the file) when there is nothing to keep."""
    data: dict[str, Any] = {}
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


def attachment_paths(files: FilesFor, step_id: NodeId) -> tuple[str, ...]:
    """A step's spec figures as absolute paths — what a briefing lists and the
    launcher stages. A step the store has never flushed has no directory, and no files."""
    try:
        area = files(step_id, MODULE_ID)
    except KeyError:
        return ()
    return tuple(str(area.absolute(name)) for name in assets(area))


def summary(step: Step) -> str:
    """One short phrase for a step's row, empty when the aspect has nothing to say."""
    count = len(read_attachments(step))
    if count == 0:
        return ""
    return "1 spec figure" if count == 1 else f"{count} spec figures"


# -- the topology: the project's one prose document under this id ------------------------------


def read_topology(project: Project) -> str:
    """How this project's graph is shaped, in the project's own words — "" when nobody
    has written it yet."""
    return project.module_text.get(MODULE_ID, "")


def topology_edit(project: Project, body: str) -> TextEdit:
    """One positioned edit replacing the whole topology — what ``topology set`` and the
    Specs tab's editor both apply, labelled apart from typing so they never coalesce."""
    return TextEdit(project.id, MODULE_ID, 0, read_topology(project), body)


TOPOLOGY_LABEL = "Set Topology"


# Last, because it names the pieces above: the one declaration everything reads.
SPEC = AspectSpec(
    id=MODULE_ID,
    label="Spec figures",
    summary=(
        "Figures from the project's spec copied beside a step so its briefing carries "
        "them; attach with `dplanner spec attach-to-step`."
    ),
    data_format=DATA_FORMAT,
    phrase=summary,
)
