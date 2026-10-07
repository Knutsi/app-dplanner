"""What a headless turn is to DPlanner: the half of the harness contract the run supervisor
drives (``docs/architecture/playbooks.md``'s *Each stage is one headless turn per harness*).

**A turn is one process that exits.** DPlanner never waits on a process for a person: a
stage runs as one invocation of the CLI with nothing on its stdin, and whatever needs
somebody — a question, a denied permission, an exhausted account — ends the turn and parks
the run, which the answer resumes in the same session. So a harness has to say three things,
and :class:`Headless` holds them:

- **the argv for a turn** (:class:`TurnSpec`): the stage's mode, a fresh session or a resumed
  one, the directories it may write, and the typed final message where the CLI offers one.
  An argv rather than a command template, because the supervisor spawns the process itself —
  no shell, no terminal, nothing to quote, and the same on Windows;
- **how to read its JSON events** into a :class:`TurnLog` — the session id, the turn's
  tokens, the account's limit telemetry, the final text and its typed form, the CLI's own
  error and any denied permission. The log is fed a line at a time, so the supervisor reads
  it live while it tees the stream, and a test reads a recorded stream the same way;
- **how the turn ended** (:meth:`Headless.classify`) in S3's words, ``done``, ``asked``,
  ``denied``, ``limit`` or ``failed`` — never from the exit alone, because a headless run
  that exits 0 can hide an open question (Claude asks in prose), a denied edit (Claude's
  ``permission_denials`` under ``success``; opencode's "auto-rejecting" on stderr) or nothing
  done at all. ``stopped`` is a person's or the supervisor's word and never the classifier's.

**Classification is one function; a harness only reads.** Each CLI's quirks are in its
reader, which normalises them into the log, and in two small hooks — where its limit
telemetry lives, and the denials it prints to stderr rather than its stream — so the order
of the rules below is written once. The rules come from what the CLIs were seen to do
(``docs/research/2026-10-03-playbooks/`` probes, ``docs/research/2026-10-07-headless-agents/``),
and the recorded streams under ``tests/fixtures/agent_turns/`` are what holds them.

**A typed final message beats prose.** Where the CLI can be held to a JSON schema (Claude
``--json-schema``, Codex ``--output-schema``) an execute turn answers
:data:`TURN_SCHEMA` and a review :data:`VERDICT_SCHEMA` (FORMAT.md's verdict), so whether it
asked is read, not guessed. A question found in prose is the fallback for a turn without
one: opencode's, and a plan, whose final text *is* the plan. The schemas are strict — every
property required, nothing extra — because Codex refuses any other kind.
"""

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from dplanner.domain.agents import Tokens


class StageKind(StrEnum):
    """The agent stages of a playbook — the ones a harness runs a turn for."""

    PLAN = "plan"
    EXECUTE = "execute"
    REVIEW = "review"


class TurnEnd(StrEnum):
    """How a turn ended: FORMAT.md's ``end``."""

    DONE = "done"
    ASKED = "asked"
    DENIED = "denied"
    LIMIT = "limit"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True)
class LimitWindow:
    """One of the account's usage windows, as the vendor last reported it."""

    name: str  # The vendor's: "five_hour" / "seven_day" (Claude), "primary" / "secondary" (Codex).
    used: float  # 0 to 1.
    resets: datetime | None


@dataclass(frozen=True)
class TurnSpec:
    """What one turn is asked to do, for a harness to spell as an argv."""

    stage: StageKind
    prompt: str
    run_dir: str  # The run's directory: the briefing, the schema file, the stream.
    # What an execute turn may write beyond the checkout it runs in: the plan repository.
    writable: tuple[str, ...] = ()
    # A fresh turn names its session with it where the CLI lets it (Claude); a resumed turn
    # continues it.
    session: str = ""
    resume: bool = False

    def resumed(self, session: str, prompt: str) -> "TurnSpec":
        """The next turn of the same stage: the session continued with one prompt — an
        answer, "continue", or "your limit reset, continue"."""
        return replace(self, session=session, prompt=prompt, resume=True)


@dataclass
class TurnLog:
    """What a turn's stream has said so far. Filled by the harness's reader."""

    session: str = ""
    tokens: Tokens = field(default_factory=Tokens)
    limits: tuple[LimitWindow, ...] = ()
    final: str = ""  # The last message the agent wrote.
    typed: Mapping[str, object] | None = None  # The final message, typed, where it is.
    error: str = ""  # The CLI's own last word on why it stopped, "" when it did not fail.
    status: int | None = None  # The HTTP status it gave with the error.
    denials: list[str] = field(default_factory=list)
    events: int = 0
    # Events since the agent last produced anything: what the supervisor's runaway detector
    # reads (a CLI retrying in a loop emits events and no tokens, forever).
    idle: int = 0

    def progressed(self) -> None:
        self.idle = 0


Reader = Callable[[TurnLog, Mapping[str, object]], None]


