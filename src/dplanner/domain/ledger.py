"""The usage ledger: what every agent run on a project consumed, one file per run.

```
<project dir>/
└── ledger/                      beside steps/, and not one of the store's plan entries
    └── 2026-10/                 the month the run was launched
        └── 20261001T192149Z-1a2b3c4d.json
```

**Usage is a ledger of external facts, not model state.** Tokens were spent whether or not
anybody presses Ctrl+Z, and they were spent by a process on one machine that the plan
never controlled. So a run is written down as a record of its own, outside the files the
store flushes (``store.PLAN_ENTRIES``): the stale check and the outside-change watch never
see it, an agent recording usage never makes a window adopt anything, and Save commits it
with the project because Save's scope is the whole project directory.

**Every file has exactly one writer, and no two writers can make the same name.** A run's
id is minted at launch from the clock and a random suffix; only the machine that launched
the run can read the vendor's records it is filled from, so only that machine ever writes
the file. Nothing needs a lock, no update is lost, and git sees files added on two
machines, which never conflict. It is the at-work claim's *one file per claim*
(``domain/at_work.py``), committed rather than kept per machine because what a run cost is
the plan's history, where a heartbeat is not.

**A record is a snapshot, rewritten whole.** The launch writes it with no tokens; every
harvest (``modules/agent_usage/harvest.py``) re-reads the vendor's records and writes
the whole record again — larger while the run goes on, the same once it has ended. Any
number of harvests, in any order, from the wrapper script, the window or a terminal, give
one file with the latest answer. A write that would change nothing is skipped, so a sweep
over finished runs leaves git quiet.

Nothing derived is stored: a step's totals, a project's, the running sums of the
Expenditure tab are all summed on read. A file this build cannot read is skipped, never a
crash — a newer build may have written it — and there is no migration: the format is in
every record.

**A headless run is format 2: the record is the run** (FORMAT.md's *Format 2*). It carries
its **turns** — one per process the run supervisor started — each with how it ended and
what it consumed, and the playbook's words (``pass``, ``stage``, ``attempt``). Usage lives
on the turns, so a session two runs share is counted once per turn and never twice; the
record's ``agents`` is their sum, made on read and never written. A terminal run is still
written as format 1, which every older build reads. Whether a run is running, parked or
over is read from its turns, never stored.
"""

import json
import os
import re
import secrets
import socket
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dplanner.core.config_dir import config_dir
from dplanner.core.fsio import write_atomic
from dplanner.domain.agents import AgentUsage, RunReport, Tokens, summed

LEDGER_DIR = "ledger"
FORMAT = 2
# What a run with no turns is written as, so a build from before format 2 still counts it.
TERMINAL_FORMAT = 1
HEADLESS = "headless"

# The fence a person writes on a run they take into a terminal of their own (*Open Session*):
# the run is over to DPlanner, and the step is theirs.
TAKEN_OVER = "taken over by a person"

# How a record's counts were come by: read from the vendor's records (``native``), read
# with part of the tree missing (``partial``), typed by hand (``manual``), or carried over
# from the step aspect that kept usage before the ledger (``legacy``).
NATIVE = "native"
PARTIAL = "partial"
MANUAL = "manual"
LEGACY = "legacy"
# The model a count was recorded against when nobody said which.
UNKNOWN_MODEL = "unknown"


