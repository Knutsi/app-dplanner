"""Documents that come from a source, seen from the terminal: the index they land in,
the tree ``spec list`` prints, the refusals, the lint — and the Qt-free apply that the
Specs tab's refresh runs. No ``qapp`` anywhere in this file."""

import json
from dataclasses import replace

import pytest
from tests.cli.spec_helpers import source

from dplanner.core.module_data import migrated
from dplanner.core.storage.local import LocalStorage
from dplanner.domain.document_source import (
    FetchedDocument,
    FetchedImage,
    Freshness,
    Snapshot,
)
from dplanner.domain.model import Project
from dplanner.domain.store import ModuleFileArea
from dplanner.modules.spec.aspect import DATA_FORMAT
from dplanner.modules.spec.documents import SpecIndex, read_index, write_index
from dplanner.modules.spec.sourced import (
    add_source,
    apply_snapshot,
    freshness_words,
    known_versions,
    locator_line,
    owned_by_source,
    remove_source,
    tree,
    updates_words,
)

SITE = "https://acme.atlassian.net"
PNG = b"\x89PNG\r\n\x1a\n" + b"pixels"


def page(key, title, body, parent="", version="1", filename="page.md"):
    return FetchedDocument(
        key=key,
        parent_key=parent,
        title=title,
        data=body.encode() if isinstance(body, str) else body,
        filename=filename,
        version=version,
        url=f"{SITE}/{key}",
    )


def data(text):
    return json.loads(text)


def _holding(entry):
    """A project whose spec entry is ``entry`` — the reader's only input."""
    project = Project(title="P")
    project.module_data["spec"] = entry
    return project


@pytest.fixture
def area(tmp_path):
    return ModuleFileArea(LocalStorage(tmp_path / "ws"), "modules/spec", lambda _p: None)


@pytest.fixture
def fetched():
    return Snapshot(
        documents=(
            page(
                "1",
                "Auth Overview",
                "# Auth\n\nsee ![flow](assets/0000000000000000.png)\n",
                version="3",
            ),
            page("2", "Token lifecycle", "# Tokens\n", parent="1"),
            page("3", "Auth Overview", "# Same title\n", parent="2"),
        ),
        images=(FetchedImage(PNG, "image.png"),),
        notes=("Board: a whiteboard, not imported",),
    )


# -- applying a snapshot, Qt-free ------------------------------------------------------------


def test_a_first_fetch_mints_names_nests_by_parent_and_counts(area, fetched):
    index, src = add_source(
        SpecIndex([], []), "confluence", "Auth", {"site": SITE, "id": "1", "type": "page"}
    )
    index, applied = apply_snapshot(area, index, src.id, fetched, "2026-09-07")
    assert (applied.added, applied.replaced, applied.removed) == (3, 0, 0)
    assert applied.summary == "3 added" and applied.notes == fetched.notes
    names = [doc.name for doc in index.documents]
    assert names == ["auth-overview", "token-lifecycle", "auth-overview-2"]
    by_name = {doc.name: doc for doc in index.documents}
    assert by_name["token-lifecycle"].parent == "auth-overview"
    assert by_name["auth-overview-2"].parent == "token-lifecycle"
    assert (
        by_name["auth-overview"].title == "Auth Overview"
        and by_name["auth-overview"].version == "3"
    )
    assert by_name["auth-overview"].source == src.id and by_name["auth-overview"].key == "1"
    assert index.sources[0].fetched == "2026-09-07"
    assert area.read_bytes("documents/" + by_name["auth-overview"].file.split("/")[1]) is not None
    assert area.names("assets")  # The image landed under its content-addressed name.
    assert known_versions(index, src.id) == {"1": "3", "2": "1", "3": "1"}


def test_a_refresh_keeps_names_when_titles_change_and_keeps_previous(area, fetched):
    index, src = add_source(
        SpecIndex([], []), "confluence_page", "Auth", {"site": SITE, "id": "1", "type": "page"}
    )
    index, _ = apply_snapshot(area, index, src.id, fetched, "2026-09-07")
    again = Snapshot(
        documents=(page("1", "Authentication", "# Auth v2\n", version="4"),),
        kept=("2",),
        order=("1", "2"),
    )
    index, applied = apply_snapshot(area, index, src.id, again, "2026-09-08")
    assert (applied.added, applied.replaced, applied.removed) == (0, 1, 1)
    assert applied.summary == "1 updated, 1 gone"
    by_name = {doc.name: doc for doc in index.documents}
    assert set(by_name) == {"auth-overview", "token-lifecycle"}
    root = by_name["auth-overview"]
    assert root.title == "Authentication" and root.version == "4" and root.previous
    assert by_name["token-lifecycle"].version == "1"  # Kept as it was, no body crossed.
    assert index.sources[0].fetched == "2026-09-08"