def _streamed_limits(log: TurnLog) -> tuple[LimitWindow, ...]:
    return log.limits


def _no_denials(_stderr: str) -> list[str]:
    return []


@dataclass(frozen=True)
class Ending:
    """How a turn ended, and what a person would need to know about it."""

    end: TurnEnd
    # For ``failed``: login, billing, model, transient, malformed, killed or unknown — the
    # 10-03 failure kinds — or abandoned-wait. For ``asked``: typed or prose. For ``denied``:
    # typed, or "".
    why: str = ""
    reason: str = ""
    resets: datetime | None = None  # For ``limit``, when it is known.
    question: str = ""  # For ``asked``.

    @property
    def needs_person(self) -> bool:
        """A failure no retry mends: a dead login, an empty balance, a model that is gone,
        or one nobody recognised."""
        return self.end is TurnEnd.FAILED and self.why in {"login", "billing", "model", "unknown"}


# What a process killed by SIGTERM or SIGKILL exits with when a shell reports it.
KILLED = (128 + 15, 128 + 9)


@dataclass(frozen=True)
class Headless:
    """How a harness runs one unattended turn, reads it and says how it ended."""

    command: Callable[[TurnSpec], list[str]]
    read: Reader
    # The account's last-known limits after a turn: its stream's, unless the CLI keeps them
    # elsewhere (Codex: in the rollout file, never in ``--json``).
    limits: Callable[[TurnLog], tuple[LimitWindow, ...]] = _streamed_limits
    # Denials the CLI prints to stderr rather than its stream (opencode).
    stderr_denials: Callable[[str], list[str]] = _no_denials

    def feed(self, log: TurnLog, line: str) -> None:
        """One line of the stream; anything that is not a JSON object is not an event."""
        try:
            event = json.loads(line)
        except ValueError:
            return
        if isinstance(event, dict):
            log.events += 1
            log.idle += 1
            self.read(log, event)

    def read_lines(self, lines: Iterable[str]) -> TurnLog:
        log = TurnLog()
        for line in lines:
            self.feed(log, line)
        return log

    def classify(self, exit_code: int | None, log: TurnLog, stderr: str = "") -> Ending:
        """How the turn ended, from its exit, its stream and its stderr — in this order,
        because each rule is only true once the ones above it are not."""
        if exit_code is None or exit_code < 0 or exit_code in KILLED:
            return Ending(TurnEnd.FAILED, "killed", f"killed by a signal (exit {exit_code})")
        if log.error:
            return ending_for_error(log.error, log.status, self.limits(log))
        if exit_code != 0:
            said = last_line(stderr)
            return Ending(TurnEnd.FAILED, "unknown", f"exit {exit_code}: {said or 'no message'}")
        denials = [*log.denials, *self.stderr_denials(stderr)]
        if denials:
            return Ending(TurnEnd.DENIED, reason="; ".join(denials))
        typed = log.typed
        if typed is not None:
            summary = _text(typed.get("summary"))
            if typed.get("outcome") == "asked":
                question = _text(typed.get("question")) or summary
                return Ending(TurnEnd.ASKED, "typed", question=question)
            if typed.get("outcome") == "denied":
                return Ending(TurnEnd.DENIED, "typed", reason=summary)
        said = f"{log.final} {_text(typed.get('summary')) if typed else ''}"
        if waits_on_itself(said):
            return Ending(TurnEnd.FAILED, "abandoned-wait", last_line(log.final) or said[:160])
        if typed is not None:
            return Ending(TurnEnd.DONE)
        question = prose_question(log.final)
        if question:
            return Ending(TurnEnd.ASKED, "prose", question=question)
        return Ending(TurnEnd.DONE)


def ending_for_error(
    message: str, status: int | None, limits: Sequence[LimitWindow] = ()
) -> Ending:
    """What the CLI's own error means — the 10-03 probe classes, read off its words and the
    HTTP status, since every CLI words them differently."""
    m = message.lower()
    said = message[:160]
    if status in (401, 403) or re.search(
        r"not logged in|invalid api key|failed to authenticate|401 unauthorized"
        r"|403 forbidden|x-api-key|subscription expired|missing bearer",
        m,
    ):
        return Ending(TurnEnd.FAILED, "login", f"log in again: {said}")
    if re.search(r"credit balance|quota exceeded|insufficient_quota|billing", m):
        return Ending(TurnEnd.FAILED, "billing", f"billing: {said}")
    if status == 429 or re.search(r"\b429\b|rate limit|usage limit", m):
        return Ending(TurnEnd.LIMIT, reason=said, resets=resets(limits))
    if status == 404 or re.search(
        r"model.*(does not exist|not found|issue with the selected)|404 not found|model:", m
    ):
        return Ending(TurnEnd.FAILED, "model", f"the model is not available: {said}")
    if re.search(r"malformed|empty .*response|stream disconnected|stream closed", m):
        return Ending(
            TurnEnd.FAILED, "malformed", f"the API answered with something unreadable: {said}"
        )
    if "unknownerror" in m or "unexpected server error" in m:
        # opencode says this, and only this, when it has no credentials at all.
        return Ending(
            TurnEnd.FAILED,
            "unknown",
            "the CLI failed before any model call; check its login and config",
        )
    if (status is not None and status >= 500) or re.search(
        r"\b5\d\d\b|overloaded|high demand|server error", m
    ):
        return Ending(TurnEnd.FAILED, "transient", f"the provider is failing; retry later: {said}")
    return Ending(TurnEnd.FAILED, "unknown", f"unrecognised failure: {said or 'no message'}")


