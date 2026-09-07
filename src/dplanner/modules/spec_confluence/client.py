"""A read-only door to one Confluence Cloud site, over the standard library.

**There is one request method and it is GET.** The client cannot write to Confluence
because nothing in it knows how to: the transport takes a URL and headers and returns a
status, headers and a body, and the fake transport the tests hand in refuses anything
else. That is the whole read-only guarantee, and it is structural rather than a promise.

Everything that arrives is data. JSON is read through ``isinstance`` chains (the
tolerant-reader house style), every id that goes back into a URL must be digits, a
redirect is followed once and only to an Atlassian host with the credential stripped when
the host changes, and a body is read against a cap. Errors come out as one
:class:`SourceUnavailableError` whose text is composed here from the status code — never
from a library's own message, which is how a credential would leak into a log.
"""

import base64
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any, Protocol
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import HTTPSHandler, OpenerDirector, ProxyHandler, Request

from dplanner.domain.document_source import SourceUnavailableError

API = "/wiki/api/v2"
TIMEOUT_S = 30.0
PAGE_LIMIT = 250  # The most v2 hands back per call.
MAX_LISTING_PAGES = 50  # Cursor pages followed for one listing: 12 500 rows, plenty.
RETRY_AFTER_CAP_S = 60.0
RATE_LIMIT_ATTEMPTS = 3
SERVER_ERROR_ATTEMPTS = 3
BACKOFF_S = (1.0, 3.0)
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024

_CLOUD_SITE = re.compile(r"^https://[a-z0-9-]+\.atlassian\.net$")
_DIGITS = re.compile(r"^\d+$")
_REDIRECT_HOSTS = (".atlassian.com", ".atlassian.net")
_RETRY = "retry"  # Not a URL: _get reads it as "the same URL again".
_JSON = "application/json"


def is_cloud_site(site: str) -> bool:
    """Whether ``site`` names an Atlassian Cloud origin this client will talk to."""
    return bool(_CLOUD_SITE.match(site))


@dataclass(frozen=True)
class Credentials:
    email: str
    token: str


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str]  # Lower-cased names.
    body: bytes


class Transport(Protocol):
    """The one call the client makes: fetch ``url`` with ``headers``, read at most
    ``max_bytes`` — and no other verb exists on this interface."""

    def get(self, url: str, headers: Mapping[str, str], *, max_bytes: int) -> Response: ...


class TooLargeError(Exception):
    """A body past the cap; the transport stops reading rather than buffering it."""


class UrllibTransport:
    """The real transport: HTTPS only, no automatic redirects, every status returned."""

    def __init__(self) -> None:
        opener = OpenerDirector()
        opener.add_handler(ProxyHandler())  # The environment's proxy, as urllib reads it.
        opener.add_handler(HTTPSHandler())
        self._opener = opener

    def get(self, url: str, headers: Mapping[str, str], *, max_bytes: int) -> Response:
        request = Request(url, headers=dict(headers), method="GET")
        with self._opener.open(request, timeout=TIMEOUT_S) as raw:
            length = raw.headers.get("Content-Length")
            if length is not None and length.isdigit() and int(length) > max_bytes:
                raise TooLargeError()
            body = raw.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise TooLargeError()
            return Response(
                status=raw.status,
                headers={key.lower(): value for key, value in raw.headers.items()},
                body=body,
            )


@dataclass(frozen=True)
class ChildRow:
    """One row of a children or descendants listing — no body, no version."""

    id: str
    type: str  # "page" | "folder" | "whiteboard" | "database" | "embed" | …
    title: str
    status: str


@dataclass(frozen=True)
class Page:
    id: str
    title: str
    version: str
    status: str
    body: str  # Storage XHTML; "" when the page has none (some live docs).
    parent_id: str = ""


@dataclass(frozen=True)
class Attachment:
    id: str
    title: str  # What ``ri:filename`` names.
    media_type: str
    size: int
    download: str  # Site-relative, as Confluence gives it.


@dataclass
class _Attempts:
    rate_limited: int = 0
    server_errors: int = 0
    redirects: int = 0
    log: list[str] = field(default_factory=list)


