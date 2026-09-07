"""What an external document source hands back: the Qt-free vocabulary between a
*source kind* and the module that imports what it fetched.

A kind (Confluence first; a wiki, a shared drive later) knows how to reach a system and
turn its pages into markdown; the spec module knows how to keep documents beside a
project. Neither may import the other, so what crosses between them is written here, in
``domain/`` beside :mod:`dplanner.domain.assets` — the same place the asset catalog's
vocabulary lives, for the same reason.

Everything here is plain data. A kind's ``fetch`` builds a :class:`Snapshot`; the spec
module writes it. The kind names the images with :func:`dplanner.domain.assets.asset_name`
before the spec module writes them, so a markdown body links the very file the write will
produce — content addressing is what makes that a fact rather than a coincidence.
"""

from collections.abc import Mapping
from dataclasses import dataclass

# A kind's own address for a source, JSON-safe, opaque to the spec module — Confluence's is
# ``{"site": "https://acme.atlassian.net", "id": "12345", "type": "page"}``.
type Locator = Mapping[str, str]


@dataclass(frozen=True)
class FetchedImage:
    """An image a fetched document links; ``filename`` carries the sniffed suffix."""

    data: bytes
    filename: str


@dataclass(frozen=True)
class FetchedDocument:
    key: str  # The kind's stable id for this page ("12345"); what a refresh matches on.
    parent_key: str  # "" for the root of the fetched tree.
    title: str
    markdown: str  # Images linked as assets/<sha16><suffix>, named by asset_name().
    version: str  # The kind's stamp ("7"); compared for equality, never interpreted.
    url: str  # Where a person opens it — https only, validated by the kind.


@dataclass(frozen=True)
class Snapshot:
    """One fetch of a source's tree.

    ``documents`` are the pages fetched — new or changed since the known versions;
    ``kept`` names the keys whose known version matched, so the importer keeps their rows
    and images without a body having crossed the wire (an unchanged page's images cannot
    be named without their bytes, which is the one reason this partition exists). A key in
    neither is gone from the source. ``notes`` says what was skipped and why.
    """

    documents: tuple[FetchedDocument, ...]
    kept: tuple[str, ...] = ()
    images: tuple[FetchedImage, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Freshness:
    """What a cheap check found, as keys — nothing was downloaded."""

    changed: tuple[str, ...] = ()
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()

    @property
    def stale(self) -> bool:
        return bool(self.changed or self.added or self.removed)


class SourceUnavailableError(Exception):
    """The source could not be read. The message is for a person, never carries a secret
    or a library's raw error; ``needs_reconnect`` says the credential itself was refused
    (an expired token) rather than the network or the page."""

    def __init__(self, message: str, *, needs_reconnect: bool = False) -> None:
        super().__init__(message)
        self.needs_reconnect = needs_reconnect
