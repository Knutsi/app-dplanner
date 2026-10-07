"""Codex as an agent harness: how it is launched, found again, and read.

**The command.** ``codex <prompt>`` — the positional argument seeds an interactive
session. Codex has no plan-mode flag (``/plan`` inside the session switches to it) and
no way to name a session up front: the thread id is minted by Codex itself. Its sandbox
reads anywhere, so the briefing outside the checkout needs no extra flag; ``--add-dir``
on Codex grants *write* access and is not wanted.

**Opening it bare.** ``codex`` with no positional argument: the same interactive session,
waiting on the first thing the person types — what *Open Agent in Code* opens.

**Finding the run afterwards.** Codex records every session as a rollout file,
``$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<local time>-<thread id>.jsonl`` (the day is
local time), whose first line is ``session_meta`` with the ``cwd`` it started in and its
``timestamp``. The launcher knows both — the wrapper records where the agent works, and
when — so the run's file is the earliest one started in that directory at or after the
launch. That id is what ``codex resume <id>`` takes, so a Codex run is resumable even
though nothing named it up front. A step's worktree is one directory per run; a step
that works in the checkout itself shares it with other runs, and the start time tells
them apart.

**The tokens, per thread and per model.** Each model response is persisted as a
``token_usage_record`` line naming its ``thread_id`` and ``response_id`` with that
response's ``usage`` — ``input_tokens`` (cached tokens are a subset of it,
``cached_input_tokens``), ``cache_write_input_tokens``, ``output_tokens`` (reasoning is a
subset) — and the model in force is the latest ``turn_context``'s. A thread's count is the
sum over its own responses, so a child's file that replays its parent's history counts
none of the parent's. A rollout from before those records falls back to its last
cumulative ``token_count``.

**Subagents are threads of their own**, each with its own rollout, and the edge from
parent to child is a row in Codex's state index (``state_<n>.sqlite``, table
``thread_spawn_edges``), read-only. The tree is the root and every descendant found there;
an index that cannot be read leaves the root alone, said as a partial count.

**A thread is found once and owned from then on.** When the launch named no session the
run's thread is the earliest rollout in its directory that no other run has claimed
(``RunFacts.claimed``); the harvest writes it into the ledger, and every later read goes
straight to it by id. The account is the plan the rollout's rate limits name (``plus``).
Codex's formats are its own and unversioned here, so every reader answers ``None`` or
nothing for what it cannot read rather than raising.

**Headless.** One turn is ``codex exec --json``, a resumed one ``codex exec resume --json …
<thread> <prompt>``. **The stage's mode is spelt as ``-c`` config overrides, on a fresh turn and
a resumed one alike**, because ``exec resume`` takes none of ``-s``, ``--approve-for-me`` or
``--add-dir`` (0.160.0), and a resume does not keep the mode its session began in — a
read-only thread resumed bare came back ``workspace-write``. Read off the rollout's
``turn_context`` against the fake API on 2026-10-07: ``--approve-for-me --add-dir <d>`` is
exactly ``sandbox_mode="workspace-write"``, ``approval_policy="on-request"``,
``approvals_reviewer="auto_review"`` and ``sandbox_workspace_write.writable_roots=[<d>]``, and
those overrides stick on ``exec resume``. A plan and a review are ``read-only`` with no
approvals; an execute turn may write the run directory and the plan repository, which the
10-04 run's 21 sandbox prompts were the lack of. Execute and review answer their stage's
schema (``--output-schema``, a file in the run directory) as the last ``agent_message``.

The ``--json`` stream names the thread (``thread.started``), each finished item
(``item.completed``; the final text is the last ``agent_message``), the turn's usage
(``turn.completed``) and a failure (``turn.failed``) — but **no limit telemetry**: the account's
windows (``rate_limits.primary``/``secondary``, a percentage and a reset) are only in the
rollout's ``token_count`` events, so :func:`read_limits` reads them there.
"""

import json
import os
import re
import sqlite3
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
    Headless,
    LimitWindow,
    StageKind,
    TurnLog,
    TurnSpec,
    schema_file,
    typed_message,
    window,
)

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


def find_rollout(
    directory: str, launched: str, home: Path | None = None, claimed: frozenset[str] = frozenset()
) -> Path | None:
    """The earliest rollout started in ``directory`` at or after ``launched`` that no other
    run has claimed.

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
            if not isinstance(payload, dict) or _spawned(payload):
                continue
            begun = _stamp(payload.get("timestamp"))
            if begun is None or begun < started - CLOCK_SLACK:
                continue
            if thread_id(path) in claimed:
                continue
            if _same_directory(payload.get("cwd"), directory):
                candidates.append((begun, path))
    return min(candidates)[1] if candidates else None


def _spawned(payload: dict[str, object]) -> bool:
    """Whether a rollout is a subagent's — found through its parent, never as a run."""
    source = payload.get("source")
    return isinstance(source, dict) and "subagent" in source


