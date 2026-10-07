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
and retries the lost one.

Qt-free: it is a CLI verb, and the run it drives must outlive every window.
"""

import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import IO

from dplanner.core.process import (
    CREATE_NEW_PROCESS_GROUP,
    ProcessStamp,
    is_live,
    spawn_detached,
    stamp_of,
)
from dplanner.domain import ledger
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
    write_schema,
)
from dplanner.domain.ledger import LedgerRecord, Turn
from dplanner.domain.model import now_stamp
from dplanner.modules.agent_briefing.protocol import opening_prompt

# Why a turn after the first began, and what it is told when nobody wrote the words.
PROMPTS = {
    "answer": "",  # An answer is always somebody's words.
    "continue": "Continue the step where you left off.",
    "reset": "Your usage limit has reset. Continue the step where you left off.",
    "retry": "Your last turn was cut off. Continue the step where you left off.",
}
LOCK_FILE = "supervisor.lock"
RECORD_LOCK = "record.lock"
PLAN_FILE = "plan.md"
# How long the stream is still read once its process group has ended: a CLI's SIGTERM
# handler may print the turn's last totals on the way out.
DRAIN_SECONDS = 2.0
OVER = (TurnEnd.DONE, TurnEnd.STOPPED)


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


def supervise(
    project_dir: Path,
    run: str,
    harnesses: tuple[AgentHarness, ...],
    *,
    prompt: str = "",
    text: str = "",
    guards: Guards | None = None,
    config: Path | None = None,
) -> str:
    """Drive the run until it is over or parked; the sentence that says which.

    ``prompt`` is why a parked run resumes — ``answer``, ``continue``, ``reset`` or
    ``retry`` — and ``text`` the words it resumes with (the answer). ``config`` is the
    directory the run directories are under, ``config_dir()`` unless a test says otherwise.
    """
    guards = guards or Guards()
    directory = ledger.run_dir(run, config)
    with supervising(directory), _stoppable() as stop:
        record = _record(project_dir, run)
        harness = harness_by_id(harnesses, record.harness)
        if harness is None or harness.headless is None:
            raise RefusedError(f"run {run}: no harness here runs {record.harness!r} headless")
        session = Session(project_dir, config, record, harness, harness.headless, guards)
        kind, words = session.opening(prompt, text, stop)
        while kind:
            ending = session.turn(kind, words, stop)
            kind, words = session.next(ending, stop)
        return words


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


def update(
    project_dir: Path,
    run: str,
    change: Callable[[LedgerRecord], LedgerRecord],
    config: Path | None = None,
) -> LedgerRecord:
    """Read the run's record, change it and write it back, all under the run's record lock."""
    directory = ledger.run_dir(run, config)
    with _os_lock(directory / RECORD_LOCK, wait=True):
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

    @property
    def directory(self) -> Path:
        return ledger.run_dir(self.record.run, self.config)

    # -- deciding ---------------------------------------------------------------------------

    def opening(self, prompt: str, text: str, stop: threading.Event) -> tuple[str, str]:
        """The first turn this supervisor starts — the launch, a parked run's resume, or what
        follows a turn the machine lost — as :meth:`next` answers."""
        record = self.record
        if record.over:
            raise RefusedError(f"run {record.run} is over")
        if record.fence:
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
            stamp = ProcessStamp(last.pid, last.boot, last.pid_started)
            if last.pid and is_live(stamp):
                raise RefusedError(
                    f"run {record.run}: turn {last.n} is still running (pid {last.pid})"
                )
            lost = Ending(TurnEnd.FAILED, "lost", "its process is gone")
            return self.next(self._finish(last, self._streamed(last.n), None, lost), stop)
        if prompt not in PROMPTS:
            raise RefusedError(
                f"run {record.run} is parked ({_said(last)}); resume it with --prompt "
                + "|".join(PROMPTS)
            )
        if prompt == "answer" and not text:
            raise RefusedError("an answer needs its words: --text")
        return prompt, text or PROMPTS[prompt]

    def next(self, ending: Ending, stop: threading.Event) -> tuple[str, str]:
        """What follows a turn: the next turn's prompt and words, or ("", why it stopped)."""
        if ending.end in OVER:
            return "", _over(self.record.run, ending.end)
        parked = f"run {self.record.run} is parked: {_said(self.record.turns[-1])}"
        if ending.end is not TurnEnd.FAILED or ending.needs_person or ending.why == "runaway":
            return "", parked
        failures = _failures(self.record)
        if failures > len(self.guards.backoff):
            return "", f"{parked}, {failures} failures in a row"
        if ending.why != "abandoned-wait" and stop.wait(self.guards.backoff[failures - 1]):
            self._end(TurnEnd.STOPPED)
            return "", _over(self.record.run, TurnEnd.STOPPED)
        self.record = _record(self.project_dir, self.record.run)
        if self.record.fence:
            self._end(TurnEnd.STOPPED)
            return "", f"run {self.record.run} was fenced"
        if ending.why == "abandoned-wait":
            return "continue", PROMPTS["continue"]
        return "retry", PROMPTS["retry"]

    # -- one turn ---------------------------------------------------------------------------

    def turn(self, kind: str, words: str, stop: threading.Event) -> Ending:
        n = len(self.record.turns) + 1
        spec = self._spec(kind, words)
        env = scrubbed_environment(os.environ, (self.harness,))
        argv = self.headless.command(spec)
        argv[0] = shutil.which(argv[0], path=env.get("PATH")) or argv[0]
        stream = self.directory / f"turn-{n}.jsonl"
        errors = self.directory / f"turn-{n}.stderr"
        turn = Turn(n=n, prompt=kind, started=now_stamp())
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
            ending = self.headless.classify(code, log, stderr)
        return self._finish(turn, log, code, ending)

    def _spec(self, kind: str, words: str) -> TurnSpec:
        stage = StageKind(self.record.stage)
        # The plan is written through `dplanner`, inside the project directory: the 10-04
        # run's 21 Codex sandbox prompts were that directory outside the writable roots.
        spec = TurnSpec(stage, words, str(self.directory), writable=(str(self.project_dir),))
        resumable = kind != "launch" and self._streamed_session()
        if resumable:
            spec = spec.resumed(self.record.session, words)
        else:
            # A fresh session: the launch, or a retry of a turn that never got one going.
            spec = replace(spec, prompt=opening_prompt(self.directory / "prompt.md"))
            if self.harness.names_session:
                session = (self.record.session if kind == "launch" else "") or str(uuid.uuid4())
                self._update(lambda record: replace(record, session=session))
                spec = replace(spec, session=session)
        write_schema(spec)
        return spec

    def _streamed_session(self) -> bool:
        """Whether some turn's stream has shown the session exists, so it can be resumed."""
        return bool(self.record.session) and any(
            self._streamed(turn.n).session for turn in self.record.turns
        )

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
        began = heard = time.monotonic()
        wall = self.guards.wall.get(stage, max(self.guards.wall.values()))
        eof, killed = False, ""
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
            killed = (
                "stopped"
                if stop.is_set()
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
        turn = replace(
            turn,
            ended=now_stamp(),
            end=ending.end.value,
            why=ending.why,
            reason=ending.question or ending.reason,
            exit=code,
            resets=ending.resets.isoformat() if ending.resets else "",
            agents=usage_of(log),
        )
        done = ending.end is TurnEnd.DONE
        verdict = (
            dict(log.typed)
            if done and log.typed and self.record.stage == StageKind.REVIEW
            else None
        )
        if done and self.record.stage == StageKind.PLAN and log.final:
            (self.directory / PLAN_FILE).write_text(log.final, encoding="utf-8")

        def finished(record: LedgerRecord) -> LedgerRecord:
            record = _with_turn(record, turn)
            if verdict is not None:
                record = replace(record, verdict=verdict)
            if ending.end in OVER:
                record = record.ended_at(turn.ended, code if done else None)
            return record

        self._update(finished)
        return ending

    def _end(self, end: TurnEnd) -> None:
        last = self.record.last_turn
        code = last.exit if last is not None and end is TurnEnd.DONE else None
        self._update(lambda record: record.ended_at(now_stamp(), code))

    def _write(self, turn: Turn) -> None:
        self._update(lambda record: _with_turn(record, turn))

    def _update(self, change: Callable[[LedgerRecord], LedgerRecord]) -> None:
        self.record = update(self.project_dir, self.record.run, change, self.config)


def usage_of(log: TurnLog) -> tuple[AgentUsage, ...]:
    """A turn's own consumption, as its stream counted it: the turn's stream is exactly the
    turn's window of the session, so it needs no cursor into the vendor's records."""
    if log.tokens == Tokens():
        return ()
    return (AgentUsage("main", {log.model or ledger.UNKNOWN_MODEL: log.tokens}),)


def start_detached(project_dir: Path, run: str, prompt: str = "", text: str = "") -> None:
    """Start a supervisor for the run that outlives whoever started it — ``agent run``'s
    launch, an answer, a reset, *Retry now*."""
    argv = ["dplanner", "agent", "supervise", run, "--project-dir", str(project_dir)]
    if prompt:
        argv += ["--prompt", prompt]
    if text:
        argv += ["--text", text]
    spawn_detached(argv)


@contextmanager
def supervising(directory: Path) -> Iterator[None]:
    """Hold the run's supervisor lock for as long as this supervisor lives, or refuse."""
    path = directory / LOCK_FILE
    with ExitStack() as stack:
        try:
            held = stack.enter_context(_os_lock(path, wait=False))
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


def _record(project_dir: Path, run: str) -> LedgerRecord:
    record = ledger.find(project_dir, run)
    if record is None:
        raise RefusedError(f"no run {run} in {project_dir}")
    if not record.headless or not record.stage:
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


@contextmanager
def _os_lock(path: Path, *, wait: bool) -> Iterator[IO[str]]:
    """An exclusive lock the operating system holds on ``path`` and drops when its holder
    exits, however it exits. ``BlockingIOError`` when another holds it and ``wait`` is
    False. The file is never deleted: a lock on a file somebody can unlink is no lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as held:
        if sys.platform == "win32":
            import msvcrt

            held.seek(0)
            try:
                msvcrt.locking(held.fileno(), msvcrt.LK_LOCK if wait else msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise BlockingIOError(str(error)) from error
        else:
            import fcntl

            fcntl.flock(held.fileno(), fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield held


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
