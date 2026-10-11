"""The headless runs the Agents browser lists: each state in the card's words, what is listed
and for how long, and which verbs can act — read from the records, never tracked."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dplanner.domain import ledger, questions
from dplanner.domain.ledger import LedgerRecord, Turn
from dplanner.modules.agent_claude import harness as claude
from dplanner.modules.agent_supervisor import limits, takeover
from dplanner.modules.step_agent_run import headless

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
AT = (NOW - timedelta(minutes=5)).isoformat()
RESET = NOW + timedelta(hours=2)
HARNESSES = (claude.HARNESS,)


def record(config: Path, *turns: Turn, n: int = 0, **fields) -> LedgerRecord:
    made = LedgerRecord(
        run=f"R{n}",
        project="p1",
        step="s1",
        harness="claude",
        launched=AT,
        machine=ledger.machine_id(config),
        session="S",
        mode=ledger.HEADLESS,
        stage="execute",
        attempt=1,
    )
    return replace(made, **fields).with_turns(turns)


def turn(end: str = "", **fields) -> Turn:
    return Turn(n=1, prompt="launch", started=AT, ended=AT if end else "", end=end, **fields)


def asked(kind: str = questions.DECISION) -> questions.Question:
    return questions.asked("p1", "s1", AT, [questions.one("?")], kind=kind)


@pytest.mark.parametrize(
    ("turns", "fields", "question", "words", "tone"),
    [
        ((turn(),), {}, None, "Running", "busy"),
        ((), {}, None, "Starting", "busy"),
        (
            (turn("asked"),),
            {},
            asked(questions.PLAN_APPROVAL),
            "Waits for you · plan approval",
            "warn",
        ),
        ((turn("asked"),), {}, asked(), "Waits for you · a decision", "warn"),
        (
            (turn("limit", resets=RESET.isoformat()),),
            {},
            None,
            f"Parked until {limits.clock(RESET)}",
            "",
        ),
        ((turn("done"),), {"ended": AT}, None, "Done", "good"),
        ((turn("stopped"),), {"ended": AT}, None, "Stopped", "bad"),
        (
            (turn("asked"),),
            {"ended": AT, "fence": {"at": AT, "by": "knut", "why": ledger.TAKEN_OVER}},
            None,
            "Taken over",
            "",
        ),
    ],
)
def test_each_state_reads_in_the_cards_words(tmp_path, turns, fields, question, words, tone):
    if question is not None:
        turns = (replace(turns[0], question=question.id),)
    made = record(tmp_path, *turns, **fields)
    found = {question.id: question} if question is not None else {}
    assert headless.state_of(made, found) == (words, tone)


def test_the_list_is_what_runs_and_what_ended_today_since_the_last_clear(tmp_path):
    plan = tmp_path / "plan"
    long_ago = (NOW - timedelta(days=2)).isoformat()
    an_hour_ago = (NOW - timedelta(hours=1)).isoformat()
    for made in (
        record(tmp_path, turn(), n=1),
        record(tmp_path, turn("done"), n=2, ended=an_hour_ago),
        record(tmp_path, turn("done"), n=3, ended=long_ago),
        replace(record(tmp_path, n=4), mode=""),  # A terminal's: the tracker's to list.
    ):
        ledger.write(plan, made)
    project = headless.read(plan)
    runs = headless.listed([project], HARNESSES, NOW, config=tmp_path)
    assert sorted(run.run for run in runs) == ["R1", "R2"]
    cleared = (NOW - timedelta(minutes=30)).isoformat()
    after = headless.listed([project], HARNESSES, NOW, cleared=cleared, config=tmp_path)
    assert [run.run for run in after] == ["R1"]


def test_the_verbs_read_as_the_terminal_refuses(tmp_path):
    plan = tmp_path / "plan"
    ledger.write(plan, record(tmp_path, turn(), n=1))
    ledger.write(plan, record(tmp_path, turn("asked"), n=2, machine="far", host="laptop"))
    rows = {
        run.run: run
        for run in headless.listed([headless.read(plan)], HARNESSES, NOW, config=tmp_path)
    }
    assert rows["R1"].follow_refusal == "" and rows["R1"].open_refusal == takeover.RUNNING
    assert rows["R2"].follow_refusal == rows["R2"].open_refusal == "it ran on laptop"


def test_a_pass_marks_its_latest_run_and_the_step_finds_it(tmp_path):
    plan = tmp_path / "plan"
    ledger.write(plan, record(tmp_path, turn("done"), n=1, pass_="P", ended=AT))
    later = (NOW - timedelta(minutes=1)).isoformat()
    ledger.write(plan, record(tmp_path, turn(), n=2, pass_="P", stage="review", launched=later))
    project = headless.read(plan)
    rows = {run.run: run for run in headless.listed([project], HARNESSES, NOW, config=tmp_path)}
    assert not rows["R1"].latest_of_pass and rows["R2"].latest_of_pass
    latest = headless.latest_on(project, "s1", HARNESSES, tmp_path)
    assert latest is not None and latest.run == "R2"
    assert headless.latest_on(project, "elsewhere", HARNESSES, tmp_path) is None


def test_ago_says_how_long_in_a_persons_words():
    assert headless.ago(NOW - timedelta(seconds=12), NOW) == "12 s ago"
    assert headless.ago(NOW - timedelta(minutes=4), NOW) == "4 min ago"
    assert headless.ago(NOW - timedelta(hours=2), NOW) == "2 h ago"
    assert headless.ago(None, NOW) == ""
