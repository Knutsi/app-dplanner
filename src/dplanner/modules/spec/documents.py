"""The project half of the spec module: the document index and the requirements.

The JSON entry beside the project (``modules/spec.json``) holds only pointers and names;
the document bytes live in the module's file area, content-addressed like a description's
images. That split is what makes a replace safe to undo: the index edit goes through a
command on the undo stack, and both the new and the previous blob stay on disk, so a
restored index always finds its file. The cost is that an orphaned blob is never pruned —
acceptable, because an orphan is recoverable where a dangling pointer is not, and the
workspace's own VCS is the real history.

Everything here is Qt-free and shared verbatim by ``cli.py`` and the Specs tab, so the two
surfaces cannot disagree about what a document or a requirement is.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import Any

from dplanner.core.fsio import slugify
from dplanner.core.module_data import stamped
from dplanner.domain.model import Project, Step
from dplanner.domain.store import ModuleFileArea
from dplanner.modules.spec.aspect import DATA_FORMAT, read_links

DOCUMENTS_DIR = "documents"
ASSETS_DIR = "assets"

KIND_PDF = "pdf"
KIND_MARKDOWN = "markdown"
KIND_TEXT = "text"


@dataclass(frozen=True)
class SpecDocument:
    name: str  # Stable identity within the project; what every verb addresses.
    filename: str  # What the file was called when it came in.
    kind: str  # KIND_PDF | KIND_MARKDOWN | KIND_TEXT, from the suffix.
    file: str  # documents/<sha256[:16]><suffix> in the module file area.
    previous: str | None  # The blob the last replace superseded, kept for diffing.
    imported: str  # ISO date of the last import or replace.


@dataclass(frozen=True)
class Requirement:
    id: str  # Unique within the project; "r1", "r2", … when not caller-chosen.
    document: str  # The SpecDocument.name it was marked in.
    title: str
    quote: str = ""  # The passage anchoring it to the document's text.
    page: int | None = None  # Where in the document, for a PDF; None for prose.


@dataclass(frozen=True)
class SpecAsset:
    """An image beside the specs: a rendered page, or something attached by hand."""

    id: str  # "a1", "a2", … — what `spec attach-to-step` addresses.
    file: str  # assets/<sha256[:16]><suffix> in the module file area.
    document: str = ""  # The SpecDocument.name it was rendered from, when it was.
    page: int | None = None
    imported: str = ""  # ISO date it arrived.


@dataclass(frozen=True)
class SpecIndex:
    """Everything ``modules/spec.json`` holds beside a project."""

    documents: list[SpecDocument]
    requirements: list[Requirement]
    assets: list[SpecAsset]


def read_index(project: Project) -> SpecIndex:
    """The index beside ``project``. Unreadable entries read as absent."""
    entry = project.module_data.get(DATA_FORMAT.module_id, {})
    documents = [
        SpecDocument(
            name=raw["name"],
            filename=raw.get("filename", raw["name"]),
            kind=raw.get("kind", KIND_TEXT),
            file=raw["file"],
            previous=raw.get("previous"),
            imported=raw.get("imported", ""),
        )
        for raw in _dicts(entry.get("documents"))
        if isinstance(raw.get("name"), str) and isinstance(raw.get("file"), str)
    ]
    requirements = [
        Requirement(
            id=raw["id"],
            document=raw.get("document", ""),
            title=raw.get("title", ""),
            quote=raw.get("quote", ""),
            page=_page(raw.get("page")),
        )
        for raw in _dicts(entry.get("requirements"))
        if isinstance(raw.get("id"), str)
    ]
    assets = [
        SpecAsset(
            id=raw["id"],
            file=raw["file"],
            document=raw.get("document", ""),
            page=_page(raw.get("page")),
            imported=raw.get("imported", ""),
        )
        for raw in _dicts(entry.get("assets"))
        if isinstance(raw.get("id"), str) and isinstance(raw.get("file"), str)
    ]
    return SpecIndex(documents=documents, requirements=requirements, assets=assets)


def _dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _page(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def write_index(index: SpecIndex) -> dict[str, Any]:
    """The module_data entry for this index — ``{}`` (remove the file) when it is empty."""
    data: dict[str, Any] = {}
    if index.documents:
        data["documents"] = [
            {
                "name": doc.name,
                "filename": doc.filename,
                "kind": doc.kind,
                "file": doc.file,
                **({"previous": doc.previous} if doc.previous else {}),
                "imported": doc.imported,
            }
            for doc in index.documents
        ]
    if index.requirements:
        data["requirements"] = [
            {
                "id": req.id,
                "document": req.document,
                "title": req.title,
                **({"quote": req.quote} if req.quote else {}),
                **({"page": req.page} if req.page is not None else {}),
            }
            for req in index.requirements
        ]
    if index.assets:
        data["assets"] = [
            {
                "id": asset.id,
                "file": asset.file,
                **({"document": asset.document} if asset.document else {}),
                **({"page": asset.page} if asset.page is not None else {}),
                "imported": asset.imported,
            }
            for asset in index.assets
        ]
    return stamped(data, DATA_FORMAT.version)


def binary_refusal(data: bytes, filename: str) -> str | None:
    """Why these bytes cannot be a spec document — None when they can.

    One sentence shared by both surfaces, so the dialog and the CLI cannot drift.
    """
    if document_kind(filename) == KIND_PDF:
        return None
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return (
            f"{filename} is neither a PDF nor UTF-8 text — "
            "a spec document has to be one or the other"
        )
    return None


def document_kind(filename: str) -> str:
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix == ".pdf":
        return KIND_PDF
    if suffix in (".md", ".markdown"):
        return KIND_MARKDOWN
    return KIND_TEXT


def default_name(filename: str) -> str:
    """The name a document gets when the caller does not choose one: a slug of the stem."""
    return slugify(PurePosixPath(filename).stem, fallback="document")


def blob_name(data: bytes, filename: str) -> str:
    return _addressed(DOCUMENTS_DIR, data, filename)


def attach_asset(area: ModuleFileArea, data: bytes, filename: str) -> str:
    """Put an image beside the spec documents; returns the path markdown links to."""
    name = _addressed(ASSETS_DIR, data, filename)
    area.write_bytes(name, data)
    return name


def _addressed(directory: str, data: bytes, filename: str) -> str:
    """Content-addressed so the same bytes land once and a pointer never churns."""
    suffix = PurePosixPath(filename).suffix.lower()
    return f"{directory}/{hashlib.sha256(data).hexdigest()[:16]}{suffix}"


def import_document(
    area: ModuleFileArea,
    documents: Sequence[SpecDocument],
    name: str,
    data: bytes,
    filename: str,
    today: str,
) -> tuple[list[SpecDocument], SpecDocument, str]:
    """Add ``name`` — or replace it, keeping the superseded blob for diffing.

    Returns the updated list, the document, and what happened: ``"added"``,
    ``"replaced"`` or ``"unchanged"`` (same bytes — nothing written).
    """
    blob = blob_name(data, filename)
    existing = next((doc for doc in documents if doc.name == name), None)
    if existing is not None and existing.file == blob:
        return list(documents), existing, "unchanged"
    area.write_bytes(blob, data)
    if document_kind(filename) == KIND_PDF:
        _write_text_layer(area, blob, data)
    if existing is None:
        document = SpecDocument(
            name=name,
            filename=filename,
            kind=document_kind(filename),
            file=blob,
            previous=None,
            imported=today,
        )
        return [*documents, document], document, "added"
    document = replace(
        existing,
        filename=filename,
        kind=document_kind(filename),
        file=blob,
        previous=existing.file,
        imported=today,
    )
    updated = [document if doc.name == name else doc for doc in documents]
    return updated, document, "replaced"


def _write_text_layer(area: ModuleFileArea, blob: str, data: bytes) -> None:
    """Extract and store a PDF's text beside it — the cache ``show``/``mark``/``diff``
    read first, named after the blob so it is derived, never pointed at. A file pdfium
    cannot parse does not fail the import: the read verbs extract in memory and will say
    what is wrong when actually asked for text."""
    from dplanner.modules.spec.pdf import text_blob_name, text_layer

    try:
        layer = text_layer(data)
    except Exception:  # pdfium raises its own hierarchy.
        return
    area.write_bytes(text_blob_name(blob), layer.encode("utf-8"))


def remove_document(
    documents: Sequence[SpecDocument],
    requirements: Sequence[Requirement],
    name: str,
) -> tuple[list[SpecDocument], list[Requirement], list[Requirement]]:
    """The index without ``name``, and the requirements that were marked in it.

    Returns (remaining documents, remaining requirements, dropped requirements). The blobs
    stay on disk — an orphan is recoverable where a dangling pointer is not (see the module
    docstring) — and step links to a dropped requirement dangle and read as absent, the same
    tolerance ``unmark`` relies on.
    """
    remaining = [doc for doc in documents if doc.name != name]
    kept = [req for req in requirements if req.document != name]
    dropped = [req for req in requirements if req.document == name]
    return remaining, kept, dropped


def matching_documents(documents: Sequence[SpecDocument], needle: str) -> list[SpecDocument]:
    """Exact name or filename first, then partial names — the caller decides how to refuse."""
    exact = [doc for doc in documents if needle in (doc.name, doc.filename)]
    if exact:
        return exact[:1]
    lowered = needle.lower()
    return [doc for doc in documents if lowered in doc.name.lower()]


def next_id(existing: Sequence[str], prefix: str) -> str:
    """The next free "<prefix>N" — requirements are "r1, r2, …", assets "a1, a2, …":
    ids a person can say out loud and an agent can guess the shape of."""
    numbers = [
        int(entry[len(prefix) :])
        for entry in existing
        if entry.startswith(prefix) and entry[len(prefix) :].isdigit()
    ]
    return f"{prefix}{max(numbers, default=0) + 1}"


def record_asset(
    assets: Sequence[SpecAsset], file: str, document: str, page: int | None, today: str
) -> tuple[list[SpecAsset], SpecAsset, str]:
    """Index an asset blob — or find it already indexed, since blobs are content-addressed.

    Returns the updated list, the entry, and ``"added"`` or ``"unchanged"``. The match is
    on (file, document, page): re-rendering the same page gives the same bytes and so the
    same file, and re-recording it must return the existing id rather than mint a new one.
    """
    existing = next(
        (
            asset
            for asset in assets
            if (asset.file, asset.document, asset.page) == (file, document, page)
        ),
        None,
    )
    if existing is not None:
        return list(assets), existing, "unchanged"
    asset = SpecAsset(
        id=next_id([asset.id for asset in assets], "a"),
        file=file,
        document=document,
        page=page,
        imported=today,
    )
    return [*assets, asset], asset, "added"


def linked_steps(project: Project, requirement_id: str) -> list[Step]:
    """Every step in ``project`` linked to this requirement — the "what is affected" query."""
    return [step for step in project.steps if requirement_id in read_links(step)]
