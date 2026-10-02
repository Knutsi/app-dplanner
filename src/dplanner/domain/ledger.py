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
harvest (``modules/step_agent_run/harvest.py``) re-reads the vendor's records and writes
the whole record again — larger while the run goes on, the same once it has ended. Any
number of harvests, in any order, from the wrapper script, the window or a terminal, give
one file with the latest answer. A write that would change nothing is skipped, so a sweep
over finished runs leaves git quiet.

Nothing derived is stored: a step's totals, a project's, the running sums of the
Expenditure tab are all summed on read. A file this build cannot read is skipped, never a
crash — a newer build may have written it — and there is no migration: the format is in
every record.
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
FORMAT = 1

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
    agents: tuple[AgentUsage, ...] = ()
    prompt_chars: int = 0  # What the briefing came to, in characters.

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
            "format": FORMAT,
            "run": self.run,
            "project": self.project,
            "step": self.step,
            "harness": self.harness,
            "launched": self.launched,
            "measurement": self.measurement,
            "agents": [_agent_json(agent) for agent in self.agents],
        }
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
        agents = raw.get("agents")
        account = raw.get("account")
        code = raw.get("exit")
        return cls(
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
            exit=code if isinstance(code, int) and not isinstance(code, bool) else None,
            harvested=_text(raw, "harvested"),
            measurement=_text(raw, "measurement") or NATIVE,
            account=(
                {str(k): str(v) for k, v in account.items()} if isinstance(account, dict) else {}
            ),
            agents=tuple(
                agent
                for agent in map(_agent_from_json, agents if isinstance(agents, list) else [])
                if agent is not None
            ),
            prompt_chars=_count(raw.get("prompt_chars")),
        )


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


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


# -- identity -----------------------------------------------------------------------------------


def new_run_id(now: datetime | None = None) -> str:
    """A run's name: the launch to the second, UTC, and eight random hex digits — sortable,
    and unique on every machine without asking any other."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    return f"{moment:%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}"


def machine_id(directory: Path | None = None) -> str:
    """This machine's id for the ledger: minted once into the config directory, so a
    renamed host is still the machine that can read its own agents' records."""
    path = (directory or config_dir()) / "machine-id"
    try:
        known = path.read_text(encoding="utf-8").strip()
    except OSError:
        known = ""
    if known:
        return known
    minted = uuid.uuid4().hex
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(path, minted + "\n")
    except OSError:
        pass  # Unwritable config: this run is still this machine's, under a fresh id.
    return minted


def host_name() -> str:
    return socket.gethostname() or os.environ.get("COMPUTERNAME", "")


# -- the files ----------------------------------------------------------------------------------


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
