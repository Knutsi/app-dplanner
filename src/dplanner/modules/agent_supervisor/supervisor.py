"""The run supervisor: one detached process per headless run, never waited on by anybody.

``dplanner agent supervise <run>`` drives a run the launch already wrote down (format 2,
``mode: headless``, its briefing in :func:`~dplanner.domain.ledger.run_dir`): it starts the
harness's headless turn (``domain/headless.py``), tees the stream into the run directory,
watches it, classifies how it ended and writes the turn into the run record. Then it does
what the ending says — and **never waits for a person**:

- ``done`` ends the run; ``stopped`` too (a SIGTERM, a fence).
- ``asked``, ``denied``, ``limit`` and a failure no retry mends (a dead login, an empty
  balance, a runaway) **park** it: the process exits, the run keeps its session, and
  whoever answers starts the supervisor again with ``--prompt``.
- a ``limit`` whose reset is known **waits** for it instead: at the reset the clock answers
  the run's ``limit`` question and the session resumes, and *Retry now* — a person's answer
  to the same question — resumes it sooner. Nothing else starts on an account that ran out
  (``limits.py``): a turn carrying no answer is parked ``limit``/``held``, unstarted.
- any other failure — a crash, a hang, an overrun, a lost turn — **retries** after 30 s,
  2 min and 10 min, resuming the session when the stream named one; a fourth failure in a
  row parks it for a person. A turn that ended waiting on its own background work is
  resumed at once with "continue", and counts toward the same streak.

**Three guards end a turn the CLI never would** (``docs/research/2026-10-03-playbooks/
failures.md``: none of the three CLIs times out a hung API): a **stall** — no output for
the harness's ``Headless.stall`` while no tool runs, since a twenty-minute test run is
silent and not hung; a **runaway** — :attr:`Guards.runaway` events in a row with nothing
produced (opencode answering a malformed reply loops forever, still emitting events); and
the stage's **wall clock**. Each ends the turn's whole process group — every member, not
just the CLI, since a test worker that ignores SIGTERM must not run on beside the retry —
and records why. Whatever happens after the spawn, the group is ended before the
supervisor lets go of the turn.

**Two locks, both the operating system's, both released when their holder dies.** The
supervisor lock (``supervisor.lock`` in the run directory) is held for the supervisor's
whole life, so a second supervisor is refused and a dead one's is free at once — no stale
file to judge. The record lock (``record.lock``) is held only across one read-modify-write
of the run's record, by the supervisor and by :func:`fence` alike, so a fence written
while a turn runs is never overwritten by the supervisor's older copy.

**A run's end is written with the turn that ended it**, so no crash can leave a ``done``
turn on a run that reads as parked; a supervisor that finds one anyway (an older build's)
ends the run rather than resumes it. A turn records its process's stamp too, so a
supervisor started after a reboot tells a turn still running from one the machine lost,
and retries the lost one — after ending, by identity, whatever of it outlived the supervisor
that started it, which nothing else would ever finish.

**Every park stands on a question, and the supervisor delivers its answer**
(``domain/questions.py``). The card is written before the parked ending; the answer, given
anywhere, is looked for whenever a supervisor starts and once more after it lets go of a
parked run, and the resume is claimed under the run's lock and the question's — the next turn
written with the answer it consumes before the question is marked consumed, so a crash in
between leaves a turn to start, never an answer to consume twice.

Qt-free: it is a CLI verb, and the run it drives must outlive every window.
"""

import errno
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO

from dplanner.cli.discovery import CALLSIGN_ENV, PROJECT_ENV, RUN_ENV
from dplanner.core.config_dir import config_dir
from dplanner.core.fsio import os_lock
from dplanner.core.process import (
    CREATE_NEW_PROCESS_GROUP,
    ProcessStamp,
    is_live,
    spawn_detached,
    stamp_of,
)
from dplanner.domain import claim_sync, ledger, questions
from dplanner.domain.agents import (
    AgentHarness,
    AgentUsage,
    Tokens,
    harness_by_id,
    scrubbed_environment,
)
from dplanner.domain.headless import (
    Ending,
    Headless,
    StageKind,
    TurnEnd,
    TurnLog,
    TurnSpec,
    stage_kind,
    verdict_of,
    write_schema,
)
from dplanner.domain.ledger import LedgerRecord, Turn
from dplanner.domain.library_file import LIBRARY_ENV
from dplanner.domain.model import Step, now_stamp
from dplanner.domain.questions import Question
from dplanner.domain.store import LibraryStore
from dplanner.modules.agent_briefing.protocol import opening_prompt
from dplanner.modules.agent_supervisor import limits
from dplanner.planning.status import Status, stored

# Why a turn after the first began, and what it is told when nobody wrote the words.
PROMPTS = {
    "answer": "",  # An answer is always somebody's words.
    "continue": "Continue the step where you left off.",
    "reset": "Your usage limit has reset. Continue the step where you left off.",
    "retry": "Your last turn was cut off. Continue the step where you left off.",
    "verdict": "Your review ended without its verdict. Give the verdict only, as your final"
    " message, in the schema you were given.",
}
# A failure that is answered at once, in the same session, rather than waited out: a turn that
# ended waiting on its own background work, and a review that ended without its verdict.
NO_VERDICT = "no-verdict"
NUDGES = {"abandoned-wait": "continue", NO_VERDICT: "verdict"}
LOCK_FILE = "supervisor.lock"
RECORD_LOCK = "record.lock"
# How often a live turn renews its squad's claim; the claim itself writes only when due.
CLAIM_BEAT = 60.0
# How long a stop waits for a run's supervisor to end its turn: the guards' grace between
# SIGTERM and SIGKILL, and a little more.
STOPPING_S = 15.0
# How long an orphaned turn's killed process is given to disappear.
ORPHAN_REAP_S = 2.0
LAUNCHES_DIR = "launches"
# How old a run with no turn must be before it may be taken for a launch nobody finished: a
# supervisor started a moment ago may not hold its lock yet.
LAUNCH_GRACE = 120.0
PLAN_FILE = "plan.md"
# The findings a fix run was handed, in its briefing's order: [{run|question, index}], written
# by the playbook engine, so the fix's typed `declined` numbers can be recorded as references.
FINDINGS_FILE = "findings.json"
# How long the stream is still read once its process group has ended: a CLI's SIGTERM
# handler may print the turn's last totals on the way out.
DRAIN_SECONDS = 2.0
OVER = (TurnEnd.DONE, TurnEnd.STOPPED)
# A turn claimed on an answer that was starting when its supervisor was lost: it may have
# acted on the answer, so it is never started again without a person.
LOST_AT_SPAWN = "lost-at-spawn"
# Failures no wait mends, beside the ones Ending.needs_person names: they park at once.
PARK_AT_ONCE = ("runaway", LOST_AT_SPAWN)
# A turn the supervisor parked without starting it: its account had run out.
HELD = "held"
# A limit whose reset had already passed when its turn ended — the turn's cleanup crossed it,
# or this clock runs ahead: waited for once, the grace only, and never twice in a row.
PAST_RESET = "past-reset"


class RefusedError(Exception):
    """The run cannot be supervised now, and the message says why."""


