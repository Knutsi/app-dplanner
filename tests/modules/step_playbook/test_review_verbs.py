"""A person's verdict on a pass, under both surfaces' one verb: ``playbook accept`` and
``playbook send-back``, driven over the real engine and supervisor with the fake agent CLI —
the review panel's buttons run exactly these."""

import json
from dataclasses import replace

from tests.modules.agent_supervisor.test_supervisor import INIT, result
from tests.modules.step_playbook.test_engine import done
from tests.modules.step_playbook.test_passes import gate

from dplanner.domain import questions
from dplanner.modules.agent_supervisor import supervisor
from dplanner.modules.step_playbook.passes import LOOK, ROUND_CAP


def _status(cli) -> str:
    return str(json.loads(cli("status", "show", "Build it", "--json"))["status"])


def _through(drive, playbook: str = "execute") -> None:
    """A pass of ``playbook`` driven to its end: nothing left but a person's look."""
    drive.cli("playbook", "set", "Build it", playbook)
    drive.cli("agent", "run", "Build it", "--playbook")
    drive.supervise()
    assert "is through" in drive.advance()


def test_accepting_a_pass_that_is_through_sets_the_step_done_as_a_persons_decision(drive):
    drive.play({"lines": [INIT, result(typed=done())]})
    _through(drive)
    said = drive.cli("playbook", "accept", "Build it", "--because", "read the diff")
    assert "done" in said and _status(drive.cli) == "done"
    notes = json.loads(drive.cli("note", "list", "Widget", "--label", "decision", "--json"))
    (note,) = notes if isinstance(notes, list) else notes["notes"]
    assert note["title"] == "Accepted after its playbook"
    assert note["body"].startswith("Accepted after pass ") and "read the diff" in note["body"]
    # Done is done: neither verb has anything left to act on.
    assert "the step is done" in drive.cli("playbook", "accept", "Build it", expect=1)
    assert "the step is done" in drive.cli(
        "playbook", "send-back", "Build it", "--note", "x", expect=1
    )


def test_sending_a_pass_back_resumes_the_work_with_the_note_and_keeps_the_round_cap(drive):
    drive.play(
        {"lines": [INIT, result(typed=done(), session="w")]},
        {"lines": [INIT, result(typed=done(), session="w")]},
    )
    _through(drive)
    drive.advanced.clear()
    said = drive.cli("playbook", "send-back", "Build it", "--note", "the empty state says nothing")
    assert "its pass advances" in said and len(drive.advanced) == 1
    look = drive.asked()
    assert (look.stage, look.purpose, look.state) == (LOOK, "gate", "answered")
    drive.advance()
    fix = drive.latest()
    assert (fix.stage, fix.attempt, fix.session) == ("execute", 2, "w")
    assert "the empty state says nothing" in drive.prompt(fix)
    drive.supervise()
    assert "is through" in drive.advance()
    # The second send-back is the look's last round: the ordinary round cap asks.
    drive.cli("playbook", "send-back", "Build it", "--note", "still nothing")
    assert "round-cap" in drive.advance()
    capped = drive.asked()
    assert (capped.stage, capped.purpose) == (LOOK, ROUND_CAP)
    said = drive.cli("playbook", "send-back", "Build it", "--note", "x", expect=1)
    assert "Control Centre" in said


def test_on_an_open_gate_the_verbs_are_its_answers(drive):
    drive.play(
        {"lines": [INIT, result("A plan", session="s")]},
        {"lines": [INIT, result(typed=done(), session="s")]},
    )
    drive.cli("playbook", "set", "Build it", "plan-execute-person")
    drive.cli("agent", "run", "Build it", "--playbook")
    drive.supervise()
    drive.advance()
    drive.supervise()
    assert "person asks" in drive.advance()
    gate = drive.asked()
    drive.cli("playbook", "send-back", "Build it", "--note", "name the lock")
    answered = drive.asked()
    assert answered.id == gate.id and answered.answer["answers"] == {
        gate.text: "Changes: name the lock"
    }
    drive.advance()
    assert drive.latest().attempt == 2 and "name the lock" in drive.prompt(drive.latest())
    drive.supervise()
    drive.advance()
    second = drive.asked()
    assert second.id != gate.id
    drive.cli("playbook", "accept", "Build it")
    assert drive.asked().answer["answers"] == {second.text: "Pass"}
    assert "is through" in drive.advance()
    assert _status(drive.cli) != "done"  # A gate's Pass moves the pass; done is a later look.


def _looks(drive) -> list[questions.Question]:
    return [q for q in questions.records(drive.plan) if q.stage == LOOK]


def _pass_id(drive) -> str:
    return str(drive.latest().pass_)


def test_a_verdict_on_a_pass_a_newer_run_has_superseded_is_refused(drive):
    """A plain run started on the step after the pass ended: while it runs no verdict acts, and
    once it is over the pass is not the step's latest work — Send Back would launch a fix
    beside it, and Accept set done work nobody looked at."""
    drive.play(
        {"lines": [INIT, result(typed=done())]},
        {"lines": [INIT, result(typed=done())]},
    )
    _through(drive)
    pass_id = _pass_id(drive)
    drive.cli("agent", "run", "Build it")
    plain = drive.latest()
    assert not plain.pass_
    said = drive.cli("playbook", "accept", "Build it", "--pass", pass_id, expect=1)
    assert f"run {plain.run} on it is not over" in said
    drive.supervise()
    for verb in (("accept",), ("send-back", "--note", "x")):
        said = drive.cli("playbook", *verb, "Build it", "--pass", pass_id, expect=1)
        assert f"run {plain.run}, of no playbook, is newer work" in said
    assert _status(drive.cli) != "done" and not _looks(drive)


