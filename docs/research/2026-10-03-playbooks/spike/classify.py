"""Classify how a headless agent run ended, from what the CLI actually printed.

Built on the probe fixtures in `probes/out/` (see `probes/run_probes.py`): every rule below
matches an error shape one of the CLIs was seen to produce, not one we guessed. The answer is
one of the five classes in `failures.md` — retry, park, person, abandon — or `ok`, with the
person-facing reason.

    uv run python classify.py            # classify every fixture and check against EXPECTED
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# The fixtures moved into the test suite (S8, 2026-10-07): tests/fixtures/agent_turns/probes/.
OUT = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "agent_turns" / "probes"
RUNAWAY_EVENTS = 200  # this many events with no token progress is a loop, not work


@dataclass(frozen=True)
class Ending:
    cls: str  # ok | retry | park | person | abandon
    kind: str  # login | billing | quota | model | transient | malformed | hang | killed | runaway | unknown
    reason: str


def classify(
    cli: str,
    exit_code: int | None,
    stdout: list[str],
    stderr: list[str],
    timed_out: bool = False,
    signalled: bool = False,
    event_count: int | None = None,
) -> Ending:
    parsed = [_json(line) for line in stdout]
    events = [e for e in parsed if e is not None]
    count = event_count if event_count is not None else len(events)
    if _runaway(events, count):
        return Ending("abandon", "runaway", f"{count} events with no token progress: a retry loop")
    if timed_out:
        return Ending("retry", "hang", "no exit and no progress: killed by the stall detector")
    if signalled or (exit_code is not None and (exit_code < 0 or exit_code == 143)):
        return Ending("retry", "killed", f"killed by a signal (exit {exit_code}); no result was written")
    message, status = _error(cli, events)
    if exit_code == 0 and not message:
        return Ending("ok", "ok", "")
    return _by_message(message, status)


def _by_message(message: str, status: int | None) -> Ending:
    m = message.lower()
    if status in (401, 403) or re.search(
        r"not logged in|invalid api key|failed to authenticate|401 unauthorized"
        r"|403 forbidden|x-api-key|subscription expired|missing bearer",
        m,
    ):
        return Ending("person", "login", f"log in again: {message[:120]}")
    if re.search(r"credit balance|quota exceeded|insufficient_quota|billing", m):
        return Ending("person", "billing", f"billing: {message[:120]}")
    if status == 429 or re.search(r"\b429\b|rate limit|usage limit", m):
        return Ending("park", "quota", f"rate or usage limit; park until it resets: {message[:120]}")
    if status == 404 or re.search(r"model.*(does not exist|not found|issue with the selected)|404 not found|model:", m):
        return Ending("person", "model", f"the role's model is not available: {message[:120]}")
    if re.search(r"malformed|empty .*response|stream disconnected|stream closed", m):
        return Ending("retry", "malformed", f"the API answered with something unreadable: {message[:120]}")
    if "unknownerror" in m or "unexpected server error" in m:
        # opencode says this, and only this, when it has no credentials at all
        return Ending("person", "unknown", "the CLI failed before any model call; check its login and config")
    if (status is not None and status >= 500) or re.search(r"\b5\d\d\b|overloaded|high demand|server error", m):
        return Ending("retry", "transient", f"the provider is failing; retry later: {message[:120]}")
    return Ending("person", "unknown", f"unrecognised failure: {message[:120] or 'no message'}")


def _error(cli: str, events: list[dict[str, object]]) -> tuple[str, int | None]:
    """The CLI's own last word on why it stopped, and the HTTP status if it gave one."""
    if cli == "claude":
        for e in reversed(events):
            if e.get("type") == "result" and e.get("is_error"):
                # note: subtype is "success" even here; is_error is what says it failed
                status = e.get("api_error_status")
                return str(e.get("result", "")), status if isinstance(status, int) else None
        return "", None
    if cli == "codex":
        for e in reversed(events):
            if e.get("type") == "turn.failed":
                err = e.get("error")
                return (str(err.get("message", "")) if isinstance(err, dict) else str(err)), None
        return "", None
    if cli == "opencode":
        for e in reversed(events):
            if e.get("type") == "error":
                err = e.get("error")
                if isinstance(err, dict):
                    data = err.get("data")
                    if isinstance(data, dict):
                        status = data.get("statusCode")
                        return (
                            f"{err.get('name', '')}: {data.get('message', '')}",
                            status if isinstance(status, int) else None,
                        )
        return "", None
    raise ValueError(cli)


def _runaway(events: list[dict[str, object]], count: int) -> bool:
    """Many step events and not one token: the CLI is retrying in a loop and will never stop."""
    steps = [e for e in events if e.get("type") == "step_finish"]
    return count >= RUNAWAY_EVENTS and bool(steps) and all(_tokens(e) == 0 for e in steps)


def _tokens(event: dict[str, object]) -> int:
    part = event.get("part")
    tokens = part.get("tokens") if isinstance(part, dict) else None
    if not isinstance(tokens, dict):
        return 0
    return int(tokens.get("input", 0) or 0) + int(tokens.get("output", 0) or 0)


def _json(line: str) -> dict[str, object] | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


EXPECTED = {
    "noauth": "person/login",
    "401": "person/login",
    "403": "person/login",
    "credit": "person/billing",
    "429": "park/quota",
    "529": "retry/transient",
    "500": "retry/transient",
    "404model": "person/model",
    "garbage": "retry/malformed",
    "hang": "retry/hang",
    "sigterm": "retry/killed",
    "sigkill": "retry/killed",
}
# where a CLI's behaviour differs from the rule above, the observed answer is the expectation
EXCEPTIONS = {
    "opencode-noauth": "person/unknown",  # opencode names no reason at all
    "opencode-garbage": "abandon/runaway",  # loops forever instead of failing
}


def classify_fixture(path: Path) -> tuple[dict[str, object], Ending]:
    record = json.loads(path.read_text())
    stdout = [*record["stdout_head"], *record["stdout_tail"]]
    ending = classify(
        str(record["cli"]),
        record["exit"],
        stdout,
        record["stderr_tail"],
        timed_out=record["timed_out_after_s"] is not None,
        signalled=record["signal_sent"] is not None,
        event_count=int(record["stdout_lines"]),
    )
    return record, ending


def main() -> None:
    wrong = 0
    for path in sorted(OUT.glob("*.json")):
        record, ending = classify_fixture(path)
        got = f"{ending.cls}/{ending.kind}"
        want = EXCEPTIONS.get(str(record["probe"]), EXPECTED[str(record["mode"])])
        mark = "ok " if got == want else "WRONG"
        wrong += got != want
        print(f"{mark} {record['probe']:20} {got:18} {ending.reason[:90]}")
    sys.exit(1 if wrong else 0)


if __name__ == "__main__":
    main()
