"""The Confluence source: a pasted URL to a locator, a locator to a snapshot, and the
caps that keep a fetch bounded.

``fetch`` walks the tree under a page or a folder breadth-first through the client's
children listings, asks for every page's current version in bulk, then downloads the
body and the referenced images of each page whose version is new — a page whose version
the caller already knows goes into ``Snapshot.kept`` without a byte crossing the wire.
``check`` is the same walk without bodies. Both take a client the module built with the
person's credentials; nothing here reads a keychain.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from dplanner.domain.assets import asset_name
from dplanner.domain.document_source import (
    FetchedDocument,
    FetchedImage,
    Freshness,
    Locator,
    Snapshot,
    SourceUnavailableError,
)
from dplanner.modules.spec_confluence.client import (
    ChildRow,
    ConfluenceClient,
    TooLargeError,
    is_cloud_site,
)
from dplanner.modules.spec_confluence.convert import attachment_names, convert

KIND = "confluence"
MAX_PAGES = 500
MAX_DEPTH = 20
MAX_FETCH_BYTES = 200 * 1024 * 1024

_PAGE_URL = re.compile(r"^/wiki/spaces/[^/]+/pages/(\d+)(?:/([^/?#]*))?/?$")
_FOLDER_URL = re.compile(r"^/wiki/spaces/[^/]+/folder/(\d+)/?$")
_VIEWPAGE = re.compile(r"^/wiki/pages/viewpage\.action$")
_SHORT = re.compile(r"^/wiki/x/")

# Raster images only, told by their first bytes: an SVG is XML that can carry script,
# and nothing a spec needs is lost by leaving it out.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
)


def parse_url(text: str) -> tuple[str, Locator]:
    """A page or folder URL as copied from the browser → (title hint, locator).

    ``ValueError`` carries the one sentence a dialog shows for what cannot be read.
    """
    parts = urlsplit(text.strip())
    site = f"{parts.scheme}://{parts.netloc}".lower()
    if not is_cloud_site(site):
        raise ValueError("paste a page or folder address from a *.atlassian.net site")
    if _SHORT.match(parts.path):
        raise ValueError(
            "that is a short link — open the page and copy the address with /pages/ in it"
        )
    page = _PAGE_URL.match(parts.path)
    if page is not None:
        slug = (page.group(2) or "").replace("+", " ").replace("-", " ").strip()
        return slug or f"Page {page.group(1)}", {"site": site, "id": page.group(1), "type": "page"}
    folder = _FOLDER_URL.match(parts.path)
    if folder is not None:
        return f"Folder {folder.group(1)}", {"site": site, "id": folder.group(1), "type": "folder"}
    if _VIEWPAGE.match(parts.path):
        page_id = parse_qs(parts.query).get("pageId", [""])[0]
        if page_id.isdigit():
            return f"Page {page_id}", {"site": site, "id": page_id, "type": "page"}
    raise ValueError("that address does not name a Confluence page or folder")


def valid_locator(locator: Mapping[str, object]) -> Locator | None:
    """The locator as this kind understands it, or None — re-checked on every read,
    because a plan is shared and a colleague's file is input."""
    site, content_id, kind = locator.get("site"), locator.get("id"), locator.get("type")
    if not isinstance(site, str) or not is_cloud_site(site):
        return None
    if not isinstance(content_id, str) or not content_id.isdigit():
        return None
    if kind not in ("page", "folder"):
        return None
    return {"site": site, "id": content_id, "type": str(kind)}


def page_url(site: str, page_id: str) -> str:
    """Where a person opens a page — the canonical form that needs no space key."""
    return f"{site}/wiki/pages/viewpage.action?pageId={page_id}"


def folder_url(site: str, folder_id: str) -> str:
    return f"{site}/wiki/spaces/~/folder/{folder_id}"


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
                suffix = _sniff(data)
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
                markdown=convert(page.body, image_map, page_links),
                version=page.version or version,
                url=page_url(locator["site"], page.id),
            )
        )
    progress(1.0)
    return Snapshot(
        documents=tuple(documents), kept=tuple(kept), images=tuple(images), notes=tuple(notes)
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


def _sniff(data: bytes) -> str | None:
    for magic, suffix in _MAGIC:
        if data.startswith(magic):
            return suffix
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None
