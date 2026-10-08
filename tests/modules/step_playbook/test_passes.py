"""Where a pass stands and what is due next: ``passes.due`` over records made by hand.

Each test writes the runs and questions a pass would have left — in the order they were
made — and asks what the engine does next. No process, no file: the derivation is pure."""

from collections.abc import Mapping
from itertools import count

import pytest

from dplanner.domain import questions
from dplanner.domain.headless import StageKind
from dplanner.domain.ledger import HEADLESS, LedgerRecord, Turn
from dplanner.domain.questions import Question
from dplanner.modules.step_playbook.aspect import Choice
from dplanner.modules.step_playbook.passes import (
    ACCEPT,
    CHANGES,
    ESCALATION,
    FIX,
    GATE,
    ONE_MORE,
    PASS,
    RETRY,
    ROUND_CAP,
    STOP,
    Ask,
    Complete,
    Entry,
    Facts,
    Halted,
    Launch,
    Progress,
    Settings,
    Wait,
    due,
    in_order,
    pinned,
)
from dplanner.modules.step_playbook.presets import preset

_clock = count()


def _at() -> str:
    return f"2026-10-08T10:00:00.{next(_clock):06d}+00:00"


def run(
    stage: str,
    *,
    end: str = "done",
    verdict: Mapping[str, object] | None = None,
    session: str = "",
    harness: str = "claude",
    declined: tuple[Mapping[str, object], ...] = (),
    over: bool = True,
) -> LedgerRecord:
    at = _at()
    turn = Turn(n=1, prompt="launch", started=at, ended=at if end else "", end=end)
    return LedgerRecord(
        run=f"run-{next(_clock)}",
        project="p1",
        step="s1",
        harness=harness,
        launched=at,
        session=session,
        ended=at if over and end in ("done", "stopped") else "",
        mode=HEADLESS,
        pass_="P",
        stage=stage,
        attempt=1,
        turns=(turn,),
        verdict=verdict,
        declined=declined,
    )


def gate(stage: str, answer: str = "", purpose: str = GATE, state: str = "") -> Question:
    asked = questions.asked(
        "p1", "s1", _at(), [questions.one("?")], pass_="P", stage=stage, purpose=purpose
    )
    if answer:
        asked = questions.answered(asked, {"?": answer}, {"kind": "person"}, _at())
    if state == questions.CONSUMED:
        asked = questions.settled_by_pass(asked, _at())
    if state == questions.WITHDRAWN:
        asked = questions.withdrawn(asked, "gone", _at())
    return asked


CHANGED = {
    "outcome": "changes",
    "summary": "One race",
    "findings": [
        {"severity": "high", "file": "a.py", "line": 3, "text": "A race", "evidence": "x"}
    ],
}
PASSED = {"outcome": "pass", "summary": "Good", "findings": []}


def settings(playbook_id: str, rounds: int = 2) -> Settings:
    return Settings(playbook_id, 1, rounds, "claude", "codex")


def next_of(playbook_id: str, *entries, rounds: int = 2, **facts):
    playbook = preset(playbook_id)
    assert playbook is not None
    return due(playbook, settings(playbook_id, rounds), list(entries), Facts(**facts))


# -- the happy paths ---------------------------------------------------------------------------


def test_a_pass_begins_at_its_first_stage_or_at_its_first_gate_for_work_under_review():
    first = next_of("plan-execute-review-other")
    assert isinstance(first, Launch) and (first.stage, first.kind) == ("plan", StageKind.PLAN)
    assert first.attempt == 1 and first.resume is None
    at_review = next_of("plan-execute-review-other", at_review=True)
    assert isinstance(at_review, Launch) and at_review.stage == "review"
    assert at_review.harness == "codex"  # The other agent.
    person = next_of("plan-execute-person", at_review=True)
    assert isinstance(person, Ask) and (person.stage, person.purpose) == ("person", GATE)


def test_execute_resumes_the_plans_session_and_is_handed_the_plan_approved():
    plan = run("plan", session="sess-1")
    execute = next_of("plan-execute-review-self", plan)
    assert isinstance(execute, Launch) and execute.kind is StageKind.EXECUTE
    assert execute.resume == plan and execute.plan == plan


