"""One contract, every provider.

The point of the storage layer is that a feature written against
:class:`~dplanner.core.storage.provider.StorageProvider` works on any backend. That claim is
only as good as the test that checks it, so this file is written once and parametrized over
all three shipped providers — and a fourth provider is proven the day it is added to
``PROVIDERS`` below.

The git provider runs against a throwaway repository, and the GitHub one against a local
bare repo standing in for the remote: no network, no credentials, and the same assertions.
Tests that genuinely need ``gh`` skip when it is absent rather than failing on a machine
that has never installed it.
"""

import subprocess

import pytest

from dplanner.core.storage.git import GitStorage
from dplanner.core.storage.github import GitHubStorage
from dplanner.core.storage.local import LocalStorage
from dplanner.core.storage.locations import repo_storage
from dplanner.core.storage.provider import RemoteStorage, StorageProvider, VersionedStorage


def _git(*args: str, cwd) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", "-b", "main", cwd=path)
    _git("config", "user.email", "test@example.com", cwd=path)
    _git("config", "user.name", "Test", cwd=path)
    # An initial commit, so HEAD exists and `git diff HEAD` has something to compare to.
    (path / ".gitkeep").write_text("")
    _git("add", "-A", cwd=path)
    _git("commit", "-q", "-m", "init", cwd=path)


def make_local(tmp_path) -> StorageProvider:
    return LocalStorage(tmp_path / "plain")


def make_git(tmp_path) -> StorageProvider:
    repo = tmp_path / "repo"
    _init_repo(repo)
    return GitStorage(repo / "workspace")


def make_github(tmp_path) -> StorageProvider:
    """A git checkout with an origin — the same class the real thing uses.

    The "remote" is a local bare repository. Push and pull are ordinary git either way, so
    this exercises the real code path; only cloning and repository creation need ``gh``,
    and those are not part of this contract.
    """
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True)
    repo = tmp_path / "clone"
    _init_repo(repo)
    _git("remote", "add", "origin", str(bare), cwd=repo)
    _git("push", "-q", "-u", "origin", "main", cwd=repo)
    return GitHubStorage(repo / "workspace")


PROVIDERS = [
    pytest.param(make_local, id="local"),
    pytest.param(make_git, id="git"),
    pytest.param(make_github, id="github"),
]


@pytest.fixture(params=PROVIDERS)
def storage(request, tmp_path):
    return request.param(tmp_path)


# -- the contract every provider satisfies -------------------------------------------------


def test_reads_back_what_it_wrote(storage):
    storage.write_text("a/b.txt", "hello")
    assert storage.read_text("a/b.txt") == "hello"
    assert storage.exists("a/b.txt")


def test_missing_file_reads_as_none(storage):
    assert storage.read_text("nope.txt") is None
    assert not storage.exists("nope.txt")


def test_bytes_round_trip(storage):
    storage.write_bytes("blob.bin", b"\x00\x01\x02")
    assert storage.read_bytes("blob.bin") == b"\x00\x01\x02"


def test_writing_creates_parent_directories(storage):
    storage.write_text("deep/deeper/deepest.txt", "x")
    assert storage.is_dir("deep/deeper")
    assert storage.list_dir("deep") == ["deeper"]


def test_list_dir_is_sorted_and_tolerant(storage):
    storage.write_text("b.txt", "")
    storage.write_text("a.txt", "")
    assert storage.list_dir("") == ["a.txt", "b.txt"]
    assert storage.list_dir("does/not/exist") == []


def test_delete_is_idempotent(storage):
    storage.write_text("gone.txt", "x")
    storage.delete("gone.txt")
    storage.delete("gone.txt")  # Missing is not an error.
    assert not storage.exists("gone.txt")


def test_delete_leaves_a_non_empty_directory_alone(storage):
    """Deleting a directory removes it only when empty — a bug must never take a tree."""
    storage.write_text("keep/file.txt", "x")
    storage.delete("keep")
    assert storage.exists("keep/file.txt")


def test_paths_cannot_escape_the_workspace(storage):
    with pytest.raises(ValueError):
        storage.read_text("../outside.txt")
    with pytest.raises(ValueError):
        storage.write_text("/etc/passwd", "no")


def test_label_is_not_empty(storage):
    assert storage.label


# -- capabilities: what differs, and how a feature asks --------------------------------------


def test_capabilities_are_honest(storage):
    """A provider claims a capability only when it can actually deliver it."""
    versioned = isinstance(storage, VersionedStorage)
    assert versioned == isinstance(storage, GitStorage)
    if isinstance(storage, RemoteStorage):
        # Only the GitHub provider declares a remote, and only when one is configured.
        assert isinstance(storage, GitHubStorage)


