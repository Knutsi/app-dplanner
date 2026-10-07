import os
import subprocess
import sys
from pathlib import Path

from dplanner.core.process import (
    CREATE_NEW_PROCESS_GROUP,
    DETACHED_PROCESS,
    ProcessStamp,
    detached_flags,
    is_live,
    spawn_detached,
    stamp_of,
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


def test_this_process_is_live_and_a_changed_start_or_boot_is_not():
    stamp = stamp_of(os.getpid())
    assert stamp is not None and is_live(stamp)
    assert not is_live(ProcessStamp(stamp.pid, stamp.boot, stamp.started + "1"))
    assert not is_live(ProcessStamp(stamp.pid, stamp.boot + "x", stamp.started))


def test_a_process_that_exited_has_no_stamp():
    done = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True
    )
    assert stamp_of(int(done.stdout)) is None
    assert stamp_of(0) is None
