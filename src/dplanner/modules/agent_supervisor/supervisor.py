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
the stage's **wall clock**. Each kills the turn's whole process group and records why.

**One supervisor per run** is a lock file in the run directory holding the supervisor's
own process stamp — a stale one, whose process is gone, is taken over. A turn records its
process's stamp too, so a supervisor started after a reboot can tell a turn still running
from one the machine lost, and retries the lost one.

Qt-free: it is a CLI verb, and the run it drives must outlive every window.
"""

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
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
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
PLAN_FILE = "plan.md"


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
    directory.mkdir(parents=True, exist_ok=True)
    with _locked(directory), _stoppable() as stop:
        record = _record(project_dir, run)
        harness = harness_by_id(harnesses, record.harness)
        if harness is None or harness.headless is None:
            raise RefusedError(f"run {run}: no harness here runs {record.harness!r} headless")
        session = Session(project_dir, directory, record, harness, harness.headless, guards)
        kind, words = session.opening(prompt, text, stop)
        while kind:
            ending = session.turn(kind, words, stop)
            kind, words = session.next(ending, stop)
        return words


@dataclass
class Session:
    """One supervisor's hold on one run: the record as last written, and how to go on."""

    project_dir: Path
    directory: Path
    record: LedgerRecord
    harness: AgentHarness
    headless: Headless
    guards: Guards

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
        if ending.end is TurnEnd.DONE:
            self._end(TurnEnd.DONE)
            return "", f"run {self.record.run} is done"
        if ending.end is TurnEnd.STOPPED:
            self._end(TurnEnd.STOPPED)
            return "", f"run {self.record.run} was stopped"
        parked = f"run {self.record.run} is parked: {_said(self.record.turns[-1])}"
        if ending.end is not TurnEnd.FAILED or ending.needs_person or ending.why == "runaway":
            return "", parked
        failures = _failures(self.record)
        if failures > len(self.guards.backoff):
            return "", f"{parked}, {failures} failures in a row"
        if ending.why != "abandoned-wait" and stop.wait(self.guards.backoff[failures - 1]):
            self._end(TurnEnd.STOPPED)
            return "", f"run {self.record.run} was stopped"
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
        with stream.open("w", encoding="utf-8") as tee, errors.open("wb") as err:
            try:
                process = _spawn(argv, Path(self.record.directory or "."), env, err)
            except OSError as error:
                failed = Ending(TurnEnd.FAILED, "unknown", f"could not start {argv[0]}: {error}")
                return self._finish(turn, TurnLog(), None, failed)
            stamp = stamp_of(process.pid) or ProcessStamp(process.pid, "", "")
            turn = replace(turn, pid=stamp.pid, boot=stamp.boot, pid_started=stamp.started)
            self._write(turn)
            log, killed = self._watch(process, tee, spec.stage, stop)
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
                session = self.record.session if kind == "launch" else ""
                self.record = replace(self.record, session=session or str(uuid.uuid4()))
                spec = replace(spec, session=self.record.session)
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
        tee: IO[str],
        stage: StageKind,
        stop: threading.Event,
    ) -> tuple[TurnLog, str]:
        """Read the turn to its end, or kill it: the log, and why it was killed ("" when it
        was not)."""
        log = TurnLog()
        lines: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=_pump, args=(process, lines), daemon=True).start()
        began = heard = time.monotonic()
        wall = self.guards.wall.get(stage, max(self.guards.wall.values()))
        while True:
            try:
                line = lines.get(timeout=self.guards.poll)
            except queue.Empty:
                line = ""
            if line is None:
                break
            now = time.monotonic()
            if line:
                heard = now
                tee.write(line)
                tee.flush()
                self.headless.feed(log, line)
                if log.session and log.session != self.record.session:
                    self.record = replace(self.record, session=log.session)
                    self._write_record()
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
                _kill(process, self.guards.grace)
                return log, killed
        process.wait()
        return log, ""

    def _streamed(self, n: int) -> TurnLog:
        """What turn ``n``'s stream said, read back from its file."""
        try:
            with (self.directory / f"turn-{n}.jsonl").open(encoding="utf-8") as stream:
                return self.headless.read_lines(stream)
        except OSError:
            return TurnLog()

    # -- writing ----------------------------------------------------------------------------

    def _finish(self, turn: Turn, log: TurnLog, code: int | None, ending: Ending) -> Ending:
        usage = usage_of(log)
        turn = replace(
            turn,
            ended=now_stamp(),
            end=ending.end.value,
            why=ending.why,
            reason=ending.question or ending.reason,
            exit=code,
            resets=ending.resets.isoformat() if ending.resets else "",
            agents=usage,
        )
        if ending.end is TurnEnd.DONE and self.record.stage == StageKind.REVIEW and log.typed:
            self.record = replace(self.record, verdict=dict(log.typed))
        if ending.end is TurnEnd.DONE and self.record.stage == StageKind.PLAN and log.final:
            (self.directory / PLAN_FILE).write_text(log.final, encoding="utf-8")
        self._write(turn)
        return ending

    def _end(self, end: TurnEnd) -> None:
        last = self.record.last_turn
        code = last.exit if last is not None and end is TurnEnd.DONE else None
        self.record = self.record.ended_at(now_stamp(), code)
        self._write_record()

    def _write(self, turn: Turn) -> None:
        turns = [t for t in self.record.turns if t.n != turn.n]
        self.record = self.record.with_turns(sorted([*turns, turn], key=lambda t: t.n))
        self._write_record()

    def _write_record(self) -> None:
        # A fence is the one write from anywhere else, and it wins.
        on_disk = ledger.find(self.project_dir, self.record.run)
        if on_disk is not None and on_disk.fence and not self.record.fence:
            self.record = replace(self.record, fence=on_disk.fence)
        ledger.write(self.project_dir, self.record)


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
    for line in process.stdout:
        lines.put(line)
    lines.put(None)


def _kill(process: "subprocess.Popen[str]", grace: float) -> None:
    """End the turn's whole process group: politely, then not."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, check=False
        )
    else:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(grace)
            return
        except subprocess.TimeoutExpired:
            pass
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    process.wait()


@contextmanager
def _locked(directory: Path) -> Iterator[None]:
    """Hold the run's supervisor lock, taking over one whose holder is gone."""
    path = directory / LOCK_FILE
    me = stamp_of(os.getpid()) or ProcessStamp(os.getpid(), "", "")
    for _ in range(2):
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            holder = _holder(path)
            if holder is not None and is_live(holder):
                raise RefusedError(f"the run is already supervised by pid {holder.pid}") from None
            path.unlink(missing_ok=True)
            continue
        with os.fdopen(handle, "w", encoding="utf-8") as lock:
            json.dump({"pid": me.pid, "boot": me.boot, "started": me.started}, lock)
        break
    else:
        raise RefusedError("the run's supervisor lock could not be taken")
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def _holder(path: Path) -> ProcessStamp | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return ProcessStamp(int(raw["pid"]), str(raw["boot"]), str(raw["started"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None


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
