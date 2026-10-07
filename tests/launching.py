"""What a test that runs Run Agent in a window needs: a repository with a commit to start a
step's worktree from, the worktree prepared inline, and a way to read which checkout a
terminal opened in.

The window prepares a step's worktree on a task, since git fetches, and a test that asserts
the line after the gesture must not race it. A test directory whose tests launch agents
takes the two fixtures into its ``conftest.py`` (``from tests.launching import …``); the
task path itself is tested once, in ``agent_launch/test_launch.py``.
"""

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest


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