def test_plain_folder_offers_no_history(tmp_path):
    """The case the sync module checks: no history, so no Save action is registered."""
    assert not isinstance(make_local(tmp_path), VersionedStorage)


# -- versioned behaviour ---------------------------------------------------------------------


@pytest.fixture
def versioned(storage) -> VersionedStorage:
    if not isinstance(storage, VersionedStorage):
        pytest.skip("provider has no history")
    return storage


def test_commit_records_a_revision(versioned):
    versioned.write_text("note.md", "first")
    assert versioned.commit("one") is True
    history = versioned.history()
    assert history[0].message == "one"
    assert history[0].author


def test_commit_with_nothing_to_do_says_so(versioned):
    versioned.write_text("note.md", "first")
    versioned.commit("one")
    assert versioned.commit("again") is False


def test_dirty_tracking_reports_changes(versioned):
    seen = []
    versioned.dirty_changed.connect(lambda dirty, count: seen.append((dirty, count)))
    versioned.refresh_dirty()
    versioned.write_text("note.md", "first")
    versioned.refresh_dirty()
    assert seen[-1] == (True, 1)
    versioned.commit("one")
    versioned.refresh_dirty()
    assert seen[-1] == (False, 0)


def test_dirty_file_count_is_askable_directly(versioned):
    """The exit dialog reads the count synchronously — it must match what refresh saw."""
    versioned.write_text("note.md", "first")
    versioned.commit("one")
    versioned.refresh_dirty()
    assert versioned.dirty_file_count() == 0
    versioned.write_text("a.md", "x")
    versioned.write_text("b.md", "y")
    versioned.refresh_dirty()
    assert versioned.dirty_file_count() == 2


def test_scopes_default_to_the_workspace_directory(versioned):
    """One repository can hold several planned directories; the scopes are the pathspecs
    every history operation is limited to, and a bare provider covers its own directory."""
    assert versioned.scopes == ("workspace",)


def test_diff_shows_an_untracked_file_as_an_addition(versioned):
    versioned.write_text("note.md", "brand new\n")
    assert "brand new" in versioned.diff()


def test_commits_are_scoped_to_the_workspace(versioned):
    """A workspace inside a bigger repository must not sweep up its neighbours."""
    outside = versioned.repo_root / "unrelated.txt"
    outside.write_text("not mine")
    versioned.write_text("note.md", "mine")
    versioned.commit("scoped")
    listing = subprocess.run(
        ["git", "-C", str(versioned.repo_root), "show", "--name-only", "--format=", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "note.md" in listing
    assert "unrelated.txt" not in listing


def test_branches_start_from_the_current_state(versioned):
    versioned.write_text("note.md", "first")
    versioned.commit("one")
    versioned.create_branch("side")
    assert versioned.current_branch() == "side"
    assert "main" in versioned.branches()
    assert "side" in versioned.branches()


def test_switching_branches_announces_the_rewritten_worktree(versioned):
    """The one inbound path: storage changed the files, so the workspace must rebuild."""
    versioned.write_text("note.md", "on main")
    versioned.commit("one")
    versioned.create_branch("side")
    versioned.write_text("note.md", "on side")
    versioned.commit("two")

    reloads = []
    versioned.worktree_changed.connect(lambda: reloads.append(True))
    versioned.switch_branch("main")
    assert reloads == [True]
    assert versioned.read_text("note.md") == "on main"


def test_switching_branches_commits_pending_work_first(versioned):
    versioned.write_text("note.md", "committed")
    versioned.commit("one")
    versioned.create_branch("side")
    versioned.write_text("note.md", "uncommitted")
    versioned.switch_branch("main")
    versioned.switch_branch("side")
    assert versioned.read_text("note.md") == "uncommitted"


def test_the_default_branch_is_protected(versioned):
    versioned.write_text("note.md", "x")
    versioned.commit("one")
    versioned.create_branch("side")
    with pytest.raises(Exception, match="protected"):
        versioned.delete_branch("main")


def test_the_checked_out_branch_cannot_be_deleted(versioned):
    versioned.write_text("note.md", "x")
    versioned.commit("one")
    versioned.create_branch("side")
    with pytest.raises(Exception, match="checked out"):
        versioned.delete_branch("side")


# -- remote behaviour ------------------------------------------------------------------------


@pytest.fixture
def remote(storage) -> RemoteStorage:
    if not isinstance(storage, RemoteStorage) or not storage.has_remote():
        pytest.skip("provider has no remote")
    return storage


def test_push_then_pull_round_trips(remote, tmp_path):
    remote.write_text("note.md", "from here")
    remote.commit("one")
    remote.push()

    # A second clone of the same "remote" sees the pushed work.
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(tmp_path / "origin.git"), str(other)], check=True)
    assert (other / "workspace" / "note.md").read_text() == "from here"


