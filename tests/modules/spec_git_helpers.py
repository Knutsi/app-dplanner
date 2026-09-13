"""A git remote for the spec-git tests: a bare repository under ``tmp_path``, served over
``file://``.

**A ``file://`` URL, never a bare path.** Git ignores ``--depth`` and ``--filter``
entirely for a plain local path, so a bare path would prove nothing about the shallow,
blobless clone the kind depends on. The two ``uploadpack`` settings are not a fudge either:
they are exactly what a host must support for a partial fetch and for asking for one
commit, so the fixture documents the requirement.
"""

import subprocess
import time
from collections.abc import Mapping
from pathlib import Path

import pytest

IDENTITY = (
    "-c",
    "user.name=Test",
    "-c",
    "user.email=test@example.com",
    "-c",
    "commit.gpgsign=false",
)


def git(*args: str, cwd: Path | None = None) -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=None if cwd is None else str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout


@pytest.fixture
def clean_git(monkeypatch, tmp_path):
    """git runs with no configuration but the test's own — the suite never reads the shell
    it runs in, and the code under test inherits this environment too."""
    home = tmp_path / "githome"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(home / "gitconfig-system"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    return home


class Remote:
    """A bare repository, and the working clone the tests commit through."""

    def __init__(self, bare: Path, work: Path) -> None:
        self.bare = bare
        self.work = work
        self.url = f"file://{bare}"

    def commit(self, files: Mapping[str, bytes | str], message: str = "change") -> str:
        for name, data in files.items():
            target = self.work / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data if isinstance(data, bytes) else data.encode())
        git("add", "-A", cwd=self.work)
        git(*IDENTITY, "commit", "-q", "-m", message, cwd=self.work)
        git("push", "-q", "origin", "main", cwd=self.work)
        return git("rev-parse", "HEAD", cwd=self.work).strip()

    def remove(self, name: str, message: str = "remove") -> str:
        git("rm", "-q", name, cwd=self.work)
        git(*IDENTITY, "commit", "-q", "-m", message, cwd=self.work)
        git("push", "-q", "origin", "main", cwd=self.work)
        return git("rev-parse", "HEAD", cwd=self.work).strip()

    def tag(self, name: str) -> None:
        git(*IDENTITY, "tag", "-a", name, "-m", name, cwd=self.work)
        git("push", "-q", "origin", name, cwd=self.work)


def make_remote(tmp_path: Path, files: Mapping[str, bytes | str]) -> Remote:
    bare = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(bare))
    # What a host must support for a partial fetch and for asking for one commit.
    git("-C", str(bare), "config", "uploadpack.allowFilter", "true")
    git("-C", str(bare), "config", "uploadpack.allowAnySHA1InWant", "true")
    work = tmp_path / "work"
    git("init", "-q", "-b", "main", str(work))
    git("-C", str(work), "remote", "add", "origin", str(bare))
    remote = Remote(bare, work)
    remote.commit(files, "init")
    return remote


def wait_for(app, predicate, timeout: float = 15.0) -> None:
    """Pump the event loop until the worker has delivered. Never ``qtbot.wait``."""
    deadline = time.time() + timeout
    while not predicate():
        assert time.time() < deadline, "the worker never delivered"
        app.processEvents()
        time.sleep(0.01)
