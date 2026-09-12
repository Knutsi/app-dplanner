"""Documents that come from a source: adding a source, applying what it fetched, the
tree the list shows, and the refusal a sourced document answers with.

Qt-free and shared verbatim by ``cli.py`` and the Specs tab. A fetch arrives as a
:class:`~dplanner.domain.document_source.Snapshot` — the kind's plain data — and
:func:`apply_snapshot` is **the one place the three-way partition lives**: a page the
snapshot carries is imported (through :func:`~.documents.import_document`, so a replace
keeps ``previous`` and ``spec diff`` answers per page), a page it *kept* stays as it is,
and a page it names in neither is gone from the source and leaves the index — its blob
stays, the way ``spec remove`` leaves one. Names are minted once and kept across
refreshes, because a citation keys on the name and a title is a thing that gets edited.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from dplanner.core.fsio import slugify
from dplanner.domain.document_source import Locator, Snapshot
from dplanner.domain.ids import next_id
from dplanner.domain.store import ModuleFileArea
from dplanner.modules.spec.documents import (
    SpecDocument,
    SpecIndex,
    SpecSource,
    attach_asset,
    import_document,
    referenced_assets,
    remove_document,
)

SOURCE_PREFIX = "src"


@dataclass(frozen=True)
class Applied:
    """What one fetch did to the index — the counts the notice reads out."""

    added: int = 0
    replaced: int = 0
    unchanged: int = 0
    removed: int = 0
    notes: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        parts = [
            f"{count} {word}"
            for count, word in (
                (self.added, "added"),
                (self.replaced, "updated"),
                (self.removed, "gone"),
            )
            if count
        ]
        return ", ".join(parts) if parts else "up to date"


@dataclass(frozen=True)
class Row:
    """One line of the nested list: a source, or a document under one or under none."""

    depth: int
    document: SpecDocument | None  # None on a source's own row.
    source: SpecSource | None  # The source a row belongs to; None for a project's own document.


def add_source(
    index: SpecIndex, kind: str, title: str, locator: Locator
) -> tuple[SpecIndex, SpecSource]:
    """A new source record with a fresh id; nothing is fetched yet."""
    source = SpecSource(
        id=next_id([entry.id for entry in index.sources], SOURCE_PREFIX),
        kind=kind,
        title=title,
        locator=dict(locator),
    )
    return replace(index, sources=[*index.sources, source]), source


def source_of(index: SpecIndex, source_id: str) -> SpecSource | None:
    return next((source for source in index.sources if source.id == source_id), None)


def documents_of(index: SpecIndex, source_id: str) -> list[SpecDocument]:
    return [doc for doc in index.documents if doc.source == source_id]


def known_versions(index: SpecIndex, source_id: str) -> dict[str, str]:
    """What the index holds of a source, by the source's own key — the kind's ``known``."""
    return {doc.key: doc.version for doc in documents_of(index, source_id)}


def owned_by_source(index: SpecIndex, name: str) -> SpecSource | None:
    """The source a document belongs to — the refusal every edit of it answers with."""
    document = next((doc for doc in index.documents if doc.name == name), None)
    return source_of(index, document.source) if document is not None and document.source else None


def remove_source(index: SpecIndex, source_id: str) -> SpecIndex:
    """The index without the source and every document it fetched. Blobs stay."""
    return replace(
        index,
        sources=[source for source in index.sources if source.id != source_id],
        documents=[doc for doc in index.documents if doc.source != source_id],
    )


def apply_snapshot(
    area: ModuleFileArea, index: SpecIndex, source_id: str, snapshot: Snapshot, today: str
) -> tuple[SpecIndex, Applied]:
    """Write what a source fetched and return the index as it now stands.

    Images first (content-addressed, so the names the kind linked are the names written),
    then every fetched page through :func:`import_document` under its existing name or a
    freshly minted one, then the rows the snapshot no longer names are dropped. The
    source's documents keep their place in the index and land in the source's own order.
    """
    source = source_of(index, source_id)
    if source is None:
        raise ValueError(f"no source {source_id!r} in the index")
    for image in snapshot.images:
        attach_asset(area, image.data, image.filename)

    existing = {doc.key: doc for doc in documents_of(index, source_id)}
    taken = {doc.name for doc in index.documents}
    names: dict[str, str] = {key: doc.name for key, doc in existing.items()}
    for page in snapshot.documents:
        if page.key not in names:
            names[page.key] = _mint(taken, page.title)
            taken.add(names[page.key])

    working = list(index.documents)
    assets = list(index.assets)
    counts = {"added": 0, "replaced": 0, "unchanged": 0}
    fetched_by_key = {page.key: page for page in snapshot.documents}
    kept = set(snapshot.kept)
    for key, page in fetched_by_key.items():
        name = names[key]
        working, document, outcome = import_document(
            area, working, name, page.markdown.encode(), f"{name}.md", today
        )
        counts[outcome] += 1
        stamped = replace(
            document,
            title=page.title,
            source=source_id,
            key=key,
            version=page.version,
            parent=names.get(page.parent_key, "") if page.parent_key else "",
        )
        working = [stamped if doc.name == name else doc for doc in working]
        assets = referenced_assets(assets, page.markdown, today)
    gone = [key for key in existing if key not in fetched_by_key and key not in kept]
    for key in gone:
        working = remove_document(working, existing[key].name)

    # The source's documents land together, in the source's order, where they were.
    ours = {doc.name: doc for doc in working if doc.source == source_id}
    ordered = [ours[names[key]] for key in _ordered(snapshot, existing) if names.get(key) in ours]
    ordered = [doc if doc.parent in ours else replace(doc, parent="") for doc in ordered]
    others = [doc for doc in working if doc.source != source_id]
    position = _first_position(index, source_id)
    merged = [*others[:position], *ordered, *others[position:]]
    sources = [
        replace(entry, fetched=today) if entry.id == source_id else entry for entry in index.sources
    ]
    applied = Applied(
        added=counts["added"],
        replaced=counts["replaced"],
        unchanged=counts["unchanged"],
        removed=len(gone),
        notes=snapshot.notes,
    )
    return replace(index, documents=merged, assets=assets, sources=sources), applied


def tree(index: SpecIndex) -> list[Row]:
    """The nested order the Specs tab and ``spec list`` share: the project's own
    documents first, then each source with its pages under it, children under parents
    in index order."""
    rows = [Row(0, doc, None) for doc in index.documents if not doc.source]
    for source in index.sources:
        rows.append(Row(0, None, source))
        children: dict[str, list[SpecDocument]] = {}
        for doc in documents_of(index, source.id):
            children.setdefault(doc.parent, []).append(doc)
        rows.extend(_nested(children, source, "", 1))
    return rows


def _nested(
    children: Mapping[str, list[SpecDocument]], source: SpecSource, parent: str, depth: int
) -> list[Row]:
    rows: list[Row] = []
    for doc in children.get(parent, []):
        rows.append(Row(depth, doc, source))
        if doc.name != parent:
            rows.extend(_nested(children, source, doc.name, depth + 1))
    return rows


def _ordered(snapshot: Snapshot, existing: Mapping[str, SpecDocument]) -> list[str]:
    """The keys the source's documents land in: the snapshot's order, then any kept
    key it did not order (an older kind), in their old order."""
    ordered = list(snapshot.keys())
    seen = set(ordered)
    ordered.extend(key for key in existing if key not in seen)
    return ordered


def _first_position(index: SpecIndex, source_id: str) -> int:
    """Where the source's block sits among the other documents: after however many of
    them came before its first row, or at the end for a source never fetched."""
    for position, doc in enumerate(index.documents):
        if doc.source == source_id:
            return len([other for other in index.documents[:position] if other.source != source_id])
    return len([doc for doc in index.documents if doc.source != source_id])


def _mint(taken: Sequence[str] | set[str], title: str) -> str:
    base = slugify(title, fallback="page")
    if base not in taken:
        return base
    number = 2
    while f"{base}-{number}" in taken:
        number += 1
    return f"{base}-{number}"
