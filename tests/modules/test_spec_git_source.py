"""The git kind's engine over a real repository served from tmp_path: what it clones, what
it refuses before downloading anything, and how it tells the remote has moved. No network,
and no test reads the developer's git configuration."""

import pytest
from tests.modules.spec_git_helpers import clean_git, git, make_remote  # noqa: F401

from dplanner.domain.document_source import SourceUnavailableError
from dplanner.modules.spec_git import client, source
from dplanner.modules.spec_git.source import (
    MAX_DOCUMENTS,
    cache_dir,
    check,
    fetch,
    open_url,
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


def test_the_clone_is_shallow_and_blobless(remote, cache):
    """The guard measures a tree; if the filter were quietly ignored the whole repository
    would already be on disk by the time it ran."""
    remote.commit({"docs/spec/later.md": "# Later\n"}, "second")
    taken(remote, cache)
    directory = cache_dir(cache, locator(remote))
    assert git("-C", str(directory), "rev-list", "--count", "HEAD").strip() == "1"
    missing = git("-C", str(directory), "rev-list", "--objects", "--all", "--missing=print")
    assert "?" in missing  # Blobs the clone deliberately does not have.
    assert not (directory / "big").exists()  # Sparse: nothing outside the folder landed.


def test_the_cache_lives_under_the_root_it_was_handed(remote, cache):
    taken(remote, cache)
    assert (cache_dir(cache, locator(remote)) / ".git").is_dir()
    assert cache_dir(cache, locator(remote)) != cache_dir(cache, locator(remote, path=""))


def test_a_version_is_the_blob_id_and_moves_only_for_what_changed(remote, cache):
    before = {d.key: d.version for d in taken(remote, cache).documents}
    remote.commit({"docs/spec/auth.md": "# Auth\n\nmore\n"}, "edit")
    after = {d.key: d.version for d in taken(remote, cache).documents}
    assert after["auth.md"] != before["auth.md"]
    assert after["tokens.md"] == before["tokens.md"]
    assert all(len(version) == 40 for version in after.values())


def test_a_tag_and_a_commit_id_are_both_fetchable(remote, cache):
    head = git("-C", str(remote.work), "rev-parse", "HEAD").strip()
    remote.tag("v1")
    remote.commit({"docs/spec/after.md": "# After\n"}, "after the tag")
    for ref in ("v1", head):
        snapshot = taken(remote, cache, ref=ref)
        assert [d.key for d in snapshot.documents] == ["README.md", "auth.md", "tokens.md"]


# -- the guard -----------------------------------------------------------------------------------


def test_a_folder_over_the_cap_is_refused_before_a_blob_is_downloaded(remote, cache, monkeypatch):
    monkeypatch.setattr(source, "MAX_DOCUMENTS", 2)
    with pytest.raises(SourceUnavailableError, match="Pick a folder inside it"):
        taken(remote, cache)
    directory = cache_dir(cache, locator(remote))
    assert not (directory / "docs").exists()  # Nothing was checked out.


def test_the_listing_says_what_each_folder_would_cost(remote, cache):
    found = probe(cache, remote.url, "main")
    holds = {folder.path: (folder.files, folder.documents) for folder in found.folders}
    assert holds[""] == (7, 5)
    assert holds["docs/spec"] == (4, 3)
    assert found.folders[0].path == "" and found.folders[0].label == "the whole repository"
    assert all(not folder.refusal for folder in found.folders)


def test_a_folder_that_would_be_refused_says_so_while_it_is_being_chosen(
    remote, cache, monkeypatch
):
    monkeypatch.setattr(source, "MAX_DOCUMENTS", 2)
    found = probe(cache, remote.url, "main")
    whole = next(folder for folder in found.folders if folder.path == "")
    assert f"more than the {2:,}" in whole.refusal and "Pick a folder inside it" in whole.refusal
    assert MAX_DOCUMENTS  # The real cap is a module constant, not a magic number in a call.


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


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("--upload-pack=sh", "cannot start with a dash"),
        ("https://host/a b", "no spaces"),
        ("http://host/repo", "https address"),
        ("git://host/repo", "unauthenticated"),
        ("ext::sh -c whoami", "no spaces"),
        ("ftp://host/repo", "https, ssh and file"),
        ("/home/me/repo", "Folder source"),
        ("~/repo", "Folder source"),
        ("./repo", "Folder source"),
        ("https://me:secret@host/repo", "out of the address"),
        ("git@host:", "names no repository"),
        ("", "paste the address"),
    ],
)
def test_an_address_that_cannot_be_used_says_why(text, reason):
    with pytest.raises(ValueError, match=reason):
        parse_url(text)


