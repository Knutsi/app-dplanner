"""The Confluence client, over a fake transport: one verb, bounded reads, pagination,
the retry ladder, and the redirect that must not carry the credential."""

import json
from pathlib import Path

import pytest

from dplanner.domain.document_source import SourceUnavailableError
from dplanner.modules.spec_confluence import client as client_mod
from dplanner.modules.spec_confluence.client import (
    ConfluenceClient,
    Credentials,
    Response,
    TooLargeError,
)

SITE = "https://acme.atlassian.net"
CREDS = Credentials(email="me@acme.example", token="tok-secret-value")


class FakeTransport:
    """Routes URLs to canned responses and records every request it saw.

    It has a ``get`` and nothing else, so a client that grew another verb would fail here
    with an AttributeError before any test even looked.
    """

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.calls = []

    def get(self, url, headers, *, max_bytes):
        self.calls.append((url, dict(headers), max_bytes))
        answer = self.routes.get(url)
        if answer is None:
            return Response(404, {}, b'{"message":"nope"}')
        if callable(answer):
            answer = answer()
        if isinstance(answer, Exception):
            raise answer
        return answer


def ok(payload, headers=None):
    return Response(200, dict(headers or {}), json.dumps(payload).encode())


@pytest.fixture
def transport():
    return FakeTransport()


@pytest.fixture
def client(transport):
    return ConfluenceClient(SITE, CREDS, transport, sleep=lambda _s: None)


def test_only_a_cloud_site_is_accepted():
    with pytest.raises(ValueError):
        ConfluenceClient("http://acme.atlassian.net", CREDS, FakeTransport())
    with pytest.raises(ValueError):
        ConfluenceClient("https://evil.example", CREDS, FakeTransport())


def test_a_page_is_read_with_its_storage_body(client, transport):
    transport.routes[f"{SITE}/wiki/api/v2/pages/12?body-format=storage"] = ok(
        {
            "id": "12",
            "title": "Auth",
            "status": "current",
            "version": {"number": 7},
            "body": {"storage": {"value": "<p>hi</p>"}},
        }
    )
    page = client.page("12")
    assert (page.title, page.version, page.body) == ("Auth", "7", "<p>hi</p>")
    _url, headers, _cap = transport.calls[0]
    assert headers["Authorization"].startswith("Basic ")
    assert headers["Accept"] == "application/json"


def test_an_id_that_is_not_digits_never_reaches_a_url(client, transport):
    with pytest.raises(SourceUnavailableError):
        client.page("../secret")
    assert transport.calls == []


def test_a_listing_follows_links_next_in_both_shapes_and_the_header(client, transport):
    base = f"{SITE}/wiki/api/v2/pages/1/direct-children?limit=250"
    transport.routes[base] = ok(
        {
            "results": [{"id": "2", "type": "page", "title": "A"}],
            "_links": {"next": "/wiki/api/v2/x?cursor=1"},
        }
    )
    transport.routes[f"{SITE}/wiki/api/v2/x?cursor=1"] = ok(
        {
            "results": [{"id": "3", "type": "folder", "title": "B"}],
            "_links": {"next": {"href": "/wiki/api/v2/x?cursor=2"}},
        }
    )
    transport.routes[f"{SITE}/wiki/api/v2/x?cursor=2"] = ok(
        {"results": [{"id": "4", "type": "page", "title": "C"}]},
        {"link": f'<{SITE}/wiki/api/v2/x?cursor=3>; rel="next"'},
    )
    transport.routes[f"{SITE}/wiki/api/v2/x?cursor=3"] = ok(
        {"results": [{"id": "5", "type": "page"}]}
    )
    rows = client.children("1", "page")
    assert [(row.id, row.type) for row in rows] == [
        ("2", "page"),
        ("3", "folder"),
        ("4", "page"),
        ("5", "page"),
    ]


def test_a_listing_pointed_at_another_host_is_refused(client, transport):
    base = f"{SITE}/wiki/api/v2/pages/1/direct-children?limit=250"
    transport.routes[base] = ok({"results": [], "_links": {"next": "https://evil.example/x"}})
    with pytest.raises(SourceUnavailableError):
        client.children("1", "page")
    assert len(transport.calls) == 1


def test_rate_limiting_waits_for_retry_after_then_gives_up(transport):
    waits: list[float] = []
    client = ConfluenceClient(SITE, CREDS, transport, sleep=waits.append)
    answers = iter(
        [
            Response(429, {"retry-after": "2"}, b""),
            Response(429, {"retry-after": "3"}, b""),
            ok({"id": "1", "title": "T", "version": {"number": 1}}),
        ]
    )
    transport.routes[f"{SITE}/wiki/api/v2/pages/1"] = lambda: next(answers)
    assert client.page("1", body=False).title == "T"
    assert waits == [2.0, 3.0]

    always = Response(429, {"retry-after": "1"}, b"")
    transport.routes[f"{SITE}/wiki/api/v2/pages/2"] = always
    with pytest.raises(SourceUnavailableError, match="rate-limiting"):
        client.page("2", body=False)


def test_a_retry_after_past_the_cap_is_not_waited_for(transport):
    waits: list[float] = []
    client = ConfluenceClient(SITE, CREDS, transport, sleep=waits.append)
    transport.routes[f"{SITE}/wiki/api/v2/pages/1"] = Response(429, {"retry-after": "1847"}, b"")
    with pytest.raises(SourceUnavailableError, match="rate-limiting"):
        client.page("1", body=False)
    assert waits == []


