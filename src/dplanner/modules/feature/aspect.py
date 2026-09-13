"""The feature aspect: a step that is a feature, and the spec passages it was read from.

A feature is a thing a person names, demos and tests — and it is a **step**. There is no
record beside the project any more: the step's title is the feature's name, its description
is the feature's description, its file area holds the pictures, and the only fact that is
the feature's own — the passages of a specification it was read out of — lives here, in the
step's own entry. What the step *gathers* is still nothing stored: ``domain/scope.py`` walks
``requires`` backwards and stops at the previous feature, recomputed on every read, so
``dplanner step link`` cannot leave a feature claiming work it no longer has.

This module was ``step_feature`` while a feature was a bare ``{"on": true}`` marker, and
then carried a catalogue record's id through format 2. Both are gone: the marker written by
the retired module is now a **complete** answer — a feature citing nothing — and
:mod:`.migrate` moves each catalogue record onto its step at open.

Everything here is Qt-free and shared verbatim by ``cli.py`` and the editor, so no two
surfaces can disagree about what a feature is.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from dplanner.core.module_data import ModuleDataFormat, Takeover, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Project, Step
from dplanner.modules.feature.migrate import absorb_catalogue

MODULE_ID = "feature"

# What ``step_feature`` last wrote. Frozen at format 1 forever.
RETIRED_STEP_FEATURE = ModuleDataFormat("step_feature")

ON_KEY = "on"
CITES_KEY = "cites"

# What format 2 stored beside a step: the id of a catalogue record. Read only by the
# migration, and named here because this is where the entry's shapes are written down.
RECORD_KEY = "feature"
# …and beside a project: the catalogue itself.
RECORDS_KEY = "features"


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


def read_sources(value: Any) -> tuple[FeatureSource, ...]:
    """Passages from whatever a file held — unreadable rows read as absent.

    Public because the migration reads the same rows out of a catalogue record, where they
    sat under the same key and the same shape.
    """
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


def source_rows(cites: Sequence[FeatureSource]) -> list[dict[str, Any]]:
    """The passages as rows on disk — what is empty is left out, as FORMAT.md asks."""
    return [
        {
            "document": source.document,
            **({"quote": source.quote} if source.quote else {}),
            **({"page": source.page} if source.page is not None else {}),
            **({"digest": source.digest} if source.digest else {}),
        }
        for source in cites
    ]


def _from_step_feature(retired: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    """A ``step_feature`` marker as a ``feature`` entry: a feature citing nothing.

    An existing entry wins — a project half-written by both builds keeps the newer answer.
    The retired marker carried nothing, and with the catalogue gone there is nothing left
    for it to be missing: ``{"on": true}`` is the whole answer now, which is why this
    converter no longer leaves a half-state behind it.
    """
    return dict(existing) if existing else write()


def _to_format_2(data: dict[str, Any]) -> dict[str, Any]:
    """A record cites N passages: its one ``source`` becomes a one-element ``sources``.

    Beside a step the same id is a marker and passes through untouched — one module id,
    two shapes, and the migration owes both a thought (FORMAT.md). A migrated passage
    carries no ``digest``, so it is judged by its match alone rather than read as behind.
    """
    rows = data.get(RECORDS_KEY)
    if not isinstance(rows, list):
        return dict(data)
    migrated = []
    for row in rows:
        if isinstance(row, dict) and "source" in row:
            row = dict(row)
            source = row.pop("source")
            if isinstance(source, dict):
                row["sources"] = [source]
        migrated.append(row)
    return {**data, RECORDS_KEY: migrated}


def _to_format_3(data: dict[str, Any]) -> dict[str, Any]:
    """Deliberately a pass-through: the shape change needs the whole project.

    Format 3 collapses the project's catalogue into each feature step's own entry, and a
    per-entry converter cannot see the project — so the work is
    :func:`~dplanner.modules.feature.migrate.absorb_catalogue`, which runs after every
    per-entry pass and reads both old shapes exactly as they were written.
    """
    return dict(data)


def read(step: Step) -> tuple[FeatureSource, ...] | None:
    """The passages this feature was read from — ``()`` for a feature citing none, and
    None for a step that is not a feature."""
    entry = step.module_data.get(MODULE_ID)
    if not entry:
        return None
    return read_sources(entry.get(CITES_KEY))


def is_feature(step: Step) -> bool:
    """Whether the graph reads this step as a feature.

    Presence of a non-empty entry, so an entry a later build wrote and this one cannot
    read still says *feature*, which is the honest answer.
    """
    return bool(step.module_data.get(MODULE_ID))


def write(cites: Sequence[FeatureSource] = ()) -> dict[str, Any]:
    """The entry that makes a step a feature, citing these passages."""
    entry: dict[str, Any] = {ON_KEY: True}
    if cites:
        entry[CITES_KEY] = source_rows(cites)
    return stamped(entry, DATA_FORMAT.version)


def clear() -> dict[str, Any]:
    """The entry that makes a step plain again: ``{}`` removes the file."""
    return {}


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when there is nothing to say."""
    cites = read(step)
    if cites is None:
        return ""
    return f"feature · {passages_phrase(cites)}" if cites else "feature"


def passages_phrase(cites: Sequence[FeatureSource]) -> str:
    """Where a feature was read from, in one phrase — worded once for every surface."""
    if not cites:
        return "cites nothing"
    first = cites[0]
    page = f" p.{first.page}" if first.page is not None else ""
    more = f" +{len(cites) - 1}" if len(cites) > 1 else ""
    return f"{first.document}{page}{more}"


def same_passage(source: FeatureSource, document: str, quote: str) -> bool:
    """Whether ``source`` already cites this passage — the document, and the quote case
    and whitespace aside, the way it is anchored."""
    return source.document == document and _flat(source.quote) == _flat(quote)


def _flat(quote: str) -> str:
    return " ".join(quote.lower().split())


def cited_at(cites: Sequence[FeatureSource], document: str, quote: str) -> int | None:
    """The index of the passage already cited, or None."""
    return next(
        (i for i, source in enumerate(cites) if same_passage(source, document, quote)),
        None,
    )


def drop_cites_for_paste(_project: Project, steps: Sequence[Step]) -> None:
    """A copied feature step is still a feature, and cites nothing — the paste policy.

    Two steps may both be features now, so a copy keeps the marker: what was copied was a
    feature. Its passages are not copied, because a passage was read into *one* feature and
    the copy has not been read into anything; citing it again is a claim only a person can
    make.
    """
    for step in steps:
        if step.module_data.get(MODULE_ID):
            step.module_data[MODULE_ID] = write()


# Last, because it names the pieces above: the one declaration everything reads.
DATA_FORMAT = ModuleDataFormat(
    MODULE_ID,
    3,
    (_to_format_2, _to_format_3),
    takeovers=(Takeover(retired=RETIRED_STEP_FEATURE, convert=_from_step_feature),),
    absorb=absorb_catalogue,
)

SPEC = AspectSpec(
    id=MODULE_ID,
    label="Feature",
    summary=(
        "Makes a step a feature: a capability a person would name and demo. The work "
        "upstream of it flows into it, its tests are read and run by it, and it carries "
        "the specification passages it was read from (`dplanner feature show`)."
    ),
    data_format=DATA_FORMAT,
    phrase=summary,
)
