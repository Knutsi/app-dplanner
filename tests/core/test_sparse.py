"""The sparse clone door over a real repository served from tmp_path: what it clones, what
it refuses before downloading anything, how it tells the remote has moved, and the shell
it runs git in. No network, and no test reads the developer's git configuration.

The remote helper is ``tests/modules/spec_git_helpers.py``'s — the spec kind is the door's
first reader, and one ``file://`` bare repository serves both suites."""

import hashlib

import pytest
from tests.modules.spec_git_helpers import clean_git, git, make_remote  # noqa: F401

from dplanner.core.storage import sparse
from dplanner.core.storage.locations import canonical_remote
from dplanner.core.storage.sparse import (
    MAX_DOCUMENTS,
    Folder,
    GitError,
    SparseClone,
    folders,
    parse_url,
    refusal,
    sparse_dir,
    valid_path,
    valid_ref,
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


def is_markdown(key: str) -> bool:
    """The door counts what a caller's predicate picks; this suite's is the plainest one."""
    return key.endswith(".md")


@pytest.fixture
def remote(tmp_path, clean_git):  # noqa: F811
    return make_remote(tmp_path, TREE)


@pytest.fixture
def cache(tmp_path):
    return tmp_path / "checkouts"


def clone(remote, cache, path="docs/spec", ref="main") -> SparseClone:
    return SparseClone(cache, remote.url, ref, path)


def taken(remote, cache, **kwargs) -> tuple[SparseClone, str, list[tuple[str, str]]]:
    """Trees brought, listed, and the folder checked out: (clone, commit, rows)."""
    made = clone(remote, cache, **kwargs)
    commit, _notes = made.bring_trees()
    rows = made.tree(commit)
    made.materialise(commit)
    return made, commit, rows


# -- the clone -----------------------------------------------------------------------------------


def test_the_clone_is_shallow_blobless_and_sparse_to_the_folder(remote, cache):
    """The guard measures a tree; if the filter were quietly ignored the whole repository
    would already be on disk by the time it ran."""
    remote.commit({"docs/spec/later.md": "# Later\n"}, "second")
    made, _commit, _rows = taken(remote, cache)
    assert git("-C", str(made.directory), "rev-list", "--count", "HEAD").strip() == "1"
    missing = git("-C", str(made.directory), "rev-list", "--objects", "--all", "--missing=print")
    assert "?" in missing  # Blobs the clone deliberately does not have.
    assert (made.directory / "docs" / "spec" / "auth.md").is_file()
    assert not (made.directory / "big").exists()  # Sparse: nothing outside the folder landed.


def test_the_trees_alone_bring_no_file_down(remote, cache):
    made = clone(remote, cache)
    commit, _notes = made.bring_trees()
    rows = made.tree(commit)
    assert {key for _oid, key in rows} == {"README.md", "auth.md", "images/flow.png", "tokens.md"}
    assert not (made.directory / "docs").exists()  # Nothing was checked out.


def test_the_cache_directory_is_the_digest_of_remote_ref_and_folder(remote, cache):
    """The digest is an on-disk contract: a cache made before the door moved to core must
    still be found by the door after it."""
    made, _commit, _rows = taken(remote, cache)
    key = f"{canonical_remote(remote.url)}\nmain\ndocs/spec"
    expected = cache / hashlib.sha256(key.encode()).hexdigest()[:16]
    assert made.directory == expected and (expected / ".git").is_dir()
    assert sparse_dir(cache, remote.url, "main", "docs/spec") == expected
    assert sparse_dir(cache, remote.url, "main", "") != expected
    assert sparse_dir(cache, "https://github.com/Acme/Widget.git", "main", "d") == sparse_dir(
        cache, "git@github.com:acme/widget", "main", "d"
    )


def test_a_version_is_the_blob_id_and_moves_only_for_what_changed(remote, cache):
    _made, _commit, before = taken(remote, cache)
    remote.commit({"docs/spec/auth.md": "# Auth\n\nmore\n"}, "edit")
    _made, _commit, after = taken(remote, cache)
    was, now = dict(_flip(before)), dict(_flip(after))
    assert now["auth.md"] != was["auth.md"]
    assert now["tokens.md"] == was["tokens.md"]
    assert all(len(oid) == 40 for oid in now.values())


def _flip(rows):
    return [(key, oid) for oid, key in rows]


def test_a_tag_and_a_commit_id_are_both_fetchable(remote, cache):
    head = git("-C", str(remote.work), "rev-parse", "HEAD").strip()
    remote.tag("v1")
    remote.commit({"docs/spec/after.md": "# After\n"}, "after the tag")
    for ref in ("v1", head):
        _made, _commit, rows = taken(remote, cache, ref=ref)
        assert sorted(key for _oid, key in rows if is_markdown(key)) == [
            "README.md",
            "auth.md",
            "tokens.md",
        ]
    assert clone(remote, cache, ref=head).pinned and not clone(remote, cache).pinned


def test_the_default_ref_is_the_remotes_default_branch(remote, cache):
    made = clone(remote, cache, ref=sparse.DEFAULT_REF)
    commit, _notes = made.bring_trees()
    assert commit == git("-C", str(remote.work), "rev-parse", "HEAD").strip()


# -- the guard -----------------------------------------------------------------------------------


def test_the_listing_says_what_each_folder_would_cost(remote, cache):
    made = clone(remote, cache, path="")
    commit, _notes = made.bring_trees()
    found = folders(made.tree(commit), is_markdown)
    holds = {folder.path: (folder.files, folder.documents) for folder in found}
    assert holds[""] == (7, 5)
    assert holds["docs/spec"] == (4, 3)
    assert found[0].path == "" and found[0].label == "the whole repository"
    assert all(not folder.refusal for folder in found)


def test_a_folder_over_the_cap_says_so_and_names_itself(monkeypatch):
    monkeypatch.setattr(sparse, "MAX_DOCUMENTS", 3)
    whole = Folder(path="", files=7, documents=5)
    assert whole.refusal == "the whole repository holds 5 documents — pick a folder inside it"
    assert not Folder(path="docs/spec", files=4, documents=3).refusal
    monkeypatch.setattr(sparse, "MAX_FILES", 3)
    assert Folder(path="docs", files=4, documents=1).refusal == (
        "docs holds 4 files — pick a folder inside it"
    )
    assert MAX_DOCUMENTS  # The real cap is a module constant, not a number in a call.


# -- has the remote moved ------------------------------------------------------------------------


def test_the_heads_agree_until_the_remote_moves(remote, cache):
    made, commit, _rows = taken(remote, cache)
    assert made.local_head() == commit == made.remote_head()
    moved = remote.commit({"docs/spec/new.md": "# New\n"}, "more")
    assert made.remote_head() == moved != made.local_head()


def test_an_annotated_tag_answers_with_the_commit_it_points_at(remote, cache):
    head = git("-C", str(remote.work), "rev-parse", "HEAD").strip()
    remote.tag("v1")
    assert clone(remote, cache, ref="v1").remote_head() == head


def test_a_remote_that_cannot_be_asked_is_no_answer_rather_than_a_refusal(cache):
    assert SparseClone(cache, "file:///nowhere/at/all.git").remote_head() == ""
    assert SparseClone(cache, "file:///nowhere/at/all.git").local_head() == ""


# -- the address ---------------------------------------------------------------------------------


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


def test_a_ref_and_a_folder_are_checked_by_character_set():
    assert valid_ref("main") and valid_ref("v1.2") and valid_ref("release/2026")
    for bad in ("--upload-pack=x", "main/../evil", "a.lock", "refs/", "a@{1}", ""):
        assert not valid_ref(bad)
    assert valid_path("") and valid_path("docs/spec")
    for bad in ("../../etc", "docs/*", "docs/[a]", "-x"):
        assert not valid_path(bad)


def test_nothing_reaches_git_through_an_unchecked_position(cache):
    """A clone validates all three on construction, so a caller cannot forget to."""
    with pytest.raises(ValueError, match="out of the address"):
        SparseClone(cache, "https://me:secret@github.com/acme/handbook.git")
    with pytest.raises(ValueError, match="branch or tag"):
        SparseClone(cache, "https://github.com/acme/handbook.git", "main/../evil")
    with pytest.raises(ValueError, match="folder"):
        SparseClone(cache, "https://github.com/acme/handbook.git", "main", "docs/*")


# -- the shell it runs in ------------------------------------------------------------------------


def test_the_subprocess_can_never_be_asked_for_a_password(monkeypatch):
    monkeypatch.setenv("GIT_DIR", "/somebody/elses/repo/.git")
    env = sparse.environment()
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_ASKPASS"] == "" and env["SSH_ASKPASS"] == ""
    assert env["SSH_ASKPASS_REQUIRE"] == "never"
    assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]
    assert "GIT_DIR" not in env  # A shell that carried one would aim every call elsewhere.


