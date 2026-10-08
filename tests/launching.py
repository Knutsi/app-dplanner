"""What a test that runs Run Agent in a window needs: a repository with a commit to start a
step's worktree from, the worktree prepared inline, and a way to read which checkout a
terminal opened in.

The window prepares a step's worktree on a task, since git fetches, and a test that asserts
the line after the gesture must not race it. A test directory whose tests launch agents
takes the two fixtures into its ``conftest.py`` (``from tests.launching import …``); the
task path itself is tested once, in ``agent_launch/test_launch.py``.
"""

import os
import signal
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from dplanner.cli.discovery import RUN_ENV
from dplanner.core.process import ProcessStamp, is_live, stamp_of


def committed(repo: Path) -> Path:
    """``repo`` with one commit: a step's worktree starts from something."""
    git = ["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t"]
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "start"], check=True)
    return repo


def checkout_of(workdir: Path) -> Path:
    """The checkout an agent worked from: the one its worktree is under, or itself."""
    from dplanner.core.storage.pointer import WORKTREES_DIR

    return workdir.parent.parent if workdir.parent.name == WORKTREES_DIR else workdir


@pytest.fixture
def library_repo(library_repo):
    return committed(library_repo)


@pytest.fixture
def services(services, monkeypatch):
    from dplanner.modules.agent_launch.module import AgentLaunchModule

    module = next(m for m in services.modules if isinstance(m, AgentLaunchModule))
    monkeypatch.setattr(module, "_deps", replace(module._deps, tasks=None))
    return services


def group_of(pid: int) -> int:
    """The process group ``pid`` is in; 0 on Windows, which has none."""
    if sys.platform == "win32":
        return 0
    else:
        return os.getpgid(pid)


@contextmanager
def orphaned_turn(run: str = "", *, leader_exits: bool = False) -> Iterator[ProcessStamp]:
    """A turn's process that outlived its supervisor: started by a parent that has already
    exited, so — as a real one is — it is nobody's child here and is reaped by the system once
    it ends. Yields its stamp; whatever is left of it is killed afterwards. The caller allows
    ``sys.executable`` to spawn.

    With ``run`` it carries the run in its environment, as everything a turn starts does.
    With ``leader_exits`` it is a child the turn's leader started, in the leader's process
    group, and the leader has gone: the group's id, ``os.getpgid`` of it, is a dead pid."""
    sleeper = "import time; time.sleep(120)"
    starter = (
        "import os, subprocess, sys; "
        + ("os.setsid(); " if leader_exits else "")
        + f"print(subprocess.Popen([sys.executable, '-c', {sleeper!r}], "
        f"start_new_session={not leader_exits}, stdin=subprocess.DEVNULL, "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).pid)"
    )
    env = {**os.environ, RUN_ENV: run} if run else None
    pid = int(subprocess.run([sys.executable, "-c", starter], capture_output=True, text=True,
                             check=True, env=env).stdout)  # fmt: skip
    stamp = stamp_of(pid)
    assert stamp is not None
    try:
        yield stamp
    finally:
        if is_live(stamp):
            os.kill(pid, signal.SIGTERM)
