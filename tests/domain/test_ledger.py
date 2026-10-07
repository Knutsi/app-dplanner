"""The usage ledger: one file per run, written whole, read tolerantly, summed on read."""

import json
from datetime import UTC, datetime

from dplanner.domain import ledger
from dplanner.domain.agents import AgentUsage, RunReport, Tokens
from dplanner.domain.ledger import LedgerRecord
from dplanner.domain.ledger import machine_id as real_machine_id


def _record(run: str = "20261001T100000Z-aaaaaaaa", **fields: object) -> LedgerRecord:
    base: dict[str, object] = {
        "run": run,
        "project": "p1",
        "step": "s1",
        "harness": "claude",
        "launched": "2026-10-01T10:00:00+00:00",
    }
    return LedgerRecord(**{**base, **fields})  # type: ignore[arg-type]


TREE = (
    AgentUsage("main", {"claude-opus-5-5": Tokens(100, 2000, 30)}, session="s-main"),
    AgentUsage(
        "a1",
        {"claude-haiku-4-5": Tokens(10, 300, 5), "claude-opus-5-5": Tokens(1, 2, 3)},
        parent="main",
        kind="Explore",
    ),
)


def test_a_record_round_trips_and_absence_encodes_the_default(tmp_path):
    record = _record(session="s-main", agents=TREE, account={"vendor": "anthropic"}, exit=0)
    assert ledger.write(tmp_path, record)
    path = tmp_path / "ledger" / "2026-10" / f"{record.run}.json"
    raw = json.loads(path.read_text())
    assert raw["format"] == ledger.TERMINAL_FORMAT and "ended" not in raw and raw["exit"] == 0
    assert raw["agents"][1] == {
        "id": "a1",
        "parent": "main",
        "kind": "Explore",
        "models": {
            "claude-haiku-4-5": {"in": 10, "cached": 300, "out": 5},
            "claude-opus-5-5": {"in": 1, "cached": 2, "out": 3},
        },
    }
    assert ledger.records(tmp_path) == [record]
    assert ledger.find(tmp_path, record.run) == record


def test_a_tree_totals_per_model_and_across_agents():
    record = _record(agents=TREE)
    assert record.tokens == Tokens(111, 2302, 38)
    assert record.models() == {
        "claude-opus-5-5": Tokens(101, 2002, 33),
        "claude-haiku-4-5": Tokens(10, 300, 5),
    }
    assert record.sessions == frozenset({"s-main"})


def test_writing_what_is_already_there_writes_nothing(tmp_path):
    """A sweep over finished runs must leave git quiet."""
    record = _record(agents=TREE)
    assert ledger.write(tmp_path, record)
    path = ledger.path_for(tmp_path, record)
    stamp = path.stat().st_mtime_ns
    assert not ledger.write(tmp_path, record)
    assert path.stat().st_mtime_ns == stamp


def test_a_file_this_build_cannot_read_is_skipped(tmp_path):
    month = tmp_path / "ledger" / "2026-10"
    month.mkdir(parents=True)
    (month / "half.json").write_text('{"format": 1, "run"')
    (month / "newer.json").write_text(json.dumps({**_record("n").to_json(), "format": 99}))
    (month / ".temp.json.tmp").write_text("{}")
    (month / ".hidden.json").write_text(json.dumps(_record("h").to_json()))
    ledger.write(tmp_path, _record("ok"))
    assert [r.run for r in ledger.records(tmp_path)] == ["ok"]
    assert ledger.records(tmp_path / "nowhere") == []


def test_an_end_is_the_first_one_seen():
    ended = _record().ended_at("2026-10-01T11:00:00+00:00", 0)
    assert ended.ended_at("2026-10-01T12:00:00+00:00", 1) == ended


def test_a_report_fills_the_record_and_a_partial_read_says_so():
    report = RunReport("found", TREE, {"vendor": "openai", "plan": "plus"}, partial=True)
    filled = _record(harness="codex").with_report(report, "2026-10-01T11:00:00+00:00")
    assert filled.session == "found" and filled.agents == TREE
    assert filled.measurement == ledger.PARTIAL and filled.account["plan"] == "plus"
    # A session named at launch is never replaced by what a read reports.
    named = _record(session="named").with_report(report, "x")
    assert named.session == "named"


