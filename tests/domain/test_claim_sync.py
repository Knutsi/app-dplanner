"""The git half of a claim (``domain/claim_sync.py``): committed alone, pushed, ranked by the
order its file arrived, and renewed on the slow clock. The remote is a local bare repository."""

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from dplanner.domain import claim_sync, claims, ledger
from dplanner.domain.model import now_stamp

WORKER = {"machine": "m1", "host": "knut-arch"}


def _found(project, id_: str) -> claims.Claim:
    claim = claims.find(project, id_)
    assert claim is not None
    return claim


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    (path / ".gitkeep").write_text("")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    return path


@pytest.fixture
def plan(tmp_path) -> Path:
    """A project directory in a clone whose origin is a bare repository."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    repo = _repo(tmp_path / "clone")
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "-u", "origin", "main")
    project = repo / "widget"
    project.mkdir()
    return project


def _taken(project: Path, *steps: str, **fields) -> claims.Claim:
    claim = replace(
        claims.claimed("p1", "kettle", steps or ("s1",), now_stamp(), worker=WORKER), **fields
    )
    claims.write(project, claim)
    return claim


def test_a_publish_commits_the_claims_alone_and_pushes_them(plan, tmp_path):
    claim = _taken(plan)
    dproj = plan / "project.dproj"
    dproj.write_text("{}", encoding="utf-8")  # Unsaved plan work, never tracked.
    _git(plan, "add", "--", "project.dproj")  # Even staged, it stays out of the claim's commit.
    config = tmp_path / "config"
    assert claim_sync.publish(plan, "Claims: kettle takes S1", config) == claim_sync.PUSHED
    remote = _git(plan, "ls-tree", "-r", "--full-tree", "--name-only", "origin/main").splitlines()
    assert claims.path_for(plan, claim).relative_to(plan.parent).as_posix() in remote
    assert "widget/project.dproj" not in remote
    assert _git(plan, "status", "--porcelain", "--", "project.dproj") == "A  widget/project.dproj"
    assert (config / "claims" / f"{claim.id}.pushed").exists()
    assert not claim_sync.unpublished(claim.id, config)


def test_a_rejected_push_leaves_the_checkout_as_it_was_and_waits_for_the_windows_sync(
    plan, tmp_path
):
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(other))
    _git(other, "-c", "user.email=o@example.com", "-c", "user.name=O", "commit", "-q",
         "--allow-empty", "-m", "theirs")  # fmt: skip
    _git(other, "push", "-q", "origin", "main")
    unsaved = plan / "notes.md"
    unsaved.write_text("half a thought\n", encoding="utf-8")
    before = _git(plan, "rev-parse", "HEAD")
    claim = _taken(plan)
    config = tmp_path / "config"
    assert claim_sync.publish(plan, "Claims", config) == claim_sync.UNPUBLISHED
    assert _git(plan, "rev-parse", "HEAD^") == before  # One commit on top; nothing rebased.
    assert _git(plan, "log", "-1", "--format=%s") == "Claims"
    assert unsaved.read_text(encoding="utf-8") == "half a thought\n"
    assert _git(plan, "stash", "list") == ""
    assert claim_sync.unpublished(claim.id, config)
    assert claims.records(plan) == [claim]  # Still held: ownership is decided here.


def test_a_publish_waits_for_the_repositorys_sync_lock_the_windows_save_takes(plan, tmp_path):
    import threading

    from dplanner.core.storage.git import sync_lock

    _taken(plan)
    done = threading.Event()
    with sync_lock(plan.parent):

        def publish() -> None:
            claim_sync.publish(plan, "Claims", tmp_path / "config")
            done.set()

        worker = threading.Thread(target=publish)
        worker.start()
        assert not done.wait(0.5)  # Held off while a Save holds the lock.
    worker.join(10)
    assert done.is_set()


def test_without_a_remote_a_publish_commits_and_outside_git_does_nothing(tmp_path):
    local = _repo(tmp_path / "local") / "widget"
    local.mkdir()
    _taken(local)
    assert claim_sync.publish(local, "Claims", tmp_path / "config") == claim_sync.COMMITTED
    folder = tmp_path / "folder"
    _taken(folder)
    assert claim_sync.publish(folder, "Claims", tmp_path / "config") == ""


def test_renewing_writes_a_due_heartbeat_and_pushes_at_most_every_thirty_minutes(plan, tmp_path):
    config = tmp_path / "config"
    here = {"machine": ledger.machine_id(config), "host": "here"}
    old = "2026-10-07T10:00:00+00:00"
    mine = _taken(plan, "s1", worker=here, heartbeat=old)
    theirs = _taken(plan, "s2", heartbeat=old)  # Another machine's: not ours to renew.
    claim_sync.renew(plan, config=config)
    assert _found(plan, mine.id).heartbeat != old
    assert _found(plan, theirs.id).heartbeat == old
    assert mine.id in _git(plan, "ls-tree", "-r", "--full-tree", "--name-only", "origin/main")
    # Pushed just now: the next due beat is written, and waits for the push that is due.
    pushed = _git(plan, "rev-parse", "origin/main")
    claims.update(plan, mine.id, lambda c: replace(c, heartbeat=old), config)
    claim_sync.renew(plan, config=config)
    assert _found(plan, mine.id).heartbeat != old
    assert _git(plan, "rev-parse", "HEAD") == pushed


def test_a_superseded_squad_stands_down_instead_of_renewing(plan, tmp_path):
    config = tmp_path / "config"
    here = {"machine": ledger.machine_id(config), "host": "here"}
    loser = _taken(plan, "s1", worker=here, heartbeat="2026-10-07T10:00:00+00:00")
    taker = replace(
        claims.claimed("p1", "osprey", ["s1"], now_stamp(), worker={"machine": "elsewhere"}),
        supersedes=({"claim": loser.id, "step": "s1"},),
    )
    claims.write(plan, taker)
    claim_sync.renew(plan, config=config)
    back = _found(plan, loser.id)
    assert back.steps == () and back.ended and back.heartbeat == loser.heartbeat
    assert claims.read_holdings(plan, now_stamp())["s1"].claim.id == taker.id


def test_the_windows_save_waits_on_the_same_lock_a_claim_publish_holds(plan):
    import threading

    from dplanner.core.storage.git import sync_lock
    from dplanner.core.storage.locations import repo_storage
    from dplanner.core.storage.provider import VersionedStorage

    storage = repo_storage(plan.parent)
    assert isinstance(storage, VersionedStorage)
    (plan / "project.dproj").write_text("{}", encoding="utf-8")
    done = threading.Event()
    with sync_lock(plan.parent):

        def save() -> None:
            storage.commit("Save")
            done.set()

        worker = threading.Thread(target=save)
        worker.start()
        assert not done.wait(0.5)
    worker.join(10)
    assert done.is_set()
