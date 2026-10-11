"""Fixtures several feature packages' tests share: a project with code and one agent step,
and the supervisors a launch would have started — ``agent run``'s, and the playbook engine's
and ``progress``'s, which launch through it."""

import subprocess
from pathlib import Path

import pytest

from dplanner.modules.agent_supervisor import supervisor

URL = "https://github.com/acme/widget"


@pytest.fixture
def code(tmp_path):
    """The project's code: a repository of its own with one commit, no remote."""
    from dplanner.core.storage.locations import init_repo

    repo = init_repo(tmp_path / "code")
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "--allow-empty", "-m", "start"],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return repo


@pytest.fixture
def plan(cli, code, tmp_path, workspace):
    """A project whose code is ``code``, with one briefed agent step, "Build it"."""
    cli("project", "create", "Widget")
    cli("location", "add", "widget", "--role", "code", "--repository", URL,
        "--checkout", str(code))  # fmt: skip
    brief = tmp_path / "brief.md"
    brief.write_text("Build the widget.\n", encoding="utf-8")
    cli("step", "add", "widget", "Build it", "--agent")
    cli("describe", "set", "Build it", "--file", str(brief))
    return workspace / "widget"


@pytest.fixture
def started(monkeypatch):
    """Every supervisor a launch would have started, as (project dir, run)."""
    calls: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        supervisor,
        "start_detached",
        lambda project_dir, run, **_kw: calls.append((project_dir, run)),
    )
    return calls
