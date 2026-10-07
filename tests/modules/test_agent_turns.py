"""Each harness's headless half against what its CLI really printed: the argv per stage, the
stream readers, and how every recorded turn ended. Fixtures only — nothing here runs a CLI.

``tests/fixtures/agent_turns/probes/`` are the 2026-10-03 fake-API probes
(``docs/research/2026-10-03-playbooks/spike/probes/``); the files beside them are the
2026-10-07 headless experiments and S8's two typed-output recordings, scrubbed, each naming
its ``source``."""

import json
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dplanner.domain.agents import harness_by_id
from dplanner.domain.headless import Headless, StageKind, TurnEnd, TurnLog, TurnSpec
from dplanner.modules import agent_harnesses
from dplanner.modules.agent_codex import harness as codex

FIXTURES = Path(__file__).parent.parent / "fixtures" / "agent_turns"
HARNESSES = agent_harnesses()


def headless(cli: str) -> Headless:
    harness = harness_by_id(HARNESSES, cli)
    assert harness is not None and harness.headless is not None
    return harness.headless


def replay(path: Path) -> tuple[Headless, TurnLog, dict[str, object]]:
    record = json.loads(path.read_text(encoding="utf-8"))
    reader = headless(str(record["cli"]))
    return reader, reader.read_lines([*record["stdout_head"], *record["stdout_tail"]]), record


def ended(path: Path) -> tuple[str, str]:
    reader, log, record = replay(path)
    got = reader.classify(record["exit"], log, "\n".join(record["stderr_tail"]))  # type: ignore[arg-type]
    return got.end, got.why


# -- every harness runs headless -------------------------------------------------------------


def test_every_harness_has_a_headless_half_and_says_so():
    for harness in HARNESSES:
        assert harness.runs_headless and "runs headless" in harness.capabilities()


# -- how each recorded turn ended ------------------------------------------------------------

# The probe classes by fake-API mode. A hang and a runaway are the supervisor's to detect and
# kill; what the classifier is then handed is a killed process.
BY_MODE = {
    "noauth": ("failed", "login"),
    "401": ("failed", "login"),
    "403": ("failed", "login"),
    "credit": ("failed", "billing"),
    "429": ("limit", ""),
    "529": ("failed", "transient"),
    "500": ("failed", "transient"),
    "404model": ("failed", "model"),
    "garbage": ("failed", "malformed"),
    "hang": ("failed", "killed"),
    "sigterm": ("failed", "killed"),
    "sigkill": ("failed", "killed"),
}
PROBE_EXCEPTIONS = {
    "opencode-noauth": ("failed", "unknown"),  # opencode names no reason at all
    "opencode-garbage": ("failed", "killed"),  # loops instead of failing, until killed
}
PROBES = sorted((FIXTURES / "probes").glob("*.json"))


@pytest.mark.parametrize("path", PROBES, ids=[p.stem for p in PROBES])
def test_every_probe_ends_as_its_failure_class(path):
    record = json.loads(path.read_text(encoding="utf-8"))
    want = PROBE_EXCEPTIONS.get(record["probe"], BY_MODE[record["mode"]])
    assert ended(path) == want


RECORDED = {
    "claude-done": ("done", ""),
    "claude-asked-prose-1": ("asked", "prose"),
    "claude-asked-prose-2": ("asked", "prose"),
    "claude-asked-prose-3": ("asked", "prose"),
    # The plan is the final text; a plan stage parks on it, and that is the engine's to do.
    "claude-plan": ("done", ""),
    # A question through the ask door ends as done: the record it wrote is what parks it.
    "claude-ask-door": ("done", ""),
    "claude-denied-1": ("denied", ""),
    "claude-denied-2": ("denied", ""),
    "claude-limit": ("limit", ""),
    "claude-review-typed": ("done", ""),
    "codex-done": ("done", ""),
    # Codex in read-only explains in prose; only a typed answer can say it was denied.
    "codex-readonly": ("done", ""),
    "codex-ask-door": ("done", ""),
    "codex-review-typed": ("done", ""),
    "opencode-done": ("done", ""),
    "opencode-ask-door": ("done", ""),
    "opencode-denied": ("denied", ""),
}


def test_every_recorded_turn_is_listed():
    assert {p.stem for p in FIXTURES.glob("*.json")} == set(RECORDED)