def test_the_addresses_a_host_hands_out_are_taken(remote):
    for address in (
        "https://github.com/acme/handbook.git",
        "ssh://git@gitlab.acme.dev/spec/handbook",
        "git@github.com:acme/handbook",
        remote.url,
    ):
        assert parse_url(address) == address


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


def test_open_url_is_a_browse_address_when_the_host_has_one():
    assert (
        open_url({"url": "git@github.com:acme/handbook.git", "ref": "main", "path": "docs/spec"})
        == "https://github.com/acme/handbook/tree/main/docs/spec"
    )
    assert open_url({"url": "file:///srv/x.git", "ref": "main", "path": ""}) == ""


# -- the shell it runs in ------------------------------------------------------------------------


def test_the_subprocess_can_never_be_asked_for_a_password(monkeypatch):
    monkeypatch.setenv("GIT_DIR", "/somebody/elses/repo/.git")
    env = client.environment()
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_ASKPASS"] == "" and env["SSH_ASKPASS"] == ""
    assert env["SSH_ASKPASS_REQUIRE"] == "never"
    assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]
    assert "GIT_DIR" not in env  # A shell that carried one would aim every call elsewhere.


def test_one_transport_is_allowed_and_it_is_the_address_s(tmp_path):
    args = client.hardening("https", tmp_path / "no-hooks")
    assert "protocol.allow=never" in args and "protocol.https.allow=always" in args
    assert "core.symlinks=false" in args
    assert any(arg.startswith("core.hooksPath=") for arg in args)


def test_a_refusal_is_one_sentence_and_never_quotes_git(cache):
    """git's own stderr can carry the address it was given; the sentence a person reads is
    composed from what went wrong, never copied out of it."""
    gone = {"url": "file:///nowhere/at/all.git", "ref": "main", "path": ""}
    with pytest.raises(SourceUnavailableError) as refused:
        fetch(cache, gone, {}, lambda _f: None, lambda: False)
    said = str(refused.value)
    assert "fatal" not in said and "\n" not in said and "access rights" not in said


def test_an_address_can_never_carry_a_credential_into_the_plan():
    """The refusal is at the door: a plan is shared, so a password can never be stored."""
    with pytest.raises(ValueError, match="out of the address"):
        parse_url("https://me:secret@github.com/acme/handbook.git")
    assert valid_locator({"url": "https://me:s@h/r", "ref": "main", "path": ""}) is None


# -- the cache ----------------------------------------------------------------------------------


def test_a_half_written_cache_is_rebuilt(remote, cache):
    taken(remote, cache)
    directory = cache_dir(cache, locator(remote))
    (directory / ".git" / "config").write_text("nonsense\n")
    assert [d.key for d in taken(remote, cache).documents] == [
        "README.md",
        "auth.md",
        "tokens.md",
    ]


def test_a_directory_holding_another_repository_is_rebuilt(remote, cache, tmp_path):
    taken(remote, cache)
    directory = cache_dir(cache, locator(remote))
    git("-C", str(directory), "remote", "set-url", "origin", "file:///somewhere/else.git")
    assert taken(remote, cache).documents  # Dropped and cloned again, not fetched from.


def test_a_checkout_nothing_has_used_in_a_month_is_dropped(remote, cache, monkeypatch):
    taken(remote, cache)
    stale = cache / "0123456789abcdef"
    stale.mkdir(parents=True)
    monkeypatch.setattr(source, "CACHE_DAYS", -1)
    taken(remote, cache)
    assert not stale.exists() and cache_dir(cache, locator(remote)).is_dir()


def test_cancelling_stops_the_fetch(remote, cache):
    with pytest.raises(SourceUnavailableError):
        fetch(cache, locator(remote), {}, lambda _f: None, lambda: True)
