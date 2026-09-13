"""The subprocess door to ``git``, for this module only.

The client here is a program, not a socket. ``core/storage/git.py`` is the storage
provider's and is bound to one checkout a module may not reach (the layering rule), so
this is the ``modules/github/gh.py`` shape: a module owning its own CLI door, with the
binary checked for, a timeout on every call, and every sentence a person reads composed
in ``source.py`` rather than copied out of stderr.

**A worker thread must never hang.** A fetch runs on a ``TaskRunner``, and git will happily
sit forever at a credential prompt, an unknown host key or a dead server. Four locks:
``GIT_TERMINAL_PROMPT=0``, ``GIT_ASKPASS`` set-but-empty (which short-circuits both
``core.askPass`` and ``SSH_ASKPASS`` inside git), ``SSH_ASKPASS_REQUIRE=never`` beside an
``ssh -o BatchMode=yes``, and ``stdin`` closed. Then a timeout on every call and a poll
loop that kills the whole **process group** — killing only ``git`` leaves ``ssh`` holding
the pipes.

**The environment is otherwise the person's**, which is what makes "your own git
credentials do the auth" true: their credential helper, their agent, their ``insteadOf``
rewrites and their proxy all work untouched. Only what would aim us at the wrong
repository is stripped.
"""

import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

# A local command answers at once; a network one may not; a checkout carries the batched
# blob fetch behind it.
LOCAL_S = 20.0
REMOTE_S = 120.0
CHECKOUT_S = 300.0
POLL_S = 0.2

# Aimed at the wrong repository by a shell that carried them — Run Agent exports an
# environment into the shells it opens, and a developer's shell may hold GIT_DIR.
_STRIPPED = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE",
    "GIT_CONFIG",
)

_FORCED = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
    "SSH_ASKPASS": "",
    "SSH_ASKPASS_REQUIRE": "never",
    "GIT_LFS_SKIP_SMUDGE": "1",  # No second tool runs inside our checkout.
    "GIT_OPTIONAL_LOCKS": "0",
    "LC_ALL": "C",  # One language, which is what lets source.py read what git said.
}

_BATCH_SSH = "ssh -o BatchMode=yes -o ConnectTimeout=10"

# Its own process group, so a kill reaches the ssh or the credential helper git started.
_WINDOWS = sys.platform.startswith("win")
_NEW_GROUP: int = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

_git_path: str | None = None


@dataclass(frozen=True)
class Ran:
    """What one git command said. ``err`` matters on success too: a server that ignores
    ``--filter`` warns there and downloads everything anyway."""

    out: str
    err: str


class GitError(Exception):
    """A git command failed. ``stderr`` is for the log; the sentence a person reads is
    composed from it in ``source.py``, because stderr can carry a URL."""

    def __init__(self, verb: str, stderr: str, *, timed_out: bool = False) -> None:
        super().__init__(f"git {verb}: {stderr.strip() or 'failed'}")
        self.verb = verb
        self.stderr = stderr
        self.timed_out = timed_out


def git_path() -> str | None:
    """Where ``git`` is, or None. Only a positive answer is remembered: a person who
    installs git while the window is open must not be told "not installed" forever."""
    global _git_path
    if _git_path is None:
        _git_path = shutil.which("git")
    return _git_path


def hardening(scheme: str, hooks_path: Path) -> list[str]:
    """The ``-c`` settings every invocation carries, whatever the person's config says.

    One transport is allowed and it is the one the validated URL named — ``ext::`` is a
    shell command dressed as a URL and is allowed by default for a direct invocation.
    Symlinks are not created in the checkout, so a repository carrying ``evil -> ~/.ssh``
    lands as a text file; hooks are pointed at a path that cannot exist, so neither the
    repository's nor the person's global ``core.hooksPath`` can run anything here.
    """
    return [
        "-c",
        "protocol.allow=never",
        "-c",
        f"protocol.{scheme}.allow=always",
        "-c",
        "core.symlinks=false",
        "-c",
        "core.quotePath=false",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.askPass=",
        "-c",
        f"core.hooksPath={hooks_path}",
        "-c",
        "gc.auto=0",
        "-c",
        "maintenance.auto=false",
        "-c",
        "fetch.recurseSubmodules=false",
        "-c",
        "submodule.recurse=false",
        "-c",
        "advice.detachedHead=false",
    ]


def environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The person's environment with the four prompt locks on and the aiming vars off."""
    env = {key: value for key, value in os.environ.items() if key not in _STRIPPED}
    env.update(_FORCED)
    # Only when they have not chosen one themselves: BatchMode turns a passphrase prompt
    # or an unknown host key into a refusal we can word, instead of a worker that hangs.
    if not env.get("GIT_SSH_COMMAND") and not env.get("GIT_SSH"):
        env["GIT_SSH_COMMAND"] = _BATCH_SSH
    env.update(extra or {})
    return env


def run_git(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: float = LOCAL_S,
    cancelled: Callable[[], bool] = lambda: False,
    extra_env: dict[str, str] | None = None,
) -> Ran:
    """Run git and return what it said, or raise :class:`GitError`.

    ``subprocess.run(timeout=…)`` is not usable here: a five-minute clone has to notice
    that the person pressed Cancel, so the wait is a poll loop instead.
    """
    git = git_path()
    if git is None:
        raise GitError(args[0] if args else "", "git is not installed")
    # Every argument was validated by source.py; stdin is closed so nothing can be
    # asked of a worker thread.
    started: subprocess.Popen[bytes] = subprocess.Popen(
        [git, *args],
        cwd=str(cwd) if cwd is not None else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment(extra_env),
        start_new_session=not _WINDOWS,
        creationflags=_NEW_GROUP if _WINDOWS else 0,
    )
    deadline = monotonic() + timeout
    while True:
        try:
            out, err = started.communicate(timeout=POLL_S)
            break
        except subprocess.TimeoutExpired:
            expired = monotonic() > deadline
            if expired or cancelled():
                _end(started)
                raise GitError(_verb(args), "timed out", timed_out=expired) from None
    said = err.decode("utf-8", "replace")
    if started.returncode != 0:
        raise GitError(_verb(args), said)
    return Ran(out=out.decode("utf-8", "replace"), err=said)


def _verb(args: Sequence[str]) -> str:
    """What was being done, for a log line — never the arguments, which carry the URL.

    The first word that is neither an option nor the value of one: ``-c`` and ``-C`` each
    take the argument after them, and ``protocol.allow=never`` is not a verb.
    """
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg in ("-c", "-C"):
            skip = True
            continue
        if not arg.startswith("-"):
            return arg
    return ""


def _end(started: "subprocess.Popen[bytes]") -> None:
    with suppress(OSError):
        if _WINDOWS:
            started.kill()
        else:
            os.killpg(os.getpgid(started.pid), signal.SIGKILL)
    with suppress(subprocess.TimeoutExpired, ValueError):
        started.communicate(timeout=LOCAL_S)
