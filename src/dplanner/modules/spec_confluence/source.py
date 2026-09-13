"""The Confluence source: a pasted URL to a locator, a locator to a snapshot, and the
caps that keep a fetch bounded.

``fetch`` walks the tree under a page or a folder breadth-first through the client's
children listings, asks for every page's current version in bulk, then downloads the
body and the referenced images of each page whose version is new — a page whose version
the caller already knows goes into ``Snapshot.kept`` without a byte crossing the wire.
``check`` is the same walk without bodies. Both take a client the module built with the
person's credentials; nothing here reads a keychain.

**Two kinds, one walk.** A *Confluence page* source and a *Confluence folder* source are
two entries in the Add Spec menu and two ``kind`` ids in the index, and what differs
between them is a :class:`ContentType` record — the words, and which address is accepted.
The walk itself stays one function: a page root is a document and seeds the queue, a
folder root only seeds it, which is one branch on a value the kind has just validated,
not a second code path. ``expected`` is that validation: it is what refuses a folder
address pasted into the page kind, and what stops a hand-edited plan aiming one kind at
the other's locator.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import SplitResult, parse_qs, urlsplit

from dplanner.domain.assets import asset_name
from dplanner.domain.document_source import (
    FetchedDocument,
    FetchedImage,
    Freshness,
    Locator,
    Snapshot,
    SourceUnavailableError,
    raster_suffix,
)
from dplanner.modules.spec_confluence.client import (
    ChildRow,
    ConfluenceClient,
    TooLargeError,
    is_cloud_site,
)
from dplanner.modules.spec_confluence.convert import attachment_names, convert

MAX_PAGES = 500
MAX_DEPTH = 20
MAX_FETCH_BYTES = 200 * 1024 * 1024

_PAGE_URL = re.compile(r"^/wiki/spaces/([A-Za-z0-9~._-]+)/pages/(\d+)(?:/([^/?#]*))?/?$")
_FOLDER_URL = re.compile(r"^/wiki/spaces/([A-Za-z0-9~._-]+)/folder/(\d+)/?$")
_SPACE_KEY = re.compile(r"^[A-Za-z0-9~._-]+$")
_VIEWPAGE = re.compile(r"^/wiki/pages/viewpage\.action$")
_SHORT = re.compile(r"^/wiki/x/")


@dataclass(frozen=True)
class ContentType:
    """What differs between a Confluence *page* source and a *folder* source: the id the
    index records, the words a person reads, and which of the two addresses is accepted."""

    type: str  # "page" | "folder" — the locator's own key, re-validated on every read.
    kind_id: str  # What a source record's ``kind`` says: the spec module's dispatch.
    noun: str  # "page" | "folder" — how a refusal names what was pasted.
    label: str  # The Add Spec entry.
    title: str  # The dialog's window title.
    caption: str  # Over the address field.
    placeholder: str


PAGE = ContentType(
    type="page",
    kind_id="confluence_page",
    noun="page",
    label="&Confluence Page…",
    title="Add Confluence Page",
    caption="The address of a Confluence page, as copied from the browser",
    placeholder="https://acme.atlassian.net/wiki/spaces/SPEC/pages/12345/Auth",
)
FOLDER = ContentType(
    type="folder",
    kind_id="confluence_folder",
    noun="folder",
    label="Confluence F&older…",
    title="Add Confluence Folder",
    caption="The address of a Confluence folder, as copied from the browser",
    placeholder="https://acme.atlassian.net/wiki/spaces/SPEC/folder/12345",
)
OTHER = {PAGE.type: FOLDER, FOLDER.type: PAGE}


def parse_url(text: str, expected: str) -> tuple[str, Locator]:
    """An address as copied from the browser → (title hint, locator), for the one content
    type ``expected`` names.

    ``ValueError`` carries the one sentence a dialog shows for what cannot be read —
    including the address that names the *other* kind, which is the refusal the split
    exists to make possible.
    """
    parts = urlsplit(text.strip())
    site = f"{parts.scheme}://{parts.netloc}".lower()
    if not is_cloud_site(site):
        raise ValueError("paste an address from a *.atlassian.net site")
    if _SHORT.match(parts.path):
        raise ValueError(
            "that is a short link — open the page and copy the address with /pages/ in it"
        )
    found = _address(parts)
    if found is None:
        raise ValueError("that address does not name a Confluence page or folder")
    content, content_id, space, slug = found
    if content.type != expected:
        other = OTHER[expected]
        raise ValueError(
            f"that is a {content.noun} address — add it with Add Spec ▸ {_plain(other.label)}"
        )
    locator = {"site": site, "id": content_id, "type": content.type}
    if space:
        locator["space"] = space
    return slug or f"{content.noun.capitalize()} {content_id}", locator


def _address(parts: SplitResult) -> tuple[ContentType, str, str, str] | None:
    """(content type, id, space key, title hint) for the three addresses we read."""
    page = _PAGE_URL.match(parts.path)
    if page is not None:
        slug = (page.group(3) or "").replace("+", " ").replace("-", " ").strip()
        return PAGE, page.group(2), page.group(1), slug
    folder = _FOLDER_URL.match(parts.path)
    if folder is not None:
        return FOLDER, folder.group(2), folder.group(1), ""
    if _VIEWPAGE.match(parts.path):
        page_id = parse_qs(parts.query).get("pageId", [""])[0]
        if page_id.isdigit():
            return PAGE, page_id, "", ""
    return None


def _plain(label: str) -> str:
    """A menu label without its mnemonic, for a sentence that quotes it."""
    return label.replace("&", "").rstrip("…").strip()


def valid_locator(locator: Mapping[str, object], expected: str) -> Locator | None:
    """The locator as this kind understands it, or None — re-checked on every read,
    because a plan is shared and a colleague's file is input. ``expected`` is the content
    type the asking kind is: a record naming the other one is not this kind's to fetch."""
    site, content_id, kind = locator.get("site"), locator.get("id"), locator.get("type")
    if not isinstance(site, str) or not is_cloud_site(site):
        return None
    if not isinstance(content_id, str) or not content_id.isdigit():
        return None
    if kind != expected:
        return None
    valid = {"site": site, "id": content_id, "type": str(kind)}
    space = locator.get("space")
    if isinstance(space, str) and _SPACE_KEY.match(space):
        valid["space"] = space
    return valid