class ConfluenceClient:
    def __init__(
        self,
        site: str,
        credentials: Credentials,
        transport: Transport | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not is_cloud_site(site):
            raise ValueError(f"{site!r} is not an Atlassian Cloud site")
        self.site = site
        self._host = urlsplit(site).hostname or ""
        self._credentials = credentials
        self._transport = transport if transport is not None else UrllibTransport()
        self._sleep = sleep

    # -- what the source walks -----------------------------------------------------------------

    def page(self, page_id: str, *, body: bool = True) -> Page:
        """One page, with its storage body unless ``body`` is False."""
        query = "?body-format=storage" if body else ""
        data = self._json(f"{API}/pages/{_digits(page_id)}{query}")
        page = _page(data)
        if page is None:
            raise SourceUnavailableError(f"Confluence answered page {page_id} in an unknown shape")
        return page

    def folder(self, folder_id: str) -> str:
        """A folder's title."""
        data = self._json(f"{API}/folders/{_digits(folder_id)}")
        title = data.get("title")
        return title if isinstance(title, str) else f"Folder {folder_id}"

    def children(self, parent_id: str, parent_type: str) -> list[ChildRow]:
        """The direct children of a page or folder, every content type, in order."""
        noun = "folders" if parent_type == "folder" else "pages"
        path = f"{API}/{noun}/{_digits(parent_id)}/direct-children?limit={PAGE_LIMIT}"
        rows = self._listing(path)
        return [row for row in (_child_row(raw) for raw in rows) if row is not None]

    def descendants(self, page_id: str) -> list[ChildRow]:
        """Every descendant of a page in one listing — cheaper than a walk for a check."""
        rows = self._listing(f"{API}/pages/{_digits(page_id)}/descendants?limit={PAGE_LIMIT}")
        return [row for row in (_child_row(raw) for raw in rows) if row is not None]

    def versions(self, page_ids: Sequence[str]) -> dict[str, str]:
        """The current version of each page, by id, without bodies — batched."""
        found: dict[str, str] = {}
        ids = [_digits(page_id) for page_id in page_ids]
        for start in range(0, len(ids), PAGE_LIMIT):
            chunk = ",".join(ids[start : start + PAGE_LIMIT])
            for raw in self._listing(f"{API}/pages?id={chunk}&limit={PAGE_LIMIT}"):
                page = _page(raw)
                if page is not None:
                    found[page.id] = page.version
        return found

    def attachments(self, page_id: str) -> list[Attachment]:
        rows = self._listing(f"{API}/pages/{_digits(page_id)}/attachments?limit={PAGE_LIMIT}")
        return [row for row in (_attachment(raw) for raw in rows) if row is not None]

    def download(self, attachment: Attachment, *, max_bytes: int = MAX_ATTACHMENT_BYTES) -> bytes:
        """The attachment's bytes — following the one redirect Confluence may answer with."""
        if attachment.size > max_bytes:
            raise TooLargeError()
        link = attachment.download
        url = urljoin(f"{self.site}/wiki/", link.lstrip("/")) if link.startswith("/") else link
        return self._get(url, accept="*/*", max_bytes=max_bytes).body

    # -- the one request path --------------------------------------------------------------------

    def _json(self, path: str) -> dict[str, Any]:
        return _object(self._get(urljoin(self.site, path), accept=_JSON, max_bytes=MAX_JSON_BYTES))

    def _listing(self, path: str) -> list[dict[str, Any]]:
        """Every row of a cursor-paginated listing, following ``_links.next`` or the
        ``Link`` header — both relative to the site, both already carrying ``/wiki``."""
        rows: list[dict[str, Any]] = []
        url: str | None = urljoin(self.site, path)
        for _ in range(MAX_LISTING_PAGES):
            if url is None:
                break
            response = self._get(url, accept=_JSON, max_bytes=MAX_JSON_BYTES)
            loaded = _object(response)
            results = loaded.get("results")
            if isinstance(results, list):
                rows.extend(row for row in results if isinstance(row, dict))
            url = self._next_url(loaded, response.headers)
        return rows

    def _next_url(self, loaded: Mapping[str, Any], headers: Mapping[str, str]) -> str | None:
        links = loaded.get("_links")
        following: Any = links.get("next") if isinstance(links, dict) else None
        if isinstance(following, dict):
            following = following.get("href")
        if not isinstance(following, str) or not following:
            header = headers.get("link", "")
            match = re.search(r"<([^>]+)>\s*;\s*rel=\"?next\"?", header)
            following = match.group(1) if match else None
        if not isinstance(following, str) or not following:
            return None
        url: str = urljoin(self.site, following)
        if urlsplit(url).hostname != self._host:
            raise SourceUnavailableError("Confluence pointed the listing at another host")
        return url

    def _get(self, url: str, *, accept: str, max_bytes: int) -> Response:
        attempts = _Attempts()
        while True:
            parts = urlsplit(url)
            if parts.scheme != "https":
                raise SourceUnavailableError("Confluence pointed at a non-https address")
            same_host = parts.hostname == self._host
            headers = {"Accept": accept, "User-Agent": "dplanner"}
            if same_host:
                headers["Authorization"] = self._authorization()
            try:
                response = self._transport.get(url, headers, max_bytes=max_bytes)
            except TooLargeError:
                raise SourceUnavailableError(
                    f"Confluence sent more than {max_bytes // (1024 * 1024)} MB for one request"
                ) from None
            except OSError:  # DNS, TLS, timeouts, resets — none of it says anything secret.
                raise SourceUnavailableError(f"could not reach {self._host}") from None
            outcome = self._outcome(response, attempts)
            if outcome is None:
                return response
            if outcome != _RETRY:
                url = outcome

    def _outcome(self, response: Response, attempts: _Attempts) -> str | None:
        """None when the response is the answer; a URL to try next after a redirect or
        a wait; a raised ``SourceUnavailableError`` otherwise."""
        status = response.status
        if 200 <= status < 300:
            return None
        if status in (301, 302, 303, 307, 308):
            attempts.redirects += 1
            if attempts.redirects > 1:
                raise SourceUnavailableError("Confluence redirected more than once")
            target = response.headers.get("location", "")
            resolved = urljoin(self.site, target)
            parts = urlsplit(resolved)
            host = parts.hostname or ""
            if parts.scheme != "https" or not host.endswith(_REDIRECT_HOSTS):
                raise SourceUnavailableError("Confluence redirected outside Atlassian")
            return resolved
        if status == 401:
            raise SourceUnavailableError(
                f"{self._host} rejected the token — it may have expired "
                "(tokens last at most a year)",
                needs_reconnect=True,
            )
        if status == 403:
            raise SourceUnavailableError(
                f"{self._host} refused: this account may not use Confluence there"
            )
        if status == 404:
            raise SourceUnavailableError(
                "not found — the page may be gone, or not visible to this account"
            )
        if status == 429:
            attempts.rate_limited += 1
            wait = _retry_after(response.headers.get("retry-after"))
            if attempts.rate_limited >= RATE_LIMIT_ATTEMPTS or wait > RETRY_AFTER_CAP_S:
                raise SourceUnavailableError(
                    "Confluence is rate-limiting requests — try again in a few minutes"
                )
            self._sleep(wait)
            return _RETRY
        if status >= 500:
            attempts.server_errors += 1
            if attempts.server_errors >= SERVER_ERROR_ATTEMPTS:
                raise SourceUnavailableError(f"{self._host} answered {status} repeatedly")
            self._sleep(BACKOFF_S[min(attempts.server_errors - 1, len(BACKOFF_S) - 1)])
            return _RETRY
        raise SourceUnavailableError(f"{self._host} answered {status}")

    def _authorization(self) -> str:
        raw = f"{self._credentials.email}:{self._credentials.token}".encode()
        return "Basic " + base64.b64encode(raw).decode("ascii")


def _object(response: Response) -> dict[str, Any]:
    try:
        loaded = json.loads(response.body)
    except ValueError:
        raise SourceUnavailableError(
            "Confluence answered with something that is not JSON"
        ) from None
    if not isinstance(loaded, dict):
        raise SourceUnavailableError("Confluence answered in a shape not understood")
    return loaded


def _retry_after(value: str | None) -> float:
    """Seconds to wait, from a Retry-After that is seconds or an HTTP date — and a
    number too large to be a wait (one library crashed on it) reads as *too long*."""
    if value is None:
        return 1.0
    text = value.strip()
    if text.isdigit():
        return float(min(int(text), 10**6))
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, when.timestamp() - time.time())