def test_a_gate_after_a_plan_asks_for_its_approval_with_the_plan():
    plan = run("plan", session="s")
    asked = next_of("plan-person-execute", plan)
    assert isinstance(asked, Ask) and asked.kind == questions.PLAN_APPROVAL and asked.plan == plan
    after_work = next_of("plan-execute-person", run("plan"), run("execute"))
    assert isinstance(after_work, Ask) and after_work.kind == questions.DECISION


def test_a_review_that_passes_ends_the_pass_and_a_spike_approved_sets_the_step_done():
    done = next_of(
        "plan-execute-review-self", run("plan"), run("execute"), run("review", verdict=PASSED)
    )
    assert isinstance(done, Complete) and not done.set_done
    spike = next_of("spike", run("plan"), gate("person", PASS))
    assert isinstance(spike, Complete) and spike.set_done


def test_progress_is_due_after_the_work_and_its_gate_answer_goes_on():
    assert isinstance(next_of("plan-execute-progress", run("plan"), run("execute")), Progress)
    accepted = next_of("plan-execute-progress", run("plan"), run("execute"), gate("progress", PASS))
    assert isinstance(accepted, Complete)


# -- gates, rounds and loop-back ---------------------------------------------------------------


def test_changes_go_back_to_the_work_in_its_session_with_the_findings():
    execute = run("execute", session="work")
    review = run("review", verdict=CHANGED, session="fresh")
    fix = next_of("plan-execute-review-self", run("plan", session="plan"), execute, review)
    assert isinstance(fix, Launch) and (fix.stage, fix.attempt) == ("execute", 2)
    assert fix.resume == execute  # Never the reviewer's session.
    (finding,) = fix.findings
    assert finding["text"] == "A race" and finding["ref"] == {"run": review.run, "index": 0}


def test_a_gate_with_no_work_before_it_sends_the_work_to_a_fix():
    fix = next_of("review-only", run("review", verdict=CHANGED))
    assert isinstance(fix, Launch) and (fix.stage, fix.kind, fix.resume) == (
        FIX,
        StageKind.EXECUTE,
        None,
    )
    again = next_of("review-only", run("review", verdict=CHANGED), run(FIX, session="f"))
    assert isinstance(again, Launch) and (again.stage, again.attempt) == ("review", 2)


def test_a_landing_executes_is_reviewed_by_the_other_agent_and_ends_at_a_person_unmerged():
    first = next_of("land")
    assert isinstance(first, Launch) and (first.stage, first.kind) == ("execute", StageKind.EXECUTE)
    execute = run("execute", session="land")
    review = next_of("land", execute)
    assert isinstance(review, Launch) and (review.stage, review.harness) == ("review", "codex")
    back = next_of("land", execute, run("review", verdict=CHANGED, harness="codex"))
    assert isinstance(back, Launch) and (back.stage, back.resume) == ("execute", execute)
    passed = [execute, run("review", verdict=PASSED, harness="codex")]
    person = next_of("land", *passed)
    assert isinstance(person, Ask) and (person.stage, person.purpose) == ("person", GATE)
    # The mainline is a person's to merge: the pass ends without a merge or a status of its own.
    through = next_of("land", *passed, gate("person", PASS))
    assert through == Complete("Land: execute ⇄ review (other agent) → human review is through")


def test_a_person_sending_the_plan_back_reruns_the_plan_with_the_note():
    plan = run("plan", session="s")
    back = next_of("plan-person-execute", plan, gate("person", "Changes: split it in two"))
    assert isinstance(back, Launch) and back.stage == "plan" and back.resume == plan
    assert back.findings[0]["text"] == "split it in two"


