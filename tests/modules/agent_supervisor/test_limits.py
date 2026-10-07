"""An account's last-known usage, and whether a new headless launch waits for its reset."""

from datetime import UTC, datetime, timedelta

import pytest

from dplanner.domain.headless import LimitWindow, TurnEnd
from dplanner.modules.agent_supervisor import limits

NOW = datetime(2026, 10, 7, 18, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=2)


def windows(five_hour: float, resets: datetime | None = LATER) -> list[LimitWindow]:
    return [LimitWindow("five_hour", five_hour, resets), LimitWindow("seven_day", 0.34, None)]


def test_a_new_launch_waits_while_a_window_is_past_the_threshold(tmp_path):
    limits.record_turn("claude", "r1", windows(0.97), TurnEnd.DONE, None, True, tmp_path)
    said = limits.hold("claude", "Claude Code", now=NOW, config=tmp_path)
    assert said.startswith("Claude Code is at 97% of its five-hour window;")
    assert "at 95%" in said and limits.clock(LATER, NOW) in said
    assert limits.hold("claude", "Claude Code", threshold=0.98, now=NOW, config=tmp_path) == ""
    # Once the window has reset, its old share holds nothing.
    assert limits.hold("claude", "Claude Code", now=LATER, config=tmp_path) == ""
    assert limits.hold("codex", "Codex", now=NOW, config=tmp_path) == ""


def test_an_account_that_ran_out_holds_until_its_reset_or_a_turn_that_produced(tmp_path):
    limits.record_turn("claude", "r1", [], TurnEnd.LIMIT, LATER, False, tmp_path)
    assert limits.exhausted("claude", NOW, tmp_path) == LATER
    assert "ran out of usage" in limits.hold("claude", "Claude Code", now=NOW, config=tmp_path)
    assert limits.exhausted("claude", LATER, tmp_path) is None
    # A failed turn that produced nothing says nothing about the account.
    limits.record_turn("claude", "r2", [], TurnEnd.FAILED, None, False, tmp_path)
    assert limits.exhausted("claude", NOW, tmp_path) == LATER
    limits.record_turn("claude", "r3", [], TurnEnd.DONE, None, True, tmp_path)
    assert limits.exhausted("claude", NOW, tmp_path) is None


def test_a_limit_with_no_reset_holds_nothing(tmp_path):
    limits.record_turn("claude", "r1", [], TurnEnd.LIMIT, None, False, tmp_path)
    assert limits.exhausted("claude", NOW, tmp_path) is None


def test_the_last_reset_is_the_fullest_windows_while_it_is_still_to_come(tmp_path):
    limits.record_turn("claude", "r1", windows(0.99), TurnEnd.DONE, None, True, tmp_path)
    assert limits.last_reset("claude", NOW, tmp_path) == LATER
    assert limits.last_reset("claude", LATER, tmp_path) is None
    known = limits.account("claude", tmp_path)
    assert (known.run, [w.name for w in known.windows]) == ("r1", ["five_hour", "seven_day"])


def test_a_turn_without_telemetry_keeps_the_last_windows(tmp_path):
    limits.record_turn("claude", "r1", windows(0.5), TurnEnd.DONE, None, True, tmp_path)
    limits.record_turn("claude", "r2", [], TurnEnd.DONE, None, True, tmp_path)
    assert limits.account("claude", tmp_path).run == "r1"


def test_the_threshold_is_a_setting_with_a_default(tmp_path):
    assert limits.hold_at(tmp_path) == limits.HOLD_AT == 0.95
    limits.set_hold_at(0.8, tmp_path)
    assert limits.hold_at(tmp_path) == 0.8
    limits.record_turn("claude", "r1", windows(0.85), TurnEnd.DONE, None, True, tmp_path)
    assert limits.hold_at(tmp_path) == 0.8  # The telemetry leaves the setting alone.
    with pytest.raises(ValueError):
        limits.set_hold_at(1.5, tmp_path)


def test_a_missing_or_broken_file_reads_as_nothing_known(tmp_path):
    assert limits.accounts(tmp_path) == {}
    limits.limits_file(tmp_path).write_text("{not json", encoding="utf-8")
    assert limits.accounts(tmp_path) == {} and limits.hold_at(tmp_path) == limits.HOLD_AT
    limits.limits_file(tmp_path).write_text(
        '{"hold_at": "high", "accounts": {"claude": {"windows": [{"name": 3}]},'
        ' "codex": {"windows": 7}}}',
        encoding="utf-8",
    )
    assert limits.hold_at(tmp_path) == limits.HOLD_AT
    assert (
        limits.account("claude", tmp_path).windows
        == limits.account("codex", tmp_path).windows
        == ()
    )


def test_a_reset_on_another_day_names_the_day():
    assert ":" in limits.clock(LATER, NOW) and len(limits.clock(LATER, NOW)) == 5
    assert len(limits.clock(NOW + timedelta(days=3), NOW)) > 5