def _digits(value: str) -> str:
    if not _DIGITS.match(value):
        raise SourceUnavailableError(f"{value!r} is not a Confluence content id")
    return quote(value, safe="")


def _page(raw: Mapping[str, Any]) -> Page | None:
    page_id = raw.get("id")
    title = raw.get("title")
    if not isinstance(page_id, str) or not isinstance(title, str):
        return None
    version = raw.get("version")
    number = version.get("number") if isinstance(version, dict) else None
    body: Any = raw.get("body")
    storage = body.get("storage") if isinstance(body, dict) else None
    value = storage.get("value") if isinstance(storage, dict) else None
    parent = raw.get("parentId")
    status = raw.get("status")
    return Page(
        id=page_id,
        title=title,
        version=str(number) if isinstance(number, int) and not isinstance(number, bool) else "",
        status=status if isinstance(status, str) else "current",
        body=value if isinstance(value, str) else "",
        parent_id=parent if isinstance(parent, str) else "",
    )


def _child_row(raw: Mapping[str, Any]) -> ChildRow | None:
    row_id = raw.get("id")
    if not isinstance(row_id, str):
        return None
    kind = raw.get("type")
    title = raw.get("title")
    status = raw.get("status")
    return ChildRow(
        id=row_id,
        type=kind if isinstance(kind, str) else "page",
        title=title if isinstance(title, str) else "",
        status=status if isinstance(status, str) else "current",
    )


def _attachment(raw: Mapping[str, Any]) -> Attachment | None:
    row_id = raw.get("id")
    title = raw.get("title")
    download = raw.get("downloadLink")
    if not isinstance(row_id, str) or not isinstance(title, str) or not isinstance(download, str):
        return None
    size = raw.get("fileSize")
    media = raw.get("mediaType")
    return Attachment(
        id=row_id,
        title=title,
        media_type=media if isinstance(media, str) else "",
        size=size if isinstance(size, int) and not isinstance(size, bool) else 0,
        download=download,
    )
