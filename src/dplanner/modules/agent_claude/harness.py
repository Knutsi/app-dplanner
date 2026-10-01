"""Claude Code as an agent harness: how it is launched, resumed, kept top-level, and read.

**The command.** An interactive session in plan mode, seeded with the opening line. The
run directory is handed over as an additional working directory (``--add-dir``) so the
briefing is read without a permission prompt — the flag takes a *list*, so it sits before
another option and never before ``{prompt}``, which it would swallow — and the session is
named up front (``--session-id``, a UUID the launcher mints), which is what makes
``claude --resume`` work afterwards.

**Opening it bare.** ``claude`` on its own: an interactive session in the default
permission mode with nothing said to it, which is what *Open Agent in Code* opens — the
briefed command's flags are all about a briefing it does not have, and its plan mode is
the one thing that launch must not bring.

**The shell markers.** What Claude Code sets in every shell it runs (``CLAUDECODE``, the
parent's session id, the child-session flag that turns transcript persistence off, its
pid, the effort, the agent flag) and what it scrubs itself before a session that must
stand on its own (its exec path, the trace id) — read off the 2.1 binary, not guessed —
plus whatever names a session, a parent, a child or the messaging bridge under the same
prefix: a 2.1.258 shell also carries ``CLAUDE_CODE_MESSAGING_SOCKET`` and ``_TOKEN``. Not
the whole prefix: ``CLAUDE_CONFIG_DIR`` and ``CLAUDE_CODE_USE_BEDROCK`` are the person's
configuration, and an agent launched without them cannot sign in. A nested ``claude``
under these markers is a *child* session — no transcript of its own, ended when the
parent's turn ends — which is how one stray window once took four agents down.

**The transcript tree.** Claude Code keeps every session as
``<config dir>/projects/<cwd with every non-alphanumeric as ->/<session id>.jsonl``, one
JSON object per line, and every subagent the session spawned beside it as
``<session id>/subagents/agent-<id>.jsonl`` with a ``.meta.json`` naming its kind. Each
``assistant`` line carries the API's ``usage`` for that request — ``input_tokens``,
``cache_creation_input_tokens``, ``cache_read_input_tokens``, ``output_tokens`` — and its
``model``. Three rules make the sum match Claude Code's own accounting, which it did to
the token on 2026-10-01 (``docs/research/2026-10-01-agent-token-tracking.md``):

- **One request, many lines.** A response is written a line per content block, all with
  the same message id and request id; a request is counted once, keyed on the pair.
- **The largest count wins.** In a subagent's file the first line of a request carries a
  placeholder output count and the last the real one; taking the first lost 90 to 99% of a
  subagent's output. Every field is the maximum over the request's lines.
- **A request belongs to the first file that has it.** A forked subagent's file begins
  with a copy of its parent's last request; counting it twice is the double count.

The session is found by its id wherever its project folder is, so neither a symlinked
working directory nor a deleted run directory hides it. The format is Claude Code's own,
documented as internal and free to change between releases, which is why the reader
answers ``None`` for anything it cannot read rather than raising.

**The account** is read from ``.claude.json``'s ``oauthAccount``: the organisation type
(``claude_max``) and the opaque account id, and nothing else in that file.
"""

import json
import os
import re
from pathlib import Path

from dplanner.domain.agents import AgentHarness, AgentUsage, RunFacts, RunReport, Tokens

SESSION_MARKERS = (
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_PID",
    "CLAUDE_EFFORT",
    "CLAUDE_CODE_EXECPATH",
    "AI_AGENT",
    "TRACEPARENT",
)
SESSION_MARKER_PREFIX = "CLAUDE_CODE_"
SESSION_MARKER_WORDS = ("SESSION", "PARENT", "CHILD", "MESSAGING")


def is_session_marker(name: str) -> bool:
    return name.startswith(SESSION_MARKER_PREFIX) and any(
        word in name for word in SESSION_MARKER_WORDS
    )


