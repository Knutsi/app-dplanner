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
import math
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
    # The CLI's own machine-readable reason, where it gives one (Claude's ``rate_limit``):
    # read before any wording, which changes between plans and releases.
    code: str = ""
    denials: list[str] = field(default_factory=list)
    events: int = 0
    # Events since the agent last produced anything: what the supervisor's runaway detector
    # reads (a CLI retrying in a loop emits events and no tokens, forever).
    idle: int = 0
    # The tool calls started and not yet finished, by the CLI's id for each: while one runs,
    # silence is a test suite at work, not a hang, and the supervisor's stall clock waits.
    tools: set[str] = field(default_factory=set)
    model: str = ""  # The model the turn ran on, where the stream names it.

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


# Ten minutes covers a CLI's own retries of a failing API (Claude's ran 4½ minutes, silent).
STALL_SECONDS = 600.0

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
    # How long the stream may be silent, no tool running, before the turn is a hang: none of
    # the three CLIs times out a hung API on its own (the 10-03 probes sat 330 s and more).
    stall: float = STALL_SECONDS

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

    def classify(
        self, exit_code: int | None, log: TurnLog, stderr: str = "", question: str | None = None
    ) -> Ending:
        """How the turn ended, from its exit, its stream, its stderr and ``question`` — the
        question the agent recorded through ``dplanner question ask`` during the turn, which the
        supervisor reads from the question store, since an agent that asked through the door
        then ends its turn in plain words. In this order, because each rule is only true once
        the ones above it are not."""
        if exit_code is None or exit_code < 0 or exit_code in KILLED:
            return Ending(TurnEnd.FAILED, "killed", f"killed by a signal (exit {exit_code})")
        if log.error or log.code:
            return ending_for_error(log.error, log.status, self.limits(log), log.code)
        if exit_code != 0:
            said = last_line(stderr)
            return Ending(TurnEnd.FAILED, "unknown", f"exit {exit_code}: {said or 'no message'}")
        if question is not None:
            return Ending(TurnEnd.ASKED, "record", question=question)
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
            # A schema-valid answer is the agent's own word on how it ended: no prose
            # heuristic second-guesses it.
            return Ending(TurnEnd.DONE)
        # Untyped prose only, and when unsure it parks rather than says done: a false park
        # costs a card or one "continue" turn, a false done loses the work without a word.
        if waits_on_itself(log.final):
            return Ending(TurnEnd.FAILED, "abandoned-wait", last_line(log.final))
        question = prose_question(log.final)
        if question:
            return Ending(TurnEnd.ASKED, "prose", question=question)
        return Ending(TurnEnd.DONE)


# The machine-readable reasons a CLI gives with an error (Claude's assistant ``error``), and
# the ending each means — read before the wording, which differs between a subscription's
# "You've hit your limit" and an API key's "rate limit".
ERROR_CODES = {
    "rate_limit": "limit",
    "authentication_failed": "login",
    "billing_error": "billing",
    "server_error": "transient",
    "model_not_found": "model",
}


def ending_for_error(
    message: str, status: int | None, limits: Sequence[LimitWindow] = (), code: str = ""
) -> Ending:
    """What the CLI's own error means — its code where it gives one, else the 10-03 probe
    classes read off its words and the HTTP status, since every CLI words them differently."""
    m = message.lower()
    said = message[:160] or code
    kind = ERROR_CODES.get(code)
    if kind == "limit":
        return Ending(TurnEnd.LIMIT, reason=said, resets=resets(limits))
    if kind is not None:
        return Ending(TurnEnd.FAILED, kind, said)
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


# A final paragraph that asks for an answer without being the question itself: "Once you let
# me know, I'll edit calc.py" after the bold question, which is how headless Claude asks.
_REQUEST = re.compile(
    r"\blet me know\b|\bplease (?:answer|confirm|choose|pick|reply|respond|decide)\b"
    r"|\bonce you (?:respond|reply|confirm|decide|answer|choose|let me know)\b"
    r"|\b(?:tell me|which would you|which do you|do you want me to|should I)\b",
    re.IGNORECASE,
)
_TRAILING_ASIDE = re.compile(r"\s*\([^()]*\)\s*$")
# Quoted words are somebody else's: an example, a log line, a message being described.
_QUOTED = re.compile(r"`[^`]*`|\"[^\"]*\"|\u201c[^\u201d]*\u201d")


