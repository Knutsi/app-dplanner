import subprocess
from pathlib import Path

from dplanner.core.process import (
    CREATE_NEW_PROCESS_GROUP,
    DETACHED_PROCESS,
    detached_flags,
    spawn_detached,
)


def test_only_windows_gets_the_detaching_flags():
    assert detached_flags("win32") == DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    assert detached_flags("linux") == 0
    assert detached_flags("darwin") == 0


def test_a_detached_spawn_leaves_the_session_and_keeps_no_pipes(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: calls.append((a, kw)))
    spawn_detached(("term", "-e", "run.sh"), cwd=tmp_path, env={"PATH": "/usr/bin"})
    ((argv,), options) = calls[0]
    assert argv == ["term", "-e", "run.sh"]
    assert options["cwd"] == tmp_path and options["env"] == {"PATH": "/usr/bin"}
    assert options["start_new_session"] is True
    assert options["creationflags"] == detached_flags()
    assert options["stdout"] is subprocess.DEVNULL and options["stderr"] is subprocess.DEVNULL