def config_dir(env: dict[str, str] | None = None) -> Path:
    """Where Claude Code keeps its state: ``$CLAUDE_CONFIG_DIR``, else ``~/.claude``."""
    environ = os.environ if env is None else env
    return Path(environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def transcript_path(session: str, directory: str, config: Path | None = None) -> Path:
    """The session's transcript, under the project directory named for the cwd."""
    project = re.sub(r"[^A-Za-z0-9]", "-", str(Path(directory)))
    return (config or config_dir()) / "projects" / project / f"{session}.jsonl"


def find_transcript(session: str, directory: str, config: Path | None = None) -> Path | None:
    """The session's main transcript: under the folder its directory names, else wherever
    a folder holds it — the folder is Claude Code's spelling of the path, not ours."""
    base = config or config_dir()
    if directory:
        named = transcript_path(session, directory, base)
        if named.is_file():
            return named
    return next(iter(sorted(base.glob(f"projects/*/{session}.jsonl"))), None)


def read_session(main: Path) -> tuple[AgentUsage, ...] | None:
    """The session's tree — the main agent and every subagent — each per model; None
    when the main transcript is missing or carries no usage this build reads."""
    seen: set[str] = set()
    models = _read_transcript(main, seen)
    if not models:
        return None
    agents = [AgentUsage("main", models, session=main.stem)]
    for path in sorted((main.parent / main.stem / "subagents").glob("agent-*.jsonl")):
        found = _read_transcript(path, seen)
        if found:
            agent_id = path.stem.removeprefix("agent-")
            agents.append(AgentUsage(agent_id, found, parent="main", kind=_kind(path)))
    return tuple(agents)


def _read_transcript(path: Path, seen: set[str]) -> dict[str, Tokens]:
    """A file's requests per model, the max of each count over a request's lines, leaving
    out requests an earlier file already counted (and adding this file's to ``seen``)."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    requests: dict[str, tuple[str, dict[str, int]]] = {}
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("type") != "assistant":
            continue
        message = record.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
            continue
        model = str(message.get("model") or "")
        if not model or model == "<synthetic>":
            continue
        key = f"{message.get('id')}|{record.get('requestId')}"
        if key in seen:
            continue
        counts = {name: _count(message["usage"].get(name)) for name in _KEYS}
        if key in requests:
            kept = requests[key][1]
            counts = {name: max(kept[name], counts[name]) for name in _KEYS}
        requests[key] = (_model_name(model), counts)
    seen.update(requests)
    totals: dict[str, Tokens] = {}
    for model, counts in requests.values():
        totals[model] = totals.get(model, Tokens()) + Tokens(
            input=counts["input_tokens"] + counts["cache_creation_input_tokens"],
            cached=counts["cache_read_input_tokens"],
            output=counts["output_tokens"],
        )
    return totals


_KEYS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)


def _model_name(model: str) -> str:
    """The model without the context-window suffix a 1M variant is logged with."""
    return model.split("[", 1)[0]


def _kind(subagent: Path) -> str:
    try:
        meta = json.loads(subagent.with_suffix(".meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    kind = meta.get("agentType") if isinstance(meta, dict) else None
    return kind if isinstance(kind, str) else ""


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def account_file(env: dict[str, str] | None = None) -> Path:
    """Where Claude Code keeps who is signed in: beside a chosen config directory, else in
    the home directory."""
    environ = os.environ if env is None else env
    chosen = environ.get("CLAUDE_CONFIG_DIR")
    return Path(chosen) / ".claude.json" if chosen else Path.home() / ".claude.json"


def read_account(path: Path | None = None) -> dict[str, str]:
    """The signed-in account in words safe to commit: the vendor, the plan, an opaque id."""
    try:
        data = json.loads((path or account_file()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    account = data.get("oauthAccount") if isinstance(data, dict) else None
    if not isinstance(account, dict):
        return {}
    words = {"vendor": "anthropic"}
    for key, field_name in (("plan", "organizationType"), ("id", "accountUuid")):
        value = account.get(field_name)
        if isinstance(value, str) and value:
            words[key] = value
    return words


def report(
    facts: RunFacts, config: Path | None = None, account: Path | None = None
) -> RunReport | None:
    """The run's session tree, found by the session the launcher named."""
    if not facts.session:
        return None
    main = find_transcript(facts.session, facts.directory, config)
    if main is None:
        return None
    agents = read_session(main)
    if agents is None:
        return None
    return RunReport(session=facts.session, agents=agents, account=read_account(account))


HARNESS = AgentHarness(
    id="claude",
    label="Claude Code",
    command="claude --add-dir {run_dir} --permission-mode plan --session-id {session} {prompt}",
    open_command="claude",
    resume="claude --resume {session}",
    superseded=(
        "claude --permission-mode plan --session-id {session} {prompt}",
        "claude --permission-mode plan {prompt}",
        "claude --permission-mode plan",
    ),
    shell_markers=SESSION_MARKERS,
    is_marker=is_session_marker,
    report=report,
    binary="claude",
    plan_mode="--permission-mode plan",
)