def thread_id(path: Path) -> str:
    """The thread id a rollout belongs to: from its first line, else from its name."""
    record = _first_record(path)
    payload = record.get("payload") if record else None
    if isinstance(payload, dict):
        value = payload.get("id")
        if isinstance(value, str) and value:
            return value
    match = ROLLOUT_NAME.match(path.name)
    return match.group(1) if match else ""


def state_index(home: Path | None = None) -> Path | None:
    """Codex's state index — the newest ``state_<n>.sqlite`` — or None."""
    numbered = []
    for path in (home or codex_home()).glob("state_*.sqlite"):
        suffix = path.stem.removeprefix("state_")
        if suffix.isdigit():
            numbered.append((int(suffix), path))
    return max(numbered)[1] if numbered else None


def _query(index: Path, sql: str, args: tuple[str, ...]) -> list[tuple[object, ...]] | None:
    try:
        connection = sqlite3.connect(f"{index.as_uri()}?mode=ro", uri=True)
        try:
            return connection.execute(sql, args).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return None


_DESCENDANTS = """
WITH RECURSIVE tree(child, parent) AS (
    SELECT child_thread_id, parent_thread_id FROM thread_spawn_edges WHERE parent_thread_id = ?
    UNION
    SELECT e.child_thread_id, e.parent_thread_id
    FROM thread_spawn_edges e JOIN tree t ON e.parent_thread_id = t.child
)
SELECT child, parent FROM tree
"""


def descendants(thread: str, home: Path | None = None) -> list[tuple[str, str]] | None:
    """Every thread spawned under ``thread``, as (child, parent); None when the index
    cannot be read."""
    index = state_index(home)
    if index is None:
        return None
    rows = _query(index, _DESCENDANTS, (thread,))
    if rows is None:
        return None
    return [(str(child), str(parent)) for child, parent in rows]


def rollout_for(thread: str, home: Path | None = None) -> Path | None:
    """A thread's rollout: where the index says it is, else by the id in its name."""
    base = home or codex_home()
    index = state_index(base)
    if index is not None:
        rows = _query(index, "SELECT rollout_path FROM threads WHERE id = ?", (thread,))
        for (recorded,) in rows or []:
            if isinstance(recorded, str) and Path(recorded).is_file():
                return Path(recorded)
    return next(iter(sorted((base / "sessions").glob(f"*/*/*/rollout-*-{thread}*.jsonl"))), None)


