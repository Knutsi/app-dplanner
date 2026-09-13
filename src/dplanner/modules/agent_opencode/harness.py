"""OpenCode as an agent harness: how it is launched, found again, and read.

**The command.** ``opencode --prompt <text>`` seeds an interactive session. A session id
(``ses_…``) is minted by OpenCode and cannot be chosen up front; ``opencode -s <id>``
continues one, so a run is resumable once its id is known.

**Finding the run afterwards.** OpenCode keeps its sessions in one SQLite database —
``$OPENCODE_DB``, else ``$XDG_DATA_HOME/opencode/opencode.db``, else
``~/.local/share/opencode/opencode.db`` — whose ``session`` table records each session's
``directory`` and ``time_created`` beside its token totals (``tokens_input``,
``tokens_output``, ``tokens_reasoning``, ``tokens_cache_read``, ``tokens_cache_write``).
The run's row is the earliest one created in the directory the agent worked in at or
after the launch, read through the standard library's ``sqlite3`` in read-only mode so
a running OpenCode is never disturbed. The schema is OpenCode's own; anything the query
cannot read answers ``None``.
"""

import os
import sqlite3
import sys
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path

from dplanner.domain.agents import AgentHarness, RunFacts, RunReport, Usage

CLOCK_SLACK = timedelta(minutes=2)


def database_path(
    env: Mapping[str, str] | None = None,
    platform: str = sys.platform,
    home: Path | None = None,
) -> Path:
    """Where OpenCode keeps its sessions on this machine.

    Platform, environment and home are arguments with defaults — ``cli/desktop.py``'s
    convention — so every platform's answer is checkable from any other. XDG is not a
    Windows idea and the data directory there is ``%LOCALAPPDATA%``, the same base
    ``cli/desktop.py`` writes the launcher icon under. A wrong guess costs a usage report
    and nothing else: :func:`report` answers None for a database that is not there, and
    ``$OPENCODE_DB`` is the way out when it moves.
    """
    environ = os.environ if env is None else env
    if environ.get("OPENCODE_DB"):
        return Path(environ["OPENCODE_DB"])
    home = home or Path.home()
    if environ.get("XDG_DATA_HOME"):
        data_home = Path(environ["XDG_DATA_HOME"])
    elif platform.startswith("win"):
        data_home = Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    else:
        data_home = home / ".local" / "share"
    return data_home / "opencode" / "opencode.db"


def _seconds(value: object) -> float | None:
    """A stored time as seconds since the epoch — OpenCode writes milliseconds."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value / 1000 if value > 1e11 else float(value)


def _usage(row: sqlite3.Row) -> Usage:
    def count(key: str) -> int:
        value = row[key]
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    cache_read, cache_write = count("tokens_cache_read"), count("tokens_cache_write")
    reasoning = count("tokens_reasoning")
    return Usage(
        input=count("tokens_input") + cache_read + cache_write,
        output=count("tokens_output") + reasoning,
        details={"cache_read": cache_read, "cache_write": cache_write, "reasoning": reasoning},
    )


COLUMNS = (
    "id, directory, time_created, tokens_input, tokens_output, tokens_reasoning,"
    " tokens_cache_read, tokens_cache_write"
)


def report(facts: RunFacts, database: Path | None = None) -> RunReport | None:
    """The run's session row: by the id when one is known, else the earliest session
    created in the run's directory at or after the launch."""
    path = database or database_path()
    if not path.is_file():
        return None
    try:
        started = datetime.fromisoformat(facts.launched.replace("Z", "+00:00"))
    except ValueError:
        return None
    since = (started - CLOCK_SLACK).timestamp()
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        try:
            connection.row_factory = sqlite3.Row
            if facts.session:
                rows = connection.execute(
                    f"SELECT {COLUMNS} FROM session WHERE id = ?", (facts.session,)
                ).fetchall()
            else:
                rows = connection.execute(
                    f"SELECT {COLUMNS} FROM session WHERE directory = ? ORDER BY time_created",
                    (facts.directory,),
                ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return None
    for row in rows:
        created = _seconds(row["time_created"])
        if facts.session or (created is not None and created >= since):
            return RunReport(session=str(row["id"]), usage=_usage(row))
    return None


HARNESS = AgentHarness(
    id="opencode",
    label="OpenCode",
    command="opencode --prompt {prompt}",
    resume="opencode -s {session}",
    shell_markers=("OPENCODE", "OPENCODE_PID"),
    report=report,
    binary="opencode",
)
