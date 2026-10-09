"""A person's verdict on a pass, under both surfaces' one verb: ``playbook accept`` and
``playbook send-back``, driven over the real engine and supervisor with the fake agent CLI —
the review panel's buttons run exactly these."""

import json

from tests.modules.agent_supervisor.test_supervisor import INIT, result
from tests.modules.step_playbook.test_engine import done

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