@dataclass(frozen=True)
class Turn:
    """One process of a headless run: why it began, how it ended, what it consumed.

    ``end`` is a :class:`~dplanner.domain.headless.TurnEnd` word, or "" while it runs — or
    since its machine lost it, which only ``pid``, ``boot`` and ``pid_started`` can tell.
    """

    n: int
    prompt: str  # Why it began: "launch", "answer", "continue", "reset", "retry" or "verdict".
    started: str
    pid: int = 0
    boot: str = ""
    pid_started: str = ""
    ended: str = ""
    end: str = ""
    why: str = ""  # For "failed": which failure (headless.Ending.why), or the supervisor's own.
    reason: str = ""
    exit: int | None = None
    resets: str = ""  # For "limit", when the account comes back, if known.
    question: str = ""
    consumed: Mapping[str, str] = field(default_factory=dict)
    # When the supervisor was about to start the process of a turn claimed on an answer: after
    # it, an absent pid no longer proves the answer was never acted on.
    spawning: str = ""
    agents: tuple[AgentUsage, ...] = ()  # The turn's own consumption: FORMAT.md's "usage".

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"n": self.n, "prompt": self.prompt, "started": self.started}
        optional: dict[str, Any] = {
            "pid": self.pid,
            "boot": self.boot,
            "pid_started": self.pid_started,
            "ended": self.ended,
            "end": self.end,
            "why": self.why,
            "reason": self.reason,
            "resets": self.resets,
            "question": self.question,
            "consumed": dict(self.consumed),
            "spawning": self.spawning,
        }
        data.update({key: value for key, value in optional.items() if value})
        if self.exit is not None:
            data["exit"] = self.exit
        if self.agents:
            data["usage"] = {"agents": [_agent_json(agent) for agent in self.agents]}
        return data

    @classmethod
    def from_json(cls, raw: object) -> "Turn | None":
        if not isinstance(raw, dict) or not isinstance(raw.get("n"), int):
            return None
        usage = raw.get("usage")
        agents = usage.get("agents") if isinstance(usage, dict) else None
        consumed = raw.get("consumed")
        return cls(
            n=raw["n"],
            prompt=_text(raw, "prompt"),
            started=_text(raw, "started"),
            pid=_count(raw.get("pid")),
            boot=_text(raw, "boot"),
            pid_started=_text(raw, "pid_started"),
            ended=_text(raw, "ended"),
            end=_text(raw, "end"),
            why=_text(raw, "why"),
            reason=_text(raw, "reason"),
            exit=_code(raw.get("exit")),
            resets=_text(raw, "resets"),
            question=_text(raw, "question"),
            consumed=(
                {str(k): str(v) for k, v in consumed.items()} if isinstance(consumed, dict) else {}
            ),
            spawning=_text(raw, "spawning"),
            agents=_agents_from_json(agents),
        )


