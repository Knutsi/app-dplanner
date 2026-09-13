"""A directory of documents, read as a source snapshot.

Two source kinds want this walk: ``spec_folder``, over a folder on this computer, and
``spec_git``, over the checkout it made of a repository. Modules never import each other,
so the walk lives here — beside :mod:`dplanner.domain.document_source`, whose vocabulary
it speaks, for the reason ``AssetSource`` sits beside the asset catalog: a thing two
packages exchange that neither may own.

:func:`entries` + :func:`snapshot` + :func:`freshness` is deliberately the shape
``spec_confluence/source.py`` already has (the walk, the fetch, the check), so the kinds
read as one idea twice rather than as two inventions.

**A key is the path**, POSIX and relative to what was scanned (``design/auth.md``) —
stable across refreshes and machines, readable in ``spec list --json``, and a natural
parent. **A version is a content digest over the document and the pictures it shows**: a
diagram redrawn beside untouched text leaves a body digest still, and a document whose
version did not move is *kept* — it would go on showing the blob it linked last time.

**Nesting follows the directories, through their index documents.** A directory's
``README.md`` (or ``index.md``) is the document its siblings hang under; a directory with
none is transparent and passes its own parent down, so a tree with no index documents
lands exactly flat. That is what makes it safe: the rule can only add nesting where a
person already wrote the page that means it.

Deliberately not done: rewriting a link from one document to another (``[see](auth.md)``).
Only the spec module knows the names it mints, so a link between documents is left as the
author wrote it.
"""

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from dplanner.domain.assets import asset_name, image_references
from dplanner.domain.document_source import (
    FetchedDocument,
    FetchedImage,
    Freshness,
    Snapshot,
    SourceUnavailableError,
    raster_suffix,
)

# What is taken in. Markdown and text are read as UTF-8; a PDF rides as bytes, and the
# spec module's importer is what extracts its text layer — this walk decides *which files
# to pick up*, never what a file is, which is the importer's question and its suffix's.
PATTERNS: tuple[str, ...] = ("*.md", "*.markdown", "*.txt", "*.pdf")

# A directory's own page, if it has one: what its siblings hang under.
INDEX_NAMES: tuple[str, ...] = ("README.md", "readme.md", "index.md", "Index.md")

_MARKDOWN = (".md", ".markdown")
_HEADING = re.compile(r"^\s{0,3}#\s+(.+?)\s*#*\s*$", re.MULTILINE)


def is_document(relative: str) -> bool:
    """Whether this path is one this walk would take in.

    Exported because ``spec_git``'s ``check`` derives the very same key set from a git
    tree, without reading a byte. If the two rules could drift, a check would lie about
    every document in the gap.
    """
    name = PurePosixPath(relative).name
    if not name or any(part.startswith(".") for part in PurePosixPath(relative).parts):
        return False
    return any(PurePosixPath(name).match(pattern) for pattern in PATTERNS)


@dataclass(frozen=True)
class FolderScan:
    """A directory read as a document source: where it is, which part of it, and the caps
    that keep one fetch bounded."""

    root: Path  # Absolute. Nothing outside it is ever read.
    subdirectory: str = ""  # POSIX, relative to root — the part of a repository to import.
    max_documents: int = 500  # The Confluence walk's MAX_PAGES.
    max_depth: int = 20
    max_file_bytes: int = 20 * 1024 * 1024
    max_total_bytes: int = 200 * 1024 * 1024  # The Confluence walk's MAX_FETCH_BYTES.

    @property
    def base(self) -> Path:
        return self.root / self.subdirectory if self.subdirectory else self.root


@dataclass(frozen=True)
class FolderEntry:
    """One document found by the walk, before its body has been handed over."""

    key: str  # POSIX, relative to the scan's base.
    parent_key: str  # The index document above it; "" at the top.
    title: str
    version: str
    path: Path = field(repr=False, default=Path())


