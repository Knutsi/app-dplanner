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
    """How the turn ended, handed what the supervisor would hand: the exit, the stream, the
    stderr and the question the turn recorded, where it recorded one."""
    reader, log, record = replay(path)
    stderr = "\n".join(record["stderr_tail"])  # type: ignore[arg-type]
    question = record.get("question")
    got = reader.classify(record["exit"], log, stderr, question)  # type: ignore[arg-type]
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
    # A question through the ask door is the record the turn wrote, handed in.
    "claude-ask-door": ("asked", "record"),
    "claude-denied-1": ("denied", ""),
    "claude-denied-2": ("denied", ""),
    "claude-limit": ("limit", ""),
    # A subscription's words name no rate and give no status; the error code says it.
    "claude-limit-subscription": ("limit", ""),
    # A real subscription limit mid-run: warnings past 90 %, then rejected with its reset.
    "claude-limit-session": ("limit", ""),
    # Answered FAQ headings, and a finished fix that mentions a wait.
    "claude-done-faq": ("done", ""),
    "claude-done-fixed-wait": ("done", ""),
    "claude-review-typed": ("done", ""),
    "codex-done": ("done", ""),
    # Codex in read-only says it could not, and why: that sentence is the denial.
    "codex-readonly": ("denied", ""),
    "codex-ask-door": ("asked", "record"),
    "codex-review-typed": ("done", ""),
    # A typed pass whose summary mentions the sandbox: the verdict, not the words, decides.
    "codex-review-typed-pass": ("done", ""),
    "opencode-done": ("done", ""),
    "opencode-ask-door": ("asked", "record"),
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


def test_a_running_tool_is_open_until_its_result_and_the_model_is_named():
    claude = headless("claude")
    log = TurnLog()
    claude.feed(log, json.dumps({"type": "system", "subtype": "init", "model": "claude-x[1m]"}))
    use = {"type": "tool_use", "id": "t1", "name": "Bash"}
    claude.feed(log, json.dumps({"type": "assistant", "message": {"content": [use]}}))
    assert log.tools == {"t1"} and log.model == "claude-x"
    done = {"type": "tool_result", "tool_use_id": "t1"}
    claude.feed(log, json.dumps({"type": "user", "message": {"content": [done]}}))
    assert log.tools == set()


def test_codex_holds_an_item_open_from_its_start_to_its_completion():
    record = json.loads((FIXTURES / "codex-done.json").read_text(encoding="utf-8"))
    reader, log = headless("codex"), TurnLog()
    for line in record["stdout_head"]:
        reader.feed(log, line)
        if '"item.started"' in line:
            assert len(log.tools) == 1
    assert log.tools == set()


def test_opencode_waits_longer_in_silence_since_it_never_shows_a_tool_running():
    assert headless("opencode").stall > headless("claude").stall == headless("codex").stall


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


def test_a_codex_limit_is_read_by_its_code_before_its_words():
    reader = headless("codex")
    error = {
        "message": "Try again at Oct 5th, 2026 2:22 AM.",
        "codex_error_info": "usage_limit_exceeded",
    }
    log = reader.read_lines([json.dumps({"type": "turn.failed", "error": error})])
    assert (log.code, reader.classify(1, log).end) == ("usage_limit_exceeded", TurnEnd.LIMIT)


def test_a_real_claude_limit_resets_when_its_rejected_window_does():
    reader, log, record = replay(FIXTURES / "claude-limit-session.json")
    got = reader.classify(record["exit"], log)  # type: ignore[arg-type]
    assert {w.name: w.used for w in log.limits} == {"five_hour": 1.0, "seven_day": 0.34}
    assert (got.end, got.resets) == (TurnEnd.LIMIT, datetime.fromtimestamp(1791396600, UTC))


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
        "declined",
    ]
    at = fresh.index("--add-dir")
    assert fresh[at + 1 : at + 3] == [RUN_DIR, PLAN_REPO] and fresh[at + 3].startswith("--")
    assert fresh[-1] == "Read your briefing" and fresh[-4] == "--json-schema"
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
    astral = TurnSpec(StageKind.EXECUTE, "go", "/runs/r1", ("/plans/\U0001f680 launch",))
    roots = overrides(command(astral))["sandbox_workspace_write.writable_roots"]
    assert roots == ["/runs/r1", "/plans/\U0001f680 launch"]
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
        "opencode", "run", "--format", "json", "--agent", "plan", "--", "Read your briefing",
    ]  # fmt: skip
    resumed = command(spec(StageKind.EXECUTE).resumed("ses_1", "continue"))
    assert option(resumed, "--session") == "ses_1" and "--auto" in resumed
    assert resumed[-1] == "continue"


