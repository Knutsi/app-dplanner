"""*Open Session*: a person takes a headless run's session into a terminal of their own.

A headless run is its supervisor's, and the supervisor resumes a parked one by itself when its
question is answered, its limit resets or somebody presses *Retry now*. So a session a person
opens interactively must first stop being the run's, or two processes would write one session:
the run is **fenced** ``taken over by a person`` (:data:`~dplanner.domain.ledger.TAKEN_OVER`)
through the one stopper, ``supervisor.stop_and_wait`` — a supervisor waiting out a limit is
signalled, a parked run nobody drives is ended here and its questions withdrawn — and only then
is the harness's own resume command (``claude --resume``, ``codex resume``, ``opencode -s``)
handed back, to run in the directory the run worked in. Its pass reads *Taken over*, and the
step leaves its squad's claim (the caller's ``Release``), so no coordinator launches it again.

A run whose turn is running is refused: it is the agent's until it parks, or a person stops it.
A run that is over is not fenced again; its session is simply opened.
"""

import shlex
from pathlib import Path

from dplanner.domain import ledger
from dplanner.domain.agents import AgentHarness, harness_by_id
from dplanner.domain.ledger import LedgerRecord
from dplanner.modules.agent_supervisor import supervisor
from dplanner.modules.agent_supervisor.supervisor import RefusedError, dplanner_argv

RUNNING = "running — Follow it, or Stop Playbook first"


def open_session_argv(library: Path | None, project_dir: Path, run: str) -> list[str]:
    """``dplanner agent open-session <run>`` as a terminal runs it: this build, this library."""
    return dplanner_argv(library, "agent", "open-session", run, "--project-dir", str(project_dir))


def elsewhere(record: LedgerRecord, config: Path | None = None) -> str:
    """Why the run's files are not on this machine, or "": a run's streams and its session
    are kept by the machine that launched it."""
    if record.machine and record.machine != ledger.machine_id(config):
        return f"it ran on {record.host or 'another machine'}"
    return ""


def open_session_refusal(
    record: LedgerRecord, harnesses: tuple[AgentHarness, ...], config: Path | None = None
) -> str:
    """Why the run's session cannot be opened here now, "" when it can."""
    if why := elsewhere(record, config):
        return why
    last = record.last_turn
    if not record.over and last is None:
        return "it has not started yet"
    if not record.over and last is not None and not last.end:
        return RUNNING
    harness = harness_by_id(harnesses, record.harness)
    if harness is None or not harness.resume:
        return f"{record.harness or 'its agent'} has no way to resume a session"
    if not record.session:
        return "it never recorded a session"
    return ""


def resume_argv(record: LedgerRecord, harness: AgentHarness) -> list[str]:
    """The harness's interactive resume of the run's session, as an argv."""
    return shlex.split(harness.resume.replace("{session}", record.session))


def take_over(
    project_dir: Path,
    run: str,
    by: str,
    harnesses: tuple[AgentHarness, ...],
    config: Path | None = None,
) -> tuple[list[str], Path]:
    """Fence the run as a person's when it is not over, and answer the command that opens its
    session and the directory to open it in. ``RefusedError`` says why not."""
    record = ledger.find(project_dir, run)
    if record is None:
        raise RefusedError(f"no run {run} in {project_dir}")
    if why := open_session_refusal(record, harnesses, config):
        raise RefusedError(f"run {run} cannot be opened: {why}")
    if not record.over:
        still = supervisor.stop_and_wait(
            project_dir, [record], by, ledger.TAKEN_OVER, supervisor.STOPPING_S, config
        )
        if still:
            raise RefusedError(f"run {run} is still stopping — try again in a moment")
    harness = harness_by_id(harnesses, record.harness)
    assert harness is not None  # The refusal above asked.
    return resume_argv(record, harness), Path(record.directory or project_dir)
