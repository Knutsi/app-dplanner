"""Where a pass stands, in words: ``passes.standing`` over records made by hand — the phrase
the card's playbook strip and ``playbook show`` both say, its tone, and the stage marked."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from tests.modules.step_playbook.test_passes import CHANGED, PASSED, gate, run, settings

from dplanner.domain import questions
from dplanner.modules.step_playbook.passes import (
    CHANGES,
    ESCALATION,
    PASS,
    ROUND_CAP,
    STOP,
    Facts,
    describe,
    standing,
    until_words,
)
from dplanner.modules.step_playbook.presets import preset

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def stands(playbook_id: str, *entries, parks=(), **facts):
    playbook = preset(playbook_id)
    assert playbook is not None
    return standing(playbook, settings(playbook_id), list(entries), parks, Facts(**facts), NOW)


def parked_on(record, question):
    """A run whose last turn parked on its own question."""
    (turn,) = record.turns
    return replace(record, turns=(replace(turn, question=question.id),))


REVIEWED = "plan-execute-review-other"


def test_each_working_stage_says_what_it_does():
    assert stands(REVIEWED, run("plan", end="", over=False)).phrase == "Planning"
    executing = stands(REVIEWED, run("plan"), run("execute", end="", over=False))
    assert (executing.phrase, executing.tone) == ("Executing", "busy")
    assert executing.stages[executing.current] == "execute"


def test_a_review_counts_its_rounds_and_a_loop_back_is_a_fix():
    first = stands(REVIEWED, run("plan"), run("execute"), run("review", end="", over=False))
    assert first.phrase == "Review 1/2"
    sent_back = (run("plan"), run("execute"), run("review", verdict=CHANGED))
    assert stands(REVIEWED, *sent_back).phrase == "Fixing (round 1)"
    fixing = replace(run("execute", end="", over=False), attempt=2)
    assert stands(REVIEWED, *sent_back, fixing).phrase == "Fixing (round 1)"
    again = stands(REVIEWED, *sent_back, replace(run("execute"), attempt=2))
    assert again.phrase == "Review 2/2"


def test_a_gate_with_no_work_before_it_fixes_in_rounds():
    review = run("review", verdict=CHANGED)
    assert stands("review-only", review).phrase == "Fixing (round 1)"


def test_a_question_says_what_it_waits_for():
    plan_gate = questions.asked(
        "p1", "s1", "2026-10-08T11:00:00+00:00", [questions.one("?")],
        kind=questions.PLAN_APPROVAL, pass_="P", stage="person", purpose="gate",
    )  # fmt: skip
    waits = stands("plan-person-execute", run("plan"), plan_gate)
    assert (waits.phrase, waits.tone) == ("Waits for you · plan approval", "warn")
    assert stands("plan-execute-person", run("plan"), run("execute"), gate("person")).phrase == (
        "Waits for you · a decision"
    )
    escalated = questions.escalated(gate("person"), {"name": "kettle"}, "a person's", "now")
    assert stands("plan-execute-person", run("plan"), escalated).phrase == "Escalated"


def test_a_coordinator_gate_waits_for_the_coordinator():
    waits = stands("plan-execute-coordinator", run("plan"), run("execute"), gate("coordinator"))
    assert waits.phrase == "Waits for the coordinator · a decision"


def test_the_last_round_waits_on_its_cap():
    entries = [
        run("plan"),
        run("execute"),
        run("review", verdict=CHANGED),
        replace(run("execute"), attempt=2),
        run("review", verdict=CHANGED),
    ]
    assert stands(REVIEWED, *entries).phrase == "Waits for you · round cap"
    cap = gate("review", purpose=ROUND_CAP)
    assert stands(REVIEWED, *entries, cap).phrase == "Waits for you · round cap"


def test_a_run_parked_on_its_own_question_waits_with_its_kind():
    asked = questions.asked(
        "p1", "s1", "2026-10-08T11:00:00+00:00", [questions.one("Which?")],
        kind=questions.PERMISSION, run="run-x",
    )  # fmt: skip
    parked = parked_on(run("execute", end="denied", over=False), asked)
    shown = stands(REVIEWED, run("plan"), parked, parks=[asked])
    assert shown.phrase == "Waits for you · a permission"


def test_a_usage_hold_says_when_it_comes_back():
    reset = NOW + timedelta(hours=2)
    held = run("execute", end="limit", over=False)
    (turn,) = held.turns
    held = replace(held, turns=(replace(turn, resets=reset.isoformat()),))
    shown = stands(REVIEWED, run("plan"), held)
    assert (shown.phrase, shown.tone) == (f"Parked until {until_words(reset, NOW)}", "")
    resets = (NOW + timedelta(days=2)).isoformat()
    card = questions.asked(
        "p1", "s1", "2026-10-08T11:00:00+00:00", [questions.one("?")], kind=questions.LIMIT,
        pass_="P", stage="execute", purpose=ESCALATION, resets=resets,
    )  # fmt: skip
    later = stands(REVIEWED, run("plan"), card).phrase
    assert later == f"Parked until {until_words(NOW + timedelta(days=2), NOW)}"


def test_a_reset_today_is_a_time_and_another_day_carries_its_date():
    assert ":" in until_words(NOW, NOW) and not any(c.isalpha() for c in until_words(NOW, NOW))
    assert any(c.isalpha() for c in until_words(NOW + timedelta(days=3), NOW))


@pytest.mark.parametrize(
    ("last", "phrase", "tone"),
    [
        (run("execute", end="stopped"), "Stopped", "bad"),
        (gate("person", STOP), "Stopped", "bad"),
        (gate("person", PASS), "Done", "good"),
    ],
)
def test_a_pass_that_ended_says_how(last, phrase, tone):
    shown = stands("plan-execute-person", run("plan"), run("execute"), last)
    assert (shown.phrase, shown.tone, shown.ended) == (phrase, tone, True)


def test_changes_from_a_person_send_the_work_back():
    shown = stands("plan-execute-person", run("plan"), run("execute"), gate("person", CHANGES))
    assert shown.phrase == "Fixing (round 1)" and not shown.ended


def test_the_description_marks_the_stage_the_pass_stands_at():
    shown = stands(REVIEWED, run("plan"), run("execute"), run("review", end="", over=False))
    lines = describe(shown).splitlines()
    assert lines[0].startswith("Review 1/2 · ") and "(pass P)" in lines[0]
    assert [line for line in lines if line.startswith("▸")] == ["▸ review (other agent)"]
    done = stands(REVIEWED, run("plan"), run("execute"), run("review", verdict=PASSED))
    assert not any(line.startswith("▸") for line in describe(done).splitlines())


def test_nothing_written_yet_reads_as_the_first_stage_due():
    assert stands(REVIEWED).phrase == "Planning"


def test_a_pass_that_ended_is_shown_for_a_day_and_one_under_way_always(tmp_path):
    from dplanner.domain import ledger
    from dplanner.domain.model import Step
    from dplanner.modules.step_playbook.engine import ENDED_SHOWN, standing_of, standings

    working, finished = Step(title="Working"), Step(title="Finished")
    pinned = settings(REVIEWED).to_json()
    for step, verdict in ((working, None), (finished, PASSED)):
        made = [replace(run("plan"), settings=pinned), run("execute")]
        made.append(run("review", verdict=PASSED) if verdict else run("review", end="", over=False))
        for record in made:
            ledger.write(tmp_path, replace(record, step=step.id, pass_=f"P-{step.title}"))
    ended_at = datetime.fromisoformat(ledger.records(tmp_path)[-1].launched)
    soon, later = ended_at + timedelta(hours=1), ended_at + ENDED_SHOWN + timedelta(hours=1)
    assert {k: s.phrase for k, s in standings(tmp_path, [working, finished], soon).items()} == {
        working.id: "Review 1/2",
        finished.id: "Done",
    }
    assert list(standings(tmp_path, [working, finished], later)) == [working.id]
    # `playbook show` says how the last pass ended, however long ago.
    shown = standing_of(tmp_path, finished, later)
    assert shown is not None and shown.phrase == "Done"
