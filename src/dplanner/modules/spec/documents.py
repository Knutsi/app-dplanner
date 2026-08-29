"""The project half of the spec module: the document index and the requirements.

The JSON entry beside the project (``modules/spec.json``) holds only pointers and names;
the document bytes live in the module's file area, content-addressed like a description's
images. That split is what makes a replace safe to undo: the index edit goes through a
command on the undo stack, and both the new and the previous blob stay on disk, so a
restored index always finds its file. The cost is that an orphaned blob is never pruned —
acceptable, because an orphan is recoverable where a dangling pointer is not, and the
workspace's own VCS is the real history. The one carve-out is the in-app editor's idle
flushes: an intermediate blob that a single editing session wrote and then superseded is
churn, not history, and :func:`prune_blob` removes it once nothing in the index names it.

Everything here is Qt-free and shared verbatim by ``cli.py`` and the Specs tab, so the two
surfaces cannot disagree about what a document or a requirement is.
"""

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import Any

from dplanner.cli.command import CliError
from dplanner.core.fsio import slugify
from dplanner.core.module_data import stamped
from dplanner.domain.assets import attach
from dplanner.domain.model import Project, Step
from dplanner.domain.store import FilesFor, ModuleFileArea
from dplanner.modules.spec.aspect import (
    DATA_FORMAT,
    MODULE_ID,
    SpecAttachment,
    read_attachments,
    read_links,
)
from dplanner.modules.spec.pdf import find_quote_pages, text_blob_name
from dplanner.modules.spec.pdf import text_layer as extract_text_layer

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


def new_document(
    area: ModuleFileArea,
    documents: Sequence[SpecDocument],
    title: str,
    today: str,
    *,
    name: str = "",
) -> tuple[list[SpecDocument], SpecDocument]:
    """A fresh markdown document seeded with ``# <title>`` — refuses a taken name.

    Shared by ``spec new`` and the Specs tab's New Spec Document, so both surfaces mint
    the same seed and refuse the same duplicates.
    """
    chosen = name or slugify(title, fallback="document")
    if any(doc.name == chosen for doc in documents):
        raise CliError(
            f"a spec document named {chosen!r} already exists — pick another title"
        )
    docs, document, _outcome = import_document(
        area, documents, chosen, f"# {title}\n".encode(), f"{chosen}.md", today
    )
    return docs, document


def save_body(
    area: ModuleFileArea,
    documents: Sequence[SpecDocument],
    session_base: SpecDocument,
    data: bytes,
    today: str,
) -> tuple[list[SpecDocument], SpecDocument, str, str | None]:
    """Replace ``session_base``'s body mid-editing-session — one session, one replace.

    However many idle flushes a session makes, ``previous`` stays pinned to the blob that
    was current when editing began, so `spec diff` answers "what did this session change",
    not "what did the last keystroke burst change". A body typed back to its starting
    bytes restores the base record exactly, un-doing the replace.

    Returns the updated list, the document, ``"saved"`` or ``"unchanged"``, and the
    superseded blob this session itself wrote (the caller may prune it) — None when the
    superseded blob predates the session.
    """
    existing = next((doc for doc in documents if doc.name == session_base.name), None)
    if existing is None:
        raise CliError(f"{session_base.name!r} is no longer in the spec index")
    blob = blob_name(data, session_base.filename)
    if blob == existing.file:
        return list(documents), existing, "unchanged", None
    superseded = existing.file if existing.file != session_base.file else None
    if blob == session_base.file:
        document = session_base  # The session's net change is nothing; restore the record.
    else:
        area.write_bytes(blob, data)
        document = replace(existing, file=blob, previous=session_base.file, imported=today)
    updated = [document if doc.name == document.name else doc for doc in documents]
    return updated, document, "saved", superseded


def prune_blob(area: ModuleFileArea, documents: Sequence[SpecDocument], blob: str) -> None:
    """Remove ``blob`` unless any document's file or previous still names it.

    Content-addressed names mean two documents can share a blob, so both fields of every
    document are checked. Only an editing session's own intermediates belong here — the
    module docstring's orphan rule stands for everything else.
    """
    if any(blob in (doc.file, doc.previous) for doc in documents):
        return
    area.remove(blob)


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


def referenced_assets(
    assets: Sequence[SpecAsset], body: str, today: str
) -> list[SpecAsset]:
    """The asset list with an entry for every ``assets/…`` file ``body`` links to.

    An image pasted into the in-app editor lands in the file area without passing through
    ``spec attach``; recording it at save time is what keeps `spec assets` and
    `attach-to-step` able to see it. Matching is by file alone — a blob already indexed,
    however it got there, is never re-minted.
    """
    known = {asset.file for asset in assets}
    updated = list(assets)
    for file in dict.fromkeys(re.findall(r"\]\((assets/[^)\s]+)\)", body)):
        if file not in known:
            updated, _asset, _outcome = record_asset(updated, file, "", None, today)
    return updated