def entries(
    scan: FolderScan,
    notes: list[str],
    cancelled: Callable[[], bool] = lambda: False,
) -> list[FolderEntry]:
    """Every document under ``scan``, parents before children, in reading order.

    ``notes`` gathers what was left out and why — one sentence each, the way the
    Confluence walk words its skips. What cannot stand at all raises instead.
    """
    base = _base(scan)
    found: list[FolderEntry] = []
    total = 0
    for directory, parent_key, index_name in _directories(scan, base, notes, cancelled):
        here = _index_key(base, directory, index_name) if index_name else parent_key
        for path in _files(directory, index_name):
            if cancelled():
                raise SourceUnavailableError("cancelled")
            if len(found) >= scan.max_documents:
                notes.append(f"more than {scan.max_documents} documents — the rest were left out")
                return found
            key = _key(base, path)
            data = _read(path, scan, key, notes)
            if data is None:
                continue
            images = _linked_images(path, data, key, scan, notes)
            total += len(data) + sum(len(image.data) for _reference, image in images)
            if total > scan.max_total_bytes:
                raise SourceUnavailableError(
                    f"this folder carries more than {scan.max_total_bytes // (1024 * 1024)} MB "
                    "— point the source at a subdirectory"
                )
            is_index = path.name == index_name
            found.append(
                FolderEntry(
                    key=key,
                    parent_key=parent_key if is_index else here,
                    title=_title(path, data),
                    version=_version(data, images),
                    path=path,
                )
            )
    return found


def snapshot(
    scan: FolderScan,
    known: Mapping[str, str],
    progress: Callable[[float], None] = lambda _f: None,
    cancelled: Callable[[], bool] = lambda: False,
) -> Snapshot:
    """What the folder holds now: bodies for what is new or changed, keys for what is not."""
    notes: list[str] = []
    found = entries(scan, notes, cancelled)
    documents: list[FetchedDocument] = []
    images: list[FetchedImage] = []
    kept: list[str] = []
    seen: set[str] = set()
    for position, entry in enumerate(found):
        if cancelled():
            raise SourceUnavailableError("cancelled")
        progress(position / max(len(found), 1))
        if known.get(entry.key) == entry.version:
            kept.append(entry.key)
            continue
        data = entry.path.read_bytes()
        linked = _linked_images(entry.path, data, entry.key, scan, [])
        for _reference, image in linked:
            name = asset_name(image.data, image.filename)
            if name not in seen:
                seen.add(name)
                images.append(image)
        documents.append(
            FetchedDocument(
                key=entry.key,
                parent_key=entry.parent_key,
                title=entry.title,
                data=_relinked(data, linked),
                filename=PurePosixPath(entry.key).name,
                version=entry.version,
            )
        )
    progress(1.0)
    return Snapshot(
        documents=tuple(documents),
        kept=tuple(kept),
        images=tuple(images),
        notes=tuple(notes),
        order=tuple(entry.key for entry in found),
    )


def freshness(scan: FolderScan, known: Mapping[str, str]) -> Freshness:
    """What changed since ``known`` — digests only; no body is handed over."""
    current = {entry.key: entry.version for entry in entries(scan, [])}
    return Freshness(
        changed=tuple(key for key in current if key in known and current[key] != known[key]),
        added=tuple(key for key in current if key not in known),
        removed=tuple(key for key in known if key not in current),
    )


# -- the walk ------------------------------------------------------------------------------------


def _base(scan: FolderScan) -> Path:
    base = scan.base
    if not base.is_dir():
        raise SourceUnavailableError(f"{base} is not a folder on this computer")
    return base.resolve()


def _directories(
    scan: FolderScan,
    base: Path,
    notes: list[str],
    cancelled: Callable[[], bool],
) -> list[tuple[Path, str, str]]:
    """Every directory under ``base``, depth-first: the directory, the key its own index
    document hangs under, and the name of that index document.

    A directory's index document is the parent of everything beside and below it; a
    directory without one passes down whatever it was given, so the rule adds nesting only
    where somebody wrote the page that means it.
    """
    walk: list[tuple[Path, str, str]] = []
    seen: set[Path] = set()

    def descend(directory: Path, parent_key: str, depth: int) -> None:
        if cancelled():
            raise SourceUnavailableError("cancelled")
        resolved = directory.resolve()
        if resolved in seen:  # A symlink pointing back up would otherwise walk forever.
            return
        seen.add(resolved)
        index_name = _index_name(directory)
        walk.append((directory, parent_key, index_name))
        here = _index_key(base, directory, index_name) if index_name else parent_key
        for child in sorted(_children(directory), key=lambda path: path.name.casefold()):
            if not _inside(child, base):
                notes.append(f"{_key(base, child)}: a symlink out of the folder, left out")
                continue
            if depth >= scan.max_depth:
                notes.append(f"{_key(base, child)}: deeper than {scan.max_depth} levels")
                continue
            descend(child, here, depth + 1)

    descend(base, "", 0)
    return walk


def _children(directory: Path) -> list[Path]:
    try:
        return [path for path in directory.iterdir() if path.is_dir() and not _hidden(path)]
    except OSError:
        return []


