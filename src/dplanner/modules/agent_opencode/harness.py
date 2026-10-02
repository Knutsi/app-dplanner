"""OpenCode as an agent harness: how it is launched, found again, and read.

**The command.** ``opencode --prompt <text>`` seeds an interactive session. A session id
(``ses_…``) is minted by OpenCode and cannot be chosen up front; ``opencode -s <id>``
continues one, so a run is resumable once its id is known.

**Opening it bare.** ``opencode`` without ``--prompt``: the same interactive session with
nothing seeded into it — what *Open Agent in Code* opens.

**Finding the run afterwards.** OpenCode keeps its sessions in one SQLite database —
``$OPENCODE_DB``, else ``$XDG_DATA_HOME/opencode/opencode.db``, else
``~/.local/share/opencode/opencode.db`` — whose ``session`` table records each session's
``directory``, ``time_created``, ``model`` (``{"id", "providerID"}``), its ``parent_id``
and its own token totals (``tokens_input``, ``tokens_output``, ``tokens_reasoning``,
``tokens_cache_read``, ``tokens_cache_write``). The run's session is the one the ledger
already names, else the earliest created in the run's directory at or after the launch that
no other run has claimed (``RunFacts.claimed``); a subagent is a session whose
``parent_id`` points back up the tree, and a parent's totals do not include its children's,
so the tree is the session and every descendant. Read through the standard library's
``sqlite3`` in read-only mode so a running OpenCode is never disturbed. The schema is
OpenCode's own; anything the query cannot read answers ``None``. The account is the
provider and whether ``auth.json`` holds a key or a login for it — its ``type`` and
nothing else.
"""

import json
import os
import sqlite3
import sys
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path

from dplanner.domain.agents import AgentHarness, AgentUsage, RunFacts, RunReport, Tokens

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


def _tokens(row: sqlite3.Row) -> Tokens:
    def count(key: str) -> int:
        value = row[key]
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    return Tokens(
        input=count("tokens_input") + count("tokens_cache_write"),
        cached=count("tokens_cache_read"),
        output=count("tokens_output") + count("tokens_reasoning"),
    )


def _model(row: sqlite3.Row) -> tuple[str, str]:
    """The session's model and its provider, from the stored JSON."""
    try:
        model = json.loads(row["model"] or "{}")
    except (TypeError, ValueError):
        return "unknown", ""
    if not isinstance(model, dict):
        return "unknown", ""
    return str(model.get("id") or "unknown"), str(model.get("providerID") or "")


COLUMNS = (
    "id, parent_id, directory, time_created, model, tokens_input, tokens_output,"
    " tokens_reasoning, tokens_cache_read, tokens_cache_write"
)

_TREE = f"""
WITH RECURSIVE tree(id) AS (
    SELECT id FROM session WHERE id = ?
    UNION
    SELECT s.id FROM session s JOIN tree t ON s.parent_id = t.id
)
SELECT {COLUMNS} FROM session WHERE id IN (SELECT id FROM tree) ORDER BY time_created
"""


def report(
    facts: RunFacts, database: Path | None = None, auth: Path | None = None
) -> RunReport | None:
    """The run's session tree: by the id when one is known, else the earliest unclaimed
    session created in the run's directory at or after the launch, and its descendants."""
    path = database or database_path()
    if not path.is_file():
        return None
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        try:
            connection.row_factory = sqlite3.Row
            root = facts.session or _first_session(connection, facts)
            rows = connection.execute(_TREE, (root,)).fetchall() if root else []
        finally:
            connection.close()
    except sqlite3.Error:
        return None
    if not rows:
        return None
    agents = []
    provider = ""
    for row in rows:
        model, provider_of = _model(row)
        is_root = row["id"] == root
        provider = provider or (provider_of if is_root else "")
        parent = str(row["parent_id"] or "")
        agents.append(
            AgentUsage(
                "main" if is_root else str(row["id"]),
                {model: _tokens(row)},
                parent="" if is_root else ("main" if parent == root else parent),
                session=str(row["id"]),
            )
        )
    return RunReport(session=root, agents=tuple(agents), account=_account(provider, auth or path))


def _first_session(connection: sqlite3.Connection, facts: RunFacts) -> str:
    try:
        started = datetime.fromisoformat(facts.launched.replace("Z", "+00:00"))
    except ValueError:
        return ""
    since = (started - CLOCK_SLACK).timestamp()
    rows = connection.execute(
        "SELECT id, time_created FROM session"
        " WHERE directory = ? AND parent_id IS NULL ORDER BY time_created",
        (facts.directory,),
    ).fetchall()
    for row in rows:
        created = _seconds(row["time_created"])
        if created is not None and created >= since and str(row["id"]) not in facts.claimed:
            return str(row["id"])
    return ""


def _account(provider: str, beside: Path) -> dict[str, str]:
    """The provider, and whether OpenCode holds an API key or a login for it."""
    words = {"vendor": provider} if provider else {}
    auth = beside if beside.name == "auth.json" else beside.parent / "auth.json"
    try:
        entries = json.loads(auth.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return words
    entry = entries.get(provider) if isinstance(entries, dict) else None
    if isinstance(entry, dict) and isinstance(entry.get("type"), str):
        words["plan"] = entry["type"]
    return words


HARNESS = AgentHarness(
    id="opencode",
    label="OpenCode",
    command="opencode --prompt {prompt}",
    open_command="opencode",
    resume="opencode -s {session}",
    shell_markers=("OPENCODE", "OPENCODE_PID"),
    report=report,
    binary="opencode",
)