def page_url(site: str, page_id: str) -> str:
    """Where a person opens a page — the canonical form that needs no space key."""
    return f"{site}/wiki/pages/viewpage.action?pageId={page_id}"


def folder_url(site: str, folder_id: str, space: str = "") -> str:
    """A folder has no canonical address without its space key; a locator from a pasted
    URL carries the key, one from elsewhere opens the site's folder view by id."""
    return f"{site}/wiki/spaces/{space or '~'}/folder/{folder_id}"


@dataclass(frozen=True)
class _Found:
    """A page found in the walk: where it hangs, and how deep."""

    row: ChildRow
    parent_key: str


def fetch(
    client: ConfluenceClient,
    locator: Locator,
    known: Mapping[str, str],
    progress: Callable[[float], None] = lambda _f: None,
    cancelled: Callable[[], bool] = lambda: False,
) -> Snapshot:
    notes: list[str] = []
    found = _walk(client, locator, notes, cancelled)
    versions = client.versions([entry.row.id for entry in found])
    documents: list[FetchedDocument] = []
    images: list[FetchedImage] = []
    kept: list[str] = []
    seen_images: set[str] = set()
    page_links = {entry.row.title: page_url(locator["site"], entry.row.id) for entry in found}
    total_bytes = 0
    for index, entry in enumerate(found):
        if cancelled():
            raise SourceUnavailableError("cancelled")
        progress(index / max(len(found), 1))
        version = versions.get(entry.row.id, "")
        if version and known.get(entry.row.id) == version:
            kept.append(entry.row.id)
            continue
        page = client.page(entry.row.id)
        image_map: dict[str, str] = {}
        wanted = attachment_names(page.body)
        if wanted:
            by_title = {attachment.title: attachment for attachment in client.attachments(page.id)}
            for filename in wanted:
                attachment = by_title.get(filename)
                if attachment is None:
                    notes.append(f"{page.title}: image {filename} is not attached to the page")
                    continue
                try:
                    data = client.download(attachment)
                except TooLargeError:
                    notes.append(
                        f"{page.title}: {filename} is larger than the cap and was left out"
                    )
                    continue
                suffix = raster_suffix(data)
                if suffix is None:
                    notes.append(f"{page.title}: {filename} is not a raster image and was left out")
                    continue
                total_bytes += len(data)
                if total_bytes > MAX_FETCH_BYTES:
                    raise SourceUnavailableError(
                        f"this tree carries more than {MAX_FETCH_BYTES // (1024 * 1024)} MB of "
                        "images — import a smaller part of it"
                    )
                name = asset_name(data, f"image{suffix}")
                image_map[filename] = name
                if name not in seen_images:
                    seen_images.add(name)
                    images.append(FetchedImage(data=data, filename=f"image{suffix}"))
        documents.append(
            FetchedDocument(
                key=page.id,
                parent_key=entry.parent_key,
                title=page.title,
                data=convert(page.body, image_map, page_links).encode("utf-8"),
                filename="page.md",  # No file behind it; the suffix is what is read.
                version=page.version or version,
                url=page_url(locator["site"], page.id),
            )
        )
    progress(1.0)
    return Snapshot(
        documents=tuple(documents),
        kept=tuple(kept),
        images=tuple(images),
        notes=tuple(notes),
        order=tuple(entry.row.id for entry in found),
    )


