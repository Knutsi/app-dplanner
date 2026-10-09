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

**Headless.** One turn is ``opencode run --format json``, resumed with ``--session <id>``. A
plan and a review run as the built-in ``plan`` agent; an execute turn runs with ``--auto``,
which approves every permission the configuration does not deny. Without it a permission is
not asked for but refused, said only on stderr — ``permission requested: edit (calc.py);
auto-rejecting`` — and the run exits 0 having done nothing, which is why stderr is read for
denials. OpenCode has no schema option, so a typed final message is whatever the agent was
asked to answer as JSON, and prose is otherwise all there is. Every event names the session
(``sessionID``); ``step_finish`` carries each request's tokens, summed over the turn; ``text``
is what the agent said; ``error`` is a failure, with the provider's status.

**Signed in** is a credential *or* a built-in model: OpenCode ran on its own ``opencode/*``
models with no login at all (2026-10-07), so ``opencode auth list`` saying "0 credentials" is
not the end of it — ``opencode models opencode`` listing anything is. Both are asked through
the CLI rather than read from ``auth.json``, so a probe on another machine asks the same.
"""

import json
import os
import re
import sqlite3
import sys
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path

from dplanner.domain.agents import (
    AgentHarness,
    AgentUsage,
    RunFacts,
    RunReport,
    Shell,
    SignedIn,
    SignIn,
    Tokens,
)
from dplanner.domain.headless import (
    STALL_SECONDS,
    Headless,
    StageKind,
    TurnLog,
    TurnSpec,
    called,
    came_back,
    shorten,
    typed_message,
)

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


def headless_command(spec: TurnSpec) -> list[str]:
    argv = ["opencode", "run", "--format", "json"]
    if spec.resume:
        argv += ["--session", spec.session]
    argv += ["--auto"] if spec.stage is StageKind.EXECUTE else ["--agent", "plan"]
    # "--" ends the options, so an answer that reads like a flag ("--help") is still a prompt.
    return [*argv, "--", spec.prompt]


def read_event(log: TurnLog, event: Mapping[str, object]) -> None:
    log.session = log.session or str(event.get("sessionID") or "")
    kind = event.get("type")
    part = event.get("part")
    part = part if isinstance(part, dict) else {}
    if kind == "step_finish":
        tokens = part.get("tokens")
        if isinstance(tokens, dict):
            cache = tokens.get("cache")
            cache = cache if isinstance(cache, dict) else {}
            step = Tokens(
                input=_count(tokens.get("input")) + _count(cache.get("write")),
                cached=_count(cache.get("read")),
                output=_count(tokens.get("output")) + _count(tokens.get("reasoning")),
            )
            log.tokens += step
            if step.worked:
                log.progressed()
    elif kind == "text":
        log.final = str(part.get("text") or "")
        log.typed = typed_message(log.final)
    elif kind == "error":
        error = event.get("error")
        error = error if isinstance(error, dict) else {}
        data = error.get("data")
        data = data if isinstance(data, dict) else {}
        log.error = f"{error.get('name', 'error')}: {data.get('message', '')}"
        status = data.get("statusCode")
        log.status = status if isinstance(status, int) else None


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


_AUTO_REJECTED = re.compile(r"permission requested: (.+?); auto-rejecting")


def stderr_denials(stderr: str) -> list[str]:
    return _AUTO_REJECTED.findall(stderr)


# opencode reports a tool only once it has finished, so no tool is ever seen running and the
# stall clock never waits on one: its threshold covers a whole tool call instead.
def say_event(event: Mapping[str, object]) -> list[str]:
    """An event as ``agent follow`` says it: what the agent wrote, each tool it called with the
    first line of what came back — opencode reports a tool once it has finished — and an
    error."""
    kind = event.get("type")
    part = event.get("part")
    part = part if isinstance(part, dict) else {}
    if kind == "text":
        return [str(part.get("text") or "")]
    if kind == "tool_use":
        state = part.get("state")
        state = state if isinstance(state, dict) else {}
        lines = [called(part.get("tool"), state.get("input"))]
        failed = state.get("status") == "error"
        return [*lines, came_back(state.get("error" if failed else "output") or "", failed)]
    if kind == "error":
        error = event.get("error")
        error = error if isinstance(error, dict) else {}
        data = error.get("data")
        message = data.get("message") if isinstance(data, dict) else ""
        return [f"· {error.get('name', 'error')}: {shorten(message or '')}"]
    return []


HEADLESS = Headless(
    command=headless_command,
    read=read_event,
    say=say_event,
    stderr_denials=stderr_denials,
    stall=2 * STALL_SECONDS,
)

_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
_CREDENTIALS = re.compile(r"(\d+) credentials?")


def signed_in(shell: Shell) -> SignedIn:
    _code, said = shell(("auth", "list"))
    counted = _CREDENTIALS.search(_ESCAPE.sub("", said))
    count = int(counted.group(1)) if counted else 0
    if count:
        return SignedIn(ok=True, detail=f"{count} credential{'s' if count != 1 else ''}")
    code, models = shell(("models", "opencode"))
    if code == 0 and any(line.startswith("opencode/") for line in models.splitlines()):
        return SignedIn(ok=True, detail="no credentials — OpenCode's built-in models")
    return SignedIn(ok=False, detail="no credentials and no built-in models")


HARNESS = AgentHarness(
    id="opencode",
    label="OpenCode",
    command="opencode --prompt {prompt}",
    open_command="opencode",
    resume="opencode -s {session}",
    shell_markers=("OPENCODE", "OPENCODE_PID"),
    report=report,
    binary="opencode",
    headless=HEADLESS,
    sign_in=SignIn(probe=signed_in, command="opencode auth login"),
    home=lambda: database_path().parent,
)