def test_the_last_round_escalates_instead_of_buying_another():
    entries = [run("plan"), run("execute"), run("review", verdict=CHANGED)]
    capped = next_of("plan-execute-review-self", *entries, rounds=1)
    assert isinstance(capped, Ask) and (capped.purpose, capped.kind) == (
        ROUND_CAP,
        questions.DECISION,
    )
    assert "A race" in capped.body
    one_more = gate("review", ONE_MORE, ROUND_CAP)
    fix = next_of("plan-execute-review-self", *entries, one_more, rounds=1)
    assert isinstance(fix, Launch) and fix.stage == "execute" and fix.findings
    # The round it bought is spent by the next verdict, and then it asks again.
    later = [*entries, one_more, run("execute"), run("review", verdict=CHANGED)]
    assert isinstance(next_of("plan-execute-review-self", *later, rounds=1), Ask)
    accepted = next_of(
        "plan-execute-review-self", *entries, gate("review", ACCEPT, ROUND_CAP), rounds=1
    )
    assert isinstance(accepted, Complete)
    stopped = next_of(
        "plan-execute-review-self", *entries, gate("review", STOP, ROUND_CAP), rounds=1
    )
    assert isinstance(stopped, Halted)


def test_a_declined_finding_reaches_the_next_round_and_the_round_cap():
    review = run("review", verdict=CHANGED)
    reason = {"finding": {"run": review.run, "index": 0}, "reason": "It cannot race"}
    fix = run("execute", declined=(reason,))
    second = next_of("plan-execute-review-self", run("plan"), run("execute"), review, fix)
    assert isinstance(second, Launch) and second.history[0]["declined"] == "It cannot race"


def test_a_pass_stands_after_a_later_gates_fix():
    playbook = preset("review-only")
    assert playbook is not None
    entries: list[Entry] = [run("review", verdict=PASSED), gate("person", CHANGES + ": tweak it")]
    fix = due(playbook, settings("review-only"), entries, Facts())
    assert isinstance(fix, Launch) and fix.stage == FIX
    after_fix = due(playbook, settings("review-only"), [*entries, run(FIX)], Facts())
    # The review passed before the person asked for changes: it is not run again.
    assert isinstance(after_fix, Ask) and after_fix.stage == "person"


# -- what is not a verdict -----------------------------------------------------------------------


def test_a_review_with_no_verdict_escalates_and_retry_runs_it_again():
    entries = [run("plan"), run("execute"), run("review")]
    asked = next_of("plan-execute-review-self", *entries)
    assert isinstance(asked, Ask) and asked.purpose == ESCALATION
    retried = next_of("plan-execute-review-self", *entries, gate("review", RETRY, ESCALATION))
    assert isinstance(retried, Launch) and (retried.stage, retried.attempt) == ("review", 2)


def test_a_failed_review_spends_no_round():
    entries = [run("plan"), run("execute"), run("review"), gate("review", RETRY, ESCALATION)]
    entries.append(run("review", verdict=CHANGED))
    fix = next_of("plan-execute-review-self", *entries, rounds=1)
    # One verdict given, the cap is one: that verdict was the last round, not the failure.
    assert isinstance(fix, Ask) and fix.purpose == ROUND_CAP


@pytest.mark.parametrize(
    ("last", "expected"),
    [
        (run("execute", end="", over=False), Wait),
        (run("execute", end="limit", over=False), Wait),
        (run("execute", end="stopped"), Halted),
        (gate("person"), Wait),
        (gate("person", state=questions.WITHDRAWN), Halted),
        (gate("person", STOP), Halted),
    ],
)
def test_a_pass_waits_on_what_runs_or_asks_and_halts_on_what_stopped(last, expected):
    assert isinstance(next_of("plan-execute-person", run("plan"), last), expected)


def test_a_step_set_done_by_hand_completes_its_pass():
    assert isinstance(next_of("plan-execute-person", run("plan"), done=True), Complete)


# -- pinning and order ---------------------------------------------------------------------------