def test_a_server_error_is_retried_then_reported(transport):
    waits: list[float] = []
    client = ConfluenceClient(SITE, CREDS, transport, sleep=waits.append)
    transport.routes[f"{SITE}/wiki/api/v2/pages/1"] = Response(503, {}, b"")
    with pytest.raises(SourceUnavailableError, match="503"):
        client.page("1", body=False)
    assert len(waits) == client_mod.SERVER_ERROR_ATTEMPTS - 1


def test_the_status_codes_map_to_sentences_and_401_asks_to_reconnect(client, transport):
    transport.routes[f"{SITE}/wiki/api/v2/pages/1"] = Response(401, {}, b"")
    with pytest.raises(SourceUnavailableError) as refused:
        client.page("1", body=False)
    assert refused.value.needs_reconnect and "expired" in str(refused.value)
    for status, word in ((403, "refused"), (404, "not found"), (418, "418")):
        transport.routes[f"{SITE}/wiki/api/v2/pages/1"] = Response(status, {}, b"")
        with pytest.raises(SourceUnavailableError, match=word) as refused:
            client.page("1", body=False)
        assert not refused.value.needs_reconnect


def test_the_token_never_appears_in_an_error(client, transport):
    transport.routes[f"{SITE}/wiki/api/v2/pages/1"] = OSError("boom tok-secret-value")
    with pytest.raises(SourceUnavailableError) as refused:
        client.page("1", body=False)
    assert "tok-secret-value" not in str(refused.value)
    transport.routes[f"{SITE}/wiki/api/v2/pages/1"] = Response(500, {}, b"tok-secret-value")
    with pytest.raises(SourceUnavailableError) as refused:
        client.page("1", body=False)
    assert "tok-secret-value" not in str(refused.value)


def test_an_answer_that_is_not_json_or_not_an_object_is_refused(client, transport):
    transport.routes[f"{SITE}/wiki/api/v2/pages/1"] = Response(200, {}, b"<html>")
    with pytest.raises(SourceUnavailableError, match="not JSON"):
        client.page("1", body=False)
    transport.routes[f"{SITE}/wiki/api/v2/pages/1"] = Response(200, {}, b"[1, 2]")
    with pytest.raises(SourceUnavailableError, match="shape"):
        client.page("1", body=False)


def test_a_body_past_the_cap_is_refused_not_buffered(client, transport):
    transport.routes[f"{SITE}/wiki/api/v2/pages/1"] = TooLargeError()
    with pytest.raises(SourceUnavailableError, match="more than"):
        client.page("1", body=False)


def test_a_download_follows_one_atlassian_redirect_without_the_credential(client, transport):
    attachment = client_mod.Attachment(
        id="a1",
        title="x.png",
        media_type="image/png",
        size=3,
        download="/download/attachments/1/x.png?v=1",
    )
    transport.routes[f"{SITE}/wiki/download/attachments/1/x.png?v=1"] = Response(
        302, {"location": "https://api.media.atlassian.com/blob/1?sig=abc"}, b""
    )
    transport.routes["https://api.media.atlassian.com/blob/1?sig=abc"] = Response(200, {}, b"PNG")
    assert client.download(attachment) == b"PNG"
    first, second = transport.calls
    assert "Authorization" in first[1]
    assert "Authorization" not in second[1]


def test_a_redirect_outside_atlassian_or_off_https_is_refused(client, transport):
    attachment = client_mod.Attachment(id="a1", title="x", media_type="", size=0, download="/d/x")
    for location in ("https://evil.example/x", "http://acme.atlassian.net/x"):
        transport.routes[f"{SITE}/wiki/d/x"] = Response(302, {"location": location}, b"")
        with pytest.raises(SourceUnavailableError):
            client.download(attachment)


def test_a_second_redirect_is_refused(client, transport):
    attachment = client_mod.Attachment(id="a1", title="x", media_type="", size=0, download="/d/x")
    transport.routes[f"{SITE}/wiki/d/x"] = Response(302, {"location": f"{SITE}/wiki/d/y"}, b"")
    transport.routes[f"{SITE}/wiki/d/y"] = Response(302, {"location": f"{SITE}/wiki/d/z"}, b"")
    with pytest.raises(SourceUnavailableError, match="more than once"):
        client.download(attachment)


def test_an_attachment_declared_past_the_cap_is_never_requested(client, transport):
    attachment = client_mod.Attachment(
        id="a1", title="x", media_type="", size=10**9, download="/d/x"
    )
    with pytest.raises(TooLargeError):
        client.download(attachment)
    assert transport.calls == []


def test_versions_are_asked_in_bulk_and_read_tolerantly(client, transport):
    transport.routes[f"{SITE}/wiki/api/v2/pages?id=1,2,3&limit=250"] = ok(
        {
            "results": [
                {"id": "1", "title": "A", "version": {"number": 4}},
                {"id": "2", "title": "B", "version": {"number": True}},
                {"id": 3, "title": "C"},
                "junk",
            ]
        }
    )
    assert client.versions(["1", "2", "3"]) == {"1": "4", "2": ""}


def test_the_client_offers_no_write(client):
    """Read-only by construction: the client has exactly one request path and it is a
    GET; the fake transport above has no other verb to call."""
    assert not any(
        name.lower().startswith(("post", "put", "delete", "patch")) for name in dir(client)
    )
    assert 'method="GET"' in Path(client_mod.__file__).read_text(encoding="utf-8")


def test_retry_after_reads_seconds_and_dates():
    assert client_mod._retry_after("5") == 5.0
    assert client_mod._retry_after(None) == 1.0
    assert client_mod._retry_after("garbage") == 1.0
    assert client_mod._retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0
    assert client_mod._retry_after("9" * 30) == 10**6
