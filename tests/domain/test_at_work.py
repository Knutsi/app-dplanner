"""An agent's claim that it is at work: what is stored, and what is derived from it.

The whole point of the record is that it never guesses. These tests pin the two halves of
that: a claim stands until somebody ends it, and every reading of *how long ago* comes out
of the stamp rather than out of a timeout that decided the agent was gone.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from dplanner.domain.at_work import (
    FRESH_MINUTES,
    SWEEP_HOURS,
    AtWork,
    AtWorkBoard,
    claim_words,
    fraction,
    heard_words,
    is_fresh,
    progress_words,
    quiet_seconds,
)


@pytest.fixture
def board(tmp_path):
    return AtWorkBoard(tmp_path / "at-work")


def _quiet(minutes: float) -> AtWork:
    seen = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()
    return AtWork(project="p1", doing="cutting the graph", started=seen, seen=seen)


def _backdate(board: AtWorkBoard, project: str, minutes: float, step: str = "") -> None:
    """Age a claim on disk, as an agent that has said nothing for a while leaves it. Written
    through the file rather than through the board: this is the format readers must survive."""
    path = board._path(project, step)
    assert path is not None
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["seen"] = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()
    path.write_text(json.dumps(stored), encoding="utf-8")


# -- the claim itself ---------------------------------------------------------------------------


def test_a_claim_is_written_and_read_back(board):
    board.start("p1", doing="cutting the graph", of=12)
    (claim,) = board.claims("p1")
    assert (claim.project, claim.doing, claim.of, claim.done) == ("p1", "cutting the graph", 12, 0)
    assert claim.started and claim.seen


def test_set_moves_a_claim_along_and_keeps_what_it_was_not_given(board):
    board.start("p1", doing="cutting the graph", of=12)
    board.set("p1", done=8)
    (claim,) = board.claims("p1")
    assert (claim.doing, claim.done, claim.of) == ("cutting the graph", 8, 12)


def test_set_begins_a_claim_when_none_stands(board):
    """An agent reporting progress without having said it started is saying the same
    thing; refusing it would cost the developer the warning it came with."""
    board.set("p1", doing="linking the steps", done=3, of=9)
    (claim,) = board.claims("p1")
    assert (claim.doing, claim.done, claim.of) == ("linking the steps", 3, 9)


def test_a_step_and_the_plan_are_two_claims_on_one_project(board):
    board.start("p1", doing="shaping")
    board.start("p1", step="s7", doing="building the modal")
    assert {claim.step for claim in board.claims("p1")} == {"", "s7"}
    assert board.claims("other") == []


def test_ending_one_claim_leaves_the_others(board):
    board.start("p1", step="s7")
    board.start("p1", step="s8")
    assert board.end("p1", "s7") is True
    assert [claim.step for claim in board.claims("p1")] == ["s8"]
    assert board.end("p1", "s7") is False  # Nothing stood; saying so is not an error.


def test_a_board_with_no_directory_holds_nothing(tmp_path):
    """The shape the test suite's registry uses, so no test writes the user's own file."""
    board = AtWorkBoard(None)
    board.start("p1", doing="whatever")
    assert board.claims() == []
    assert board.end("p1") is False


def test_an_unreadable_file_is_skipped_rather_than_raised(board, tmp_path):
    board.start("p1")
    (tmp_path / "at-work" / "torn.json").write_text("{not json", encoding="utf-8")
    assert len(board.claims()) == 1


def test_a_claim_a_newer_build_wrote_is_read_for_what_it_carries(board, tmp_path):
    board.start("p1", doing="shaping")
    path = next((tmp_path / "at-work").glob("*.json"))
    path.write_text('{"project": "p1", "doing": "shaping", "wingspan": 4}', encoding="utf-8")
    (claim,) = board.claims()
    assert claim.doing == "shaping"


# -- the sign of life ---------------------------------------------------------------------------


def test_every_run_renews_the_claims_of_its_own_project(board):
    board.start("p1", doing="shaping")
    board.start("p2", doing="elsewhere")
    _backdate(board, "p1", 30)
    _backdate(board, "p2", 30)
    board.touch("p1")
    assert quiet_seconds(board.claims("p1")[0]) < 60
    assert quiet_seconds(board.claims("p2")[0]) > 60


def test_a_run_never_makes_a_claim(board):
    """Running a verb is evidence for a claim somebody made, not a claim of its own."""
    board.touch("p1")
    assert board.claims() == []


def test_a_claim_nobody_renewed_since_yesterday_is_swept_by_the_next_one(board, tmp_path):
    board.start("p1", doing="ancient")
    path = next((tmp_path / "at-work").glob("*.json"))
    ancient = (datetime.now(UTC) - timedelta(hours=SWEEP_HOURS + 1)).isoformat()
    path.write_text(f'{{"project": "p1", "seen": "{ancient}"}}', encoding="utf-8")
    board.start("p2", doing="now")
    assert [claim.project for claim in board.claims()] == ["p2"]


def test_a_quiet_claim_is_never_swept_while_it_is_merely_quiet(board):
    """An agent can spend an hour on one tool call; only a day of silence is gone."""
    board.start("p1", doing="thinking")
    _backdate(board, "p1", 60 * (SWEEP_HOURS - 1))
    board.set("p2", doing="elsewhere")
    assert {claim.project for claim in board.claims()} == {"p1", "p2"}


# -- the reading --------------------------------------------------------------------------------


def test_a_claim_reads_as_at_work_until_it_has_been_quiet_a_while(board):
    assert is_fresh(_quiet(FRESH_MINUTES - 1))
    assert not is_fresh(_quiet(FRESH_MINUTES + 1))


def test_a_quiet_claim_is_still_a_claim(board):
    """It stops reading as *at work*; it does not stop existing. Nothing here decides a
    process is dead, because nothing here can see one."""
    board.start("p1")
    assert board.claims("p1")
    assert not board.at_work("p1", now=datetime.now(UTC) + timedelta(minutes=FRESH_MINUTES + 1))


def test_how_long_ago_is_said_coarsely(board):
    assert heard_words(_quiet(0)) == "heard just now"
    assert heard_words(_quiet(4)) == "heard 4 minutes ago"
    assert heard_words(_quiet(FRESH_MINUTES + 5)) == f"last heard {FRESH_MINUTES + 5} minutes ago"
    assert heard_words(_quiet(125)) == "last heard 2 hours ago"
    assert heard_words(AtWork(project="p1")) == "not heard from yet"


def test_a_count_is_shown_only_when_the_agent_offered_one(board):
    assert progress_words(AtWork(project="p1", done=8, of=20)) == "8 of 20"
    assert progress_words(AtWork(project="p1", done=8)) == ""
    assert fraction(AtWork(project="p1", done=8, of=20)) == pytest.approx(0.4)
    assert fraction(AtWork(project="p1")) == -1.0


def test_the_words_say_what_where_how_far_and_when():
    claim = AtWork(project="p1", doing="linking the steps", done=8, of=20, seen=_quiet(0).seen)
    words = claim_words(claim, "Payments", "S7")
    assert (
        words
        == "An agent is at work on Payments · S7 — linking the steps · 8 of 20 · heard just now"
    )


def test_the_words_change_tense_rather_than_disappearing():
    claim = _quiet(FRESH_MINUTES + 10)
    assert claim_words(claim, "Payments").startswith("An agent was at work on Payments")
