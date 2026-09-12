"""Codex as an agent harness: how it is launched, found again, and read.

**The command.** ``codex <prompt>`` — the positional argument seeds an interactive
session. Codex has no plan-mode flag (``/plan`` inside the session switches to it) and
no way to name a session up front: the thread id is minted by Codex itself. Its sandbox
reads anywhere, so the briefing outside the checkout needs no extra flag; ``--add-dir``
on Codex grants *write* access and is not wanted.

**Finding the run afterwards.** Codex records every session as a rollout file,
``$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<local time>-<thread id>.jsonl`` (the day is
local time), whose first line is ``session_meta`` with the ``cwd`` it started in and its
``timestamp``. The launcher knows both — the wrapper records where the agent works, and
when — so the run's file is the earliest one started in that directory at or after the
launch. That id is what ``codex resume <id>`` takes, so a Codex run is resumable even
though nothing named it up front. A step's worktree is one directory per run; a step
that works in the checkout itself shares it with other runs, and the start time tells
them apart.

**The tokens.** Each usage update is persisted as an ``event_msg`` line whose payload is
``token_count`` with ``info.total_token_usage`` — the *cumulative* totals for the thread:
``input_tokens`` (cached tokens are a subset of it, ``cached_input_tokens``),
``output_tokens`` (reasoning is a subset, ``reasoning_output_tokens``) and
``cache_write_input_tokens``. The last such line is the session's total. Codex's format
is its own and unversioned here, so the reader answers ``None`` for anything it cannot
read rather than raising.
"""

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from dplanner.domain.agents import AgentHarness, RunFacts, RunReport, Usage

ROLLOUT_NAME = re.compile(r"^rollout-.*-([0-9a-f-]{36})(?:_.*)?\.jsonl$")
# How far before the launch stamp a rollout may start and still be this run's: the two
# clocks are the same machine's, so this only covers a stamp taken after the shell ran.
CLOCK_SLACK = timedelta(minutes=2)


def codex_home(env: dict[str, str] | None = None) -> Path:
    environ = os.environ if env is None else env
    return Path(environ.get("CODEX_HOME") or Path.home() / ".codex")


def _same_directory(recorded: object, directory: str) -> bool:
    if not isinstance(recorded, str) or not recorded:
        return False
    try:
        return Path(recorded).resolve() == Path(directory).resolve()
    except OSError:
        return recorded == directory


def _stamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


def _first_record(path: Path) -> dict[str, object] | None:
    try:
        with path.open(encoding="utf-8") as handle:
            line = handle.readline()
        record = json.loads(line)
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def find_rollout(directory: str, launched: str, home: Path | None = None) -> Path | None:
    """The earliest rollout started in ``directory`` at or after ``launched``.

    Only the launch day and its neighbours are searched — the directories are named by
    local date, the stamp is UTC, and a run may straddle midnight.
    """
    started = _stamp(launched)
    if started is None:
        return None
    sessions = (home or codex_home()) / "sessions"
    candidates: list[tuple[datetime, Path]] = []
    local_day = started.astimezone()
    for offset in (-1, 0, 1):
        day = local_day + timedelta(days=offset)
        folder = sessions / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}"
        if not folder.is_dir():
            continue
        for path in folder.glob("rollout-*.jsonl"):
            record = _first_record(path)
            if record is None or record.get("type") != "session_meta":
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            begun = _stamp(payload.get("timestamp"))
            if begun is None or begun < started - CLOCK_SLACK:
                continue
            if _same_directory(payload.get("cwd"), directory):
                candidates.append((begun, path))
    return min(candidates)[1] if candidates else None


def thread_id(path: Path) -> str:
    """The thread id a rollout belongs to: from its first line, else from its name."""
    record = _first_record(path)
    payload = record.get("payload") if record else None
    if isinstance(payload, dict):
        for key in ("id", "session_id"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
    match = ROLLOUT_NAME.match(path.name)
    return match.group(1) if match else ""


def read_rollout(path: Path) -> Usage | None:
    """The last cumulative ``token_count`` the rollout persisted, or None."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    totals: dict[str, object] | None = None
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("type") != "event_msg":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            continue
        info = payload.get("info")
        usage = info.get("total_token_usage") if isinstance(info, dict) else None
        if isinstance(usage, dict):
            totals = usage
    if totals is None:
        return None

    def count(key: str) -> int:
        value = totals.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    return Usage(
        input=count("input_tokens") + count("cache_write_input_tokens"),
        output=count("output_tokens"),
        details={
            "cached_input": count("cached_input_tokens"),
            "cache_write": count("cache_write_input_tokens"),
            "reasoning": count("reasoning_output_tokens"),
        },
    )


def report(facts: RunFacts, home: Path | None = None) -> RunReport | None:
    if not facts.directory:
        return None
    rollout = find_rollout(facts.directory, facts.launched, home)
    if rollout is None:
        return None
    return RunReport(session=thread_id(rollout), usage=read_rollout(rollout))


HARNESS = AgentHarness(
    id="codex",
    label="Codex",
    command="codex {prompt}",
    resume="codex resume {session}",
    shell_markers=("CODEX_THREAD_ID", "CODEX_SESSION_ID"),
    report=report,
    binary="codex",
)
