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

**The transcript.** Claude Code keeps every session as
``<config dir>/projects/<cwd with every non-alphanumeric as ->/<session id>.jsonl``, one
JSON object per line, and each ``assistant`` line carries the API's ``usage`` for that
message: ``input_tokens``, ``cache_creation_input_tokens``, ``cache_read_input_tokens``
and ``output_tokens``. A message is written more than once — a line per content block,
the same id and the same usage on each — so the reader keeps one usage per message id.
The format is Claude Code's own, documented as internal and free to change between
releases, which is why the reader answers ``None`` for anything it cannot read rather
than raising: the OpenTelemetry metrics are the supported channel, and they need a
collector listening, which is a feature for another day.
"""

import json
import os
import re
from pathlib import Path

from dplanner.domain.agents import AgentHarness, RunFacts, RunReport, Usage

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


def read_transcript(path: Path) -> Usage | None:
    """The tokens a transcript's assistant messages report, one usage per message id;
    None when the file is missing, unreadable, or carries no usage this build reads."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    per_message: dict[str, dict[str, int]] = {}
    for index, line in enumerate(lines):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("type") != "assistant":
            continue
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        counts = {key: _count(usage.get(key)) for key in _KEYS}
        per_message[str(message.get("id") or index)] = counts
    if not per_message:
        return None
    totals = {key: sum(counts[key] for counts in per_message.values()) for key in _KEYS}
    cache_read = totals["cache_read_input_tokens"]
    cache_creation = totals["cache_creation_input_tokens"]
    return Usage(
        input=totals["input_tokens"] + cache_read + cache_creation,
        output=totals["output_tokens"],
        details={
            "uncached": totals["input_tokens"],
            "cache_read": cache_read,
            "cache_creation": cache_creation,
        },
    )


_KEYS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def report(facts: RunFacts, config: Path | None = None) -> RunReport | None:
    """The run's own transcript, found by the session the launcher named and the
    directory the agent worked in."""
    if not facts.session or not facts.directory:
        return None
    usage = read_transcript(transcript_path(facts.session, facts.directory, config))
    return None if usage is None else RunReport(session=facts.session, usage=usage)


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
)