def linked_steps(project: Project, requirement_id: str) -> list[Step]:
    """Every step in ``project`` linked to this requirement — the "what is affected" query."""
    return [step for step in project.steps if requirement_id in read_links(step)]


# -- reading, anchoring and copying: the shared half of the verbs -----------------------------
# Called by the verbs, by ``lint_checks()`` and by ``step_author()`` — user-facing
# refusals, so they raise CliError (Qt-free, like everything here).


def blob_bytes(area: ModuleFileArea, document: SpecDocument, blob: str) -> bytes:
    data = area.read_bytes(blob)
    if data is None:
        raise CliError(f"{document.name}: {blob} is missing from the workspace")
    return data


def document_text(area: ModuleFileArea, document: SpecDocument) -> str | None:
    """The text a quote can anchor in — a PDF's layer, prose decoded — or None when the
    file is missing or the PDF unreadable. None means "cannot check", never "failed"."""
    try:
        if document.kind == KIND_PDF:
            return layer_from(area, document, document.file)
        return blob_bytes(area, document, document.file).decode("utf-8")
    except CliError:
        return None


def quote_anchors(text: str, quote: str, kind: str) -> tuple[bool, list[int]]:
    """Whether a quote appears in a document's text, and on which pages for a PDF —
    every page, because the same sentence can recur and ``--page`` naming any
    occurrence is right.

    One implementation for ``spec mark`` and ``project lint``, so the mark that passed
    can never be the requirement lint flags — or the other way round.
    """
    if kind == KIND_PDF:
        pages = find_quote_pages(text, quote)
        return bool(pages), pages
    normalized = " ".join(quote.lower().split())
    return normalized in " ".join(text.lower().split()), []


def layer_from(area: ModuleFileArea, document: SpecDocument, blob: str) -> str:
    """The text layer: the file import wrote, or extracted in memory for a document
    imported before layers existed — a read verb never writes."""
    stored = area.read_bytes(text_blob_name(blob))
    if stored is not None:
        return stored.decode("utf-8")
    data = blob_bytes(area, document, blob)
    try:
        return extract_text_layer(data)
    except Exception as error:  # pdfium raises its own hierarchy.
        raise CliError(
            f"{document.name}: could not extract text ({error}) — read the original "
            f"from `dplanner spec path`"
        ) from error


def some(noun: str, ids: Sequence[str]) -> str:
    """"asset 'a1'" or "assets 'a1', 'a2'" — refusals read the same at any count."""
    listed = ", ".join(repr(entry) for entry in ids)
    return f"{noun}{'s' if len(ids) != 1 else ''} {listed}"


def linked_ids(project: Project, step: Step, ids: Sequence[str]) -> list[str]:
    """The step's links with ``ids`` added — refusing every unknown id in one message,
    before anything is written. Shared by ``spec link`` and ``step add --link``."""
    known = {req.id for req in read_index(project).requirements}
    unknown = [entry for entry in ids if entry not in known]
    if unknown:
        raise CliError(
            f"no {some('requirement', unknown)} in {project.title!r} — "
            "see `dplanner spec requirements`"
        )
    links = read_links(step)
    return [*links, *[entry for entry in ids if entry not in links]]


def copied_to_step(
    files: FilesFor, project: Project, step: Step, asset_ids: Sequence[str]
) -> tuple[list[SpecAttachment], list[str]]:
    """Copy each asset's blob beside the step; the updated attachments and copied names.

    Copied, not referenced: the step stays self-contained if the project's spec — or the
    whole asset — is later removed, and the briefing gets a real file. Every id is
    resolved and every blob read before the first copy, so a bad id refuses the batch.
    Shared by ``spec attach-to-step`` and ``step add --attach``.
    """
    index = read_index(project)
    by_id = {asset.id: asset for asset in index.assets}
    missing = [entry for entry in asset_ids if entry not in by_id]
    if missing:
        raise CliError(
            f"no {some('asset', missing)} in {project.title!r} — see `dplanner spec assets`"
        )
    project_area = files(project.id, MODULE_ID)
    blobs: dict[str, bytes] = {}
    for asset_id in asset_ids:
        data = project_area.read_bytes(by_id[asset_id].file)
        if data is None:
            raise CliError(f"{asset_id}: {by_id[asset_id].file} is missing from the workspace")
        blobs[asset_id] = data
    attachments = read_attachments(step)
    copied: list[str] = []
    step_area = files(step.id, MODULE_ID)
    for asset_id in asset_ids:
        asset = by_id[asset_id]
        file = attach(step_area, blobs[asset_id], PurePosixPath(asset.file).name)
        copied.append(file)
        if not any(entry.asset == asset_id for entry in attachments):
            attachments = [
                *attachments,
                SpecAttachment(
                    file=file, document=asset.document, page=asset.page, asset=asset_id
                ),
            ]
    return attachments, copied
