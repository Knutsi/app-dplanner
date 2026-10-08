"""The git half of a claim (``domain/claim_sync.py``): committed alone, pushed, ranked by the
order its file arrived, and renewed on the slow clock. The remote is a local bare repository."""

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from dplanner.domain import claim_sync, claims, ledger
from dplanner.domain.model import now_stamp

WORKER = {"machine": "m1", "host": "knut-arch"}


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
    (plan / "project.dproj").write_text("{}", encoding="utf-8")  # Unsaved plan work.
    config = tmp_path / "config"
    assert claim_sync.publish(plan, "Claims: kettle takes S1", config) == "pushed"
    remote = _git(plan, "ls-tree", "-r", "--full-tree", "--name-only", "origin/main").splitlines()
    assert claims.path_for(plan, claim).relative_to(plan.parent).as_posix() in remote
    assert "widget/project.dproj" not in remote
    assert "project.dproj" in _git(plan, "status", "--porcelain")
    assert (config / "claims" / f"{claim.id}.pushed").exists()


def test_without_a_remote_a_publish_commits_and_outside_git_does_nothing(tmp_path):
    local = _repo(tmp_path / "local") / "widget"
    local.mkdir()
    _taken(local)
    assert claim_sync.publish(local, "Claims", tmp_path / "config") == "committed"
    folder = tmp_path / "folder"
    _taken(folder)
    assert claim_sync.publish(folder, "Claims", tmp_path / "config") == ""
    assert claim_sync.push_order(folder) == []


def test_push_order_is_the_order_the_files_were_committed(plan, tmp_path):
    first = _taken(plan, "s1")
    claim_sync.publish(plan, "first", tmp_path / "config")
    second = _taken(plan, "s2")
    claim_sync.publish(plan, "second", tmp_path / "config")
    assert claim_sync.push_order(plan) == [first.id, second.id]


def test_renewing_writes_a_due_heartbeat_and_pushes_at_most_every_thirty_minutes(plan, tmp_path):
    config = tmp_path / "config"
    here = {"machine": ledger.machine_id(config), "host": "here"}
    old = "2026-10-07T10:00:00+00:00"
    mine = _taken(plan, "s1", worker=here, heartbeat=old)
    theirs = _taken(plan, "s2", heartbeat=old)  # Another machine's: not ours to renew.
    claim_sync.renew(plan, config=config)
    assert claims.find(plan, mine.id).heartbeat != old
    assert claims.find(plan, theirs.id).heartbeat == old
    assert mine.id in _git(plan, "ls-tree", "-r", "--full-tree", "--name-only", "origin/main")
    # Pushed just now: the next due beat is written, and waits for the push that is due.
    pushed = _git(plan, "rev-parse", "origin/main")
    claims.update(plan, mine.id, lambda c: replace(c, heartbeat=old), config)
    claim_sync.renew(plan, config=config)
    assert claims.find(plan, mine.id).heartbeat != old
    assert _git(plan, "rev-parse", "HEAD") == pushed
