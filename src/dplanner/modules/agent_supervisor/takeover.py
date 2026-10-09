"""*Open Session*: a person takes a headless run's session into a terminal of their own.

A headless run is its supervisor's, and its pass's: the supervisor resumes a parked run by
itself when its question is answered, its limit resets or somebody presses *Retry now*, and an
advance launches the next stage — into the same session, since a pass's plan, execute and fix
runs share one. So a session a person opens interactively must first stop being anybody
else's, or two processes would write it. :func:`take_over` does that **under the step's launch
lock**, which every advance and launch of the step waits for: the run's pass is halted with
*Stop Playbook*'s own machinery (the engine's, handed in as :data:`HaltPass` — its runs fenced
``taken over by a person``, :data:`~dplanner.domain.ledger.TAKEN_OVER`, its gates and questions
withdrawn), every other run on the session is stopped through the one stopper,
``supervisor.stop_and_wait``, and only once each of them is over is the step released from the
squad whose run it was (the caller's ``Release``) and the harness's own resume command
(``claude --resume``, ``codex resume``, ``opencode -s``) handed back, to run in the directory the
run worked in. Its pass reads *Taken over*.

A session one of whose turns is running is refused: it is the agent's until it parks, or a
person stops it. Every step is idempotent, so a takeover that timed out waiting for a run to
stop is finished — the release included — by asking again.
"""

import shlex
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from dplanner.domain import claims, ledger
from dplanner.domain.agents import AgentHarness, harness_by_id
from dplanner.domain.ledger import LedgerRecord
from dplanner.domain.model import now_stamp
from dplanner.domain.workflow import Release
from dplanner.modules.agent_supervisor import supervisor
from dplanner.modules.agent_supervisor.supervisor import RefusedError, dplanner_argv

RUNNING = "running — Follow it, or Stop Playbook first"

# Halt the step's latest playbook pass when it is the named one, waiting up to the seconds
# given: (project_dir, step, pass, by, why, wait) → the runs here still stopping.
HaltPass = Callable[[Path, str, str, str, str, float], Sequence[str]]


def open_session_argv(library: Path | None, project_dir: Path, run: str) -> list[str]:
    """``dplanner agent open-session <run>`` as a terminal runs it: this build, this library."""
    return dplanner_argv(library, "agent", "open-session", run, "--project-dir", str(project_dir))


def elsewhere(record: LedgerRecord, config: Path | None = None) -> str:
    """Why the run's files are not on this machine, or "": a run's streams and its session
    are kept by the machine that launched it. Read without minting this machine's id, so a
    follower writes nothing."""
    if record.machine and record.machine != ledger.known_machine_id(config):
        return f"it ran on {record.host or 'another machine'}"
    return ""


def on_session(record: LedgerRecord, others: Iterable[LedgerRecord]) -> list[LedgerRecord]:
    """The runs among ``others`` that write the run's session — itself included."""
    return [
        each
        for each in others
        if each.run == record.run or (record.session and each.session == record.session)
    ]


def open_session_refusal(
    record: LedgerRecord,
    harnesses: tuple[AgentHarness, ...],
    config: Path | None = None,
    others: Iterable[LedgerRecord] = (),
) -> str:
    """Why the run's session cannot be opened here now, "" when it can. ``others`` are its
    project's runs: one on the same session whose turn is running refuses it too."""
    if why := elsewhere(record, config):
        return why
    last = record.last_turn
    if not record.over and last is None:
        return "it has not started yet"
    if not record.over and last is not None and not last.end:
        return RUNNING
    for each in on_session(record, others):
        turn = each.last_turn
        if each.run != record.run and not each.over and turn is not None and not turn.end:
            return f"its session's {each.stage or 'next'} run is {RUNNING}"
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
    *,
    halt: HaltPass,
    release: Callable[[Path, Release], bool],
    config: Path | None = None,
    wait: float = supervisor.STOPPING_S,
) -> tuple[list[str], Path]:
    """Make the run's session the person's alone, and answer the command that opens it and
    the directory to open it in. ``RefusedError`` says why not — a run still stopping after
    ``wait`` seconds included, which asking again finishes."""
    record = ledger.find(project_dir, run)
    if record is None:
        raise RefusedError(f"no run {run} in {project_dir}")
    if why := elsewhere(record, config):
        raise RefusedError(f"run {run} cannot be opened: {why}")
    with supervisor.launching(record.project, record.step, config, wait=True):
        record = ledger.find(project_dir, run) or record
        if why := open_session_refusal(record, harnesses, config, ledger.records(project_dir)):
            raise RefusedError(f"run {run} cannot be opened: {why}")
        still: list[str] = []
        if record.pass_:
            still += halt(project_dir, record.step, record.pass_, by, ledger.TAKEN_OVER, wait)
        writing = [r for r in on_session(record, ledger.records(project_dir)) if not r.over]
        still += supervisor.stop_and_wait(project_dir, writing, by, ledger.TAKEN_OVER, wait, config)
        if still:
            raise RefusedError(f"run {still[0]} is still stopping — try again in a moment")
        holding = claims.read_holdings(project_dir, now_stamp()).get(record.step)
        if record.claim and holding is not None and holding.claim.id == record.claim:
            release(project_dir, Release(record.project, record.step, "taken over"))
    harness = harness_by_id(harnesses, record.harness)
    assert harness is not None  # The refusal above asked.
    return resume_argv(record, harness), Path(record.directory or project_dir)
