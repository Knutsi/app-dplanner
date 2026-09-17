"""The PATH a desktop launch does not inherit — asked for once, and put back.

A window opened from Finder, the Dock, Spotlight or a ``.desktop`` entry is started by the
session's launcher, not by a shell, so it inherits that launcher's ``PATH`` and nothing
else. On macOS that is launchd's ``/usr/bin:/bin:/usr/sbin:/sbin``. Every tool a developer
installed is somewhere else — ``/opt/homebrew/bin/gh``, ``~/.local/bin/uv``, the agent CLIs,
whisper — and :func:`shutil.which` reads ``os.environ["PATH"]``, so every one of them comes
back ``None``. The application then reports, correctly and uselessly, that this machine has
no GitHub CLI, on a machine where ``gh`` works perfectly from a terminal.

That is one bug, not twenty: nothing is wrong with any of the callers, and none of them are
touched here. The environment is repaired once, before the window is built, and every
``which`` after it answers what a terminal would.

**It asks a login shell, because only the user's own profile knows.** ``brew shellenv``,
``uv``'s installer and every version manager write their line into ``.zprofile`` or
``.profile``, and a login shell is what reads those. Not an *interactive* one: ``-i`` drags
in nvm, pyenv, direnv and a prompt framework, which turns a 40 ms question into seconds.
When the shell cannot be asked — absent, slow, a machine with no shell at all — the known
prefixes below are most of the same answer for none of the cost, so the repair degrades
instead of failing.

**Nothing here ever shortens PATH.** Entries are appended and only when absent, so a
process that was deliberately given a path keeps it first, and calling twice changes
nothing. That is what makes it safe to run before anything has looked at the environment.

This lives in ``core/`` beside ``config_dir`` and for the same reason: it is a per-machine
fact both surfaces need, and it loads no Qt.
"""

import os
import subprocess
import sys
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from pathlib import Path

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]

# Long enough for a profile that sources a version manager, short enough that a hung shell
# never holds a window closed. The fallback covers the timeout.
SHELL_TIMEOUT_S = 3.0

# `command -p` runs the *standard* printenv, not whatever the profile put in front of it.
PATH_QUERY = "command -p printenv PATH"

# Where tools actually live when a desktop launch cannot see them, in the order a shell
# would find them. Used when the shell cannot be asked, and as the belt to its braces —
# a profile that exports PATH only for interactive shells is otherwise invisible.
KNOWN_PREFIXES: tuple[str, ...] = (
    "/opt/homebrew/bin",  # Homebrew on Apple silicon: the common case this exists for.
    "/opt/homebrew/sbin",
    "/usr/local/bin",  # Homebrew on Intel, and the usual /usr/local install.
    "/usr/local/sbin",
    "~/.local/bin",  # uv, pipx and pip --user. Where `dplanner` itself lands.
    "~/.cargo/bin",
    "~/.bun/bin",
    "/opt/local/bin",  # MacPorts.
)


def _run(command: list[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        command, capture_output=True, text=True, check=False, timeout=SHELL_TIMEOUT_S
    )


def login_shell(environ: MutableMapping[str, str] | None = None) -> str:
    """The user's shell, or "" when the environment does not say."""
    return (os.environ if environ is None else environ).get("SHELL", "")


def login_path(
    *,
    platform: str = sys.platform,
    environ: MutableMapping[str, str] | None = None,
    run: Runner | None = None,
) -> str:
    """What the user's login shell says ``PATH`` is — "" when it cannot be asked.

    Never raises: a missing shell, a non-zero exit, a timeout and a machine with no
    subprocesses at all are all the same answer here, which is "ask something else".
    """
    if platform.startswith("win"):  # Explorer hands a full PATH; there is nothing to repair.
        return ""
    shell = login_shell(environ)
    if not shell:
        return ""
    runner = _run if run is None else run
    try:
        result = runner([shell, "-lc", PATH_QUERY])
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def existing_prefixes(home: Path, prefixes: tuple[str, ...] = KNOWN_PREFIXES) -> list[str]:
    """The prefixes that are actually directories on this machine, ``~/`` resolved.

    ``prefixes`` is an argument so a test controls the whole set: half of :data:`KNOWN_PREFIXES`
    are absolute and exist on the machine running the suite, which would otherwise leak into
    every assertion about what a repair added.
    """
    expanded = (
        str(home / prefix[2:]) if prefix.startswith("~/") else prefix for prefix in prefixes
    )
    return [prefix for prefix in expanded if Path(prefix).is_dir()]


def missing_from(current: str, candidates: list[str]) -> list[str]:
    """The candidates ``current`` does not already hold, in order, without duplicates."""
    held = set(current.split(os.pathsep))
    found: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in held:
            held.add(candidate)
            found.append(candidate)
    return found


@dataclass(frozen=True)
class Repair:
    """What one :func:`repair` did — what the checklist row reads afterwards."""

    added: tuple[str, ...]
    asked_shell: bool  # Whether there was a ``$SHELL`` to ask at all.
    shell_answered: bool  # Whether it said anything. False with asked_shell is the bad case.


# The repair this process did, or None when none ran — which is every CLI run. It happens
# once, before the window is built, and a checklist probe may not shell out, so the answer is
# settled where it is known and read afterwards: the Problems count's arrangement.
_last: Repair | None = None


def last() -> Repair | None:
    """The repair this process did, or None when none ran."""
    return _last


def repair(
    *,
    platform: str = sys.platform,
    environ: MutableMapping[str, str] | None = None,
    home: Path | None = None,
    prefixes: tuple[str, ...] = KNOWN_PREFIXES,
    run: Runner | None = None,
    remember: bool = True,
) -> Repair:
    """Append what a desktop launch lost to ``PATH``, in place, and say what happened.

    Idempotent, and never removes or reorders what is already there. No ``added`` means the
    environment was already complete, which is the ordinary case on Linux and every case on
    Windows. ``remember`` is what :func:`last` reads; a test turns it off so it does not
    write over another test's answer.
    """
    global _last
    if platform.startswith("win"):
        return Repair((), asked_shell=False, shell_answered=False)
    target = os.environ if environ is None else environ
    current = target.get("PATH", "")
    said = login_path(platform=platform, environ=target, run=run)
    candidates = said.split(os.pathsep) if said else []
    candidates += existing_prefixes(Path.home() if home is None else home, prefixes)
    added = missing_from(current, candidates)
    if added:
        target["PATH"] = os.pathsep.join([current, *added]) if current else os.pathsep.join(added)
    done = Repair(tuple(added), asked_shell=bool(login_shell(target)), shell_answered=bool(said))
    if remember:
        _last = done
    return done


def reading(done: Repair | None) -> tuple[bool, str]:
    """Whether this process's PATH is the user's, and the words that say so.

    What the checklist row reads, and **no subprocess**: it reports the repair that already
    happened rather than probing again. ``None`` is no repair at all, which is every CLI run
    — a verb was typed into a shell, so the PATH is the user's by construction.

    It deliberately says nothing about *which tools* are installed. Each tool that matters
    has a row of its own, and a second list of the same names would be two rows able to
    disagree about one fact. What only this row knows is whether the PATH a launcher handed
    the window was replaced with the user's.
    """
    if done is None:
        return True, "started from a shell — this is already your own PATH"
    if done.asked_shell and not done.shell_answered:
        return False, (
            "your login shell could not be asked what your PATH is — tools installed by "
            "Homebrew or uv may be invisible here but fine in a terminal"
        )
    if not done.added:
        return True, "already complete when the window opened"
    return True, f"recovered {len(done.added)} from your login shell: {', '.join(done.added)}"
