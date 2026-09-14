"""Content-addressed files in a module's file area.

Shared by every aspect that keeps files beside a node — descriptions with images, notes
with reference material. Files are named by the hash of their content, so attaching the same
file twice is a no-op and a rename upstream never churns a link. The suffix is kept because
a browser and a person both use it to tell what the file is.

An asset add is not undoable, and that is the honest trade: undoing a paste would leave
prose pointing at a file that had gone. An orphaned blob is recoverable; a dangling link
is not.

In the middle is what *prose* says about a file: which assets a document links,
and — for a picture — which part of it the reader is meant to act on (:class:`ClickTarget`).

The last part of this file is the asset *catalog*: the vocabulary a module uses to say
which files it keeps and what still uses each — one derivation with three readers (the
Assets tab, ``dplanner asset list``, ``asset prune``). The catalog is computed on every
read and never stored; a module contributes an :class:`AssetSource` from its Qt-free half
and the composition root assembles the tuple, exactly as lint checks arrive.
"""

import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

from dplanner.domain.model import Library, NodeId, Project
from dplanner.domain.shelf import shelved_text
from dplanner.domain.store import FilesFor, ModuleFileArea

ASSETS_DIR = "assets"


def asset_name(data: bytes, filename: str) -> str:
    """``assets/<hash><suffix>`` — the path to reference from prose in the same module."""
    suffix = PurePosixPath(filename).suffix.lower()
    return f"{ASSETS_DIR}/{hashlib.sha256(data).hexdigest()[:16]}{suffix}"


def attach(area: ModuleFileArea, data: bytes, filename: str) -> str:
    """Put a file in the module's area; returns the path to link to."""
    name = asset_name(data, filename)
    area.write_bytes(name, data)
    return name


def assets(area: ModuleFileArea) -> list[str]:
    """Every asset the area holds, sorted, as area-relative paths."""
    return sorted(f"{ASSETS_DIR}/{name}" for name in area.names(ASSETS_DIR))


def area_assets(files: FilesFor, node_id: NodeId, module_id: str) -> list[str]:
    """Every asset beside a node — and none for a node the store has never flushed.

    The ``KeyError`` tolerance in one place, because every :class:`AssetSource` scan needs
    it: a step created this run has no directory yet, and that is an empty area, not an
    error.
    """
    try:
        area = files(node_id, module_id)
    except KeyError:
        return []
    return assets(area)


# -- what prose says about a file: which ones, and where on one to act ------------------------

_ASSET_REFERENCE = re.compile(r"\]\(\s*(assets/[^)\s]+)\s*\)")


def asset_references(markdown: str) -> list[str]:
    """Every area-relative asset path the markdown links to, in order, deduplicated.

    Both link forms, because :meth:`ProseEdit._link` writes ``![alt](assets/…)`` for an
    image and ``[name](assets/…)`` for anything else. The one definition of what a
    reference is, shared by the spec index and the asset catalog, so no two scanners can
    disagree. (:func:`image_references` answers a different question — any relative
    *image* embed, whatever it points at — for the dangling-link lints.)

    A ``#…`` fragment is taken off: what follows the hash says which *part* of the file is
    meant (:func:`click_targets`), and a catalog that read it as part of the name would
    count one attachment as two and offer a used one for pruning.
    """
    found = (without_fragment(ref) for ref in _ASSET_REFERENCE.findall(markdown))
    return list(dict.fromkeys(found))


_IMAGE_REFERENCE = re.compile(r"!\[[^\]]*\]\(\s*([^)\s]+)")


def image_references(markdown: str) -> list[str]:
    """The area-relative image paths the markdown embeds — ``![](assets/…)``.

    External URLs and absolute paths are not a module's files and are skipped. Written
    here, beside the store the paths point into, so the lint checks and any renderer
    cannot disagree about what an embed is — two aspects had already grown identical
    copies of it before it moved.
    """
    found = _IMAGE_REFERENCE.findall(markdown)
    local = [ref for ref in found if "://" not in ref and not ref.startswith("/")]
    return [without_fragment(ref) for ref in local]


# -- click targets: where on a picture the reader is meant to act ------------------------------

# ``assets/<hash>.png#click=120,340,80,32`` — the area of the picture a step of a test
# means, in the image's own pixels, several separated by ``;``. A fragment because that is
# what a fragment is for everywhere else: the file is the file, and what follows the ``#``
# says which part of it is being pointed at. Nothing on disk changes, no reader that does
# not know the syntax breaks, and a link that carries one still names exactly one asset —
# which is why the two scanners above strip it before they answer.
_CLICK_TARGET = re.compile(r"click=(-?\d+),(-?\d+),(\d+),(\d+)")


@dataclass(frozen=True)
class ClickTarget:
    """A rectangle on a picture, in the picture's own pixels.

    An agent that drove the screen knows where the button was; a person writing a test by
    hand does not, and never has to — a picture with no target is the ordinary case and the
    only thing a target adds is a ring drawn round the spot.
    """

    x: int
    y: int
    width: int
    height: int


def click_targets(reference: str) -> tuple[ClickTarget, ...]:
    """The targets a link's fragment marks, in the order they were written.

    Read from the whole reference rather than from a fragment the caller split off, so
    there is one place that knows the spelling.
    """
    _name, _, fragment = reference.partition("#")
    return tuple(
        ClickTarget(int(x), int(y), int(width), int(height))
        for x, y, width, height in _CLICK_TARGET.findall(fragment)
    )


