"""Starting a process the user owns: detached, so closing the application never takes it down.

A terminal running an agent, a second application window, an RDP session — each outlives the
process that started it, on every platform. On POSIX that is ``start_new_session``: the child
leaves the session, and the SIGHUP that arrives when it ends. Windows needs flags instead.
"""

import subprocess
import sys
from collections.abc import Mapping, Sequence
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
