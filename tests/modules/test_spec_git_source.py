"""The git kind over the clone door, against a real repository served from tmp_path: what a
fetch turns into a Snapshot, what a check turns into a Freshness, and the locator it keeps
in the spec index. The door itself — the clone, the guard, the shell — is
``tests/core/test_sparse.py``'s. No network, and no test reads the developer's git
configuration."""

import pytest
from tests.modules.spec_git_helpers import clean_git, git, make_remote  # noqa: F401

from dplanner.core.storage import sparse
from dplanner.domain.document_source import SourceUnavailableError
from dplanner.modules.spec_git.source import (
    browse_url,
    cache_dir,
    check,
    fetch,
    parse_url,
    probe,
    valid_locator,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels"

TREE: dict[str, bytes | str] = {
    "README.md": "# Handbook\n",
    "big/one.bin": b"\x00" * 8,
    "docs/notes.md": "# Notes\n",
    "docs/spec/README.md": "# Spec\n",
    "docs/spec/auth.md": "# Auth\n\n![flow](images/flow.png)\n",
    "docs/spec/images/flow.png": PNG,
    "docs/spec/tokens.md": "# Tokens\n",
}


@pytest.fixture
def remote(tmp_path, clean_git):  # noqa: F811
    return make_remote(tmp_path, TREE)


@pytest.fixture
def cache(tmp_path):
    return tmp_path / "spec-git"


def locator(remote, path="docs/spec", ref="main"):
    return {"url": remote.url, "ref": ref, "path": path}


def taken(remote, cache, **kwargs):
    return fetch(cache, locator(remote, **kwargs), {}, lambda _f: None, lambda: False)


# -- the fetch -----------------------------------------------------------------------------------


def test_a_fetch_imports_only_the_chosen_folder(remote, cache):
    snapshot = taken(remote, cache)
    assert [document.key for document in snapshot.documents] == [
        "README.md",
        "auth.md",
        "tokens.md",
    ]
    auth = snapshot.documents[1]
    assert auth.parent_key == "README.md"
    assert "assets/" in auth.data.decode() and [i.data for i in snapshot.images] == [PNG]


def test_the_cache_is_the_doors_directory_for_the_locator(remote, cache):
    taken(remote, cache)
    directory = cache_dir(cache, locator(remote))
    assert directory == sparse.sparse_dir(cache, remote.url, "main", "docs/spec")
    assert (directory / ".git").is_dir() and not (directory / "big").exists()


def test_a_documents_version_is_its_blob_id_and_moves_only_when_it_changed(remote, cache):
    before = {d.key: d.version for d in taken(remote, cache).documents}
    remote.commit({"docs/spec/auth.md": "# Auth\n\nmore\n"}, "edit")
    after = {d.key: d.version for d in taken(remote, cache).documents}
    assert after["auth.md"] != before["auth.md"]
    assert after["tokens.md"] == before["tokens.md"]
    assert all(len(version) == 40 for version in after.values())


# -- the guard -----------------------------------------------------------------------------------


def test_a_folder_over_the_cap_is_refused_before_a_blob_is_downloaded(remote, cache, monkeypatch):
    monkeypatch.setattr(sparse, "MAX_DOCUMENTS", 2)
    with pytest.raises(SourceUnavailableError, match="pick a folder inside it"):
        taken(remote, cache)
    directory = cache_dir(cache, locator(remote))
    assert not (directory / "docs").exists()  # Nothing was checked out.


def test_the_listing_counts_documents_by_the_walks_own_rule(remote, cache):
    """A picture beside a page is a file and not a document, for the listing as for the walk."""
    found = probe(cache, remote.url, "main")
    holds = {folder.path: (folder.files, folder.documents) for folder in found.folders}
    assert holds[""] == (7, 5)
    assert holds["docs/spec"] == (4, 3)
    assert found.ref == "main" and probe(cache, remote.url, "").ref == sparse.DEFAULT_REF


def test_a_listing_refuses_a_ref_it_cannot_read(cache):
    with pytest.raises(SourceUnavailableError, match="branch or tag"):
        probe(cache, "https://github.com/acme/handbook.git", "--upload-pack=x")


# -- the check -----------------------------------------------------------------------------------


def test_check_names_what_moved_from_the_trees_alone(remote, cache):
    known = {d.key: d.version for d in taken(remote, cache).documents}
    remote.commit({"docs/spec/auth.md": "# Auth\n\nmore\n", "docs/spec/new.md": "# New\n"})
    remote.remove("docs/spec/tokens.md")
    found = check(cache, locator(remote), known)
    assert found.changed == ("auth.md",)
    assert found.added == ("new.md",)
    assert found.removed == ("tokens.md",)


def test_check_is_silent_while_the_remote_has_not_moved(remote, cache):
    known = {d.key: d.version for d in taken(remote, cache).documents}
    assert not check(cache, locator(remote), known).stale


def test_a_pinned_commit_is_never_stale_and_asks_nobody(remote, cache):
    head = git("-C", str(remote.work), "rev-parse", "HEAD").strip()
    gone = {"url": "file:///nowhere/at/all.git", "ref": head, "path": ""}
    assert not check(cache, gone, {"a.md": "x"}).stale


# -- the locator ---------------------------------------------------------------------------------


def test_a_locator_from_a_colleagues_plan_is_re_validated():
    good = {"url": "https://github.com/acme/handbook.git", "ref": "main", "path": "docs"}
    assert valid_locator(good) == good
    for bad in (
        {**good, "path": "../../etc"},
        {**good, "path": "docs/*"},
        {**good, "ref": "--upload-pack=x"},
        {**good, "ref": "main/../evil"},
        {**good, "url": "ext::sh -c whoami"},
        {**good, "ref": 7},
        {"url": good["url"]},
    ):
        assert valid_locator(bad) is None


def test_the_browse_address_is_https_when_the_host_has_one():
    assert (
        browse_url({"url": "git@github.com:acme/handbook.git", "ref": "main", "path": "docs/spec"})
        == "https://github.com/acme/handbook/tree/main/docs/spec"
    )
    assert (
        browse_url({"url": "ssh://git@gitlab.acme.dev:22/spec/handbook", "ref": "v1", "path": ""})
        == "https://gitlab.acme.dev/spec/handbook/tree/v1"
    )
    assert browse_url({"url": "file:///srv/x.git", "ref": "main", "path": ""}) == ""


def test_an_address_can_never_carry_a_credential_into_the_plan():
    """The refusal is at the door: a plan is shared, so a password can never be stored."""
    with pytest.raises(ValueError, match="out of the address"):
        parse_url("https://me:secret@github.com/acme/handbook.git")
    assert valid_locator({"url": "https://me:s@h/r", "ref": "main", "path": ""}) is None


# -- what a person reads -------------------------------------------------------------------------


def test_a_refusal_is_one_sentence_and_never_quotes_git(cache, clean_git):  # noqa: F811
    """git's own stderr can carry the address it was given; the sentence a person reads is
    composed from what went wrong, never copied out of it."""
    gone = {"url": "file:///nowhere/at/all.git", "ref": "main", "path": ""}
    with pytest.raises(SourceUnavailableError) as refused:
        fetch(cache, gone, {}, lambda _f: None, lambda: False)
    said = str(refused.value)
    assert "fatal" not in said and "\n" not in said and "access rights" not in said


def test_cancelling_stops_the_fetch(remote, cache):
    with pytest.raises(SourceUnavailableError):
        fetch(cache, locator(remote), {}, lambda _f: None, lambda: True)