def test_run_ids_sort_by_launch_and_never_collide():
    early = ledger.new_run_id(datetime(2026, 10, 1, 9, 0, tzinfo=UTC))
    late = ledger.new_run_id(datetime(2026, 10, 1, 10, 0, tzinfo=UTC))
    assert early.startswith("20261001T090000Z-") and early < late
    assert ledger.new_run_id() != ledger.new_run_id()


def test_a_session_claimed_by_one_record_is_off_limits_to_the_others():
    first = _record("a", session="s1")
    second = _record("b", agents=(AgentUsage("main", {}, session="s2"),))
    assert ledger.claimed([first, second]) == {"s1", "s2"}
    assert ledger.claimed([first, second], other_than="a") == {"s2"}


def test_a_retired_usage_row_becomes_a_legacy_record_named_by_its_session():
    rows = [
        {
            "harness": "claude",
            "session": "s1",
            "input": 1500,
            "output": 40,
            "details": {"cache_read": 1000, "cache_creation": 400},
            "ended": "2026-09-11T10:00:00+00:00",
            "prompt_chars": 18412,
        },
        {
            "harness": "codex",
            "session": "",
            "input": 900,
            "output": 80,
            "details": {"cached_input": 600},
        },
    ]
    claude_row, codex_row = ledger.legacy("p1", "s7", rows)
    assert claude_row.run == "legacy-s1" and claude_row.measurement == ledger.LEGACY
    assert claude_row.models() == {ledger.UNKNOWN_MODEL: Tokens(500, 1000, 40)}
    assert claude_row.prompt_chars == 18412 and claude_row.ended == claude_row.launched
    assert codex_row.run == "legacy-s7-1"
    assert codex_row.tokens == Tokens(300, 600, 80)


def test_the_machine_id_is_minted_once_and_kept(tmp_path):
    # Imported at collection, before the suite pins ledger.machine_id for every test.
    minted = real_machine_id(tmp_path)
    assert minted and real_machine_id(tmp_path) == minted
    assert (tmp_path / "machine-id").read_text().strip() == minted


def _turn(n: int, *, end: str = "done", agents: tuple[AgentUsage, ...] = ()) -> ledger.Turn:
    return ledger.Turn(
        n=n,
        prompt="launch" if n == 1 else "answer",
        started=f"2026-10-07T10:0{n}:00+00:00",
        pid=4000 + n,
        boot="boot-1",
        pid_started="123",
        ended=f"2026-10-07T10:0{n}:30+00:00" if end else "",
        end=end,
        exit=0 if end else None,
        agents=agents,
    )


def test_a_headless_run_is_format_2_and_its_usage_is_its_turns(tmp_path):
    first = _turn(1, end="asked", agents=(AgentUsage("main", {"m": Tokens(10, 100, 1)}),))
    second = _turn(2, agents=(AgentUsage("main", {"m": Tokens(5, 50, 2)}),))
    record = _record(mode="headless", stage="execute", attempt=1, pass_="p-1").with_turns(
        (first, second)
    )
    assert record.tokens == Tokens(15, 150, 3)
    ledger.write(tmp_path, record)
    raw = json.loads(ledger.path_for(tmp_path, record).read_text())
    assert raw["format"] == 2 and raw["pass"] == "p-1" and "agents" not in raw
    assert raw["turns"][0]["usage"]["agents"][0]["models"]["m"] == {
        "in": 10,
        "cached": 100,
        "out": 1,
    }
    assert raw["turns"][0]["end"] == "asked" and raw["turns"][0]["pid"] == 4001
    assert ledger.find(tmp_path, record.run) == record


def test_a_run_is_parked_while_its_last_turn_has_ended_and_it_has_not():
    running = _record(mode="headless").with_turns((_turn(1, end=""),))
    parked = running.with_turns((_turn(1, end="limit"),))
    over = parked.ended_at("2026-10-07T11:00:00+00:00", 0)
    assert (running.parked, parked.parked, over.parked, over.over) == (False, True, False, True)


def test_a_turn_a_newer_build_cannot_read_is_dropped_and_the_rest_kept(tmp_path):
    record = _record(mode="headless").with_turns((_turn(1),))
    raw = {**record.to_json(), "turns": [_turn(1).to_json(), {"no": "n"}]}
    loaded = LedgerRecord.from_json(raw)
    assert loaded is not None and loaded.turns == (_turn(1),)