@dataclass(frozen=True)
class LedgerRecord:
    run: str
    project: str
    step: str
    harness: str
    launched: str  # ISO stamp of the launch, UTC.
    machine: str = ""  # The machine id that launched it — the only one that can harvest it.
    host: str = ""  # That machine's name, for a person reading the file.
    directory: str = ""  # Where the agent worked, resolved.
    session: str = ""  # The main agent's session: named at launch, or claimed at harvest.
    ended: str = ""  # When the shell ended, once something saw it; never cleared.
    exit: int | None = None
    harvested: str = ""  # When the vendor's records were last read; "" before the first read.
    measurement: str = NATIVE
    account: Mapping[str, str] = field(default_factory=dict)
    # A headless run's: the sum of its turns' usage, made on read and never written.
    agents: tuple[AgentUsage, ...] = ()
    prompt_chars: int = 0  # What the briefing came to, in characters.
    # Format 2, a headless run: FORMAT.md's words, playbooks.md's meanings.
    mode: str = ""  # "headless", or "" for a run in a terminal.
    playbook: str = ""
    pass_: str = ""  # "pass" on disk.
    stage: str = ""
    attempt: int = 0
    callsign: str = ""
    claim: str = ""
    turns: tuple[Turn, ...] = ()
    verdict: Mapping[str, Any] | None = None  # A review's typed final message, as given.
    # A fix's findings it would not act on: [{finding: {run|question, index}, reason}].
    declined: tuple[Mapping[str, Any], ...] = ()
    # What the pass pinned, on its first record only: {preset, revision, rounds, roles,
    # overrides} (playbooks.md's *A pass pins its settings*).
    settings: Mapping[str, Any] | None = None
    fence: Mapping[str, str] | None = None  # A takeover's {at, by, why}: the run is over.

    @property
    def headless(self) -> bool:
        return self.mode == HEADLESS

    @property
    def over(self) -> bool:
        return bool(self.ended)

    @property
    def last_turn(self) -> Turn | None:
        return self.turns[-1] if self.turns else None

    @property
    def parked(self) -> bool:
        """Its last turn ended and the run did not: it waits for an answer, a reset, a
        retry — or for its supervisor's backoff, which only the supervisor's lock knows."""
        last = self.last_turn
        return not self.over and last is not None and bool(last.end)

    def with_turns(self, turns: Sequence[Turn]) -> "LedgerRecord":
        """The record with these turns, and its usage summed from them."""
        return replace(self, turns=tuple(turns), agents=merged(turn.agents for turn in turns))

    @property
    def tokens(self) -> Tokens:
        return summed(agent.tokens for agent in self.agents)

    def models(self) -> dict[str, Tokens]:
        """What the whole tree consumed, per model."""
        totals: dict[str, Tokens] = {}
        for agent in self.agents:
            for model, counts in agent.models.items():
                totals[model] = totals.get(model, Tokens()) + counts
        return totals

    @property
    def sessions(self) -> frozenset[str]:
        """Every vendor session this record owns: the main one and its subagents' own."""
        found = {agent.session for agent in self.agents if agent.session}
        if self.session:
            found.add(self.session)
        return frozenset(found)

    def with_report(self, report: RunReport, harvested: str) -> "LedgerRecord":
        return replace(
            self,
            session=self.session or report.session,
            agents=report.agents,
            account=dict(report.account) or self.account,
            measurement=PARTIAL if report.partial else NATIVE,
            harvested=harvested,
        )

    def ended_at(self, ended: str, code: int | None) -> "LedgerRecord":
        """The record with its end — the first one seen; a later sighting changes nothing."""
        if self.ended:
            return self
        return replace(self, ended=ended, exit=code)

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "format": FORMAT if self.headless else TERMINAL_FORMAT,
            "run": self.run,
            "project": self.project,
            "step": self.step,
            "harness": self.harness,
            "launched": self.launched,
            "measurement": self.measurement,
        }
        if self.headless:
            data["turns"] = [turn.to_json() for turn in self.turns]
        else:
            data["agents"] = [_agent_json(agent) for agent in self.agents]
        # Absence encodes the default, FORMAT.md's rule: an unended run has no "ended".
        optional: dict[str, Any] = {
            "machine": self.machine,
            "host": self.host,
            "dir": self.directory,
            "session": self.session,
            "ended": self.ended,
            "harvested": self.harvested,
            "account": dict(self.account),
            "prompt_chars": self.prompt_chars,
            "mode": self.mode,
            "playbook": self.playbook,
            "pass": self.pass_,
            "stage": self.stage,
            "attempt": self.attempt,
            "callsign": self.callsign,
            "claim": self.claim,
            "verdict": dict(self.verdict) if self.verdict is not None else None,
            "declined": [dict(each) for each in self.declined],
            "settings": dict(self.settings) if self.settings is not None else None,
            "fence": dict(self.fence) if self.fence is not None else None,
        }
        data.update({key: value for key, value in optional.items() if value})
        if self.exit is not None:
            data["exit"] = self.exit
        return data

    @classmethod
    def from_json(cls, raw: object) -> "LedgerRecord | None":
        """A stored record, or None for one this build cannot read."""
        if not isinstance(raw, dict) or not isinstance(raw.get("format"), int):
            return None
        if raw["format"] > FORMAT:
            return None
        run, project, step = _text(raw, "run"), _text(raw, "project"), _text(raw, "step")
        if not (run and project and step):
            return None
        account = raw.get("account")
        raw_turns = raw.get("turns")
        turns = tuple(
            turn
            for turn in map(Turn.from_json, raw_turns if isinstance(raw_turns, list) else [])
            if turn is not None
        )
        verdict, fence = raw.get("verdict"), raw.get("fence")
        declined, settings = raw.get("declined"), raw.get("settings")
        record = cls(
            run=run,
            project=project,
            step=step,
            harness=_text(raw, "harness"),
            launched=_text(raw, "launched"),
            machine=_text(raw, "machine"),
            host=_text(raw, "host"),
            directory=_text(raw, "dir"),
            session=_text(raw, "session"),
            ended=_text(raw, "ended"),
            exit=_code(raw.get("exit")),
            harvested=_text(raw, "harvested"),
            measurement=_text(raw, "measurement") or NATIVE,
            account=(
                {str(k): str(v) for k, v in account.items()} if isinstance(account, dict) else {}
            ),
            agents=_agents_from_json(raw.get("agents")),
            prompt_chars=_count(raw.get("prompt_chars")),
            mode=_text(raw, "mode"),
            playbook=_text(raw, "playbook"),
            pass_=_text(raw, "pass"),
            stage=_text(raw, "stage"),
            attempt=_count(raw.get("attempt")),
            callsign=_text(raw, "callsign"),
            claim=_text(raw, "claim"),
            verdict=verdict if isinstance(verdict, dict) else None,
            declined=tuple(d for d in declined if isinstance(d, dict))
            if isinstance(declined, list)
            else (),
            settings=settings if isinstance(settings, dict) else None,
            fence=({str(k): str(v) for k, v in fence.items()} if isinstance(fence, dict) else None),
        )
        return record.with_turns(turns) if record.headless else record