def test_an_unchanged_body_is_unchanged_and_the_partition_is_one_place(area, fetched):
    index, src = add_source(
        SpecIndex([], []), "confluence_page", "Auth", {"site": SITE, "id": "1", "type": "page"}
    )
    index, _ = apply_snapshot(area, index, src.id, fetched, "2026-09-07")
    same = replace(fetched, images=())
    index, applied = apply_snapshot(area, index, src.id, same, "2026-09-08")
    assert (applied.added, applied.replaced, applied.unchanged, applied.removed) == (0, 0, 3, 0)
    assert applied.summary == "up to date"
    assert all(doc.previous is None for doc in index.documents)


def test_the_source_documents_keep_their_place_among_the_projects_own(area, fetched):
    own = SpecIndex([], [])
    index, src = add_source(own, "confluence", "Auth", {"site": SITE, "id": "1", "type": "page"})
    index, _ = apply_snapshot(area, index, src.id, fetched, "2026-09-07")
    rows = tree(index)
    assert [
        (row.depth, row.document.name if row.document else str(row.source and row.source.title))
        for row in rows
    ] == [
        (0, "Auth"),
        (1, "auth-overview"),
        (2, "token-lifecycle"),
        (3, "auth-overview-2"),
    ]
    owner = owned_by_source(index, "token-lifecycle")
    assert owner is not None and owner.id == src.id
    assert owned_by_source(index, "nope") is None
    assert remove_source(index, src.id) == SpecIndex([], index.assets, [])


def test_the_index_round_trips_format_5_and_reads_a_dangling_source_as_none(area, fetched):
    index, src = add_source(
        SpecIndex([], []), "confluence_page", "Auth", {"site": SITE, "id": "1", "type": "page"}
    )
    index, _ = apply_snapshot(area, index, src.id, fetched, "2026-09-07")
    entry = write_index(index)
    assert entry["format"] == 5 and entry["sources"][0]["locator"] == {
        "site": SITE,
        "id": "1",
        "type": "page",
    }

    assert read_index(_holding(entry)) == index
    entry["sources"] = []
    orphaned = read_index(_holding(entry))
    assert all(not doc.source and not doc.key and not doc.version for doc in orphaned.documents)
    entry["documents"][1]["parent"] = "../../etc"
    entry["sources"] = write_index(index)["sources"]
    assert read_index(_holding(entry)).documents[1].parent == ""


# -- the migration ------------------------------------------------------------------------------


def _migrated(entry):
    """The entry as an open would leave it: every migration from its stamp to ours."""
    brought = migrated(entry, DATA_FORMAT)
    assert brought is not None
    return brought


def test_format_5_tells_the_two_confluence_kinds_apart_by_the_locator():
    entry = {
        "format": 4,
        "sources": [
            {"id": "src1", "kind": "confluence", "locator": {"id": "1", "type": "page"}},
            {"id": "src2", "kind": "confluence", "locator": {"id": "2", "type": "folder"}},
        ],
    }
    kinds = [source["kind"] for source in _migrated(entry)["sources"]]
    assert kinds == ["confluence_page", "confluence_folder"]


def test_format_5_leaves_another_builds_kind_alone_and_survives_a_ragged_entry():
    entry = {
        "format": 4,
        "sources": [
            {"id": "src1", "kind": "wiki", "locator": {"type": "folder"}},
            {"id": "src2", "kind": "confluence"},  # No locator at all: a page by default.
            "not a source at all",
        ],
    }
    sources = _migrated(entry)["sources"]
    assert [entry if isinstance(entry, str) else entry["kind"] for entry in sources] == [
        "wiki",
        "confluence_page",
        "not a source at all",
    ]


def test_format_5_passes_a_step_entry_through_untouched():
    # One format covers the project's index and a step's figures; only one has sources.
    step = {"format": 4, "attachments": [{"file": "assets/abc.png"}]}
    assert _migrated(step)["attachments"] == step["attachments"]
    assert _migrated(step)["format"] == 5
    assert _migrated({"format": 4}) == {}  # Nothing to store still leaves no file behind.


# -- the terminal -------------------------------------------------------------------------------


