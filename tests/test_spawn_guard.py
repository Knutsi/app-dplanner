"""The suite's spawn guard (``conftest.py``'s ``_no_real_spawns``) refuses what it must and
lets git and a test's own fake through."""

import os
import subprocess
import sys

import pytest

from dplanner.core.process import spawn_detached
from dplanner.modules.agent_launch import launcher
from tests.platforms import POSIX_MODE_BITS


def _refused(guard, start):
    with pytest.raises(pytest.fail.Exception):
        start()
    refused = list(guard.refused)
    guard.refused.clear()  # Seen and meant: the guard's own teardown must not fail this test.
    return refused


def test_a_terminal_is_refused(_no_real_spawns, tmp_path):
    refused = _refused(_no_real_spawns, lambda: launcher.spawn(["ghostty", "-e", "x"], tmp_path))
    assert refused == [["ghostty", "-e", "x"]]


def test_a_multiplexers_first_stage_is_refused(_no_real_spawns, tmp_path):
    command = ["herdr", "workspace", "create", "&&", "herdr", "pane", "run", "{pane}", "x"]
    refused = _refused(_no_real_spawns, lambda: launcher.spawn(command, tmp_path))
    assert refused == [["herdr", "workspace", "create"]]


def test_an_agent_cli_is_refused_however_it_is_started(_no_real_spawns):
    refused = _refused(_no_real_spawns, lambda: subprocess.run(["claude", "--version"]))
    assert refused == [["claude", "--version"]]


def test_anything_detached_is_refused(_no_real_spawns):
    refused = _refused(_no_real_spawns, lambda: spawn_detached([sys.executable, "-c", "pass"]))
    assert refused == [[sys.executable, "-c", "pass"]]


def test_git_runs():
    assert subprocess.run(["git", "--version"], capture_output=True).returncode == 0


@POSIX_MODE_BITS
def test_an_allowed_fake_runs_under_an_agents_name(allow_spawn, tmp_path):
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\necho fake\n", encoding="utf-8")
    fake.chmod(0o755)
    allow_spawn(fake)
    env = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}"}
    done = subprocess.run(["claude"], capture_output=True, text=True, env=env)
    assert done.stdout == "fake\n"


def test_allowing_a_fake_lets_no_real_one_through(_no_real_spawns, allow_spawn, tmp_path):
    allow_spawn(tmp_path / "claude")  # Never written: the name alone is not the file.
    refused = _refused(_no_real_spawns, lambda: subprocess.run(["claude"]))
    assert refused == [["claude"]]