def read_thread(path: Path) -> tuple[dict[str, Tokens], str]:
    """A rollout's own consumption per model, and the plan its rate limits name."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}, ""
    own = thread_id(path)
    model, plan = "", ""
    responses: dict[str, tuple[str, dict[str, object]]] = {}
    last_total: tuple[str, dict[str, object]] | None = None
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or not isinstance(record.get("payload"), dict):
            continue
        payload = record["payload"]
        kind = record.get("type")
        if kind == "turn_context" and isinstance(payload.get("model"), str):
            model = payload["model"]
        elif kind == "token_usage_record" and payload.get("thread_id") == own:
            usage = payload.get("usage")
            if isinstance(usage, dict):
                responses[str(payload.get("response_id") or len(responses))] = (model, usage)
        elif kind == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info")
            total = info.get("total_token_usage") if isinstance(info, dict) else None
            if isinstance(total, dict):
                last_total = (model, total)
            limits = payload.get("rate_limits")
            if isinstance(limits, dict) and isinstance(limits.get("plan_type"), str):
                plan = limits["plan_type"]
    counted = list(responses.values()) or ([last_total] if last_total else [])
    totals: dict[str, Tokens] = {}
    for used_model, usage in counted:
        name = used_model or "unknown"
        totals[name] = totals.get(name, Tokens()) + _tokens(usage)
    return totals, plan


def _tokens(usage: dict[str, object]) -> Tokens:
    def count(key: str) -> int:
        value = usage.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    cached = count("cached_input_tokens")
    return Tokens(
        input=max(count("input_tokens") - cached, 0) + count("cache_write_input_tokens"),
        cached=cached,
        output=count("output_tokens"),
    )


def report(facts: RunFacts, home: Path | None = None) -> RunReport | None:
    """The run's thread tree: its root — named, or the earliest unclaimed rollout in its
    directory — and every thread spawned under it."""
    if facts.session:
        root = rollout_for(facts.session, home)
    elif facts.directory:
        root = find_rollout(facts.directory, facts.launched, home, facts.claimed)
    else:
        return None
    if root is None:
        return None
    thread = thread_id(root)
    models, plan = read_thread(root)
    agents = [AgentUsage("main", models, session=thread)]
    spawned = descendants(thread, home)
    for child, parent in spawned or []:
        path = rollout_for(child, home)
        found, _ = read_thread(path) if path is not None else ({}, "")
        agents.append(
            AgentUsage(child, found, parent="main" if parent == thread else parent, session=child)
        )
    account = {"vendor": "openai", **({"plan": plan} if plan else {})}
    return RunReport(session=thread, agents=tuple(agents), account=account, partial=spawned is None)


READ_ONLY = {"sandbox_mode": "read-only", "approval_policy": "never"}
APPROVE_FOR_ME = {
    "sandbox_mode": "workspace-write",
    "approval_policy": "on-request",
    "approvals_reviewer": "auto_review",
}


def headless_command(spec: TurnSpec) -> list[str]:
    settings: dict[str, object] = dict(READ_ONLY)
    if spec.stage is StageKind.EXECUTE:
        roots = [spec.run_dir, *spec.writable]
        settings = {**APPROVE_FOR_ME, "sandbox_workspace_write.writable_roots": roots}
    argv = ["codex", "exec", *(["resume"] if spec.resume else []), "--json"]
    for key, value in settings.items():
        # A JSON string or list is TOML too — unescaped, since TOML refuses the surrogate
        # pairs JSON escapes an astral character into.
        argv += ["-c", f"{key}={json.dumps(value, ensure_ascii=False)}"]
    schema = schema_file(spec)
    if schema is not None:
        argv += ["--output-schema", str(schema)]
    # "--" ends the options, so an answer that reads like a flag ("--help") is still a prompt.
    return [*argv, "--", *([spec.session] if spec.resume else []), spec.prompt]


def read_event(log: TurnLog, event: Mapping[str, object]) -> None:
    kind = event.get("type")
    if kind == "thread.started":
        log.session = str(event.get("thread_id") or log.session)
    elif kind == "item.started":
        item = event.get("item")
        if isinstance(item, dict):
            log.tools.add(str(item.get("id")))
    elif kind == "item.completed":
        log.progressed()
        item = event.get("item")
        if isinstance(item, dict):
            log.tools.discard(str(item.get("id")))
        if isinstance(item, dict) and item.get("type") == "agent_message":
            log.final = str(item.get("text") or "")
            log.typed = typed_message(log.final)
            # Prose only: a schema-valid answer says for itself whether it was denied.
            log.denials = refusals(log.final) if log.typed is None else []
    elif kind == "turn.completed":
        usage = event.get("usage")
        if isinstance(usage, dict):
            log.tokens = _tokens(usage)
    elif kind == "turn.failed":
        error = event.get("error")
        log.error = str(error.get("message", "")) if isinstance(error, dict) else str(error)
        log.error = log.error or "the turn failed"


# Codex in a read-only sandbox does not fail: it says it could not and hands the change back
# as text. A sentence that both refuses an act and names the sandbox as why is a denial; one
# that only mentions the sandbox ("reviewed read-only; no issues") is not.
_REFUSED = re.compile(
    r"\b(?:couldn(?:'|\u2019)?t|could not|can(?:'|\u2019)?t|cannot|was unable to|am unable to)"
    r" (?:\w+ )?(?:edit|write|modify|change|create|commit|apply|run|delete|save)\b",
    re.IGNORECASE,
)
_BECAUSE_SANDBOX = re.compile(
    r"read-only|sandbox|not (?:allowed|permitted)|permission"
    r"|writ(?:e|ing) is (?:not )?(?:enabled|blocked)",
    re.IGNORECASE,
)


def refusals(text: str) -> list[str]:
    """The sentences of a final message that refuse an act for want of permission."""
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [s.strip()[:160] for s in sentences if _REFUSED.search(s) and _BECAUSE_SANDBOX.search(s)]


def read_limits(thread: str, home: Path | None = None) -> tuple[LimitWindow, ...]:
    """The account's windows as the thread's rollout last recorded them; () when there is
    no rollout or it names none."""
    path = rollout_for(thread, home) if thread else None
    try:
        lines = path.read_text(encoding="utf-8").splitlines() if path is not None else []
    except OSError:
        return ()
    for line in reversed(lines):
        if '"rate_limits"' not in line:
            continue
        try:
            payload = json.loads(line).get("payload")
        except (ValueError, AttributeError):
            continue
        limits = payload.get("rate_limits") if isinstance(payload, dict) else None
        windows = tuple(
            found
            for name in ("primary", "secondary")
            if isinstance(limits, dict)
            and isinstance(given := limits.get(name), dict)
            and (found := window(name, given.get("used_percent"), given.get("resets_at"), 100))
        )
        # A limit of another kind ("premium") is recorded with no windows at all, right
        # after the account's own: it says nothing about when the account comes back.
        if windows:
            return windows
    return ()


HEADLESS = Headless(
    command=headless_command,
    read=read_event,
    limits=lambda log: read_limits(log.session),
)


def signed_in(shell: Shell) -> SignedIn:
    """``codex login status``: "Logged in using ChatGPT" on stderr and exit 0, else not."""
    code, said = shell(("login", "status"))
    line = next((line.strip() for line in said.splitlines() if line.strip()), "")
    if code == 0 and line.startswith("Logged in"):
        return SignedIn(ok=True, detail=line[:1].lower() + line[1:])
    return SignedIn(ok=False, detail="not signed in")


HARNESS = AgentHarness(
    id="codex",
    label="Codex",
    command="codex {prompt}",
    open_command="codex",
    resume="codex resume {session}",
    shell_markers=("CODEX_THREAD_ID", "CODEX_SESSION_ID"),
    report=report,
    binary="codex",
    headless=HEADLESS,
    sign_in=SignIn(probe=signed_in, command="codex login"),
)