@pytest.fixture
def sourced(cli, tmp_path, workspace):
    """A project whose index carries a fetched source, written the way the window writes
    it — the CLI never fetches, so the test applies a snapshot straight into the file."""
    cli("project", "create", "Search rewrite")
    cli("spec", "import", "Search rewrite", source(tmp_path, "own.md", "# Own"))
    index_path = next(workspace.glob("*/modules/spec.json"))
    index = read_index(_holding(json.loads(index_path.read_text())))
    area = ModuleFileArea(LocalStorage(index_path.parent.parent), "modules/spec", lambda _p: None)
    index, src = add_source(
        index, "confluence_page", "Auth", {"site": SITE, "id": "1", "type": "page"}
    )
    snapshot = Snapshot(
        documents=(page("1", "Auth Overview", "# Auth\n"), page("2", "Tokens", "# T\n", parent="1"))
    )
    index, _ = apply_snapshot(area, index, src.id, snapshot, "2026-09-07")
    index_path.write_text(json.dumps(write_index(index)))
    return "Search rewrite"


def test_list_prints_the_tree_and_json_carries_the_source_facts(cli, sourced):
    text = cli("spec", "list", sourced)
    assert text.splitlines()[0].startswith("own")
    # The kind id and the locator: the terminal cannot reach a kind to word one.
    assert f"[confluence_page] Auth  (src1, fetched 2026-09-07)  site={SITE} id=1 type=page" in text
    assert "\n  auth-overview — Auth Overview" in text and "\n    tokens" in text
    listed = data(cli("spec", "list", sourced, "--json"))
    assert listed["sources"] == [
        {
            "id": "src1",
            "kind": "confluence_page",
            "title": "Auth",
            "locator": {"site": SITE, "id": "1", "type": "page"},
            "fetched": "2026-09-07",
            "documents": 2,
        }
    ]
    tokens = next(doc for doc in listed["documents"] if doc["name"] == "tokens")
    assert (tokens["source"], tokens["key"], tokens["parent"], tokens["title"]) == (
        "src1",
        "2",
        "auth-overview",
        "Tokens",
    )
    assert "source" not in listed["documents"][0]


def test_a_sourced_document_is_shown_and_diffed_like_any_other(cli, sourced):
    assert cli("spec", "show", sourced, "tokens").strip() == "# T"
    assert cli("spec", "show", sourced, "Auth Overview").strip() == "# Auth"  # By title too.


def test_a_sourced_document_refuses_import_and_remove_with_a_pointer(cli, sourced, tmp_path):
    out = cli(
        "spec", "import", sourced, source(tmp_path, "x.md", "# X"), "--name", "tokens", expect=1
    )
    assert "belongs to the source 'Auth'" in out and "Specs tab" in out
    out = cli("spec", "remove", sourced, "tokens", expect=1)
    assert "belongs to the source 'Auth'" in out
    assert "tokens" in cli("spec", "list", sourced)


def test_lint_names_a_source_never_fetched(cli, tmp_path, workspace):
    cli("project", "create", "Search rewrite")
    cli("spec", "import", "Search rewrite", source(tmp_path, "own.md", "# Own"))
    index_path = next(workspace.glob("*/modules/spec.json"))
    index, _src = add_source(
        read_index(_holding(json.loads(index_path.read_text()))),
        "confluence",
        "Auth",
        {"site": SITE, "id": "1", "type": "page"},
    )
    index_path.write_text(json.dumps(write_index(index)))
    out = cli("project", "lint", "Search rewrite", expect=1)
    assert "source 'Auth' (confluence) has never been fetched" in out


# -- what a surface says ------------------------------------------------------------------------


def test_freshness_is_worded_once_in_documents_not_pages():
    """Three of the four kinds have no pages; this is the one place the word is chosen."""
    assert freshness_words(Freshness()) == ""
    assert freshness_words(Freshness(changed=("a",))) == (
        "1 document changed at the source — Refresh to take them in"
    )
    assert freshness_words(Freshness(changed=("a",), added=("b",), removed=("c",))) == (
        "2 documents changed, 1 gone at the source — Refresh to take them in"
    )
    assert freshness_words(Freshness(removed=("c",))) == (
        "1 gone at the source — Refresh to take them in"
    )


def test_updates_are_counted_across_the_sources_that_have_them():
    assert updates_words([]) == "" and updates_words([Freshness()]) == ""
    assert updates_words([Freshness(changed=("a",)), Freshness()]) == (
        "1 document changed in 1 source — Refresh All to take them in"
    )
    assert updates_words([Freshness(added=("a", "b")), Freshness(removed=("c",))]) == (
        "2 documents changed, 1 gone in 2 sources — Refresh All to take them in"
    )


def test_a_locator_prints_as_one_greppable_line():
    assert locator_line({"id": "1", "site": SITE, "type": "page"}) == (
        f"site={SITE} id=1 type=page"
    )
    assert locator_line({"path": "/home/knut/specs"}) == "path=/home/knut/specs"
    assert locator_line({"zebra": "z", "url": "u", "alpha": "a"}) == "url=u alpha=a zebra=z"
    assert locator_line({}) == ""