def test_a_pass_pins_its_roles_and_refuses_one_nobody_runs():
    playbook = preset("plan-execute-review-other")
    assert playbook is not None
    pin = pinned(playbook, None, "claude", ("claude", "codex"))
    assert (pin.implementer, pin.reviewer, pin.rounds) == ("claude", "codex", 2)
    alone = pinned(playbook, None, "claude", ("claude",))
    assert alone.reviewer == "claude"  # The same vendor, fresh: still the control.
    both = ("claude", "codex")
    chosen = pinned(playbook, Choice(playbook, rounds=3, reviewer="codex"), "claude", both)
    assert chosen.rounds == 3 and chosen.overrides == {"rounds": 3.0, "reviewer": "codex"}
    with pytest.raises(ValueError, match="codex"):
        pinned(playbook, Choice(playbook, reviewer="codex"), "claude", ("claude",))
    with pytest.raises(ValueError, match="opencode"):
        pinned(playbook, None, "opencode", ("claude",))
    assert Settings.from_json(pin.to_json()) == pin


def test_records_are_read_in_the_order_they_were_made():
    first, second = run("plan"), gate("person")
    assert in_order([first], [second]) == [first, second]
    assert in_order([], [second]) + in_order([first], []) == [second, first]


# -- Kettle Watch round 1 ---------------------------------------------------------------------


def test_a_verdict_that_does_not_validate_is_no_verdict():
    """opencode, with no schema flag, ended on a bare outcome: that is no verdict."""
    entries = [run("plan"), run("execute"), run("review", verdict={"outcome": "pass"})]
    asked = next_of("plan-execute-review-self", *entries)
    assert isinstance(asked, Ask) and asked.purpose == ESCALATION


@pytest.mark.parametrize(
    "said", ["Pass only after fixing the race", "pass, but rename it", "Approve", "Accept"]
)
def test_only_the_gates_own_pass_label_approves_and_other_words_are_changes(said):
    plan = run("plan", session="s")
    back = next_of("plan-person-execute", plan, gate("person", said))
    assert isinstance(back, Launch) and back.stage == "plan"
    assert back.findings[0]["text"] == said
    for exactly in ("Pass", " pass. ", "PASS"):
        assert isinstance(next_of("plan-person-execute", plan, gate("person", exactly)), Launch)
        assert next_of("plan-person-execute", plan, gate("person", exactly)).stage == "execute"


def test_one_more_round_after_a_persons_changes_carries_the_persons_note():
    entries: list[Entry] = [run("plan"), run("execute"), gate("person", "Rename the flag")]
    capped = next_of("plan-execute-person", *entries, rounds=1)
    assert (
        isinstance(capped, Ask) and capped.purpose == ROUND_CAP and "Rename the flag" in capped.body
    )
    fix = next_of("plan-execute-person", *entries, gate("person", ONE_MORE, ROUND_CAP), rounds=1)
    assert isinstance(fix, Launch) and fix.stage == "execute"
    (finding,) = fix.findings
    assert finding["text"] == "Rename the flag" and "question" in finding["ref"]


def test_a_refused_launch_is_retried_on_retry_now_or_the_clock_and_stopped_on_stop():
    entries: list[Entry] = [run("plan", session="s")]
    card = questions.asked(
        "p1", "s1", _at(), [questions.one("?")], kind=questions.LIMIT,
        pass_="P", stage="execute", attempt=1, purpose=ESCALATION,
    )  # fmt: skip
    assert isinstance(next_of("plan-execute-person", *entries, card), Wait)
    retried = questions.answered(card, {"?": questions.RETRY_NOW}, {"kind": "person"}, _at())
    again = next_of("plan-execute-person", *entries, retried)
    assert isinstance(again, Launch) and (again.stage, again.attempt) == ("execute", 1)
    clocked = questions.answered(card, {"?": "reset"}, {"kind": questions.CLOCK}, _at())
    assert isinstance(next_of("plan-execute-person", *entries, clocked), Launch)
    stopped = questions.answered(card, {"?": STOP}, {"kind": "person"}, _at())
    assert isinstance(next_of("plan-execute-person", *entries, stopped), Halted)


def test_the_coordinator_may_not_answer_a_progress_gate():
    progress = gate("progress")
    assert questions.may_answer(progress, questions.COORDINATOR)
    assert not questions.may_answer(progress, questions.PERSON)
    assert not questions.may_answer(gate("coordinator"), questions.COORDINATOR)
