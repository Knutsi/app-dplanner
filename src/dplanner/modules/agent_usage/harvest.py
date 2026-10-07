"""Harvesting a run: reading what it consumed back from the vendor's records into the ledger.

**Nothing has to see a run end for its tokens to be counted.** The launch writes the
run's record into the project's ledger (``domain/ledger.py``) — which step, which agent
CLI, where it works, the session when the CLI lets one be named. Everything after that is
a *harvest*: ask the harness to read its own records of the run's session tree and write
the record again. A harvest is idempotent — the same records read twice give the same
answer, a larger one while the run goes on — so it may run any number of times, from
anywhere on the machine that launched the run, in any order:

- the wrapper script, the moment the agent exits (``dplanner usage harvest --run …``),
  which needs no window at all;
- the window, when its poll sees the shell end;
- the window's sweep, at start and every few minutes, over every run of this machine
  that has not been read since it ended — a terminal closed on the agent, a reboot that
  emptied ``/tmp``, a window that was not running;
- ``dplanner usage harvest --all``, by hand.

Missing any one of them costs nothing; the next one reads the same records. Only the
vendor deleting them first loses anything: Claude Code keeps a transcript thirty days, so
the sweep stops looking after that.

**A session is claimed once.** A CLI that mints its own session ids (Codex, OpenCode) is
found by the directory the run worked in and its launch time, and two runs in one checkout
must not both take the first session there: every harvest is handed the sessions the
library's other records already own, and writes the one it found into its own record, so
from then on it is read by id.

**A headless run is not harvested.** Its supervisor is its record's one writer, and counts
each turn from the turn's own stream as the turn ends — a turn lost with its supervisor is
counted from the stream it left, when the next supervisor ends it ``lost``. A harvest
rewriting the record beside a live supervisor would be a second writer, and the vendor's
whole-session total would count a session two runs share twice.
"""

from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from dplanner.domain import ledger
from dplanner.domain.agents import AgentHarness, RunFacts, harness_by_id
from dplanner.domain.ledger import LedgerRecord
from dplanner.domain.model import now_stamp

# How long a run's records are worth looking for: Claude Code deletes a transcript after
# thirty days (``cleanupPeriodDays``), and nothing reads back what is gone.
SWEEP_DAYS = 30


def harvest(
    record: LedgerRecord, harnesses: Sequence[AgentHarness], claimed: frozenset[str] = frozenset()
) -> LedgerRecord:
    """The record with what the vendor's records say now; the record as it was when they
    say nothing — not there yet, gone, or a CLI this build cannot read."""
    harness = harness_by_id(tuple(harnesses), record.harness)
    if harness is None or harness.report is None or record.headless:
        return record
    facts = RunFacts(
        session=record.session,
        directory=record.directory,
        launched=record.launched,
        ended=record.ended,
        claimed=claimed - record.sessions,
    )
    report = harness.report(facts)
    if report is None or not report.agents:
        return record
    filled = record.with_report(report, record.harvested)
    if filled == record and not _unread_since_end(record):
        return record  # Nothing new: no write, so a live run's sweeps leave git quiet.
    return replace(filled, harvested=now_stamp())


def store(project_dir: Path, record: LedgerRecord) -> bool:
    """Write the record, keeping an end another process wrote meanwhile — a harvest begun
    before the wrapper said the agent exited must not write the exit away. A headless
    record is never written here: its supervisor is its one writer."""
    if record.headless:
        return False
    current = ledger.find(project_dir, record.run)
    if current is not None and current.ended and not record.ended:
        record = record.ended_at(current.ended, current.exit)
    return ledger.write(project_dir, record)


def harvest_run(
    project_dirs: Sequence[Path],
    run: str,
    harnesses: Sequence[AgentHarness],
    code: int | None = None,
    ended: bool = False,
) -> LedgerRecord | None:
    """Harvest one run wherever its record is; ``ended`` marks its end first."""
    found = _records(project_dirs)
    for project_dir, records in found.items():
        record = next((r for r in records if r.run == run), None)
        if record is None:
            continue
        if record.headless:
            return record  # Its supervisor's alone: no end from a wrapper, no write.
        if ended:
            record = record.ended_at(now_stamp(), code)
        claimed = ledger.claimed(_all(found), other_than=run)
        record = harvest(record, harnesses, claimed)
        store(project_dir, record)
        return record
    return None


def due(record: LedgerRecord, machine: str, now: datetime) -> bool:
    """Whether a sweep on ``machine`` should read the run again: it is this machine's, its
    records may still exist, and it has not been read since it ended."""
    if record.machine != machine or record.measurement in (ledger.MANUAL, ledger.LEGACY):
        return False
    if record.headless:
        return False
    launched = _parse(record.launched)
    if launched is None or now - launched > timedelta(days=SWEEP_DAYS):
        return False
    return not record.ended or _unread_since_end(record)


def _unread_since_end(record: LedgerRecord) -> bool:
    """Whether the run ended and nobody has read its records since — the one read every
    run is owed after its end, whatever the reads before it found."""
    if not record.ended:
        return False
    harvested, ended = _parse(record.harvested), _parse(record.ended)
    return harvested is None or ended is None or harvested < ended


def anything_due(project_dirs: Sequence[Path], machine: str = "") -> bool:
    """Whether a sweep would read anything — cheap, the ledger's own small files only, so a
    window asks before it starts a thread to read the vendors' large ones."""
    machine = machine or ledger.machine_id()
    moment = datetime.now().astimezone()
    return any(
        due(record, machine, moment)
        for project_dir in project_dirs
        for record in ledger.records(project_dir)
    )


def sweep(
    project_dirs: Sequence[Path],
    harnesses: Sequence[AgentHarness],
    machine: str = "",
    now: datetime | None = None,
) -> int:
    """Harvest every run on these projects that is due; the number of records written."""
    machine = machine or ledger.machine_id()
    moment = now or datetime.now().astimezone()
    found = _records(project_dirs)
    claimed = set(ledger.claimed(_all(found)))
    written = 0
    for project_dir, records in found.items():
        for record in records:
            if not due(record, machine, moment):
                continue
            harvested = harvest(record, harnesses, frozenset(claimed))
            claimed |= harvested.sessions
            if harvested is not record:  # Nothing to read yet stays due: try next sweep.
                written += store(project_dir, harvested)
    return written


def _records(project_dirs: Iterable[Path]) -> dict[Path, list[LedgerRecord]]:
    return {project_dir: ledger.records(project_dir) for project_dir in project_dirs}


def _all(found: dict[Path, list[LedgerRecord]]) -> list[LedgerRecord]:
    return [record for records in found.values() for record in records]


def _parse(stamp: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()
