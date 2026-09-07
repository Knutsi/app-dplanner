"""The Confluence source over a fake client: the URL a person pastes, the walk with its
caps and skips, the version skip, and what a fetch downloads and names."""

import hashlib

import pytest

from dplanner.domain.assets import asset_name
from dplanner.domain.document_source import SourceUnavailableError
from dplanner.modules.spec_confluence import source as source_mod
from dplanner.modules.spec_confluence.client import Attachment, ChildRow, Page, TooLargeError
from dplanner.modules.spec_confluence.source import check, fetch, parse_url, valid_locator

SITE = "https://acme.atlassian.net"
PNG = b"\x89PNG\r\n\x1a\n" + b"pixels"


class FakeClient:
    """Answers from dicts; records what was asked so a test can count requests."""

    def __init__(self):
        self.pages = {}  # id -> Page
        self.children_of = {}  # (id, type) -> [ChildRow]
        self.attachments_of = {}  # page id -> [Attachment]
        self.blobs = {}  # attachment id -> bytes | Exception
        self.folders = {}  # id -> title
        self.bodies_fetched = []
        self.downloads = []

    def page(self, page_id, *, body=True):
        if body:
            self.bodies_fetched.append(page_id)
        page = self.pages.get(page_id)
        if page is None:
            raise SourceUnavailableError("not found")
        return page if body else Page(page.id, page.title, page.version, page.status, "")

    def folder(self, folder_id):
        return self.folders[folder_id]

    def children(self, parent_id, parent_type):
        return list(self.children_of.get((parent_id, parent_type), []))

    def versions(self, ids):
        return {i: self.pages[i].version for i in ids if i in self.pages}

    def attachments(self, page_id):
        return list(self.attachments_of.get(page_id, []))

    def download(self, attachment, *, max_bytes=0):
        self.downloads.append(attachment.id)
        blob = self.blobs[attachment.id]
        if isinstance(blob, Exception):
            raise blob
        return blob


def page(page_id, title, version="1", body="<p>text</p>", status="current"):
    return Page(id=page_id, title=title, version=version, status=status, body=body)


def row(row_id, title, kind="page", status="current"):
    return ChildRow(id=row_id, type=kind, title=title, status=status)


@pytest.fixture
def tree():
    client = FakeClient()
    client.pages["1"] = page(
        "1", "Root", "3", '<p>see</p><ac:image><ri:attachment ri:filename="flow.png"/></ac:image>'
    )
    client.pages["2"] = page("2", "Child", "1", "<p>child</p>")
    client.pages["3"] = page("3", "Grandchild", "2")
    client.pages["9"] = page("9", "Draft", "1", status="draft")
    client.children_of[("1", "page")] = [
        row("2", "Child"),
        row("7", "Board", "whiteboard"),
        row("9", "Draft", status="draft"),
    ]
    client.children_of[("2", "page")] = [row("3", "Grandchild")]
    client.attachments_of["1"] = [
        Attachment(
            id="a1", title="flow.png", media_type="image/png", size=len(PNG), download="/d/flow.png"
        )
    ]
    client.blobs["a1"] = PNG
    return client


def locator(content_id="1", kind="page"):
    return {"site": SITE, "id": content_id, "type": kind}


# -- the pasted URL ---------------------------------------------------------------------------


def test_a_page_url_in_its_three_shapes_becomes_a_locator():
    title, found = parse_url("https://acme.atlassian.net/wiki/spaces/ENG/pages/12345/Auth+Overview")
    assert (title, found) == ("Auth Overview", {"site": SITE, "id": "12345", "type": "page"})
    assert parse_url("https://acme.atlassian.net/wiki/spaces/ENG/pages/12345")[1]["id"] == "12345"
    assert parse_url("https://acme.atlassian.net/wiki/pages/viewpage.action?pageId=77")[1] == {
        "site": SITE,
        "id": "77",
        "type": "page",
    }
    assert parse_url(" https://Acme.atlassian.net/wiki/spaces/ENG/folder/5 ")[1] == {
        "site": SITE,
        "id": "5",
        "type": "folder",
    }


@pytest.mark.parametrize(
    "text",
    [
        "https://evil.example/wiki/spaces/ENG/pages/1/x",
        "http://acme.atlassian.net/wiki/spaces/ENG/pages/1/x",
        "https://acme.atlassian.net/wiki/x/AbCd",
        "https://acme.atlassian.net/wiki/spaces/ENG/overview",
        "not a url",
    ],
)
def test_other_addresses_are_refused_with_a_sentence(text):
    with pytest.raises(ValueError):
        parse_url(text)


def test_a_locator_read_off_disk_is_validated_again():
    assert valid_locator({"site": SITE, "id": "1", "type": "page"}) == locator()
    assert valid_locator({"site": "https://evil.example", "id": "1", "type": "page"}) is None
    assert valid_locator({"site": SITE, "id": "../x", "type": "page"}) is None
    assert valid_locator({"site": SITE, "id": "1", "type": "space"}) is None
    assert valid_locator({"site": 3, "id": "1"}) is None


# -- the fetch ----------------------------------------------------------------------------------