def test_pull_reports_whether_anything_arrived(remote):
    remote.write_text("note.md", "x")
    remote.commit("one")
    remote.push()
    assert remote.pull() is False  # Already up to date.


def test_remote_label_is_readable(remote):
    assert remote.remote_label()


def _second_clone(tmp_path, name="other"):
    """Another person's clone of the same remote, committing as someone else."""
    other = tmp_path / name
    subprocess.run(["git", "clone", "-q", str(tmp_path / "origin.git"), str(other)], check=True)
    _git("config", "user.email", "bo@example.com", cwd=other)
    _git("config", "user.name", "Bo", cwd=other)
    return other


def test_a_save_after_someone_elses_lands_on_top_of_theirs(remote, tmp_path):
    """Two clones of one plan repository, two Saves: the second is rebased onto the first
    and pushed, never refused for being second — and their commit is in the tree now."""
    remote.write_text("note.md", "from here")
    remote.commit("one")
    remote.push()

    other = _second_clone(tmp_path)
    (other / "workspace" / "theirs.md").write_text("from there")
    _git("add", "-A", cwd=other)
    _git("commit", "-q", "-m", "theirs", cwd=other)
    _git("push", "-q", cwd=other)

    arrived = []
    remote.worktree_changed.connect(lambda: arrived.append(True))
    remote.write_text("note.md", "from here, again")
    remote.commit("two")
    remote.push()

    assert arrived == [True]
    assert remote.read_text("theirs.md") == "from there"
    log = [rev.message for rev in remote.history(3)]
    assert log == ["two", "theirs", "one"]
    on_origin = subprocess.run(
        ["git", "log", "--format=%s", "main"],
        cwd=tmp_path / "origin.git",
        capture_output=True,
        text=True,
    )
    assert on_origin.stdout.split()[:3] == ["two", "theirs", "one"]


def test_pull_rebases_local_commits_onto_what_arrived(remote, tmp_path):
    remote.write_text("note.md", "x")
    remote.commit("one")
    remote.push()
    other = _second_clone(tmp_path)
    (other / "workspace" / "theirs.md").write_text("from there")
    _git("add", "-A", cwd=other)
    _git("commit", "-q", "-m", "theirs", cwd=other)
    _git("push", "-q", cwd=other)

    remote.write_text("mine.md", "local, unpushed")
    remote.commit("mine")
    assert remote.pull() is True
    assert [rev.message for rev in remote.history(3)] == ["mine", "theirs", "one"]
    assert remote.read_text("theirs.md") == "from there"


def test_a_conflicting_save_is_refused_and_leaves_the_tree_as_it_was(remote, tmp_path):
    remote.write_text("note.md", "from here")
    remote.commit("one")
    remote.push()
    other = _second_clone(tmp_path)
    (other / "workspace" / "note.md").write_text("from there")
    _git("add", "-A", cwd=other)
    _git("commit", "-q", "-m", "theirs", cwd=other)
    _git("push", "-q", cwd=other)

    remote.write_text("note.md", "from here, changed")
    remote.commit("two")
    remote.write_text("draft.md", "not yet committed")
    with pytest.raises(Exception, match="same lines"):
        remote.push()
    assert remote.read_text("note.md") == "from here, changed"
    assert remote.read_text("draft.md") == "not yet committed"  # The autostash came back.
    assert [rev.message for rev in remote.history(2)] == ["two", "one"]
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=tmp_path / "clone", capture_output=True, text=True
    ).stdout
    assert "rebase" not in status  # No rebase left in progress.


# -- a provider over a whole repository ------------------------------------------------------


def test_repo_storage_commits_only_its_scopes(tmp_path):
    """The constructor moving a plan uses: a commit at the root that sweeps up exactly the
    directories it was scoped to, and nothing beside them."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "plans").mkdir()
    (repo / "plans" / "a.txt").write_text("plan")
    (repo / "src").mkdir()
    (repo / "src" / "b.txt").write_text("code")
    scoped = repo_storage(repo, ["plans"])
    assert isinstance(scoped, VersionedStorage)
    assert scoped.commit("plans only") is True
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout
    assert "src/" in status and "plans/" not in status
    assert scoped.history(1)[0].message == "plans only"


def test_repo_storage_over_a_checkout_with_an_origin_has_the_remote(tmp_path):
    make_github(tmp_path)
    whole = repo_storage(tmp_path / "clone")
    assert isinstance(whole, RemoteStorage) and whole.has_remote()
