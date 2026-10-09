import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from dplanner.core.process import (
    CREATE_NEW_PROCESS_GROUP,
    DETACHED_PROCESS,
    RUN_ENV,
    ProcessStamp,
    detached_flags,
    is_live,
    process_alive,
    run_bounded,
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


@pytest.mark.parametrize("given", [None, {"PATH": "/usr/bin", RUN_ENV: "r-1"}])
def test_a_detached_spawn_never_carries_a_run(monkeypatch, given):
    """A stop ends every process carrying its run; a detached one is nobody's turn."""
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: calls.append(kw))
    monkeypatch.setenv(RUN_ENV, "r-1")
    monkeypatch.setenv("PATH", "/usr/bin")
    spawn_detached(("dplanner", "playbook", "advance", "S1"), env=given)
    assert RUN_ENV not in calls[0]["env"] and calls[0]["env"]["PATH"] == "/usr/bin"


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


def test_a_bounded_run_answers_with_what_the_process_said():
    done = run_bounded([sys.executable, "-c", "print('said'); raise SystemExit(3)"], timeout=30)
    assert (done.returncode, done.stdout.strip()) == (3, "said")


def test_a_bounded_run_that_overruns_ends_what_it_started_too(tmp_path: Path):
    """The helper a CLI leaves behind holds the output pipe: ``subprocess.run``'s timeout
    ends the CLI and then waits on the pipe for as long as the helper lives."""
    marker = tmp_path / "helper.pid"
    helper = "import time; time.sleep(60)"
    starter = (
        "import subprocess, sys, time; "
        f"helper = subprocess.Popen([sys.executable, '-c', {helper!r}]); "
        f"open({str(marker)!r}, 'w').write(str(helper.pid)); "
        "time.sleep(60)"
    )
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded([sys.executable, "-c", starter], timeout=2)

    assert time.monotonic() - started < 15
    pid = int(marker.read_text())
    deadline = time.monotonic() + 5
    while process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not process_alive(pid)
