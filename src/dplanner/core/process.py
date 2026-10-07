"""Starting a process the user owns, and knowing later whether it is still that process.

**Detached**, so closing the application never takes it down.

A terminal running an agent, a second application window, an RDP session — each outlives the
process that started it, on every platform. On POSIX that is ``start_new_session``: the child
leaves the session, and the SIGHUP that arrives when it ends. Windows needs flags instead.

**Still that process** is a :class:`ProcessStamp`: the pid, the machine's boot and the
process's start time. A pid alone is reused — after a reboot almost at once — so a record
that kept only the pid would read a stranger as its own process still running.
"""

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

# CreateProcess flags, spelled as their Win32 values rather than read off ``subprocess``,
# which defines them only on Windows. A getattr fallback would make
# ``detached_flags("win32")`` answer 0 in the very suite that has to check it.
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def detached_flags(platform: str = sys.platform) -> int:
    """The Windows half of ``start_new_session``; nothing anywhere else.

    Windows has no sessions and no SIGHUP, so a child already outlives its parent there and
    ``start_new_session`` is silently ignored. What the child *would* inherit is the console
    the application was started from, and that console's Ctrl+C. ``DETACHED_PROCESS`` unhooks
    it; ``CREATE_NEW_PROCESS_GROUP`` is the flag ``core/storage/sparse.py`` sets for the same
    reason. Not ``CREATE_NEW_CONSOLE``: a terminal or a GUI opens its own window already, so
    it would only add a stray black one behind each spawn.
    """
    return DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP if platform.startswith("win") else 0


def spawn_detached(
    argv: Sequence[str], *, cwd: Path | None = None, env: Mapping[str, str] | None = None
) -> None:
    """Start ``argv`` detached and forget it: its output goes nowhere and nobody waits on it."""
    subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=env,
        start_new_session=True,
        creationflags=detached_flags(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@dataclass(frozen=True)
class ProcessStamp:
    """Which process, exactly: live only while all three still match.

    ``boot`` is the machine's boot id where the system names one (Linux's ``boot_id``,
    macOS's ``kern.boottime``) and "" on Windows, where the creation time — to the 100 ns —
    already tells two processes with one pid apart across reboots.
    """

    pid: int
    boot: str
    started: str


def stamp_of(pid: int) -> ProcessStamp | None:
    """The running process with this pid, or None when there is none."""
    if not process_alive(pid):
        return None
    return ProcessStamp(pid, _boot(), _started(pid))


def is_live(stamp: ProcessStamp) -> bool:
    return stamp_of(stamp.pid) == stamp


def process_alive(pid: int) -> bool:
    """Whether a process with this id exists — any process; :func:`is_live` asks which.

    The ``else`` is load-bearing rather than style: mypy exempts a block guarded by a
    ``sys.platform`` comparison from its checks on the platform that never reaches it, and a
    fall-through after an always-taken ``return`` is not such a block — ``mypy --platform
    win32`` read it as dead code. One branch each, and each checked where it runs.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _windows_process_alive(pid)
    else:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # Somebody else's process, but a process.
        return True


def _windows_process_alive(pid: int) -> bool:
    import ctypes

    still_active = 259
    query_limited_information = 0x1000
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
    handle = kernel32.OpenProcess(query_limited_information, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return int(code.value) == still_active
    finally:
        kernel32.CloseHandle(handle)


def _boot() -> str:
    if sys.platform == "linux":
        try:
            return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        except OSError:
            return ""
    elif sys.platform == "darwin":
        return _output(["sysctl", "-n", "kern.boottime"])
    else:
        return ""


def _started(pid: int) -> str:
    """When the process started, in whatever unit the system counts it — compared, never read."""
    if sys.platform == "linux":
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
        except OSError:
            return ""
        # The command name is in parentheses and may hold spaces; starttime is the 22nd
        # field, the 20th after the closing one.
        fields = stat.rpartition(")")[2].split()
        return fields[19] if len(fields) > 19 else ""
    elif sys.platform == "win32":
        return _windows_started(pid)
    else:
        return _output(["ps", "-o", "lstart=", "-p", str(pid)])


def _windows_started(pid: int) -> str:
    import ctypes

    query_limited_information = 0x1000
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
    handle = kernel32.OpenProcess(query_limited_information, False, pid)
    if not handle:
        return ""
    try:
        times = [ctypes.c_ulonglong() for _ in range(4)]
        if not kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return ""
        return str(times[0].value)  # The creation time.
    finally:
        kernel32.CloseHandle(handle)


def _output(argv: list[str]) -> str:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip()
