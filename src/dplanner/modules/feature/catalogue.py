"""The project half of the feature module: the catalogue of records.

Beside a *project*, ``modules/feature.json`` holds one record per feature — title,
description, where in a spec it came from, the images that show it — whether or not the
feature is on the graph yet. Beside a *step*, the same id holds only the record's id
(:mod:`.aspect`). The catalogue is stored because a feature nobody has placed yet is a fact
the graph cannot derive; what a placed feature *gathers* is never stored, for the reason
``domain/scope.py`` gives.

A record is created and removed only by the feature verbs. Clearing the marker or
deleting the instance step leaves the record in the catalogue as *unplaced* — undo has
to restore either side independently, the same rule an edge to a deleted step follows.

Everything here is Qt-free and shared verbatim by ``cli.py``, the panel and the editor, so
no two surfaces can disagree about what a feature is.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from dplanner.cli.command import CliError
from dplanner.core.module_data import stamped
from dplanner.domain.assets import (
    AssetLocation,
    AssetSource,
    AssetUse,
    area_assets,
)
from dplanner.domain.commands import Command, SetModuleDataCommand
from dplanner.domain.ids import next_id
from dplanner.domain.model import Library, NodeId, Project, Step
from dplanner.domain.store import FilesFor
from dplanner.modules.feature.aspect import DATA_FORMAT, MODULE_ID, read, write

RECORDS_KEY = "features"
ID_PREFIX = "f"

# The vendor type a dragged feature travels as; the payload names the record and the
# project it belongs to, so a drop onto another project's canvas can refuse honestly.
FEATURE_MIME = "application/x-dplanner-feature"


@dataclass(frozen=True)
class FeatureSource:
    """One passage a feature was read from: the document, the quote, the page — and the
    document's digest at the time, so a later read can tell whether the spec moved on.

    The quote is the anchor; where it sits is derived on every read (``core/anchors.py``).
    ``digest`` is ``""`` for a passage cited before stamps existed, which is judged by its
    match alone rather than read as behind."""

    document: str
    quote: str = ""
    page: int | None = None
    digest: str = ""


@dataclass(frozen=True)
class FeatureRecord:
    id: str  # "f1", "f2", … — what every verb and every marker addresses.
    title: str
    description: str = ""  # Markdown, a string in the record: a project holds N of these.
    sources: tuple[FeatureSource, ...] = ()  # The passages it was read from, in cite order.
    images: tuple[str, ...] = ()  # assets/<sha16><suffix> in the *project's* feature area.


def read_catalogue(project: Project) -> list[FeatureRecord]:
    """The records beside ``project``, in catalogue order. Unreadable rows read as absent."""
    entry = project.module_data.get(MODULE_ID, {})
    raw = entry.get(RECORDS_KEY)
    if not isinstance(raw, list):
        return []
    return [
        FeatureRecord(
            id=row["id"],
            title=row.get("title", ""),
            description=row.get("description", "") or "",
            sources=_sources(row.get("sources")),
            images=tuple(name for name in row.get("images", ()) if isinstance(name, str)),
        )
        for row in raw
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    ]


def _sources(value: Any) -> tuple[FeatureSource, ...]:
    if not isinstance(value, list):
        return ()
    found = []
    for raw in value:
        if not isinstance(raw, dict) or not isinstance(raw.get("document"), str):
            continue
        page = raw.get("page")
        digest = raw.get("digest")
        found.append(
            FeatureSource(
                document=raw["document"],
                quote=raw.get("quote", "") or "",
                page=page if isinstance(page, int) and not isinstance(page, bool) else None,
                digest=digest if isinstance(digest, str) else "",
            )
        )
    return tuple(found)


def write_catalogue(records: Sequence[FeatureRecord]) -> dict[str, Any]:
    """The module_data entry for these records — ``{}`` (remove the file) when empty."""
    if not records:
        return {}
    rows = []
    for record in records:
        row: dict[str, Any] = {"id": record.id, "title": record.title}
        if record.description:
            row["description"] = record.description
        if record.sources:
            row["sources"] = [
                {
                    "document": source.document,
                    **({"quote": source.quote} if source.quote else {}),
                    **({"page": source.page} if source.page is not None else {}),
                    **({"digest": source.digest} if source.digest else {}),
                }
                for source in record.sources
            ]
        if record.images:
            row["images"] = list(record.images)
        rows.append(row)
    return stamped({RECORDS_KEY: rows}, DATA_FORMAT.version)


def next_feature_id(records: Sequence[FeatureRecord]) -> str:
    return next_id([record.id for record in records], ID_PREFIX)


def find_record(project: Project, needle: str) -> FeatureRecord:
    """The record ``needle`` names: its id exactly, else a unique part of its title.

    Refuses the way ``find_step`` does — an ambiguous name lists the ids rather than
    guessing — and names ``dplanner feature list`` when nothing matches.
    """
    records = read_catalogue(project)
    for record in records:
        if record.id == needle:
            return record
    lowered = needle.lower()
    exact = [record for record in records if record.title.lower() == lowered]
    partial = exact or [record for record in records if lowered in record.title.lower()]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise CliError(f"no feature {needle!r} in {project.title!r} — see `dplanner feature list`")
    listed = ", ".join(f"{record.id} ({record.title})" for record in partial)
    raise CliError(f"{needle!r} matches several features: {listed}")


def with_record(records: Sequence[FeatureRecord], updated: FeatureRecord) -> list[FeatureRecord]:
    """``records`` with ``updated`` in place of the record sharing its id."""
    return [updated if record.id == updated.id else record for record in records]


def without_record(records: Sequence[FeatureRecord], feature_id: str) -> list[FeatureRecord]:
    return [record for record in records if record.id != feature_id]


def mint_for_step(records: Sequence[FeatureRecord], step: Step) -> FeatureRecord:
    """A fresh record titled like ``step`` — what marking a plain step as a feature makes.
    The caller writes it into the catalogue beside the marker, in one command."""
    return FeatureRecord(id=next_feature_id(records), title=step.title or "Untitled feature")


def placements(project: Project) -> dict[str, list[Step]]:
    """Record id → the steps naming it. One step is the rule; two is the lint finding."""
    found: dict[str, list[Step]] = {}
    for step in project.steps:
        record = read(step)
        if record:
            found.setdefault(record, []).append(step)
    return found


def instance_of(project: Project, feature_id: str) -> Step | None:
    """The step that realises ``feature_id`` — the first, if a hand edit made two."""
    steps = placements(project).get(feature_id, [])
    return steps[0] if steps else None


def unregistered(project: Project) -> list[Step]:
    """Feature steps naming no record — markers the retired module wrote."""
    return [step for step in project.steps if read(step) == ""]


def image_paths(files: FilesFor, project_id: NodeId, record: FeatureRecord) -> tuple[str, ...]:
    """A record's images as absolute paths — what a briefing lists. A project the store
    has never flushed has no directory, and no files."""
    try:
        area = files(project_id, MODULE_ID)
    except KeyError:
        return ()
    return tuple(str(area.absolute(name)) for name in record.images)


# -- drag and drop -----------------------------------------------------------------------------


def drag_payload(project_id: NodeId, feature_id: str) -> bytes:
    return json.dumps({"project": project_id, "feature": feature_id}).encode("utf-8")


def parse_drag(data: bytes) -> tuple[str, str] | None:
    """``(project id, feature id)`` from a payload, or None for anything else."""
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    project, feature = parsed.get("project"), parsed.get("feature")
    if not isinstance(project, str) or not isinstance(feature, str) or not feature:
        return None
    return project, feature


# -- policies and sources the composition root assembles ----------------------------------------


def drop_marker_for_paste(_project: Project, steps: Sequence[Step]) -> None:
    """A copied feature step is a plain step — the paste policy this module hands in.

    A record has at most one instance, and the original still is it; a copy that kept the
    marker would make the feature placed twice, which is exactly what the drop and
    ``feature set`` refuse.
    """
    for step in steps:
        step.module_data.pop(MODULE_ID, None)


def asset_source() -> AssetSource:
    """The feature module's slice of the project's asset catalog: a record's images.

    A file is used while any record's ``images`` names it; a name dropped from a record
    stays on disk by design (an attach is not undoable, an orphan is recoverable) and is
    what ``asset prune`` sweeps.
    """

    def scan(_library: Library, project: Project, files: FilesFor) -> Sequence[AssetLocation]:
        used: dict[str, list[AssetUse]] = {}
        for record in read_catalogue(project):
            for name in record.images:
                used.setdefault(name, []).append(
                    AssetUse(
                        "project",
                        project.id,
                        project.title,
                        f"feature {record.id} — {record.title}",
                    )
                )
        return [
            AssetLocation(
                node_id=project.id,
                module_id=MODULE_ID,
                name=name,
                uses=tuple(used.get(name, ())),
            )
            for name in area_assets(files, project.id, MODULE_ID)
        ]

    return AssetSource(id=MODULE_ID, label="Feature images", scan=scan)


def summary_line(record: FeatureRecord, instance: Step | None) -> str:
    """One row for ``feature list`` and the panel's secondary line, worded once."""
    placed = f"placed: {instance.title!r}" if instance is not None else "not placed"
    if not record.sources:
        return placed
    first = record.sources[0]
    page = f" p.{first.page}" if first.page is not None else ""
    more = f" +{len(record.sources) - 1}" if len(record.sources) > 1 else ""
    return f"{placed} · {first.document}{page}{more}"


def same_passage(source: FeatureSource, document: str, quote: str) -> bool:
    """Whether ``source`` already cites this passage — the document, and the quote case
    and whitespace aside, the way it is anchored."""
    return source.document == document and _flat(source.quote) == _flat(quote)


def _flat(quote: str) -> str:
    return " ".join(quote.lower().split())


def cited_at(record: FeatureRecord, document: str, quote: str) -> int | None:
    """The index of the passage ``record`` already cites, or None."""
    return next(
        (i for i, source in enumerate(record.sources) if same_passage(source, document, quote)),
        None,
    )


def registration(project: Project, step: Step) -> list[Command]:
    """The commands that make ``step`` a new, registered feature: a fresh record titled
    like the step in the catalogue, and the marker naming it on the step.

    One list because it is one gesture — New ▸ Feature, the Type toggle, ``feature set``
    without an id — and one gesture is one undo. A step already the instance of a record
    is left alone (nothing to do); an unregistered one is registered.
    """
    if read(step):
        return []
    records = read_catalogue(project)
    record = mint_for_step(records, step)
    return [
        SetModuleDataCommand(project.id, MODULE_ID, write_catalogue([*records, record])),
        SetModuleDataCommand(step.id, MODULE_ID, write(record.id)),
    ]