@pytest.mark.parametrize("name", sorted(RECORDED))
def test_every_recorded_turn_ends_as_it_did(name):
    assert ended(FIXTURES / f"{name}.json") == RECORDED[name]


def test_claude_asked_in_prose_and_the_question_is_read_out():
    reader, log, _ = replay(FIXTURES / "claude-asked-prose-1.json")
    got = reader.classify(0, log)
    assert got.question == "Should the `add()` function in calc.py also accept strings?"


def test_the_denied_permissions_are_named():
    reader, log, _ = replay(FIXTURES / "claude-denied-2.json")
    assert [d.split()[0] for d in log.denials] == ["Bash", "Bash"]
    reader, log, record = replay(FIXTURES / "opencode-denied.json")
    assert reader.classify(0, log, "\n".join(record["stderr_tail"])).reason == "edit (calc.py)"  # type: ignore[arg-type]


# -- the readers -----------------------------------------------------------------------------


def test_the_claude_stream_names_the_session_the_tokens_and_the_accounts_windows():
    _, log, _ = replay(FIXTURES / "claude-asked-prose-1.json")
    assert log.session == "619a06fa-44e9-492c-86a6-970bc1e62261"
    assert (log.tokens.input, log.tokens.cached, log.tokens.output) == (10 + 7742, 13689, 380)
    windows = {w.name: (w.used, w.resets) for w in log.limits}
    assert windows == {
        "five_hour": (0.05, datetime.fromtimestamp(1791353400, UTC)),
        "seven_day": (0.26, datetime.fromtimestamp(1791450000, UTC)),
    }


def test_a_typed_review_is_read_from_both_clis_that_offer_one():
    for name in ("claude-review-typed", "codex-review-typed"):
        _, log, _ = replay(FIXTURES / f"{name}.json")
        assert log.typed is not None and log.typed["outcome"] == "changes", name
        findings = log.typed["findings"]
        assert isinstance(findings, list) and findings[0]["file"] == "calc.py"


def test_the_codex_stream_names_the_thread_and_counts_cached_input_apart():
    _, log, _ = replay(FIXTURES / "codex-done.json")
    assert log.session.startswith("01a1149f")
    assert log.tokens.cached and log.tokens.output
    assert log.final.startswith("Added `multiply(a, b)`")


def test_the_opencode_stream_sums_its_steps():
    _, log, _ = replay(FIXTURES / "opencode-done.json")
    assert log.session.startswith("ses_")
    assert (log.tokens.input, log.tokens.cached, log.tokens.output) == (
        4797 + 280 + 198 + 607,
        7424 + 12160 + 12416 + 12160,
        83 + 19 + 150 + 13 + 136 + 4 + 36 + 21,
    )


def test_a_cli_looping_without_tokens_never_stops_idling():
    _, log, _ = replay(FIXTURES / "probes" / "opencode-garbage.json")
    assert log.events > 0 and log.idle == log.events


# The 2026-10-04 run's real limit, in the rollout's words: the account's own windows, then a
# "premium" limit recorded with none, then the turn's error.
ROLLOUT_LIMITS = [
    {
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "rate_limits": {
                "limit_id": "codex",
                "primary": {"used_percent": 98.0, "window_minutes": 300, "resets_at": 1791159725},
                "secondary": {
                    "used_percent": 44.0,
                    "window_minutes": 10080,
                    "resets_at": 1791699373,
                },
                "plan_type": "plus",
            },
        },
    },
    {
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "rate_limits": {"limit_id": "premium", "primary": None, "secondary": None},
        },
    },
]
THREAD = "01a1085d-9901-7060-8649-8c52350c43d8"
USAGE_LIMIT = (
    "You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit "  # noqa: RUF001 — its words
    "https://chatgpt.com/codex/settings/usage to purchase more credits or try again at "
    "Oct 5th, 2026 2:22 AM."
)


def test_a_codex_limit_resets_when_the_rollout_says_its_fullest_window_does(tmp_path, monkeypatch):
    folder = tmp_path / "sessions" / "2026" / "10" / "04"
    folder.mkdir(parents=True)
    rollout = folder / f"rollout-2026-10-04T21-21-54-{THREAD}.jsonl"
    rollout.write_text("\n".join(json.dumps(line) for line in ROLLOUT_LIMITS), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    assert [w.name for w in codex.read_limits(THREAD)] == ["primary", "secondary"]
    reader = headless("codex")
    stream = [
        json.dumps({"type": "thread.started", "thread_id": THREAD}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "turn.failed", "error": {"message": USAGE_LIMIT}}),
    ]
    got = reader.classify(1, reader.read_lines(stream))
    assert (got.end, got.resets) == (TurnEnd.LIMIT, datetime.fromtimestamp(1791159725, UTC))
    assert codex.read_limits("no-such-thread") == ()