@dataclass(frozen=True)
class Guards:
    """What ends a turn the CLI would not end itself, and how long a retry waits."""

    # The wall clock per stage. The 10-04 run's steps took 9 to 52 minutes of agent time,
    # and a step is sized at two to four hours; a plan or a review is a fraction of that.
    wall: Mapping[str, float] = field(
        default_factory=lambda: {
            StageKind.PLAN: 45 * 60.0,
            StageKind.EXECUTE: 3 * 3600.0,
            StageKind.REVIEW: 45 * 60.0,
        }
    )
    # Events in a row with nothing produced. opencode's malformed-reply loop sent eleven a
    # second; an agent at work produces something far more often than this.
    runaway: int = 1000
    backoff: tuple[float, ...] = (30.0, 120.0, 600.0)
    grace: float = 10.0  # Between SIGTERM and SIGKILL.
    poll: float = 1.0  # How often a silent turn is looked at.
    # How often a run parked on a limit looks for Retry now while it waits for the reset.
    wake: float = 5.0
    # How long after the reset the clock resumes it: a reset is the vendor's word to the
    # second, and a turn a moment early would only park again.
    reset_grace: float = 60.0


def supervise(
    project_dir: Path,
    run: str,
    harnesses: tuple[AgentHarness, ...],
    *,
    prompt: str = "",
    text: str = "",
    guards: Guards | None = None,
    config: Path | None = None,
    library: Path | None = None,
    advance: Callable[[Path, LedgerRecord], None] | None = None,
) -> str:
    """Drive the run until it is over or parked; the sentence that says which.

    ``prompt`` is why a parked run resumes — ``answer``, ``continue``, ``reset`` or
    ``retry`` — and ``text`` the words it resumes with (the answer). ``config`` is the
    directory the run directories are under, ``config_dir()`` unless a test says otherwise.
    ``library`` is the library the run was launched from, which every turn's ``dplanner``
    calls must reach. ``advance`` is told about a playbook's run that ended ``done`` — the
    pass's next stage is then due — and never waited on (:func:`advance_detached`).
    """
    guards = guards or Guards()
    # Absolute: a turn runs in its worktree, where a relative path names nothing.
    library = library.expanduser().resolve() if library is not None else None
    said, again = "", False
    while True:
        try:
            said = _drive(project_dir, run, harnesses, prompt, text, guards, config, library)
        except RefusedError:
            if again:  # Another supervisor holds the run, and delivers the answer itself.
                return said
            raise
        # An answer given while this supervisor let go of the run: whoever answered started a
        # supervisor that either holds the lock now — and delivers it — or found it held and
        # gave up, which this check, made after letting go, makes up for.
        if not answer_waiting(project_dir, run):
            return said + _advanced(project_dir, run, advance)
        prompt, text, again = "", "", True


def _drive(
    project_dir: Path,
    run: str,
    harnesses: tuple[AgentHarness, ...],
    prompt: str,
    text: str,
    guards: Guards,
    config: Path | None,
    library: Path | None,
) -> str:
    with supervising(ledger.run_dir(run, config)), _stoppable() as stop:
        record = _record(project_dir, run)
        harness = harness_by_id(harnesses, record.harness)
        if harness is None or harness.headless is None:
            raise RefusedError(f"run {run}: no harness here runs {record.harness!r} headless")
        session = Session(
            project_dir, config, record, harness, harness.headless, guards, library=library
        )
        kind, words = session.opening(prompt, text, stop)
        while kind:
            ending = session.turn(kind, words, stop)
            kind, words = session.next(ending, stop)
        return words


def _advanced(
    project_dir: Path, run: str, advance: Callable[[Path, LedgerRecord], None] | None
) -> str:
    """Hand a playbook's finished stage on to its pass; what to add to the sentence."""
    record = ledger.find(project_dir, run)
    last = record.last_turn if record is not None else None
    if advance is None or record is None or last is None or not record.pass_:
        return ""
    if not record.over or last.end != TurnEnd.DONE:
        return ""
    try:
        advance(project_dir, record)
    except OSError as error:
        return f"; its pass did not advance: {error}"
    return "; its pass advances"


def answer_waiting(project_dir: Path, run: str) -> bool:
    """Whether the run stands parked on a question somebody has answered, or holds a resume
    claimed on an answer that never started — either way, a supervisor has work to do."""
    record = ledger.find(project_dir, run)
    last = record.last_turn if record is not None else None
    if record is None or last is None or record.over or record.fence:
        return False
    if not last.end:
        return not last.pid and bool(last.consumed)
    question = questions.find(project_dir, last.question) if last.question else None
    return question is not None and question.state == questions.ANSWERED


def fence(project_dir: Path, run: str, by: str, why: str, config: Path | None = None) -> None:
    """Fence the run — a takeover's one write to a run it did not launch — under the same
    record lock the supervisor writes under, so neither write is lost."""
    stamp = {"at": now_stamp(), "by": by, "why": why}
    update(
        project_dir,
        run,
        lambda record: record if record.fence else replace(record, fence=stamp),
        config,
    )


def stop(project_dir: Path, run: str, by: str, why: str, config: Path | None = None) -> None:
    """Fence the run, and end the turn a supervisor on this machine is driving with the
    SIGTERM it turns into ``stopped``. A supervisor elsewhere — or on Windows, where the
    signal cannot be caught — finds the fence before its next turn."""
    fence(project_dir, run, by, why, config)
    directory = ledger.run_dir(run, config)
    if sys.platform != "win32" and supervised(directory):
        with suppress(OSError, ValueError):
            os.kill(int((directory / LOCK_FILE).read_text(encoding="utf-8")), signal.SIGTERM)


def stop_and_wait(
    project_dir: Path,
    records: Iterable[LedgerRecord],
    by: str,
    why: str,
    wait: float,
    config: Path | None = None,
) -> list[str]:
    """Stop the runs and wait up to ``wait`` seconds for each to be over: the runs of this
    machine still stopping, by id. Each is fenced; a supervisor here is signalled and waited
    for; a run nobody supervises — parked, never started, or a turn that outlived its
    supervisor — is ended here (:func:`settle_fenced`). A run on another machine is fenced
    only: that machine's supervisor obeys the fence when the ledger reaches it."""
    records = list(records)
    here = ledger.machine_id(config)
    for record in records:
        stop(project_dir, record.run, by, why, config)
    deadline = time.monotonic() + wait
    still: list[str] = []
    for record in records:
        if record.machine != here:
            continue
        directory = ledger.run_dir(record.run, config)
        while supervised(directory) and time.monotonic() < deadline:
            time.sleep(0.2)
        if supervised(directory) or not settle_fenced(project_dir, record.run, wait, config):
            still.append(record.run)
    return still


def settle_fenced(project_dir: Path, run: str, grace: float, config: Path | None = None) -> bool:
    """End a fenced run of this machine that no supervisor drives — what a supervisor finding
    the fence does: whatever of it still runs ended first (:func:`end_orphaned_turn`), then
    the run, its questions withdrawn. A run already over is swept too, for a process its turn
    left behind. The run's supervisor lock is held throughout, so none starts on it
    meanwhile. Whether the run is over now, nothing of it running; False while a supervisor
    holds it, or something of it will not end."""
    try:
        with os_lock(ledger.run_dir(run, config) / LOCK_FILE, wait=False):
            record = ledger.find(project_dir, run)
            if record is None:
                return True
            if record.machine != ledger.machine_id(config):
                return record.over
            if not record.over and not record.fence:
                return False
            if not end_orphaned_turn(record, grace):
                return False
            if not record.over:
                update(project_dir, run, lambda fresh: fresh.ended_at(now_stamp(), None), config)
                questions.withdraw_unsettled(project_dir, run, "the run was stopped", config=config)
            return True
    except BlockingIOError:
        return False