def resets(limits: Sequence[LimitWindow]) -> datetime | None:
    """When an account that hit its limit comes back: when its fullest window resets. Not
    "the window at 100 %" — the real Codex limits of 2026-10-04 struck at 98 % and 99 %, and
    the fullest window's reset was, to the minute, the "try again at" of the message."""
    known = [w for w in limits if w.resets is not None]
    return max(known, key=lambda w: w.used).resets if known else None


# How far up from the end of a final message a question still counts as how it ended.
PROSE_TAIL = 5
_TRAILING_ASIDE = re.compile(r"\s*\([^()]*\)\s*$")


def prose_question(text: str) -> str:
    """The question a final message ends on, or "". Headless Claude cannot use its question
    tool and asks in prose instead — and rarely as the very last line: it bolds the question
    and adds "Once you let me know, I'll…" — so any of the last few lines ending in ``?``,
    markdown and a trailing ``(yes/no)`` aside, is the question."""
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    for line in reversed(lines[-PROSE_TAIL:]):
        bare = _TRAILING_ASIDE.sub("", line).strip("*_`># -").strip()
        if bare.endswith("?"):
            return bare
    return ""


_WAITS_ON_ITSELF = re.compile(  # \u2019: the typographic apostrophe agents write
    r"\bI(?:'|\u2019)?ll pick (?:it |this |things )?(?:up|back up) when\b"
    r"|\b(?:I(?:'|\u2019)?ll be|I will be) notified\b"
    r"|\bwait(?:ing)? (?:on|for) (?:the |my |its |a )?(?:full |test )?"
    r"(?:suite|tests?|background|build|run|job|task|workers?|command|process)\b",
    re.IGNORECASE,
)


def waits_on_itself(text: str) -> bool:
    """Whether a final message ends the turn to wait on the agent's own background work — a
    suite, a build, a task it started. Headless, the process exits with the turn and the work
    dies with it, and nobody wakes the agent: the turn was abandoned, not finished, and
    "continue" resumes it. Waiting on a *person* is not this — that is a question."""
    return bool(_WAITS_ON_ITSELF.search(text))


def typed_message(text: str) -> Mapping[str, object] | None:
    """A final message that is the typed one: a JSON object with an ``outcome``, alone or in
    a fenced block; None for prose."""
    body = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", body, re.DOTALL)
    try:
        value = json.loads(fenced.group(1) if fenced else body)
    except ValueError:
        return None
    return value if isinstance(value, dict) and "outcome" in value else None


def last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1][:160] if lines else ""


def stamp(epoch: object) -> datetime | None:
    """An epoch-seconds field as a time; None for anything else."""
    if isinstance(epoch, (int, float)) and not isinstance(epoch, bool):
        return datetime.fromtimestamp(epoch, UTC)
    return None


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


TURN_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["outcome", "summary", "question"],
    "properties": {
        "outcome": {"type": "string", "enum": ["done", "asked", "denied"]},
        "summary": {"type": "string"},
        "question": {"type": "string"},  # "" unless the outcome is asked.
    },
}

VERDICT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["outcome", "summary", "findings"],
    "properties": {
        "outcome": {"type": "string", "enum": ["pass", "changes"]},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["severity", "file", "line", "text", "evidence"],
                "properties": {
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "text": {"type": "string"},
                    "evidence": {"type": "string"},
                },
            },
        },
    },
}


def schema_for(stage: StageKind) -> Mapping[str, object] | None:
    """The final message a stage answers with; None for a plan, whose answer is its text."""
    return {StageKind.EXECUTE: TURN_SCHEMA, StageKind.REVIEW: VERDICT_SCHEMA}.get(stage)


def schema_text(stage: StageKind) -> str:
    schema = schema_for(stage)
    return json.dumps(schema, separators=(",", ":")) if schema is not None else ""


def schema_file(spec: TurnSpec) -> Path | None:
    """Where a CLI that takes its schema as a file (Codex) finds it, in the run directory."""
    return Path(spec.run_dir) / f"{spec.stage}.schema.json" if schema_for(spec.stage) else None


def write_schema(spec: TurnSpec) -> Path | None:
    """Writes the stage's schema file before the turn starts; the supervisor's job."""
    path = schema_file(spec)
    if path is not None:
        path.write_text(schema_text(spec.stage) + "\n", encoding="utf-8")
    return path