# -- the argv per stage ----------------------------------------------------------------------

RUN_DIR = str(Path("runs") / "r1")
PLAN_REPO = str(Path("plans") / "app")


def spec(stage: StageKind, **given: object) -> TurnSpec:
    return TurnSpec(stage, "Read your briefing", RUN_DIR, (PLAN_REPO,), **given)  # type: ignore[arg-type]


def option(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]


def test_claude_names_a_fresh_session_resumes_it_and_never_lets_add_dir_swallow_the_prompt():
    command = headless("claude").command
    fresh = command(spec(StageKind.EXECUTE, session="s-1"))
    assert fresh[:3] == ["claude", "-p", "--output-format"] and "--strict-mcp-config" in fresh
    assert option(fresh, "--session-id") == "s-1" and "--resume" not in fresh
    assert option(fresh, "--permission-mode") == "auto"
    assert json.loads(option(fresh, "--json-schema"))["required"] == [
        "outcome",
        "summary",
        "question",
    ]
    at = fresh.index("--add-dir")
    assert fresh[at + 1 : at + 3] == [RUN_DIR, PLAN_REPO] and fresh[at + 3].startswith("--")
    assert fresh[-1] == "Read your briefing" and fresh[-3] == "--json-schema"
    resumed = command(spec(StageKind.EXECUTE).resumed("s-1", "Answer: raise"))
    assert option(resumed, "--resume") == "s-1" and "--session-id" not in resumed
    assert resumed[-1] == "Answer: raise"
    plan = command(spec(StageKind.PLAN))
    assert option(plan, "--permission-mode") == "plan" and "--json-schema" not in plan
    review = command(spec(StageKind.REVIEW))
    assert option(review, "--permission-mode") == "plan"
    assert "findings" in json.loads(option(review, "--json-schema"))["properties"]


def overrides(argv: list[str]) -> dict[str, object]:
    """The ``-c`` overrides as Codex reads them: TOML values."""
    pairs = [argv[i + 1].split("=", 1) for i, word in enumerate(argv) if word == "-c"]
    return {key: tomllib.loads(f"v = {value}")["v"] for key, value in pairs}


def test_codex_states_the_stages_mode_as_overrides_fresh_and_resumed_alike():
    command = headless("codex").command
    windows_like = TurnSpec(StageKind.EXECUTE, "go", "C:\\runs\\r1", ("C:\\plans\\app",))
    for turn in (windows_like, windows_like.resumed("t-1", "continue")):
        argv = command(turn)
        assert overrides(argv) == {
            "sandbox_mode": "workspace-write",
            "approval_policy": "on-request",
            "approvals_reviewer": "auto_review",
            "sandbox_workspace_write.writable_roots": ["C:\\runs\\r1", "C:\\plans\\app"],
        }
        assert option(argv, "--output-schema") == str(Path("C:\\runs\\r1") / "execute.schema.json")
        assert not {"-s", "--sandbox", "--approve-for-me", "--add-dir"} & set(argv)
    fresh, resumed = command(windows_like), command(windows_like.resumed("t-1", "continue"))
    assert fresh[:3] == ["codex", "exec", "--json"] and fresh[-1] == "go"
    assert resumed[:4] == ["codex", "exec", "resume", "--json"] and resumed[-2:] == [
        "t-1",
        "continue",
    ]
    for stage in (StageKind.PLAN, StageKind.REVIEW):
        argv = command(spec(stage))
        assert overrides(argv) == {"sandbox_mode": "read-only", "approval_policy": "never"}
    assert "--output-schema" not in command(spec(StageKind.PLAN))


def test_opencode_runs_the_plan_agent_to_read_and_auto_to_work():
    command = headless("opencode").command
    assert command(spec(StageKind.PLAN)) == [
        "opencode", "run", "--format", "json", "--agent", "plan", "Read your briefing",
    ]  # fmt: skip
    resumed = command(spec(StageKind.EXECUTE).resumed("ses_1", "continue"))
    assert option(resumed, "--session") == "ses_1" and "--auto" in resumed
    assert resumed[-1] == "continue"