def end_orphaned_turn(record: LedgerRecord, grace: float) -> bool:
    """End whatever of the run still runs with no supervisor to end it — SIGTERM, then
    SIGKILL after ``grace`` — and answer whether nothing of it is left.

    Found by identity, never by a pid alone: every process whose environment carries the run
    (``DPLANNER_RUN``, which a turn and everything it starts inherit), and the turn's recorded
    process group while it is provably the turn's — its leader the very process recorded (pid,
    boot and start time), or a member carrying the run. So a child that outlived its leader,
    and a turn whose supervisor died before it wrote its pid down, are ended too. Only Linux
    lets one process read another's environment; elsewhere the recorded leader alone counts."""
    last = record.last_turn
    leader = ProcessStamp(last.pid, last.boot, last.pid_started) if last and last.pid else None
    group = _turn_group(record.run, leader)
    if not _run_left(record.run, leader, group):
        return True
    _end_run(record.run, leader, group, hard=False)
    deadline = time.monotonic() + grace
    while _run_left(record.run, leader, group) and time.monotonic() < deadline:
        time.sleep(0.05)
    if _run_left(record.run, leader, group):
        _end_run(record.run, leader, group, hard=True)
    deadline = time.monotonic() + ORPHAN_REAP_S
    while _run_left(record.run, leader, group) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not _run_left(record.run, leader, group)


def carrying_run(run: str) -> list[ProcessStamp]:
    """Every process of this machine whose environment names ``run``, as it was when found —
    never this one nor an ancestor of it, which a stop given from inside the run would
    otherwise end, the person's own shell with it. Linux only; [] elsewhere, where no process
    may read another's environment."""
    if sys.platform != "linux":
        return []
    else:
        lineage = _lineage()
        found = []
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit() or int(proc.name) in lineage:
                continue
            stamp = stamp_of(int(proc.name)) if _carries(int(proc.name), run) else None
            if stamp is not None:
                found.append(stamp)
        return found


def _carries(pid: int, run: str) -> bool:
    try:
        environ = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:  # Gone meanwhile, or somebody else's.
        return False
    return f"{RUN_ENV}={run}".encode() in environ.split(b"\0")


def _lineage() -> set[int]:
    """This process and every ancestor of it, by each one's parent in ``/proc/<pid>/stat``."""
    pids, pid = set(), os.getpid()
    while pid > 0 and pid not in pids:
        pids.add(pid)
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
        except OSError:
            break
        # The command name is in parentheses and may hold spaces; the parent is the second
        # field after the closing one.
        fields = stat.rpartition(")")[2].split()
        pid = int(fields[1]) if len(fields) > 1 and fields[1].isdigit() else 0
    return pids


def _signal_carrier(found: ProcessStamp, run: str, sig: signal.Signals) -> None:
    """Signal a process :func:`carrying_run` found only while it is still that process and
    still carries the run — a pid can be reused between the scan and the signal. Linux holds
    the process by a pidfd across the check and signals through it, so the signal reaches the
    process checked or none; without pidfds the stamp is checked just before the kill."""
    if sys.platform != "linux":
        return
    else:
        try:
            handle = os.pidfd_open(found.pid)
        except OSError as error:
            if error.errno != errno.ENOSYS:
                return  # Gone already.
            handle = -1  # A kernel without pidfds.
        try:
            if is_live(found) and _carries(found.pid, run):
                with suppress(ProcessLookupError, PermissionError):
                    if handle < 0:
                        os.kill(found.pid, sig)
                    else:
                        signal.pidfd_send_signal(handle, sig)
        finally:
            if handle >= 0:
                os.close(handle)


def _turn_group(run: str, leader: ProcessStamp | None) -> int:
    """The turn's process group, when it is provably still the turn's; 0 when not."""
    if sys.platform == "win32" or leader is None:
        return 0
    else:
        if is_live(leader):
            return leader.pid
        for found in carrying_run(run):
            with suppress(OSError):
                if os.getpgid(found.pid) == leader.pid:
                    return leader.pid
        return 0


def _run_left(run: str, leader: ProcessStamp | None, group: int) -> bool:
    if (leader is not None and is_live(leader)) or carrying_run(run):
        return True
    if sys.platform == "win32" or not group:
        return False
    else:
        try:
            os.killpg(group, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


def _end_run(run: str, leader: ProcessStamp | None, group: int, *, hard: bool) -> None:
    if sys.platform == "win32":
        if leader is not None and is_live(leader):
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(leader.pid)], capture_output=True, check=False
            )
    else:
        sig = signal.SIGKILL if hard else signal.SIGTERM
        for found in carrying_run(run):
            _signal_carrier(found, run, sig)
        if group:
            with suppress(ProcessLookupError, PermissionError):
                os.killpg(group, sig)


def update(
    project_dir: Path,
    run: str,
    change: Callable[[LedgerRecord], LedgerRecord],
    config: Path | None = None,
) -> LedgerRecord:
    """Read the run's record, change it and write it back, all under the run's record lock."""
    directory = ledger.run_dir(run, config)
    with os_lock(directory / RECORD_LOCK, wait=True):
        changed = change(_record(project_dir, run))
        ledger.write(project_dir, changed)
        return changed


