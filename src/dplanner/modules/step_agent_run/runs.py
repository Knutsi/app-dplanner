"""A launched shell, as this machine remembers it, and how its end is noticed.

The aspect on the step says where the agent *stands*; this is the other half — which
shell was opened for it, on this machine, and whether that shell is still there. Nothing
here reaches the plan: a run is a per-user, per-machine fact (a temp directory, a pid),
kept in the user's own store so a rebuilt window re-adopts the runs it launched before,
and never in a file that travels with the project.

Every run is watched through two files the wrapper script writes beside the prompt (see
``step_agent_instruction/launcher.py``): the shell's facts on start, and the agent's exit
status when it ends. :func:`settle` reads them and answers what became of the run —
``finished`` (exit 0), ``failed`` (any other status), ``closed`` (the terminal was shut on
it, whether the script's trap said so or the shell's pid is simply gone) or ``lost`` (the
run directory is gone — a reboot cleaned the temp files). A run with no outcome yet is
live, which is the only state that keeps the watcher's timer running.
"""

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from dplanner.domain.agents import RunFacts
from dplanner.domain.model import now_stamp

CLOSED = "closed"


@dataclass(frozen=True)
class AgentRun:
    step_id: str
    shell_file: str
    exit_file: str
    launched: str  # ISO stamp.
    outcome: str = ""  # "" while live, else finished | failed | closed | lost.
    code: int | None = None  # The agent's exit status, when there was one.
    ended: str = ""  # ISO stamp of the outcome.
    # Which agent CLI ran, by harness id ("" for a custom command nothing knows), and
    # the session it was: named by the launcher up front, or found by the harness's
    # own records once the run ended — what its usage is read from and what resumes it.
    harness: str = ""
    session: str = ""
    # What the briefing this run opened with came to, in characters. Kept here and not only
    # on the step's usage row because a run that is still going has no usage row yet, and a
    # harness with no token reader never gets one.
    prompt_chars: int = 0

    @property
    def key(self) -> str:
        """The run directory: one per launch, which is what makes it the identity."""
        return str(Path(self.shell_file).parent)

    @property
    def live(self) -> bool:
        return not self.outcome

    def to_json(self) -> dict[str, Any]:
        return {
            "step": self.step_id,
            "shell": self.shell_file,
            "exit": self.exit_file,
            "launched": self.launched,
            "outcome": self.outcome,
            "code": self.code,
            "ended": self.ended,
            "harness": self.harness,
            "session": self.session,
            "prompt_chars": self.prompt_chars,
        }

    @classmethod
    def from_json(cls, raw: Any) -> "AgentRun | None":
        """A stored run, or None for a row this build cannot read — never a crash over
        one, since the store is the user's and a newer build may have written it."""
        if not isinstance(raw, dict):
            return None
        try:
            code = raw.get("code")
            briefed = raw.get("prompt_chars")
            return cls(
                step_id=str(raw["step"]),
                shell_file=str(raw["shell"]),
                exit_file=str(raw["exit"]),
                launched=str(raw.get("launched", "")),
                outcome=str(raw.get("outcome", "")),
                code=int(code) if isinstance(code, int) else None,
                ended=str(raw.get("ended", "")),
                harness=str(raw.get("harness", "")),
                session=str(raw.get("session", "")),
                prompt_chars=briefed if isinstance(briefed, int) else 0,
            )
        except (KeyError, TypeError, ValueError):
            return None


def new_run(
    step_id: str,
    shell_file: str,
    exit_file: str,
    harness: str = "",
    session: str = "",
    prompt_chars: int = 0,
) -> AgentRun:
    return AgentRun(
        step_id,
        shell_file,
        exit_file,
        now_stamp(),
        harness=harness,
        session=session,
        prompt_chars=prompt_chars,
    )


def run_facts(run: AgentRun) -> RunFacts:
    """What a harness's ``report`` is handed: the session the launcher named (else the
    one the shell recorded), where the agent worked, and when."""
    shell = read_shell(run)
    return RunFacts(
        session=run.session or shell.get("session", ""),
        directory=shell.get("dir", ""),
        launched=run.launched,
        ended=run.ended,
    )


def read_shell(run: AgentRun) -> dict[str, str]:
    """The shell's facts (``tty``, ``pid``, ``pane``, ``program``, ``title``, ``session``,
    and once the agent is in place ``dir`` and ``resume``), or {} before the script has
    written them."""
    try:
        text = Path(run.shell_file).read_text()
    except OSError:
        return {}
    facts: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            facts[key.strip()] = value.strip()
    return facts


def shell_pid(run: AgentRun) -> int | None:
    pid = read_shell(run).get("pid", "")
    return int(pid) if pid.isdigit() else None


def settle(run: AgentRun, alive: Callable[[int], bool] | None = None) -> AgentRun:
    """The run with its outcome recorded, if the shell has ended; else the run as it was.

    Order matters: the exit file is the shell's own word and wins; a dead pid without one
    is a terminal closed hard enough that the trap never ran; a vanished directory is a
    machine that cleaned up under us. ``alive`` is injectable for tests.
    """
    if not run.live:
        return run
    exit_path = Path(run.exit_file)
    try:
        word = exit_path.read_text().strip()
    except OSError:
        word = None
    if word is not None:
        if not word.lstrip("-").isdigit():
            return _ended(run, CLOSED)  # The trap's word: no status, the window went.
        code = int(word)
        return _ended(run, "finished" if code == 0 else "failed", code)
    pid = shell_pid(run)
    if pid is not None and not (alive or process_alive)(pid):
        return _ended(run, CLOSED)
    if not exit_path.parent.is_dir():
        return _ended(run, "lost")
    return run


def _ended(run: AgentRun, outcome: str, code: int | None = None) -> AgentRun:
    return replace(run, outcome=outcome, code=code, ended=now_stamp())


def process_alive(pid: int) -> bool:
    """Whether a process with this id still exists — the wrapper shell's, here."""
    if sys.platform == "win32":
        return _windows_process_alive(pid)
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


def describe(run: AgentRun, state: str) -> str:
    """One phrase for a row's second line: the state while live, the outcome after."""
    if run.live:
        return state.replace("-", " ") or "launched"
    if run.outcome == "finished":
        return "finished"
    if run.outcome == "failed":
        return f"failed (exit {run.code})"
    if run.outcome == CLOSED:
        return "terminal closed"
    return "lost — its run directory is gone"