def check(client: ConfluenceClient, locator: Locator, known: Mapping[str, str]) -> Freshness:
    """What changed since ``known`` — versions only, no bodies."""
    found = _walk(client, locator, [], lambda: False)
    versions = client.versions([entry.row.id for entry in found])
    current = {entry.row.id for entry in found}
    return Freshness(
        changed=tuple(
            key for key in current if key in known and versions.get(key, known[key]) != known[key]
        ),
        added=tuple(key for key in current if key not in known),
        removed=tuple(key for key in known if key not in current),
    )


def probe_access(client: ConfluenceClient, locator: Locator) -> str:
    """The title the credentials can read at the locator — the Connect dialog's probe."""
    if locator["type"] == "folder":
        return client.folder(locator["id"])
    return client.page(locator["id"], body=False).title


def _walk(
    client: ConfluenceClient,
    locator: Locator,
    notes: list[str],
    cancelled: Callable[[], bool],
) -> list[_Found]:
    """Every current page under the locator, breadth-first, parents before children."""
    found: list[_Found] = []
    queue: list[tuple[str, str, str, int]] = []  # (id, type, parent key, depth)
    if locator["type"] == "page":
        root = client.page(locator["id"], body=False)
        row = ChildRow(id=root.id, type="page", title=root.title, status=root.status)
        found.append(_Found(row, ""))
        queue.append((root.id, "page", root.id, 1))
    else:
        queue.append((locator["id"], "folder", "", 1))
    seen = {locator["id"]}
    while queue:
        if cancelled():
            raise SourceUnavailableError("cancelled")
        parent_id, parent_type, parent_key, depth = queue.pop(0)
        for row in client.children(parent_id, parent_type):
            if row.id in seen:
                continue
            seen.add(row.id)
            if row.type == "page":
                if row.status != "current":
                    continue
                if len(found) >= MAX_PAGES:
                    notes.append(f"more than {MAX_PAGES} pages — the rest were left out")
                    return found
                found.append(_Found(row, parent_key))
                if depth < MAX_DEPTH:
                    queue.append((row.id, "page", row.id, depth + 1))
                else:
                    notes.append(f"{row.title}: deeper than {MAX_DEPTH} levels, not descended")
            elif row.type == "folder":
                if depth < MAX_DEPTH:
                    queue.append((row.id, "folder", parent_key, depth + 1))
            else:
                notes.append(f"{row.title or row.id}: a {row.type}, not imported")
    return found