def paragraphs(text: str) -> list[list[str]]:
    """A message's paragraphs, each its non-empty lines, stripped."""
    blocks = re.split(r"\n\s*\n", text.strip())
    found = [[line.strip() for line in block.splitlines() if line.strip()] for block in blocks]
    return [block for block in found if block]


def _bare(line: str) -> str:
    return _TRAILING_ASIDE.sub("", line).strip("*_`># -").strip()


def prose_question(text: str) -> str:
    """The question a final message leaves open, or "". Headless Claude cannot use its
    question tool and asks in prose — and the question must still be open at the very end:
    the final paragraph ends on it, or the final paragraph asks for an answer ("Once you let
    me know, I'll…") and the question is the last one just above. A question answered by the
    lines after it — an FAQ heading, "Why did it fail? The dependency was missing." — is not
    one, and neither is an offer with no question to answer ("Let me know if you'd like
    changes"). A known limit, accepted as the fallback's: a question quoted at the very end
    ("> Should add() accept strings?") still reads as asked — parking is the safe mistake."""
    blocks = paragraphs(text)
    if not blocks:
        return ""
    final = blocks[-1]
    if _bare(final[-1]).endswith("?"):
        return _bare(final[-1])
    if not _REQUEST.search(" ".join(final)):
        return ""
    for block in reversed(blocks[-3:]):
        for line in reversed(block):
            if _bare(line).endswith("?"):
                return _bare(line)
    return ""


_WAITS_ON_ITSELF = re.compile(  # \u2019: the typographic apostrophe agents write
    r"\bI(?:'|\u2019)?ll (?:pick (?:it |this |things )?(?:back )?up|continue|carry on) when\b"
    r"|\bI(?:'|\u2019)?ll be notified\b|\bI will be notified\b"
    r"|(?:^|[.;:!]\s+|\bI(?:'|\u2019)?m |\bI am )(?:now |still )?waiting (?:on|for) "
    r"(?:the |my |its |a )?(?:full |test )?"
    r"(?:suite|tests?|background|build|run|job|task|workers?|command|process)\b",
    re.IGNORECASE | re.MULTILINE,
)


def waits_on_itself(text: str) -> bool:
    """Whether a message ends its turn committed to wait on the agent's own background work —
    a suite, a build, a task it started — said in its final paragraph, in its own words.
    Headless, the process exits with the turn and the work dies with it, and nobody wakes the
    agent: the turn was abandoned, not finished, and "continue" resumes it. A finished fix
    that mentions a wait ("fixed the worker waiting for the job") is not this, nor a quoted
    example, nor waiting on a *person* — that is a question. A known limit, accepted as the
    fallback's: "Waiting on the build was the bug; fixed now." still reads as a wait — one
    cheap "continue" is the safe mistake."""
    blocks = paragraphs(text)
    return bool(blocks) and bool(_WAITS_ON_ITSELF.search(_QUOTED.sub("", "\n".join(blocks[-1]))))


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


def number(value: object) -> float | None:
    """A field that should be a finite number, or None — a reader never raises on a vendor's
    odd value."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def stamp(epoch: object) -> datetime | None:
    """An epoch-seconds field as a time; None for anything else, or out of range."""
    seconds = number(epoch)
    try:
        return datetime.fromtimestamp(seconds, UTC) if seconds is not None else None
    except (OverflowError, OSError, ValueError):
        return None


def window(name: str, used: object, resets_at: object, scale: float = 1) -> LimitWindow | None:
    """One usage window from a vendor's fields — ``used`` in its own scale (Claude a fraction,
    Codex a percentage) — or None when the share is not a number."""
    share = number(used)
    return LimitWindow(name, share / scale, stamp(resets_at)) if share is not None else None


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