@dataclass
class Session:
    """One supervisor's hold on one run: the record as last written, and how to go on."""

    project_dir: Path
    config: Path | None  # Where the run directories are: ``config_dir()`` when None.
    record: LedgerRecord
    harness: AgentHarness
    headless: Headless
    guards: Guards
    # The turn a claimed answer resumes with, written before it is spawned.
    claimed: Turn | None = None
    # The library the run was launched from; None leaves the inherited one.
    library: Path | None = None

    @property
    def directory(self) -> Path:
        return ledger.run_dir(self.record.run, self.config)

    @property
    def kind(self) -> StageKind:
        kind = stage_kind(self.record.stage)
        assert kind is not None  # _record refuses a run whose stage is no agent stage.
        return kind

    @property
    def account(self) -> str:
        return limits.account_of(self.harness)

    # -- deciding ---------------------------------------------------------------------------

    def opening(self, prompt: str, text: str, stop: threading.Event) -> tuple[str, str]:
        """The first turn this supervisor starts — the launch, a parked run's resume, or what
        follows a turn the machine lost — as :meth:`next` answers."""
        self._reconcile()
        record = self.record
        if record.over:
            raise RefusedError(f"run {record.run} is over")
        if record.fence:
            # A turn that outlived its supervisor is ended first: until it is gone, the run
            # is not over, whatever the fence says.
            if not end_orphaned_turn(record, self.guards.grace):
                raise RefusedError(f"run {record.run} is fenced, and its last turn will not end")
            self._end(TurnEnd.STOPPED)
            raise RefusedError(f"run {record.run} was fenced: {record.fence.get('why', '')}")
        last = record.last_turn
        if last is None:
            return "launch", ""
        if last.end in OVER:
            # A turn that ended the run, written by a build that wrote the run's end apart.
            self._end(TurnEnd(last.end))
            return "", _over(record.run, TurnEnd(last.end))
        if not last.end:
            if not last.pid and last.consumed:
                return self._recover(last, stop)
            # This supervisor holds the run's lock, so the one that started the turn is gone,
            # and a worker still running has nobody to finish its turn or advance its pass:
            # it is ended, by identity, before its turn is recorded lost and retried.
            if not end_orphaned_turn(record, self.guards.grace):
                raise RefusedError(
                    f"run {record.run}: turn {last.n} is still running (pid {last.pid}),"
                    " and will not end"
                )
            lost = Ending(TurnEnd.FAILED, "lost", "its process is gone")
            return self.next(self._finish(last, self._streamed(last.n), None, lost), stop)
        if (
            not text
            and last.question
            and (prompt == "answer" or (not prompt and self._answered(last) is not None))
        ):
            return self._claim(last)
        if not prompt and not text and self._waits_for_reset(last):
            # Picked up again after a reboot, or by hand: the clock still resumes it.
            return self._await_reset(last, stop)
        if prompt not in PROMPTS:
            raise RefusedError(
                f"run {record.run} is parked ({_said(last)}); resume it with --prompt "
                + "|".join(PROMPTS)
            )
        if prompt == "answer" and not text:
            raise RefusedError("an answer needs its words: --text")
        # Words handed to the supervisor, or a resume that is no answer: the run goes on
        # without what it parked on.
        self._settle(f"the run resumed with {prompt}")
        return prompt, text or PROMPTS[prompt]

    def next(self, ending: Ending, stop: threading.Event) -> tuple[str, str]:
        """What follows a turn: the next turn's prompt and words, or ("", why it stopped)."""
        if ending.end in OVER:
            if ending.end is TurnEnd.STOPPED and self._fenced():
                return "", f"run {self.record.run} was fenced"
            return "", _over(self.record.run, ending.end)
        last = self.record.turns[-1]
        failures = _failures(self.record)
        if self._parks(ending, failures):
            parked = f"run {self.record.run} is parked: {_said(last)}"
            if ending.end is TurnEnd.FAILED and failures > len(self.guards.backoff):
                parked += f", {failures} failures in a row"
            questions.withdraw_unsettled(
                self.project_dir,
                self.record.run,
                "the run parked on another question",
                keep=last.question,
                config=self.config,
            )
            if self._answered(last) is not None:
                # Answered while the turn was ending: resume on it at once.
                try:
                    return self._claim(last)
                except RefusedError as refused:
                    return "", f"{parked}; {refused}"
            if self._waits_for_reset(last):
                return self._await_reset(last, stop)
            return "", f"{parked}, on {questions.short(last.question)}"
        # Going on by itself: nothing the run asked before it failed stands any more, an
        # answer not yet acted on included — no turn will consume it now.
        questions.withdraw_unsettled(
            self.project_dir, self.record.run, "the run went on by itself", config=self.config
        )
        nudge = NUDGES.get(ending.why, "")
        if not nudge and stop.wait(self.guards.backoff[failures - 1]):
            self._end(TurnEnd.STOPPED)
            return "", _over(self.record.run, TurnEnd.STOPPED)
        self.record = _record(self.project_dir, self.record.run)
        if self.record.fence:
            self._end(TurnEnd.STOPPED)
            return "", f"run {self.record.run} was fenced"
        if nudge:
            return nudge, PROMPTS[nudge]
        return "retry", PROMPTS["retry"]

    # -- one turn ---------------------------------------------------------------------------

    def turn(self, kind: str, words: str, stop: threading.Event) -> Ending:
        claimed, self.claimed = self.claimed, None
        n = claimed.n if claimed is not None else len(self.record.turns) + 1
        out = limits.exhausted(self.account, config=self.config)
        if claimed is None and out is not None:
            # Nothing else starts on an account that ran out; an answer always goes, since
            # it was consumed for this turn, and Retry now is a person saying go.
            said = f"{self.harness.label} is out of usage until {limits.clock(out)}"
            held = Turn(n=n, prompt=kind, started=now_stamp())
            return self._finish(held, TurnLog(), None, Ending(TurnEnd.LIMIT, HELD, said, out))
        spec = self._spec(kind, words)
        env = scrubbed_environment(os.environ, (self.harness,))
        # Every `dplanner` call the turn makes reaches the plan its run was launched from:
        # the run (what `question ask` parks), the project and the library — and is the
        # member that runs it, never the coordinator whose shell started the supervisor.
        env[RUN_ENV], env[PROJECT_ENV] = self.record.run, self.record.project
        env[CALLSIGN_ENV] = self.record.callsign
        if self.library is not None:
            env[LIBRARY_ENV] = str(self.library)
        argv = self.headless.command(spec)
        argv[0] = shutil.which(argv[0], path=env.get("PATH")) or argv[0]
        stream = self.directory / f"turn-{n}.jsonl"
        errors = self.directory / f"turn-{n}.stderr"
        turn = claimed or Turn(n=n, prompt=kind, started=now_stamp())
        if claimed is not None:
            # From here an absent pid no longer proves the answer was never acted on.
            turn = replace(turn, spawning=now_stamp())
            self._write(turn)
        log = TurnLog()
        with stream.open("w", encoding="utf-8") as tee, errors.open("wb") as err:
            try:
                process = _spawn(argv, Path(self.record.directory or "."), env, err)
            except OSError as error:
                failed = Ending(TurnEnd.FAILED, "unknown", f"could not start {argv[0]}: {error}")
                return self._finish(turn, log, None, failed)
            try:
                stamp = stamp_of(process.pid) or ProcessStamp(process.pid, "", "")
                turn = replace(turn, pid=stamp.pid, boot=stamp.boot, pid_started=stamp.started)
                self._write(turn)
                killed = self._watch(process, log, tee, spec.stage, stop)
            except BaseException as error:
                # Never leave a turn running unsupervised: end its group, say why, go.
                _end_group(process, self.guards.grace)
                failed = Ending(
                    TurnEnd.FAILED, "supervisor-error", f"{type(error).__name__}: {error}"
                )
                with suppress(Exception):
                    self._finish(turn, log, process.returncode, failed)
                raise
        code = process.returncode
        stderr = errors.read_text(encoding="utf-8", errors="replace")[-16_000:]
        if killed == "stopped":
            ending = Ending(TurnEnd.STOPPED, reason="the supervisor was told to stop")
        elif killed:
            ending = Ending(TurnEnd.FAILED, killed, _KILLED_BECAUSE[killed])
        else:
            recorded = self._asked_since(turn.started)
            ending = self.headless.classify(
                code, log, stderr, recorded.text if recorded is not None else None
            )
            if recorded is not None and ending.end is TurnEnd.ASKED:
                turn = replace(turn, question=recorded.id)
            if ending.end is TurnEnd.LIMIT:
                ending = self._with_reset(ending, turn.n)
            if self._owes_verdict(kind, ending, log):
                ending = Ending(TurnEnd.FAILED, NO_VERDICT, "the review ended without its verdict")
        return self._finish(turn, log, code, ending)

    def _owes_verdict(self, kind: str, ending: Ending, log: TurnLog) -> bool:
        """A review that ended done with no verdict — none typed, or one that does not validate
        against the schema — not nudged for one yet: it gets one
        more turn in its session. Nudged once already, it ends the run without one — which
        is a failure the pass escalates, never a pass."""
        nudged = kind == "verdict" or any(t.prompt == "verdict" for t in self.record.turns)
        return (
            self.kind is StageKind.REVIEW
            and ending.end is TurnEnd.DONE
            and verdict_of(log.typed) is None
            and not nudged
        )

    def _with_reset(self, ending: Ending, n: int) -> Ending:
        """When a limit lifts: as its own turn said, else as the account last said — a CLI
        may stop on its error before it reports the windows. A reset already past is kept as
        the deadline, marked :data:`PAST_RESET`, so the run resumes once after the grace; the
        turn before this one marked so too, and it is unknown — a person's, never a loop."""
        now = datetime.now(UTC)
        reset = ending.resets or limits.last_reset(self.account, now, self.config)
        if reset is None or reset > now:
            return replace(ending, resets=reset)
        earlier = [t for t in self.record.turns if t.n < n]
        if earlier and earlier[-1].why == PAST_RESET:
            return replace(ending, resets=None)
        return replace(ending, resets=reset, why=PAST_RESET)

    def _spec(self, kind: str, words: str) -> TurnSpec:
        stage = self.kind
        # The plan is written through `dplanner`, inside the project directory: the 10-04
        # run's 21 Codex sandbox prompts were that directory outside the writable roots.
        spec = TurnSpec(
            stage,
            words,
            str(self.directory),
            writable=(str(self.project_dir),),
            checkout=self.record.directory,
            config=str(self.config or config_dir()),
        )
        opening = opening_prompt(self.directory / "prompt.md")
        if kind == "launch" and self._continues():
            # A loop-back, or an execute after its plan: the work stage's own session goes on.
            spec = spec.resumed(self.record.session, opening)
        elif kind != "launch" and self._streamed_session():
            spec = spec.resumed(self.record.session, words)
        else:
            # A fresh session: the launch, or a retry of a turn that never got one going.
            spec = replace(spec, prompt=opening)
            if self.harness.names_session:
                session = (self.record.session if kind == "launch" else "") or str(uuid.uuid4())
                self._update(lambda record: replace(record, session=session))
                spec = replace(spec, session=session)
        write_schema(spec)
        return spec

    def _continues(self) -> bool:
        """Whether this run's launch resumes a session an earlier run of its pass worked in —
        derived, never stored: a fresh session is one no other run names."""
        record = self.record
        if not record.session or not record.pass_:
            return False
        return any(
            other.run != record.run
            and other.pass_ == record.pass_
            and other.session == record.session
            for other in ledger.records(self.project_dir)
        )

    def _streamed_session(self) -> bool:
        """Whether some turn's stream has shown the session exists, so it can be resumed."""
        return bool(self.record.session) and any(
            self._streamed(turn.n).session for turn in self.record.turns
        )

    def _fenced(self) -> bool:
        """Whether a takeover or a release fenced the run while its turn runs: read on every
        poll, so the turn stops within a second wherever the fence was written here."""
        record = ledger.find(self.project_dir, self.record.run)
        return record is not None and bool(record.fence)

    def _watch(
        self,
        process: "subprocess.Popen[str]",
        log: TurnLog,
        tee: IO[str],
        stage: StageKind,
        stop: threading.Event,
    ) -> str:
        """Read the turn to its end, or kill it; why it was killed ("" when it was not).

        The stream closing is not the turn ending — a CLI can close its output and hang on
        the way out — so the guards keep running until the process has exited too. However
        it ends, the turn's process group is ended with it, and what the stream said on the
        way out is read before the reader is let go."""
        lines: queue.Queue[str | None] = queue.Queue()
        reader = threading.Thread(target=_pump, args=(process, lines), daemon=True)
        reader.start()
        began = heard = beat = time.monotonic()
        wall = self.guards.wall.get(stage, max(self.guards.wall.values()))
        eof, killed = False, ""
        renewing: threading.Thread | None = None
        while True:
            try:
                line = lines.get(timeout=self.guards.poll)
            except queue.Empty:
                line = ""
            if line is None:
                eof, line = True, ""
            now = time.monotonic()
            if line:
                heard = now
                self._heard(log, tee, line)
            if eof and process.poll() is not None:
                break
            if (
                self.record.claim
                and now - beat >= CLAIM_BEAT
                and not (renewing and renewing.is_alive())
            ):
                # A live turn is the squad's sign of life while its coordinator waits the
                # stage out; off this thread, since a renewal may push.
                beat = now
                renewing = threading.Thread(
                    target=claim_sync.renew,
                    args=(self.project_dir, self.record.claim, self.config),
                    daemon=True,
                )
                renewing.start()
            killed = (
                "stopped"
                if stop.is_set() or self._fenced()
                else "runaway"
                if log.idle >= self.guards.runaway
                else "timeout"
                if now - began > wall
                else "hang"
                if not log.tools and now - heard > self.headless.stall
                else ""
            )
            if killed:
                break
        _end_group(process, self.guards.grace)
        deadline = time.monotonic() + DRAIN_SECONDS
        while not eof and (left := deadline - time.monotonic()) > 0:
            try:
                line = lines.get(timeout=left)
            except queue.Empty:
                break
            if line is None:
                eof = True
            else:
                self._heard(log, tee, line)
        reader.join(max(0.0, deadline - time.monotonic()))
        return killed

    def _heard(self, log: TurnLog, tee: IO[str], line: str) -> None:
        tee.write(line)
        tee.flush()
        self.headless.feed(log, line)
        if log.session and log.session != self.record.session:
            session = log.session
            self._update(lambda record: replace(record, session=session))

    def _streamed(self, n: int) -> TurnLog:
        """What turn ``n``'s stream said, read back from its file."""
        try:
            with (self.directory / f"turn-{n}.jsonl").open(encoding="utf-8") as stream:
                return self.headless.read_lines(stream)
        except OSError:
            return TurnLog()

    # -- writing ----------------------------------------------------------------------------

    def _finish(self, turn: Turn, log: TurnLog, code: int | None, ending: Ending) -> Ending:
        """Write how the turn ended — and, when it ended the run, the run's end in the same
        write, so no crash can leave a finished turn on a run that reads as parked."""
        ended = now_stamp()
        limits.record_turn(
            self.account,
            self.record.run,
            self.headless.limits(log),
            ending.end,
            ending.resets,
            limits.parse(ended) or datetime.now(UTC),
            self.config,
        )
        turn = replace(
            turn,
            ended=ended,
            end=ending.end.value,
            why=ending.why,
            reason=ending.question or ending.reason,
            exit=code,
            resets=ending.resets.isoformat() if ending.resets else "",
            agents=usage_of(log, self.headless.model(log)),
        )
        if not turn.question and self._parks(ending, _failures(_with_turn(self.record, turn))):
            # The card first: a crash after it leaves a card on a lost turn, which the next
            # supervisor withdraws as it retries — never a parked run nobody is asked about.
            question = _question_for(self.record, turn, ending)
            questions.write(self.project_dir, question)
            turn = replace(turn, question=question.id)
        done = ending.end is TurnEnd.DONE
        verdict = verdict_of(log.typed) if done and self.kind is StageKind.REVIEW else None
        if done and self.kind is StageKind.PLAN and log.final:
            (self.directory / PLAN_FILE).write_text(log.final, encoding="utf-8")
        declined = (
            self._declined(log.typed)
            if done and log.typed and self.kind is StageKind.EXECUTE
            else ()
        )

        def finished(record: LedgerRecord) -> LedgerRecord:
            record = _with_turn(record, turn)
            if verdict is not None:
                record = replace(record, verdict=dict(verdict))
            if declined:
                record = replace(record, declined=declined)
            if ending.end in OVER:
                record = record.ended_at(turn.ended, code if done else None)
            return record

        self._update(finished)
        if ending.end in OVER:
            self._settle(f"the run is {ending.end}")
        return ending

    def _declined(self, typed: Mapping[str, object]) -> tuple[dict[str, object], ...]:
        """A fix's typed declines, each finding's number in its briefing turned into the
        reference the engine handed it under (:data:`FINDINGS_FILE`); a number it was not
        handed is dropped."""
        try:
            handed = json.loads((self.directory / FINDINGS_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ()
        given = typed.get("declined")
        if not isinstance(handed, list) or not isinstance(given, list):
            return ()
        found = []
        for each in given:
            number = each.get("finding") if isinstance(each, dict) else None
            if isinstance(number, int) and 1 <= number <= len(handed):
                found.append({"finding": handed[number - 1], "reason": str(each.get("reason", ""))})
        return tuple(found)

    def _end(self, end: TurnEnd) -> None:
        last = self.record.last_turn
        code = last.exit if last is not None and end is TurnEnd.DONE else None
        self._update(lambda record: record.ended_at(now_stamp(), code))
        self._settle(f"the run is {end}")

    # -- its questions ------------------------------------------------------------------------

    def _asked_since(self, started: str) -> Question | None:
        """The question the agent recorded through `dplanner question ask` during the turn —
        answered already, if somebody was quick."""
        found = [
            q
            for q in questions.of_run(self.project_dir, self.record.run)
            if not q.settled and q.asked >= started
        ]
        return found[-1] if found else None

    def _parks(self, ending: Ending, failures: int) -> bool:
        """Whether the ending parks the run, ``failures`` being the failed turns in a row."""
        if ending.end in OVER:
            return False
        if ending.end is not TurnEnd.FAILED or ending.needs_person or ending.why in PARK_AT_ONCE:
            return True
        return failures > len(self.guards.backoff)

    def _answered(self, turn: Turn) -> Question | None:
        question = questions.find(self.project_dir, turn.question) if turn.question else None
        return question if question is not None and question.state == questions.ANSWERED else None

    def _claim(self, last: Turn) -> tuple[str, str]:
        """Claim the resume on the answer to the question the run parked on — under the run's
        lock and the question's, re-reading both: the run still this machine's, not fenced,
        not over, its last turn parked on this question, the question answered. One ledger
        write records the next turn with the answer it consumes, then the question is marked
        consumed; a crash between the two leaves a turn :meth:`_recover` starts, never one
        consumed twice."""
        run, machine = self.record.run, ledger.machine_id(self.config)
        with (
            os_lock(self.directory / RECORD_LOCK, wait=True),
            questions.held(last.question, self.config),
        ):
            record = _record(self.project_dir, run)
            latest = record.last_turn
            question = questions.find(self.project_dir, last.question)
            refusal = _not_ours(record, machine) or (
                "it is no longer parked on that question"
                if not record.parked or latest is None or latest.question != last.question
                else f"{questions.short(last.question)} is gone"
                if question is None
                else f"{question.short} is {question.state}, not answered"
                if question.state != questions.ANSWERED
                else ""
            )
            if refusal or question is None or latest is None:
                raise RefusedError(f"run {run} cannot resume on its answer: {refusal}")
            kind, words = resumed_by(question)
            claimed = Turn(
                n=latest.n + 1,
                prompt=kind,
                started=now_stamp(),
                consumed={"question": question.id, "answer": str(question.answer.get("id", ""))},
            )
            ledger.write(self.project_dir, _with_turn(record, claimed))
            questions.write(
                self.project_dir, questions.consumed(question, now_stamp(), run, claimed.n)
            )
        self.record = _record(self.project_dir, run)
        self.claimed = claimed
        self._settle("the run resumed on another answer")
        return kind, words

    def _recover(self, claimed: Turn, stop: threading.Event) -> tuple[str, str]:
        """A turn claimed on an answer whose process has no pid. If it was never about to
        start — no ``spawning`` — start it, after the claim's own locked check, never
        consuming the answer again. If it may have started, the agent may already have acted
        on the answer, so it ends ``failed``/``lost-at-spawn`` and parks for a person."""
        if claimed.spawning:
            said = questions.short(claimed.consumed.get("question", ""))
            lost = Ending(
                TurnEnd.FAILED,
                LOST_AT_SPAWN,
                f"turn {claimed.n} was starting on the answer to {said} when its supervisor was"
                " lost, and may have acted on it: resume it again only if it did not",
            )
            return self.next(self._finish(claimed, self._streamed(claimed.n), None, lost), stop)
        with os_lock(self.directory / RECORD_LOCK, wait=True):
            record = _record(self.project_dir, self.record.run)
            refusal = _not_ours(record, ledger.machine_id(self.config))
            latest = record.last_turn
            if not refusal and (latest is None or latest.n != claimed.n or latest.end):
                refusal = "its claimed turn has moved on"
            if refusal:
                raise RefusedError(f"run {record.run} cannot resume on its answer: {refusal}")
        found = questions.find(self.project_dir, claimed.consumed.get("question", ""))
        if found is not None and found.answer.get("id") == claimed.consumed.get("answer"):
            questions.update(
                self.project_dir,
                found.id,
                lambda q: (
                    questions.consumed(q, now_stamp(), self.record.run, claimed.n)
                    if q.state == questions.ANSWERED
                    else q
                ),
                self.config,
            )
        self.claimed = claimed
        words = resumed_by(found)[1] if found is not None else PROMPTS["continue"]
        return claimed.prompt, words

    def _waits_for_reset(self, last: Turn) -> bool:
        return waits_for_reset(self.project_dir, last)

    def _await_reset(self, last: Turn, stop: threading.Event) -> tuple[str, str]:
        """Wait for the limit's reset, then answer its question for the clock and resume —
        or resume at once on Retry now, or stop for a fence, a SIGTERM or a question that no
        longer stands. A clock is no person: nothing here waits on anybody, and Retry now is
        an answer the supervisor finds, never a process it needs."""
        reset = limits.parse(last.resets) or datetime.now(UTC)
        due = reset + timedelta(seconds=self.guards.reset_grace)
        run = self.record.run
        while True:
            question = questions.find(self.project_dir, last.question)
            if question is None or question.state not in questions.UNSETTLED:
                return "", f"run {run} is parked on {questions.short(last.question)}, which is gone"
            if question.state == questions.ANSWERED:
                try:
                    return self._claim(last)
                except RefusedError as refused:
                    return "", f"run {run} is parked; {refused}"
            record = _record(self.project_dir, run)
            if record.over:
                return "", f"run {run} is over"
            if record.fence:
                self.record = record
                self._end(TurnEnd.STOPPED)
                return "", f"run {run} was fenced"
            left = (due - datetime.now(UTC)).total_seconds()
            if left <= 0:
                questions.clock_answer(self.project_dir, last.question, self.config)
                continue
            if stop.wait(min(self.guards.wake, left)):
                if _record(self.project_dir, run).fence:  # Stopped by its fence's SIGTERM.
                    continue
                # A shutdown, not a decision: the run stays parked on its limit, and the next
                # supervisor `revive` starts waits on. Only a fence ends a waiting run.
                return "", f"run {run} is parked on its limit; its supervisor was stopped"

    def _reconcile(self) -> None:
        """Mend what a supervisor that died between two writes left: an ended run's cards
        still standing, a parked run with no card."""
        record, last = self.record, self.record.last_turn
        if record.over:
            self._settle("the run is over")
            return
        if last is None or not last.end or last.question or last.end in OVER:
            return
        ending = Ending(TurnEnd(last.end), last.why, last.reason)
        if self._parks(ending, _failures(record)):
            question = _question_for(record, last, ending)
            questions.write(self.project_dir, question)
            self._write(replace(last, question=question.id))

    def _settle(self, why: str, keep: str = "") -> None:
        """Withdraw what the run no longer waits on: it ended, or went on without it."""
        questions.withdraw_unsettled(self.project_dir, self.record.run, why, keep, self.config)

    def _write(self, turn: Turn) -> None:
        self._update(lambda record: _with_turn(record, turn))

    def _update(self, change: Callable[[LedgerRecord], LedgerRecord]) -> None:
        self.record = update(self.project_dir, self.record.run, change, self.config)


def usage_of(log: TurnLog, model: str) -> tuple[AgentUsage, ...]:
    """A turn's own consumption on ``model``, as its stream counted it: the turn's stream is
    exactly the turn's window of the session, so it needs no cursor into the vendor's records."""
    if log.tokens == Tokens():
        return ()
    return (AgentUsage("main", {model or ledger.UNKNOWN_MODEL: log.tokens}),)


def waits_for_reset(project_dir: Path, last: Turn) -> bool:
    """Whether a run whose last turn is ``last`` stands parked on a limit whose reset is
    known, its question still unanswered: its supervisor waits for the clock to resume it,
    and only Retry now comes sooner."""
    if last.end != TurnEnd.LIMIT or not last.resets or not last.question:
        return False
    question = questions.find(project_dir, last.question)
    return question is not None and question.state in (questions.OPEN, questions.ESCALATED)


# The questions Retry now answers: a run held for its account, or one that cannot go on alone.
RETRYABLE = (questions.LIMIT, questions.BLOCKED)


def resumed_by(question: Question) -> tuple[str, str]:
    """Why a turn resumes on the answer, and the words it resumes with: the clock's answer is a
    reset and Retry now a retry — each the session's own short prompt — and anything else
    is the answer itself."""
    if question.answer.get("by", {}).get("kind") == questions.CLOCK:
        return "reset", PROMPTS["reset"]
    if question.kind in RETRYABLE and list(question.answer.get("answers", {}).values()) == [
        questions.RETRY_NOW
    ]:
        return "retry", PROMPTS["retry"]
    return "answer", questions.answer_text(question)


def dplanner_argv(library: Path | None, *words: str) -> list[str]:
    """``dplanner <words>`` as this interpreter runs this build (``python -m dplanner``), never
    whatever ``dplanner`` is on PATH: a run launched from a branch's build is driven by that
    build, not by the installed one, which may not know the record's words. ``library`` is the
    library it acts on."""
    named = ["--library", str(library.expanduser().resolve())] if library is not None else []
    return [sys.executable, "-m", "dplanner", *named, *words]


def start_detached(
    project_dir: Path,
    run: str,
    prompt: str = "",
    text: str = "",
    *,
    library: Path | None = None,
) -> None:
    """Start a supervisor for the run that outlives whoever started it — ``agent run``'s
    launch, an answer, a reset, *Retry now* — this build's (:func:`dplanner_argv`).
    ``library`` is the library it was launched from, which its turns are told."""
    argv = dplanner_argv(library, "agent", "supervise", run, "--project-dir", str(project_dir))
    if prompt:
        argv += ["--prompt", prompt]
    if text:
        argv += ["--text", text]
    spawn_detached(argv)


def advance_detached(step: str, *, library: Path | None = None) -> None:
    """Start ``dplanner playbook advance <step>`` that outlives whoever started it: a pass's
    stage ended, or its gate was answered, and the engine decides what is due next. This
    interpreter, as :func:`start_detached` is."""
    spawn_detached(dplanner_argv(library, "playbook", "advance", step))


def wake_detached(project_dir: Path, question: str, *, library: Path | None = None) -> None:
    """Start ``dplanner playbook wake <question>``: a pass held on its account's usage waits
    for the reset in a process of its own, then answers the card for the clock and advances."""
    spawn_detached(
        dplanner_argv(library, "playbook", "wake", question, "--project-dir", str(project_dir))
    )


def revive(
    project_dirs: Iterable[Path],
    config: Path | None = None,
    *,
    claimed: Callable[[LedgerRecord], bool] | None = None,
    library: Path | None = None,
    grace: float = LAUNCH_GRACE,
) -> list[str]:
    """Start a supervisor for every run of this machine a supervisor should hold and none
    does; the runs it started, by id. What a machine's start does:

    - a run whose last turn has no end — a reboot or a killed supervisor lost it — is
      supervised again, and the new supervisor ends whatever of that turn still runs, records
      it ``failed``/``lost`` and retries it;
    - a run with no turn at all is a launch interrupted between writing its record and
      starting its supervisor. With ``claimed`` to ask — what the step's status says *on
      disk*: :func:`claimed_on_disk` over ``library`` unless a caller says otherwise — it is
      started when its step is still claimed in progress, and its record
      deleted when it is not and the run is past ``grace``; :func:`_settle` has the rest.

    - a run parked on a limit whose reset is known (:func:`waits_for_reset`) is supervised
      again, and the new supervisor waits for the reset — or resumes at once when it has
      passed.

    Any other parked run waits for a person and is never touched here."""
    here = ledger.machine_id(config)
    if claimed is None and library is not None:
        claimed = claimed_on_disk(library)
    started: list[str] = []
    for project_dir in project_dirs:
        for record in ledger.records(project_dir):
            last = record.last_turn
            if not record.headless or record.over:
                continue
            if (
                last is not None
                and last.end
                and not waits_for_reset(project_dir, last)
                and not answer_waiting(project_dir, record.run)
            ):
                continue
            if record.machine != here or supervised(ledger.run_dir(record.run, config)):
                continue
            if last is None:
                if claimed is not None and _settle(
                    project_dir, record, claimed, config, library, grace
                ):
                    started.append(record.run)
                continue
            start_detached(project_dir, record.run, library=library)
            started.append(record.run)
    return started


def _settle(
    project_dir: Path,
    record: LedgerRecord,
    claimed: Callable[[LedgerRecord], bool],
    config: Path | None,
    library: Path | None,
    grace: float,
) -> bool:
    """Settle a run with no turn, under its step's launch lock; True when it was started.

    Everything is read again inside the lock — the record from the ledger, the step's status
    through ``claimed``, which reads what is on disk — because what was read before it may
    be older than the launch that has since saved its claim and started. A launch's record
    is only ever deleted when nothing could still be starting it: no supervisor holds the
    run, its step reads unclaimed, and it is older than ``grace`` seconds — a supervisor
    started a moment ago may not have taken its lock yet."""
    with ExitStack() as held:
        try:
            held.enter_context(launching(record.project, record.step, config))
        except BlockingIOError:
            return False  # Its launch is still under way.
        fresh = ledger.find(project_dir, record.run)
        if fresh is None or fresh.turns or fresh.over:
            return False
        if supervised(ledger.run_dir(fresh.run, config)):
            return False
        # A pass's later stage is claimed by its pass, whatever the step's status says (a
        # review runs on a step at Ready for review); only a pass's first record stands on
        # the step as its launch leaves it (launch_stands).
        if claimed(fresh) or (fresh.pass_ and fresh.settings is None):
            start_detached(project_dir, fresh.run, library=library)
            return True
        if _age(fresh) > grace:
            ledger.path_for(project_dir, fresh).unlink(missing_ok=True)
        return False


def claimed_on_disk(library: Path) -> Callable[[LedgerRecord], bool]:
    """Whether a run's step stands as its launch left it (:func:`launch_stands`) in the plan
    as it is on disk, read afresh each time it is asked — a model loaded earlier may be older
    than the launch that has since saved its claim. Only :func:`revive` asks, and only of a
    run with no turn."""

    def claimed(record: LedgerRecord) -> bool:
        store = LibraryStore(library)
        try:
            plan = store.load()
            return plan.has(record.step) and launch_stands(record, plan.step(record.step))
        finally:
            store.close()

    return claimed


def launch_stands(record: LedgerRecord, step: Step) -> bool:
    """Whether ``step`` stands as the launch of ``record``, a run with no turn, left it — so
    the run is still owed its start. In progress, which a launch saves only after writing its
    run; or Ready for review under a pass's run that reviews, which a pass begun at review
    leaves as it is rather than take the work up again (``agent run``'s ``_begin_pass``)."""
    status = stored(step)
    return status is Status.IN_PROGRESS or (
        bool(record.pass_)
        and status is Status.READY_FOR_REVIEW
        and stage_kind(record.stage) is StageKind.REVIEW
    )


def _age(record: LedgerRecord) -> float:
    """Seconds since the run was launched; none at all for a stamp this build cannot read."""
    try:
        launched = datetime.fromisoformat(record.launched)
    except ValueError:
        return 0.0
    if launched.tzinfo is None:
        launched = launched.replace(tzinfo=UTC)
    return (datetime.now(UTC) - launched).total_seconds()


@contextmanager
def launching(
    project: str, step: str, config: Path | None = None, *, wait: bool = False
) -> Iterator[None]:
    """Hold the step's launch lock — ``config_dir()/launches/<project>-<step>.lock``, the
    operating system's — or raise ``BlockingIOError`` when another launch holds it. Every
    launch of a step takes it from its first check to its start, on both surfaces, so two
    launches of one step can never both find it free and both start an agent. A playbook's
    advance ``wait``s for it instead — the holder is a launch moments from done, and the
    advance that gave up could be the one that reads the stage that just ended."""
    path = (config or config_dir()) / LAUNCHES_DIR / f"{project}-{step}.lock"
    with os_lock(path, wait=wait):
        yield


def supervised(directory: Path) -> bool:
    """Whether a live supervisor holds the run in ``directory``."""
    if not (directory / LOCK_FILE).exists():
        return False
    try:
        with os_lock(directory / LOCK_FILE, wait=False):
            return False
    except BlockingIOError:
        return True


@contextmanager
def supervising(directory: Path) -> Iterator[None]:
    """Hold the run's supervisor lock for as long as this supervisor lives, or refuse."""
    path = directory / LOCK_FILE
    with ExitStack() as stack:
        try:
            held = stack.enter_context(os_lock(path, wait=False))
        except BlockingIOError:
            raise RefusedError(f"the run is already supervised ({_holder(path)})") from None
        held.truncate(0)
        held.write(str(os.getpid()))
        held.flush()
        yield


_KILLED_BECAUSE = {
    "hang": "the stream fell silent with no tool running",
    "runaway": "the stream kept going and the agent produced nothing",
    "timeout": "the stage ran past its wall clock",
}


def _not_ours(record: LedgerRecord, machine: str) -> str:
    """Why this machine may not start the run's next turn, or "": a resume is claimed only
    on a run that is not over, not fenced, and was launched here."""
    if record.over or record.fence:
        return "it is over" if record.over else "it was fenced"
    if record.machine and record.machine != machine:
        return f"{record.host or record.machine} launched it"
    return ""


def _question_for(record: LedgerRecord, turn: Turn, ending: Ending) -> Question:
    """The question a park that nobody asked through the door stands on: a question found in
    the agent's words, a denied permission, an exhausted account, or a run that cannot go on
    alone."""
    said = ending.question or ending.reason or _said(turn)
    kind, header, text, body = {
        TurnEnd.ASKED: (questions.DECISION, "Question", said, ""),
        TurnEnd.DENIED: (
            questions.PERMISSION,
            "Permission",
            "The agent was denied a permission it needed. How should it go on?",
            said,
        ),
        TurnEnd.LIMIT: (
            questions.LIMIT,
            "Usage limit",
            f"The account ran out of usage. The run resumes by itself at {limits.clock(reset)}."
            if (reset := limits.parse(turn.resets)) is not None
            else "The account ran out of usage, and when it resets is unknown."
            " Retry the run once it has.",
            said,
        ),
    }.get(
        ending.end,
        (questions.BLOCKED, "Blocked", f"The run cannot go on alone: {said}", ""),
    )
    options = [(questions.RETRY_NOW, "Resume the run now")] if ending.end is TurnEnd.LIMIT else []
    return questions.asked(
        record.project,
        record.step,
        now_stamp(),
        [questions.one(text, header, options)],
        kind=kind,
        run=record.run,
        by={
            "callsign": record.callsign,
            "harness": record.harness,
            "machine": record.machine,
            "host": record.host,
        },
        body=body,
        resets=turn.resets,
    )


def _record(project_dir: Path, run: str) -> LedgerRecord:
    record = ledger.find(project_dir, run)
    if record is None:
        raise RefusedError(f"no run {run} in {project_dir}")
    if not record.headless or stage_kind(record.stage) is None:
        raise RefusedError(f"run {run} is not a headless stage run")
    return record


def _with_turn(record: LedgerRecord, turn: Turn) -> LedgerRecord:
    others = [t for t in record.turns if t.n != turn.n]
    return record.with_turns(sorted([*others, turn], key=lambda t: t.n))


def _over(run: str, end: TurnEnd) -> str:
    return f"run {run} is done" if end is TurnEnd.DONE else f"run {run} was stopped"


def _said(turn: Turn) -> str:
    return f"turn {turn.n} {turn.end}" + (f" ({turn.why})" if turn.why else "")


def _failures(record: LedgerRecord) -> int:
    """The failed turns at the end of the run, in a row."""
    count = 0
    for turn in reversed(record.turns):
        if turn.end != TurnEnd.FAILED:
            break
        count += 1
    return count


def _spawn(
    argv: list[str], cwd: Path, env: dict[str, str], err: IO[bytes]
) -> "subprocess.Popen[str]":
    """The turn in a process group of its own, so a kill takes its children with it."""
    return subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=err,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=sys.platform != "win32",
        creationflags=CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )


def _pump(process: "subprocess.Popen[str]", lines: "queue.Queue[str | None]") -> None:
    assert process.stdout is not None
    with suppress(ValueError, OSError):  # The pipe closed under the read.
        for line in process.stdout:
            lines.put(line)
    lines.put(None)


def _end_group(process: "subprocess.Popen[str]", grace: float) -> None:
    """End every process of the turn's group and reap the CLI — politely, then not.

    The CLI exiting is not the group ending: a test worker it started may ignore SIGTERM, so
    the group is asked for until it is empty, and killed when the grace runs out. Windows
    has no group to signal, so the tree is killed at once while its root still names it.
    """
    if sys.platform == "win32":
        if process.poll() is None:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
            )
    else:
        group = process.pid  # The CLI leads its own session, so its pid is the group's id.
        if _group_alive(process, group):
            with suppress(ProcessLookupError):
                os.killpg(group, signal.SIGTERM)
            deadline = time.monotonic() + grace
            while _group_alive(process, group) and time.monotonic() < deadline:
                time.sleep(0.05)
            if _group_alive(process, group):
                with suppress(ProcessLookupError):
                    os.killpg(group, signal.SIGKILL)
    process.wait()


def _group_alive(process: "subprocess.Popen[str]", group: int) -> bool:
    process.poll()  # Reap the CLI, so its own zombie does not keep the group alive.
    if sys.platform == "win32":
        return process.returncode is None
    else:
        try:
            os.killpg(group, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


def _holder(path: Path) -> str:
    try:
        pid = path.read_text(encoding="utf-8").strip()
    except OSError:
        pid = ""
    return f"pid {pid}" if pid else "by another process"


@contextmanager
def _stoppable() -> Iterator[threading.Event]:
    """An event SIGTERM sets: a person or a fence stopping the run ends its turn ``stopped``
    rather than leaving it to read as lost."""
    stop = threading.Event()
    if threading.current_thread() is not threading.main_thread():
        yield stop
        return
    previous = signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        yield stop
    finally:
        signal.signal(signal.SIGTERM, previous)