def test_a_fetch_walks_the_tree_skips_drafts_and_other_kinds_and_names_images(tree):
    snapshot = fetch(tree, locator(), {})
    docs = {doc.key: doc for doc in snapshot.documents}
    assert [doc.key for doc in snapshot.documents] == ["1", "2", "3"]
    assert (
        docs["2"].parent_key == "1" and docs["3"].parent_key == "2" and docs["1"].parent_key == ""
    )
    assert docs["1"].version == "3" and docs["1"].url.endswith("pageId=1")
    name = asset_name(PNG, "image.png")
    assert f"![image]({name})" in docs["1"].markdown
    assert [(image.filename, image.data) for image in snapshot.images] == [("image.png", PNG)]
    assert any("Board" in note and "whiteboard" in note for note in snapshot.notes)
    assert "9" not in docs


def test_a_page_whose_version_is_known_is_kept_without_a_body_request(tree):
    snapshot = fetch(tree, locator(), {"1": "3", "2": "0"})
    assert snapshot.kept == ("1",)
    assert [doc.key for doc in snapshot.documents] == ["2", "3"]
    assert tree.bodies_fetched == ["2", "3"]
    assert snapshot.images == () and tree.downloads == []


def test_a_folder_root_lists_its_pages_at_the_top(tree):
    tree.folders["5"] = "Specs"
    tree.pages["4"] = page("4", "Filed", "1")
    tree.children_of[("5", "folder")] = [row("1", "Root"), row("6", "Sub", "folder")]
    tree.children_of[("6", "folder")] = [row("4", "Filed")]
    snapshot = fetch(tree, locator("5", "folder"), {})
    parents = {doc.key: doc.parent_key for doc in snapshot.documents}
    assert parents == {"1": "", "2": "1", "3": "2", "4": ""}


def test_images_are_filtered_by_reference_type_and_size(tree):
    tree.attachments_of["1"] = [
        Attachment(id="a1", title="flow.png", media_type="image/png", size=1, download="/d/1"),
        Attachment(id="a2", title="other.png", media_type="image/png", size=1, download="/d/2"),
    ]
    tree.blobs["a1"] = b"<svg onload=alert(1)>"
    tree.blobs["a2"] = PNG
    snapshot = fetch(tree, locator(), {})
    root = next(doc for doc in snapshot.documents if doc.key == "1")
    assert "not a raster image" in " ".join(snapshot.notes)
    assert "*[image flow.png — not exported]*" in root.markdown
    assert tree.downloads == ["a1"]  # other.png is attached but never shown: not fetched.
    tree.blobs["a1"] = TooLargeError()
    snapshot = fetch(tree, locator(), {})
    assert "larger than the cap" in " ".join(snapshot.notes)
    tree.attachments_of["1"] = []
    snapshot = fetch(tree, locator(), {})
    assert "not attached" in " ".join(snapshot.notes)


def test_the_page_cap_and_the_depth_cap_hold(tree, monkeypatch):
    monkeypatch.setattr(source_mod, "MAX_PAGES", 2)
    snapshot = fetch(tree, locator(), {})
    assert [doc.key for doc in snapshot.documents] == ["1", "2"]
    assert any("more than 2 pages" in note for note in snapshot.notes)
    monkeypatch.setattr(source_mod, "MAX_PAGES", 500)
    monkeypatch.setattr(source_mod, "MAX_DEPTH", 1)
    snapshot = fetch(tree, locator(), {})
    assert [doc.key for doc in snapshot.documents] == ["1", "2"]
    assert any("deeper than" in note for note in snapshot.notes)


def test_a_cycle_in_the_listing_is_walked_once(tree):
    tree.children_of[("3", "page")] = [row("1", "Root")]
    snapshot = fetch(tree, locator(), {})
    assert [doc.key for doc in snapshot.documents] == ["1", "2", "3"]


def test_cancellation_is_honoured_between_requests(tree):
    asked = iter([False, False, True, True, True, True])
    with pytest.raises(SourceUnavailableError, match="cancelled"):
        fetch(tree, locator(), {}, cancelled=lambda: next(asked))


def test_the_total_image_cap_refuses_the_fetch(tree, monkeypatch):
    monkeypatch.setattr(source_mod, "MAX_FETCH_BYTES", 4)
    with pytest.raises(SourceUnavailableError, match="MB of images"):
        fetch(tree, locator(), {})


def test_progress_runs_to_one(tree):
    seen: list[float] = []
    fetch(tree, locator(), {}, progress=seen.append)
    assert seen[-1] == 1.0 and all(0 <= f <= 1 for f in seen)


# -- the check ----------------------------------------------------------------------------------


def test_a_check_compares_versions_without_a_single_body(tree):
    fresh = check(tree, locator(), {"1": "3", "2": "9", "8": "1"})
    assert (fresh.changed, fresh.added, fresh.removed) == (("2",), ("3",), ("8",))
    assert fresh.stale and tree.bodies_fetched == [] and tree.downloads == []
    assert not check(tree, locator(), {"1": "3", "2": "1", "3": "2"}).stale


def test_probe_access_names_what_the_credentials_can_read(tree):
    tree.folders["5"] = "Specs"
    assert source_mod.probe_access(tree, locator()) == "Root"
    assert source_mod.probe_access(tree, locator("5", "folder")) == "Specs"
    assert tree.bodies_fetched == []


def test_sniffing_knows_the_four_raster_formats():
    assert source_mod._sniff(PNG) == ".png"
    assert source_mod._sniff(b"\xff\xd8\xff\xe0") == ".jpg"
    assert source_mod._sniff(b"GIF89a...") == ".gif"
    assert source_mod._sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ".webp"
    assert source_mod._sniff(b"<svg/>") is None
    assert hashlib.sha256(PNG).hexdigest()[:16] in asset_name(PNG, "image.png")