def _files(directory: Path, index_name: str) -> list[Path]:
    """The directory's own documents: its index document first, then the rest by name."""
    try:
        found = [
            path
            for path in directory.iterdir()
            if path.is_file() and not _hidden(path) and is_document(path.name)
        ]
    except OSError:
        return []
    found.sort(key=lambda path: path.name.casefold())
    lead = [path for path in found if path.name == index_name]
    return lead + [path for path in found if path.name != index_name]


def _index_name(directory: Path) -> str:
    for name in INDEX_NAMES:
        if (directory / name).is_file():
            return name
    return ""


def _index_key(base: Path, directory: Path, index_name: str) -> str:
    return _key(base, directory / index_name)


def _hidden(path: Path) -> bool:
    return path.name.startswith(".")


def _inside(path: Path, base: Path) -> bool:
    try:
        return path.resolve().is_relative_to(base)
    except OSError:
        return False


def _key(base: Path, path: Path) -> str:
    try:
        return PurePosixPath(path.resolve().relative_to(base)).as_posix()
    except (OSError, ValueError):
        return path.name


# -- one document ---------------------------------------------------------------------------------


def _read(path: Path, scan: FolderScan, key: str, notes: list[str]) -> bytes | None:
    try:
        size = path.stat().st_size
    except OSError:
        notes.append(f"{key}: could not be read")
        return None
    if size > scan.max_file_bytes:
        # The Confluence kind's words for the same skip: the cap is the application's, not
        # something the person chose, so naming it teaches nothing.
        notes.append(f"{key}: larger than the cap and was left out")
        return None
    try:
        data = path.read_bytes()
    except OSError:
        notes.append(f"{key}: could not be read")
        return None
    if not _is_pdf(key):
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            notes.append(f"{key}: not UTF-8 text and was left out")
            return None
    return data


def _title(path: Path, data: bytes) -> str:
    """The first heading of a markdown body, else the file's stem."""
    if _is_markdown(path.name):
        heading = _HEADING.search(data.decode("utf-8", "replace"))
        if heading is not None and heading.group(1).strip():
            return heading.group(1).strip()
    return path.stem


def _linked_images(
    path: Path, data: bytes, key: str, scan: FolderScan, notes: list[str]
) -> list[tuple[str, FetchedImage]]:
    """The pictures a markdown body shows, as (what it wrote, the file read from beside it).

    The reference is carried because a skipped picture must not shift the ones after it:
    the rewrite pairs each link with its own bytes, never by position.
    """
    if not _is_markdown(key):
        return []
    base = scan.base.resolve()
    found: list[tuple[str, FetchedImage]] = []
    for reference in image_references(data.decode("utf-8", "replace")):
        if reference.startswith("assets/"):
            continue  # Already an area path: somebody's export, not a file beside this one.
        target = (path.parent / reference).resolve()
        if not _inside(target, base) or not target.is_file():
            notes.append(f"{key}: image {reference} is not in the folder")
            continue
        blob = target.read_bytes()
        if len(blob) > scan.max_file_bytes:
            notes.append(f"{key}: image {reference} is larger than the cap and was left out")
            continue
        suffix = raster_suffix(blob)
        if suffix is None:
            notes.append(f"{key}: image {reference} is not a raster image and was left out")
            continue
        found.append((reference, FetchedImage(data=blob, filename=f"image{suffix}")))
    return found


def _relinked(data: bytes, images: Sequence[tuple[str, FetchedImage]]) -> bytes:
    """The body with every picture it showed pointing at the area path it will land in."""
    if not images:
        return data
    names = {reference: asset_name(image.data, image.filename) for reference, image in images}
    body = data.decode("utf-8")

    def link(match: re.Match[str]) -> str:
        name = names.get(match.group(1))
        return match.group(0) if name is None else match.group(0).replace(match.group(1), name)

    return _EMBED.sub(link, body).encode("utf-8")


_EMBED = re.compile(r"!\[[^\]]*\]\(\s*([^)\s]+)")


def _version(data: bytes, images: Sequence[tuple[str, FetchedImage]]) -> str:
    """The digest of the document *and* the pictures it shows.

    The body alone would leave a document unchanged when a diagram beside it was redrawn:
    its version would not move, the fetch would keep the old row, and the page would go on
    showing a picture that is no longer there.
    """
    digest = hashlib.sha256(data)
    for _reference, image in images:
        digest.update(hashlib.sha256(image.data).digest())
    return digest.hexdigest()[:16]


def _is_markdown(name: str) -> bool:
    return PurePosixPath(name).suffix.lower() in _MARKDOWN


def _is_pdf(name: str) -> bool:
    return PurePosixPath(name).suffix.lower() == ".pdf"