def _agent_json(agent: AgentUsage) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": agent.id,
        "models": {
            model: {"in": counts.input, "cached": counts.cached, "out": counts.output}
            for model, counts in sorted(agent.models.items())
        },
    }
    for key, value in (("parent", agent.parent), ("session", agent.session), ("kind", agent.kind)):
        if value:
            data[key] = value
    return data


def _agents_from_json(raw: object) -> tuple[AgentUsage, ...]:
    found = map(_agent_from_json, raw if isinstance(raw, list) else [])
    return tuple(agent for agent in found if agent is not None)


def merged(trees: Iterable[Sequence[AgentUsage]]) -> tuple[AgentUsage, ...]:
    """Several turns' trees as one: each agent's counts summed per model, by its id."""
    by_id: dict[str, AgentUsage] = {}
    for tree in trees:
        for agent in tree:
            known = by_id.get(agent.id)
            if known is None:
                by_id[agent.id] = agent
                continue
            models = dict(known.models)
            for model, counts in agent.models.items():
                models[model] = models.get(model, Tokens()) + counts
            by_id[agent.id] = replace(known, models=models)
    return tuple(by_id.values())


def _agent_from_json(raw: object) -> AgentUsage | None:
    if not isinstance(raw, dict) or not _text(raw, "id"):
        return None
    models = raw.get("models")
    if not isinstance(models, dict):
        return None
    return AgentUsage(
        id=_text(raw, "id"),
        parent=_text(raw, "parent"),
        session=_text(raw, "session"),
        kind=_text(raw, "kind"),
        models={
            str(model): Tokens(
                _count(counts.get("in")), _count(counts.get("cached")), _count(counts.get("out"))
            )
            for model, counts in models.items()
            if isinstance(counts, dict)
        },
    )


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", name)


