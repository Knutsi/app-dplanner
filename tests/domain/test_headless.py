"""The headless half of the harness contract, apart from any one CLI: the order the
classifier reads a turn's ending in, the prose question, the reset and the schemas."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime

from dplanner.domain.headless import (
    TURN_SCHEMA,
    VERDICT_SCHEMA,
    Ending,
    Headless,
    LimitWindow,
    StageKind,
    TurnEnd,
    TurnLog,
    TurnSpec,
    ending_for_error,
    prose_question,
    resets,
    schema_file,
    typed_message,
    waits_on_itself,
    write_schema,
)

# A harness whose stream is the log's fields, one event each: what the classifier sees once
# a real harness's reader has normalised its CLI.
PLAIN = Headless(
    command=lambda spec: [spec.prompt],
    read=lambda log, event: setattr(log, str(event["field"]), event["value"]),
)


def ending(exit_code: int | None = 0, stderr: str = "", **fields: object) -> Ending:
    lines = [json.dumps({"field": name, "value": value}) for name, value in fields.items()]
    return PLAIN.classify(exit_code, PLAIN.read_lines(lines), stderr)


def test_a_clean_exit_with_nothing_said_is_done():
    assert ending(final="Done. Added multiply.") == Ending(TurnEnd.DONE)


def test_a_killed_process_failed_whatever_its_stream_said():
    for code in (None, -9, -15, 137, 143):
        got = ending(code, final="Should I go on?")
        assert (got.end, got.why) == (TurnEnd.FAILED, "killed")


def test_the_clis_own_error_comes_before_a_quiet_ending():
    got = ending(1, error="API Error: 429 rate limit", denials=["Edit calc.py"])
    assert got.end is TurnEnd.LIMIT


def test_a_failed_exit_with_no_error_says_the_last_stderr_line():
    got = ending(2, stderr="starting\nboom: config.toml unreadable\n")
    assert (got.end, got.why) == (TurnEnd.FAILED, "unknown")
    assert "boom: config.toml unreadable" in got.reason


def test_a_denial_under_a_clean_exit_is_denied_not_done():
    got = ending(final="Done!", denials=["Edit calc.py", "Bash git commit"])
    assert got == Ending(TurnEnd.DENIED, reason="Edit calc.py; Bash git commit")


def test_a_harness_reads_denials_off_stderr_when_its_stream_has_none():
    quiet = Headless(command=PLAIN.command, read=PLAIN.read, stderr_denials=lambda e: [e])
    assert quiet.classify(0, TurnLog(), "edit (calc.py)").end is TurnEnd.DENIED


def test_a_typed_message_is_read_and_beats_prose():
    asked = {"outcome": "asked", "summary": "Need a call", "question": "Raise or return None?"}
    assert ending(typed=asked, final="…?") == Ending(
        TurnEnd.ASKED, "typed", question="Raise or return None?"
    )
    denied = {"outcome": "denied", "summary": "The sandbox is read-only", "question": ""}
    assert ending(typed=denied) == Ending(TurnEnd.DENIED, "typed", "The sandbox is read-only")
    # A typed answer that did not ask is done, even if its prose ends on a question mark.
    done = {"outcome": "done", "summary": "Added it", "question": ""}
    assert ending(typed=done, final="Want tests too?").end is TurnEnd.DONE


def test_prose_ending_on_a_question_is_asked():
    got = ending(
        final="I can do either.\n\n**Raise, or return None?** (pick one)\n\nThen I'll go on."
    )
    assert got == Ending(TurnEnd.ASKED, "prose", question="Raise, or return None?")


def test_the_prose_question_is_in_the_last_few_lines_and_nowhere_else():
    assert prose_question("Should it accept strings?\n- Yes\n- No\nTell me, and I'll edit it.")
    assert not prose_question("Why did it fail?\n" + "\n".join(f"step {n}" for n in range(6)))
    assert not prose_question("Let me know if you'd like changes, or tell me to proceed.")
    assert not prose_question("")


def test_the_clis_words_map_to_the_failure_kinds():
    cases = {
        ("Not logged in · Please run /login", None): (TurnEnd.FAILED, "login"),
        ("forbidden", 403): (TurnEnd.FAILED, "login"),
        ("Credit balance is too low", None): (TurnEnd.FAILED, "billing"),
        ("You've hit your usage limit. Try again at 2:22 AM.", None): (TurnEnd.LIMIT, ""),
        ("model: claude-retired-1", 404): (TurnEnd.FAILED, "model"),
        ("stream disconnected before completion", None): (TurnEnd.FAILED, "malformed"),
        ("Overloaded", 529): (TurnEnd.FAILED, "transient"),
        ("something new", None): (TurnEnd.FAILED, "unknown"),
    }
    for (message, status), want in cases.items():
        got = ending_for_error(message, status)
        assert (got.end, got.why) == want, message
    assert ending_for_error("Credit balance is too low", None).needs_person
    assert not ending_for_error("Overloaded", 529).needs_person


def test_a_limit_resets_when_its_fullest_window_does():
    soon, later = datetime(2026, 10, 5, 0, 22, tzinfo=UTC), datetime(2026, 10, 11, tzinfo=UTC)
    windows = (LimitWindow("primary", 0.98, soon), LimitWindow("secondary", 0.44, later))
    assert resets(windows) == soon
    got = ending_for_error("usage limit", None, windows)
    assert (got.end, got.resets) == (TurnEnd.LIMIT, soon)
    assert resets(()) is None


def test_the_log_counts_events_and_idles_until_the_agent_produces_something():
    def read(log: TurnLog, event: Mapping[str, object]) -> None:
        if event.get("tokens"):
            log.progressed()

    reader = Headless(command=PLAIN.command, read=read)
    log = reader.read_lines(['{"tokens": 0}', "not json", '{"tokens": 5}', "{}", "[]", "{}"])
    assert (log.events, log.idle) == (4, 2)


def test_a_typed_message_is_a_json_object_with_an_outcome():
    assert typed_message('{"outcome": "pass", "summary": "ok", "findings": []}')
    assert typed_message('```json\n{"outcome": "done"}\n```') == {"outcome": "done"}
    assert typed_message("All done.") is None
    assert typed_message('{"summary": "no outcome"}') is None


def test_a_resumed_turn_keeps_its_stage_and_directories():
    spec = TurnSpec(StageKind.EXECUTE, "Read the briefing", "/runs/r1", ("/plan",), "s-1")
    again = spec.resumed("s-1", "Answer: raise")
    assert again == TurnSpec(
        StageKind.EXECUTE, "Answer: raise", "/runs/r1", ("/plan",), "s-1", True
    )


def test_the_schemas_are_strict_and_only_execute_and_review_have_one(tmp_path):
    for schema in (TURN_SCHEMA, VERDICT_SCHEMA):
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])  # type: ignore[call-overload]
    plan = TurnSpec(StageKind.PLAN, "p", str(tmp_path))
    assert schema_file(plan) is None and write_schema(plan) is None
    review = TurnSpec(StageKind.REVIEW, "p", str(tmp_path))
    written = write_schema(review)
    assert written is not None and written == tmp_path / "review.schema.json"
    assert json.loads(written.read_text(encoding="utf-8")) == VERDICT_SCHEMA


def test_a_turn_that_ends_to_wait_on_its_own_background_work_was_abandoned():
    # Kettle Five's own last words on S8, 2026-10-07, before its process exited with the suite.
    said = "Waiting on the full suite (running on four workers); I'll pick up when it finishes."
    got = ending(final=said)
    assert (got.end, got.why) == (TurnEnd.FAILED, "abandoned-wait")
    assert not got.needs_person
    done = {"outcome": "done", "summary": "Started the build; I'll be notified when it ends."}
    assert ending(typed=done).why == "abandoned-wait"
    # Waiting on a person is a question, never this.
    for person in (
        "I've asked how divide should behave. Waiting for a person's answer before implementing.",
        "The question is recorded. I'll wait for the person's answer before changing calc.py.",
        "Done! Waiting for approval to run the verification test.",
    ):
        assert not waits_on_itself(person), person