def test_one_transport_is_allowed_and_it_is_the_address_s(tmp_path):
    args = sparse.hardening("https", tmp_path / "no-hooks")
    assert "protocol.allow=never" in args and "protocol.https.allow=always" in args
    assert "core.symlinks=false" in args
    assert any(arg.startswith("core.hooksPath=") for arg in args)


def test_a_refusal_is_one_sentence_and_never_quotes_git(cache, clean_git):  # noqa: F811
    """git's own stderr can carry the address it was given; the sentence a person reads is
    composed from what went wrong, never copied out of it."""
    gone = SparseClone(cache, "file:///nowhere/at/all.git")
    with pytest.raises(GitError) as failed:
        gone.bring_trees()
    said = refusal(failed.value, gone.url, gone.ref)
    assert "fatal" not in said.sentence and "\n" not in said.sentence
    assert "access rights" not in said.sentence
    timed = refusal(GitError("fetch", "timed out", timed_out=True), gone.url, gone.ref)
    assert timed.sentence.endswith("did not answer in time") and not timed.fixable_here
    denied = refusal(GitError("fetch", "Authentication failed for x"), gone.url, gone.ref)
    assert denied.fixable_here  # Somebody at this computer can clear it.


def test_cancelling_stops_the_fetch(remote, cache, monkeypatch):
    """Cancel is read between polls, so the poll is made shorter than a clone takes."""
    monkeypatch.setattr(sparse, "POLL_S", 0.0001)
    with pytest.raises(GitError) as stopped:
        clone(remote, cache).bring_trees(cancelled=lambda: True)
    assert not stopped.value.timed_out
    assert not clone(remote, cache).directory.exists()  # A killed clone lands nothing.


# -- the cache -----------------------------------------------------------------------------------


def test_a_half_written_cache_is_rebuilt(remote, cache):
    made, _commit, _rows = taken(remote, cache)
    (made.directory / ".git" / "config").write_text("nonsense\n")
    _made, _commit, rows = taken(remote, cache)
    assert sorted(key for _oid, key in rows if is_markdown(key)) == [
        "README.md",
        "auth.md",
        "tokens.md",
    ]


def test_a_directory_holding_another_repository_is_rebuilt(remote, cache):
    made, _commit, _rows = taken(remote, cache)
    git("-C", str(made.directory), "remote", "set-url", "origin", "file:///somewhere/else.git")
    _made, _commit, rows = taken(remote, cache)  # Dropped and cloned again, not fetched from.
    assert rows


def test_a_clone_nothing_has_used_in_a_month_is_dropped(remote, cache, monkeypatch):
    made, _commit, _rows = taken(remote, cache)
    stale = cache / "0123456789abcdef"
    stale.mkdir(parents=True)
    monkeypatch.setattr(sparse, "CACHE_DAYS", -1)
    made.sweep()
    assert not stale.exists() and made.directory.is_dir()  # Its own is never swept.