def test_a_verdict_names_the_pass_and_the_run_it_was_given_on(drive):
    """Sent back and through again, the pass is the same pass with newer work: Accept as the
    person saw it before the fix is refused, and a newer pass refuses one on the older."""
    drive.play(
        {"lines": [INIT, result(typed=done(), session="w")]},
        {"lines": [INIT, result(typed=done(), session="w")]},
        {"lines": [INIT, result(typed=done(), session="v")]},
    )
    _through(drive)
    first, seen = _pass_id(drive), drive.latest().run
    drive.cli("playbook", "send-back", "Build it", "--note", "the empty state says nothing")
    drive.advance()
    fix = drive.latest()
    drive.supervise()
    assert "is through" in drive.advance()
    said = drive.cli(
        "playbook", "accept", "Build it", f"--pass={first}", f"--run={seen}", "--question=",
        expect=1,
    )  # fmt: skip
    assert f"has run since — its latest is {fix.run}" in said and _status(drive.cli) != "done"
    drive.cli("agent", "run", "Build it", "--playbook")
    drive.supervise()
    drive.advance()
    said = drive.cli("playbook", "accept", "Build it", f"--pass={first}", expect=1)
    assert f"pass {first} is no longer its latest — {_pass_id(drive)} is" in said
    # Named as it stands — or left to default to it — the verdict acts, and says on what.
    said = drive.cli("playbook", "accept", "Build it", f"--pass={_pass_id(drive)}")
    assert f"(pass {_pass_id(drive)}, run {drive.latest().run})" in said
    assert _status(drive.cli) == "done"


def test_a_gate_answer_names_the_gate_it_was_given_on(drive):
    """The tab showed Q1 open: Pass meant Q1. Once Q1 is answered — the pass through, or at a
    newer gate — the same click is refused, never read as the look's Accept or Q2's Pass."""
    drive.play(
        {"lines": [INIT, result("A plan", session="s")]},
        {"lines": [INIT, result(typed=done(), session="s")]},
        {"lines": [INIT, result(typed=done(), session="s")]},
    )
    drive.cli("playbook", "set", "Build it", "plan-execute-person")
    drive.cli("agent", "run", "Build it", "--playbook")
    drive.supervise()
    drive.advance()
    drive.supervise()
    drive.advance()
    first = drive.asked()
    drive.cli("playbook", "send-back", "Build it", "--note", "name the lock")
    drive.advance()
    drive.supervise()
    drive.advance()
    second = drive.asked()
    said = drive.cli("playbook", "accept", "Build it", f"--question={first.id}", expect=1)
    assert f"{first.short} is no longer the gate it waits on" in said
    said = drive.cli("playbook", "send-back", "Build it", "--note", "x", "--question=", expect=1)
    assert f"now waits on {second.short}" in said
    drive.cli("playbook", "accept", "Build it", f"--question={second.id}")
    assert "is through" in drive.advance()
    said = drive.cli("playbook", "accept", "Build it", f"--question={second.id}", expect=1)
    assert f"{second.short} is no longer the gate it waits on" in said
    assert _status(drive.cli) != "done"


def test_accept_waits_for_a_recorded_pr_that_is_not_merged(drive):
    drive.play({"lines": [INIT, result(typed=done())]})
    _through(drive)
    drive.cli("github", "set", "Build it", "--pr", "12")
    said = drive.cli("playbook", "accept", "Build it", f"--pass={_pass_id(drive)}", expect=1)
    assert "its PR is open" in said and _status(drive.cli) != "done"


def test_a_verdict_holds_the_steps_launch_lock_until_its_follow_ups_are_done(
    drive, at_work_board, monkeypatch
):
    """No advance, launch or other verdict reads the pass between a verdict's check and what
    it wrote reaching the plan — the gate's answer, and the done status's claim ended."""
    drive.play({"lines": [INIT, result(typed=done())]})
    _through(drive)
    run = drive.latest()
    held: list[bool] = []

    def probe(*_args, **_kwargs) -> bool:
        try:
            with supervisor.launching(run.project, run.step):
                held.append(False)
        except BlockingIOError:
            held.append(True)
        return True

    monkeypatch.setattr(at_work_board, "end", probe)
    drive.cli("playbook", "accept", "Build it")
    assert held == [True]
    monkeypatch.setattr(supervisor, "spawn_detached", lambda *_a, **_k: probe())
    drive.cli("status", "set", "Build it", "ready-for-review")
    held.clear()
    drive.cli("playbook", "send-back", "Build it", "--note", "again")
    assert held == [True]


def test_a_pass_that_is_through_is_a_persons_look_never_an_agents(drive, monkeypatch):
    """From an agent's shell neither verb gives the look — Accept would set the step done on
    an agent's word — and the look's gate is one only a person answers."""
    drive.play({"lines": [INIT, result(typed=done())]})
    _through(drive)
    monkeypatch.setenv("CLAUDECODE", "1")  # Claude Code's shell marker, no run named.
    for verb in (("accept", "--because", "it reads well"), ("send-back", "--note", "x")):
        said = drive.cli("playbook", *verb, "Build it", expect=1)
        assert "waits on a person's look — an agent escalates it, never gives it" in said
    assert _status(drive.cli) != "done" and not _looks(drive)
    look = replace(gate(LOOK), state=questions.OPEN)
    assert questions.may_answer(look, questions.COORDINATOR)
    assert LOOK in questions.PERSON_ONLY