def target_fragment(targets: Sequence[ClickTarget]) -> str:
    """The fragment for ``targets`` — ``""`` for none, so a caller can concatenate it."""
    if not targets:
        return ""
    return "#" + ";".join(f"click={t.x},{t.y},{t.width},{t.height}" for t in targets)


def without_fragment(reference: str) -> str:
    """The asset a reference names, with any ``#…`` taken off."""
    return reference.partition("#")[0]


def targets_by_asset(markdown: str) -> dict[str, tuple[ClickTarget, ...]]:
    """Every asset the markdown marks, and what it marks on it.

    A picture linked twice — once plain, once with a target — is one asset with one set of
    targets: the union in writing order, because both links are about the same file and a
    reader shown one of the two would be shown the wrong one half the time.
    """
    found: dict[str, tuple[ClickTarget, ...]] = {}
    for reference in _IMAGE_REFERENCE.findall(markdown):
        if "://" in reference or reference.startswith("/"):
            continue
        name = without_fragment(reference)
        marks = tuple(dict.fromkeys(found.get(name, ()) + click_targets(reference)))
        if marks or name not in found:
            found[name] = marks
    return found


# -- the catalog: what exists, and what still uses it -----------------------------------------


@dataclass(frozen=True)
class AssetUse:
    """One thing that still needs an asset — a row in the browser's "used by" list."""

    subject_kind: str  # "step" | "project" — what the use belongs to; drives navigation.
    subject_id: NodeId
    subject: str  # The subject's title, so a report needs no second lookup.
    where: str  # "description", "test T101 — Rejects an empty query", "spec figure a2", …


@dataclass(frozen=True)
class AssetLocation:
    """One copy: a file in one node's module area, and what references it there.

    Empty ``uses`` means nothing would miss this copy — the same bytes may still be
    referenced from *another* area, which is why pruning is per-location.
    """

    node_id: NodeId
    module_id: str
    name: str  # Area-relative: assets/<sha256[:16]><suffix>.
    uses: tuple[AssetUse, ...]


# One scan per contributing module: every copy its areas hold, with that module's own
# answer to "what uses this". Deliberately the LintCheck three-argument shape.
AssetScan = Callable[[Library, Project, FilesFor], Sequence[AssetLocation]]


@dataclass(frozen=True)
class AssetSource:
    """One module's contribution to the catalog, assembled by the composition root."""

    id: str  # The owning module id — the browser's and ``--source``'s filter key.
    label: str  # "Descriptions", "Tests", "Spec figures", …
    scan: AssetScan
    # False: unused copies here are kept on purpose — the pool stages images *before*
    # anything uses them, so a sweep must not treat staging as neglect.
    prunable: bool = True


@dataclass(frozen=True)
class AssetEntry:
    """One distinct content, wherever it lives — the browser's row and ``asset list``'s.

    Identical bytes carry the same content-addressed name in every area, so grouping by
    name is grouping by content; the entry's locations are the copies.
    """

    name: str
    locations: tuple[tuple[AssetSource, AssetLocation], ...]

    @property
    def unused(self) -> bool:
        return all(not location.uses for _source, location in self.locations)

    @property
    def uses(self) -> tuple[AssetUse, ...]:
        return tuple(use for _source, location in self.locations for use in location.uses)


def catalog(
    library: Library, project: Project, files: FilesFor, sources: Sequence[AssetSource]
) -> list[AssetEntry]:
    """Every asset the project carries, grouped by content name — derived on every read.

    Never stored: ``dplanner test attach`` changes an area with no window running to
    notice, and a stored answer would only ever be the last reader's.
    """
    grouped: dict[str, list[tuple[AssetSource, AssetLocation]]] = {}
    for source in sources:
        for location in source.scan(library, project, files):
            grouped.setdefault(location.name, []).append(
                (source, _with_shelved_use(library, location))
            )
    return [
        AssetEntry(name=name, locations=tuple(locations))
        for name, locations in sorted(grouped.items())
    ]


def _with_shelved_use(library: Library, location: AssetLocation) -> AssetLocation:
    """A file the module's *shelved* prose links is still in use.

    A source scans what its aspect holds now; an aspect turned off holds nothing, and its
    prose sits on the shelf with the links intact. Marking those here, once, is what keeps
    ``asset prune`` from sweeping away a picture the next toggle-on would bring back to.
    """
    node = library.node(location.node_id)
    if location.name not in asset_references(shelved_text(node, location.module_id)):
        return location
    use = AssetUse(node.kind, node.id, getattr(node, "title", ""), f"{location.module_id} (off)")
    return replace(location, uses=(*location.uses, use))


def prunable(entries: Sequence[AssetEntry]) -> list[tuple[AssetSource, AssetLocation]]:
    """The copies a sweep may remove: unused, and from a source that allows sweeping.

    The one computation ``asset prune`` and the browser's Clean Up share, so the dry run,
    the deletion and the button can never disagree about what would go.
    """
    return [
        (source, location)
        for entry in entries
        for source, location in entry.locations
        if source.prunable and not location.uses
    ]
