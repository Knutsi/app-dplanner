"""What an external document source hands back: the Qt-free vocabulary between a
*source kind* and the module that imports what it fetched.

A kind — a folder on this computer, a git repository, a Confluence page, a Confluence
folder — knows how to reach a place and turn what is there into documents; the spec module
knows how to keep documents beside a project. Neither may import the other, so what crosses
between them is written here, in ``domain/`` beside :mod:`dplanner.domain.assets` — the
same place the asset catalog's vocabulary lives, for the same reason.

Everything here is plain data. A kind's ``fetch`` builds a :class:`Snapshot`; the spec
module writes it. The kind names the images with :func:`dplanner.domain.assets.asset_name`
before the spec module writes them, so a markdown body links the very file the write will
produce — content addressing is what makes that a fact rather than a coincidence.
"""

from collections.abc import Mapping
from dataclasses import dataclass

# A kind's own address for a source, JSON-safe, opaque to the spec module — a Confluence
# page's is ``{"site": "https://acme.atlassian.net", "id": "12345", "type": "page"}``, a
# folder's ``{"path": "/home/knut/specs"}``. Re-validated on every read: a plan is shared.
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
    data: bytes  # The document as it should land: markdown, plain text or a PDF.
    # What it is called where it came from. Only the **suffix** is read — it is what says
    # whether this is markdown, text or a PDF; the spec module keeps its own minted name
    # as the stem, so a kind cannot rename every row of an existing plan by changing this.
    filename: str
    version: str  # The kind's stamp ("7"); compared for equality, never interpreted.
    # Where a person opens it — https only, validated by the kind. Nothing reads it yet;
    # a kind fills it in because only a kind can, and the surface that offers "open this
    # where it came from" is the one consumer to come.
    url: str = ""


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
    # Every key — fetched and kept — in the source's own order, parents before children;
    # empty means the fetched documents first, then the kept ones.
    order: tuple[str, ...] = ()

    def keys(self) -> tuple[str, ...]:
        if self.order:
            return self.order
        return (*(document.key for document in self.documents), *self.kept)


@dataclass(frozen=True)
class SourceStatus:
    """Whether a source can be fetched right now, and if not, why — the words beside a
    Connect button and a greyed verb's reason."""

    ready: bool
    message: str = ""
    # Whether the kind's ``connect`` can close *this* gap: a site not yet connected, a
    # token that expired. A malformed locator, a missing git, a kind this build does not
    # have are all not-ready and none of them is connectable — so the strip says the
    # message and offers no button, because a dialog about the wrong thing is worse than
    # no dialog. A status must claim it, which is why the default is False.
    connectable: bool = False


@dataclass(frozen=True)
class Freshness:
    """What a cheap check found, as keys — nothing was downloaded."""

    changed: tuple[str, ...] = ()
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()

    @property
    def stale(self) -> bool:
        return bool(self.changed or self.added or self.removed)


# Raster images only, told by their first bytes: an SVG is XML that can carry script, and
# nothing a spec needs is lost by leaving it out. One table, because two kinds sniffing
# differently would name one picture two ways.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
)


def raster_suffix(data: bytes) -> str | None:
    """The suffix these bytes are a raster image under, or None."""
    for magic, suffix in _MAGIC:
        if data.startswith(magic):
            return suffix
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


class SourceUnavailableError(Exception):
    """The source could not be read. The message is for a person, never carries a secret
    or a library's raw error; ``needs_reconnect`` says the credential itself was refused
    (an expired token) rather than the network or the page."""

    def __init__(self, message: str, *, needs_reconnect: bool = False) -> None:
        super().__init__(message)
        self.needs_reconnect = needs_reconnect