def _text(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    return value if isinstance(value, str) else ""


def _code(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


# -- identity -----------------------------------------------------------------------------------


def new_run_id(now: datetime | None = None) -> str:
    """A run's name: the launch to the second, UTC, and eight random hex digits — sortable,
    and unique on every machine without asking any other."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    return f"{moment:%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}"


MACHINE_ID_FILE = "machine-id"


def known_machine_id(directory: Path | None = None) -> str:
    """This machine's id when one was minted, "" when none was — read without writing, for a
    reader that must leave the config directory as it found it (``agent follow``)."""
    return _stored_machine_id(directory)


def machine_id(directory: Path | None = None) -> str:
    """This machine's id for the ledger: minted once into the config directory, so a
    renamed host is still the machine that can read its own agents' records."""
    if known := _stored_machine_id(directory):
        return known
    path = (directory or config_dir()) / MACHINE_ID_FILE
    minted = uuid.uuid4().hex
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(path, minted + "\n")
    except OSError:
        pass  # Unwritable config: this run is still this machine's, under a fresh id.
    return minted


def _stored_machine_id(directory: Path | None) -> str:
    try:
        return ((directory or config_dir()) / MACHINE_ID_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def host_name() -> str:
    return socket.gethostname() or os.environ.get("COMPUTERNAME", "")


# -- the files ----------------------------------------------------------------------------------


def run_dir(run: str, directory: Path | None = None) -> Path:
    """A headless run's working files — its briefing, each turn's stream and stderr, the
    plan it wrote — derived from its id and never stored, because only the launching machine
    can use them. Not ``/tmp``: a parked run must find them after a reboot."""
    return (directory or config_dir()) / "runs" / run


def path_for(project_dir: Path, record: LedgerRecord) -> Path:
    month = record.launched[:7] if len(record.launched) >= 7 else "unknown"
    return project_dir / LEDGER_DIR / month / f"{record.run}.json"


def write(project_dir: Path, record: LedgerRecord) -> bool:
    """Write the record — and nothing when the file already says the same. True when it
    wrote."""
    path = path_for(project_dir, record)
    text = json.dumps(record.to_json(), indent=2, sort_keys=True) + "\n"
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, text)
    return True


def records(project_dir: Path) -> list[LedgerRecord]:
    """Every record of the project this build can read, oldest launch first."""
    root = project_dir / LEDGER_DIR
    if not root.is_dir():
        return []
    found = [record for path in _files(root) if (record := _load(path)) is not None]
    return sorted(found, key=lambda record: (record.launched, record.run))


def find(project_dir: Path, run: str) -> LedgerRecord | None:
    root = project_dir / LEDGER_DIR
    for path in root.glob(f"*/{run}.json"):
        record = _load(path)
        if record is not None and record.run == run:
            return record
    return None


def fingerprint(project_dir: Path) -> tuple[tuple[str, int], ...]:
    """What the ledger looks like on disk, cheaply: a view polls this to notice a record
    another process wrote, since nothing watches the directory."""
    root = project_dir / LEDGER_DIR
    if not root.is_dir():
        return ()
    stamps: list[tuple[str, int]] = []
    for path in _files(root):
        try:
            stamps.append((path.name, path.stat().st_mtime_ns))
        except OSError:
            continue
    return tuple(stamps)


def _files(root: Path) -> list[Path]:
    # The dot excludes write_atomic's temporaries, which sit beside the file they become.
    return sorted(path for path in root.glob("*/*.json") if not path.name.startswith("."))


def _load(path: Path) -> LedgerRecord | None:
    try:
        return LedgerRecord.from_json(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None  # A half-written file, or one a newer build wrote.


# -- reading it back ------------------------------------------------------------------------------


def by_step(found: Iterable[LedgerRecord]) -> dict[str, list[LedgerRecord]]:
    steps: dict[str, list[LedgerRecord]] = {}
    for record in found:
        steps.setdefault(record.step, []).append(record)
    return steps


def claimed(found: Iterable[LedgerRecord], other_than: str = "") -> frozenset[str]:
    """Every session some record owns, except the run named — what a harvest must not take."""
    owned: set[str] = set()
    for record in found:
        if record.run != other_than:
            owned |= record.sessions
    return frozenset(owned)


def legacy(project: str, step: str, rows: Sequence[Mapping[str, Any]]) -> list[LedgerRecord]:
    """The rows the retired ``agent_usage`` aspect kept on a step, as ledger records.

    A row said ``input`` (everything sent, cache reads included) and ``output``, with the
    vendor's own split under ``details`` — cache reads under ``cache_read`` (Claude,
    OpenCode) or ``cached_input`` (Codex). The model was never recorded.
    """
    converted: list[LedgerRecord] = []
    for index, row in enumerate(rows):
        raw_details = row.get("details")
        details: Mapping[str, Any] = raw_details if isinstance(raw_details, dict) else {}
        cached = _count(details.get("cache_read")) or _count(details.get("cached_input"))
        sent, out = _count(row.get("input")), _count(row.get("output"))
        session = str(row.get("session") or "")
        ended = str(row.get("ended") or "")
        converted.append(
            LedgerRecord(
                run="legacy-" + _safe(session or f"{step}-{index}"),
                project=project,
                step=step,
                harness=str(row.get("harness") or ""),
                launched=ended,
                session=session,
                ended=ended,
                measurement=LEGACY,
                prompt_chars=_count(row.get("prompt_chars")),
                agents=(
                    AgentUsage(
                        id="main",
                        session=session,
                        models={UNKNOWN_MODEL: Tokens(max(sent - cached, 0), cached, out)},
                    ),
                ),
            )
        )
    return converted