def test_an_answer_that_reads_like_a_flag_is_still_the_prompt():
    # Each parser was checked on 2026-10-07 against a local fake API in a throwaway home:
    # after "--", "--help MARKER" reached the model as the message, for all four forms.
    for cli in ("claude", "codex", "opencode"):
        command = headless(cli).command
        fresh = command(spec(StageKind.EXECUTE, session="s-1"))
        assert fresh[-2:] == ["--", "Read your briefing"], cli
        resumed = command(spec(StageKind.EXECUTE).resumed("s-1", "--help"))
        tail = ["--", "s-1", "--help"] if cli == "codex" else ["--", "--help"]
        assert resumed[-len(tail) :] == tail, cli
        assert resumed.count("--help") == 1, cli


def test_codex_reads_a_refusal_for_want_of_permission_and_nothing_less():
    _, log, _ = replay(FIXTURES / "codex-readonly.json")
    assert log.denials and "read-only" in log.denials[0]
    assert codex.refusals("I couldn't commit: writing is not permitted in this sandbox.")
    for fine in (
        "Reviewed in a read-only sandbox; no issues found.",
        "I couldn't reproduce the failure, so I added a test for it.",
        "Added it. The sandbox is read-only for the plan, which is expected.",
    ):
        assert not codex.refusals(fine), fine


ODD = [
    {"type": "system", "subtype": "init", "session_id": 7},
    {"type": "rate_limit_event", "rate_limit_info": {"unifiedWindows": {
        "five_hour": {"utilization": "unknown", "resetsAt": 1791353400},
        "seven_day": {"utilization": 0.3, "resetsAt": 10**20},
        "opus": "n/a",
        "hourly": {"utilization": float("nan")},
    }}},
    {"type": "assistant", "error": 12, "message": None},
    {"type": "result", "result": None, "usage": {"input_tokens": "many"},
     "permission_denials": [3, {"tool_input": "x"}]},
    {"type": "thread.started", "thread_id": None},
    {"type": "item.completed", "item": {"type": "agent_message", "text": 5}},
    {"type": "turn.completed", "usage": {"input_tokens": -1, "cached_input_tokens": "x"}},
    {"type": "turn.failed", "error": None},
    {"type": "step_finish", "sessionID": [], "part": {"tokens": {"input": "x", "cache": 4}}},
    {"type": "text", "part": {"text": None}},
    {"type": "error", "error": "boom"},
]  # fmt: skip


def test_no_reader_raises_on_a_valid_event_with_odd_values():
    for cli in ("claude", "codex", "opencode"):
        reader = headless(cli)
        log = reader.read_lines(json.dumps(event) for event in ODD)
        reader.classify(0, log)
    log = headless("claude").read_lines([json.dumps(ODD[1])])
    # The odd windows are skipped; the good one stays, its impossible reset unknown.
    assert [(w.name, w.used, w.resets) for w in log.limits] == [("seven_day", 0.3, None)]


def test_a_codex_rollout_with_odd_windows_reads_as_none(tmp_path):
    folder = tmp_path / "sessions" / "2026" / "10" / "04"
    folder.mkdir(parents=True)
    odd = {"payload": {"rate_limits": {"primary": {"used_percent": "high", "resets_at": 1e30}}}}
    (folder / f"rollout-2026-10-04T21-21-54-{THREAD}.jsonl").write_text(
        "[]\n" + json.dumps(odd), encoding="utf-8"
    )
    assert codex.read_limits(THREAD, tmp_path) == ()
