"""``dplanner playbook stop``: a pass stopped in every state it can be in — a live turn, a
supervisor waiting out a reset, a parked run, a run never started, an orphaned turn, a stage
between turns, a question of the pass — and nothing of it ever starting again by itself.

The real supervisor drives each run in-process over the fake agent CLI (``test_engine``'s
``Driver``); a live supervisor is stopped by the stop's own SIGTERM, sent to this process,
whose supervisor lock it holds. Never a real agent CLI, never a model API.
"""

import json
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests.modules.agent_supervisor.test_supervisor import INIT, limit_at, result
from tests.modules.step_playbook.test_engine import _status
from tests.platforms import PROCESS_ENVIRONMENTS

from dplanner.core.process import is_live, stamp_of
from dplanner.domain import claims, ledger, questions
from dplanner.domain.ledger import Turn
from dplanner.domain.model import now_stamp
from dplanner.modules.agent_supervisor import supervisor
from dplanner.modules.step_playbook import engine

STEP = "Build it"


def stop(drive, *, expect: int = 0) -> str:
    return str(drive.cli("playbook", "stop", STEP, expect=expect))


def stop_while(drive, ready) -> list[str]:
    """Stop the pass from another thread once ``ready()`` holds, while the main thread's
    supervisor drives the run: the stop's SIGTERM reaches it as a real one would."""
    said: list[str] = []

    def stopping() -> None:
        deadline = time.monotonic() + 20
        while not ready() and time.monotonic() < deadline:
            time.sleep(0.02)
        said.append(stop(drive))

    thread = threading.Thread(target=stopping)
    thread.start()
    drive.supervise()
    thread.join()
    return said


def nothing_restarts(drive, cli_library, monkeypatch) -> None:
    """Every way a pass moves by itself finds nothing to do: its runs are over, an advance
    reads it halted, a machine's start revives nothing, and a second stop has nothing left."""
    runs = [r for r in ledger.records(drive.plan) if r.pass_]
    assert runs and all(r.over for r in runs)
    launched = len(drive.started)
    assert "stopped" in drive.advance() or "withdrawn" in drive.advance()
    revived: list[str] = []
    monkeypatch.setattr(supervisor, "start_detached", lambda _d, run, **_k: revived.append(run))
    supervisor.revive([drive.plan], library=cli_library, grace=0)
    assert revived == [] and len(drive.started) == launched
    assert "nothing to stop" in stop(drive)


def test_a_live_turn_is_ended_and_the_step_goes_back_to_pending(drive, cli_library, monkeypatch):
    drive.cli("playbook", "set", STEP, "execute")
    drive.play({"lines": [INIT], "hold": 30})
    drive.cli("agent", "run", STEP, "--playbook")
    assert _status(drive.cli, STEP) == "in-progress"
    began = time.monotonic()
    (said,) = stop_while(drive, lambda: bool(drive.latest().turns))
    assert time.monotonic() - began < 15
    record = drive.latest()
    assert record.over and record.fence and record.last_turn.end == "stopped"
    assert "execute attempt 1 was running" in said and "it reads pending" in said
    assert "worktree and branch are kept" in said
    assert _status(drive.cli, STEP) == "pending"
    nothing_restarts(drive, cli_library, monkeypatch)


def test_a_supervisor_waiting_out_a_usage_reset_is_stopped(drive, cli_library, monkeypatch):
    drive.cli("playbook", "set", STEP, "execute")
    drive.play({"lines": limit_at(time.time() + 3600), "exit": 1})
    drive.cli("agent", "run", STEP, "--playbook")
    (said,) = stop_while(drive, lambda: drive.latest().parked)
    record = drive.latest()
    assert record.over and record.fence
    (limit,) = questions.of_run(drive.plan, record.run)
    assert limit.state == questions.WITHDRAWN  # Neither the clock nor Retry now answers it.
    assert "parked" in said
    nothing_restarts(drive, cli_library, monkeypatch)


def test_a_parked_run_nobody_supervises_is_ended_and_its_question_withdrawn(
    drive, cli_library, monkeypatch
):
    drive.cli("playbook", "set", STEP, "execute")
    drive.play({"lines": [INIT], "exit": 1, "stderr": "Error: 401 Unauthorized — not logged in"})
    drive.cli("agent", "run", STEP, "--playbook")
    parked = drive.supervise()
    assert parked.parked
    said = stop(drive)
    assert "execute attempt 1 was parked" in said
    record = drive.latest()
    assert record.over and record.fence
    assert {q.state for q in questions.of_run(drive.plan, record.run)} == {questions.WITHDRAWN}
    drive.cli("agent", "retry", STEP, expect=1)
    nothing_restarts(drive, cli_library, monkeypatch)


def test_a_run_whose_supervisor_never_started_is_ended(drive, cli_library, monkeypatch):
    drive.cli("playbook", "set", STEP, "execute")
    drive.cli("agent", "run", STEP, "--playbook")  # Its supervisor is captured, never run.
    assert "execute attempt 1 was not started" in stop(drive)
    assert drive.latest().over
    nothing_restarts(drive, cli_library, monkeypatch)


@pytest.fixture
def orphan(allow_spawn):
    from tests.launching import orphaned_turn

    with orphaned_turn() as stamp:
        yield stamp


def test_an_orphaned_turn_is_ended_by_its_recorded_stamp(drive, orphan, cli_library, monkeypatch):
    drive.cli("playbook", "set", STEP, "execute")
    drive.cli("agent", "run", STEP, "--playbook")
    turn = Turn(n=1, prompt="launch", started=now_stamp(), pid=orphan.pid, boot=orphan.boot,
                pid_started=orphan.started)  # fmt: skip
    supervisor.update(drive.plan, drive.latest().run, lambda r: r.with_turns((turn,)))
    assert "was running" in stop(drive)
    assert not is_live(orphan) and drive.latest().over
    nothing_restarts(drive, cli_library, monkeypatch)


def test_a_stage_done_whose_advance_has_not_run_is_stopped_between_stages(
    drive, cli_library, monkeypatch
):
    drive.cli("playbook", "set", STEP, "spike")
    drive.play({"lines": [INIT, result("A plan", session="s")]})
    drive.cli("agent", "run", STEP, "--playbook")
    drive.supervise()  # The plan is done, and its advance is still to come.
    assert "plan attempt 1 was done" in stop(drive)
    assert "was stopped: the playbook was stopped" in drive.advance()
    assert questions.records(drive.plan) == []  # No gate was asked.
    nothing_restarts(drive, cli_library, monkeypatch)


def test_an_open_gate_is_withdrawn_and_cannot_be_answered(drive, cli_library, monkeypatch):
    drive.cli("playbook", "set", STEP, "spike")
    drive.play({"lines": [INIT, result("A plan", session="s")]})
    drive.cli("agent", "run", STEP, "--playbook")
    drive.supervise()
    drive.advance()
    gate = drive.asked()
    said = stop(drive)
    assert f"withdrew {gate.short}" in said
    drive.cli("--project", "Widget", "question", "answer", gate.short, "Pass", expect=1)
    nothing_restarts(drive, cli_library, monkeypatch)


def test_an_answer_not_yet_acted_on_is_withdrawn_too(drive, cli_library, monkeypatch):
    drive.cli("playbook", "set", STEP, "plan-person-execute")
    drive.play({"lines": [INIT, result("A plan", session="s")]})
    drive.cli("agent", "run", STEP, "--playbook")
    drive.supervise()
    drive.advance()
    gate = drive.asked()
    drive.answer(gate, "Pass")  # Its advance — the execute — is started detached, not run.
    assert f"withdrew {gate.short}" in stop(drive)
    withdrawn = questions.find(drive.plan, gate.id)
    assert withdrawn is not None and withdrawn.state == questions.WITHDRAWN
    nothing_restarts(drive, cli_library, monkeypatch)


def test_a_held_launchs_card_is_withdrawn_and_neither_clock_nor_retry_resumes_it(
    drive, cli_library, monkeypatch
):
    from dplanner.modules.agent_supervisor import limits

    drive.cli("playbook", "set", STEP, "plan-execute-person")
    drive.play({"lines": [INIT, result("A plan", session="s")]})
    drive.cli("agent", "run", STEP, "--playbook")
    drive.supervise()
    reset = datetime.now(UTC) + timedelta(hours=2)
    monkeypatch.setattr(limits, "hold", lambda *_a, **_k: "Claude Code is at 97 %")
    monkeypatch.setattr(limits, "held_until", lambda *_a, **_k: reset)
    drive.advance()
    card = drive.asked()
    assert card.kind == questions.LIMIT  # A `playbook wake` sleeps until its reset.
    assert f"withdrew {card.short}" in stop(drive)
    monkeypatch.setattr(limits, "hold", lambda *_a, **_k: "")
    assert "no longer waits" in engine.wake(drive.plan, card.id, sleep=lambda _s: None)
    drive.cli("--project", "Widget", "question", "answer", card.short, "Retry now", expect=1)
    nothing_restarts(drive, cli_library, monkeypatch)


def test_work_under_review_keeps_its_status(drive):
    drive.cli("status", "set", STEP, "ready-for-review")
    drive.cli("playbook", "set", STEP, "plan-execute-person")
    drive.cli("agent", "run", STEP, "--playbook")  # It starts at its gate.
    said = stop(drive)
    assert "reads" not in said and _status(drive.cli, STEP) == "ready-for-review"


def test_stopping_twice_says_so_and_a_new_pass_then_starts(drive):
    assert "nothing to stop" in stop(drive)  # No pass at all.
    drive.cli("playbook", "set", STEP, "execute")
    drive.cli("agent", "run", STEP, "--playbook")
    first = drive.latest()
    stop(drive)
    report = json.loads(drive.cli("playbook", "stop", STEP, "--json"))
    assert report == {"step": report["step"], "stopped": False}
    drive.cli("agent", "run", STEP, "--playbook")
    assert drive.latest().pass_ != first.pass_ and not drive.latest().over


def test_a_squads_step_is_released_from_its_claim(drive):
    drive.cli("claim", "take", STEP, "--callsign", "osprey", "--project", "widget")
    drive.cli("playbook", "set", STEP, "execute")
    drive.cli("agent", "run", STEP, "--playbook", "--callsign", "osprey-1")
    report = json.loads(drive.cli("playbook", "stop", STEP, "--json"))
    assert report["released"] and report["status"] == "pending" and report["stopped"]
    assert claims.read_holdings(drive.plan, now_stamp()) == {}


def test_what_a_stop_would_end_is_said_in_a_persons_words(drive, cli_library):
    """``stoppable``: what the confirmation names, and "" — greyed — once nothing is left."""
    from dplanner.cli.lookup import find_step
    from dplanner.domain.store import LibraryStore

    def said() -> str:
        store = LibraryStore(cli_library)
        try:
            return engine.stoppable(drive.plan, find_step(store.load(), STEP))
        finally:
            store.close()

    assert said() == ""
    drive.cli("playbook", "set", STEP, "spike")
    drive.play({"lines": [INIT, result("A plan", session="s")]})
    drive.cli("agent", "run", STEP, "--playbook")
    assert said() == "its plan stage is not started"
    drive.supervise()
    assert said() == "its plan stage is done, its next stage not yet begun"
    drive.advance()
    assert said() == f"its person stage waits on {drive.asked().short}"
    stop(drive)
    assert said() == ""


# -- what a stop must never leave behind (the S28 review's eight findings) -----------------------


@PROCESS_ENVIRONMENTS
def test_a_child_that_outlived_its_turns_leader_is_ended(drive, cli_library, monkeypatch):
    """The leader the turn recorded is gone; a child it started runs on in its group."""
    from tests.launching import group_of, orphaned_turn

    drive.cli("playbook", "set", STEP, "execute")
    drive.cli("agent", "run", STEP, "--playbook")
    run = drive.latest().run
    with orphaned_turn(run, leader_exits=True) as child:
        leader = group_of(child.pid)
        assert leader != child.pid and stamp_of(leader) is None
        turn = Turn(n=1, prompt="launch", started=now_stamp(), pid=leader, boot=child.boot,
                    pid_started="1")  # fmt: skip
        supervisor.update(drive.plan, run, lambda r: r.with_turns((turn,)))
        assert "was running" in stop(drive)
        assert not is_live(child) and drive.latest().over
    nothing_restarts(drive, cli_library, monkeypatch)


@PROCESS_ENVIRONMENTS
@pytest.mark.parametrize("claimed", [False, True], ids=["launch", "claimed-answer"])
def test_a_turn_whose_supervisor_died_before_writing_its_pid_is_ended(
    drive, cli_library, monkeypatch, claimed
):
    """The supervisor was killed between the spawn and the pid's write: a launch's turn is not
    in the record at all, an answer's is ``spawning`` with no pid. Its process carries the
    run all the same."""
    from tests.launching import orphaned_turn

    drive.cli("playbook", "set", STEP, "execute")
    drive.cli("agent", "run", STEP, "--playbook")
    run = drive.latest().run
    if claimed:
        turn = Turn(n=1, prompt="answer", started=now_stamp(), spawning=now_stamp(),
                    consumed={"question": "q", "answer": "a"})  # fmt: skip
        supervisor.update(drive.plan, run, lambda r: r.with_turns((turn,)))
    with orphaned_turn(run) as agent:
        stop(drive)
        assert not is_live(agent) and drive.latest().over
    nothing_restarts(drive, cli_library, monkeypatch)


def test_a_stop_waits_for_a_launch_holding_the_step_and_stops_what_it_began(
    drive, cli_library, monkeypatch
):
    begin, paused, go = engine.Engine.begin, threading.Event(), threading.Event()

    def held_begin(self, *args, **kwargs):
        paused.set()
        go.wait(10)
        return begin(self, *args, **kwargs)

    monkeypatch.setattr(engine.Engine, "begin", held_begin)
    drive.cli("playbook", "set", STEP, "execute")
    launch = threading.Thread(target=lambda: drive.cli("agent", "run", STEP, "--playbook"))
    launch.start()
    assert paused.wait(10)  # The launch holds the step's lock, its pass not yet written.
    said: list[str] = []
    stopping = threading.Thread(target=lambda: said.append(stop(drive)))
    stopping.start()
    stopping.join(0.5)
    assert said == []
    go.set()
    launch.join()
    stopping.join()
    assert "execute attempt 1 was not started" in said[0] and drive.latest().over
    nothing_restarts(drive, cli_library, monkeypatch)


def test_a_spikes_final_approval_answered_but_not_acted_on_is_withdrawn(
    drive, cli_library, monkeypatch
):
    drive.cli("playbook", "set", STEP, "spike")
    drive.play({"lines": [INIT, result("A plan", session="s")]})
    drive.cli("agent", "run", STEP, "--playbook")
    drive.supervise()
    drive.advance()
    gate = drive.asked()
    drive.answer(gate, "Pass")  # Its advance would mark the step done; it has not run.
    assert f"withdrew {gate.short}" in stop(drive)
    assert "withdrawn" in drive.advance() or "stopped" in drive.advance()
    assert _status(drive.cli, STEP) == "pending"
    nothing_restarts(drive, cli_library, monkeypatch)


def test_a_stop_whose_plan_change_did_not_land_is_finished_by_the_next(drive, monkeypatch):
    from dplanner.modules.agent_claims import ownership

    drive.cli("claim", "take", STEP, "--callsign", "osprey", "--project", "widget")
    drive.cli("playbook", "set", STEP, "execute")
    drive.cli("agent", "run", STEP, "--playbook", "--callsign", "osprey-1")
    release = ownership.release

    def unreachable(*_args, **_kwargs):
        raise OSError("the claims push was refused")

    monkeypatch.setattr(ownership, "release", unreachable)
    assert "again finishes it" in stop(drive, expect=1)
    assert claims.read_holdings(drive.plan, now_stamp()) != {}
    monkeypatch.setattr(ownership, "release", release)
    report = json.loads(drive.cli("playbook", "stop", STEP, "--json"))
    assert report["stopped"] and report["released"]
    assert claims.read_holdings(drive.plan, now_stamp()) == {}

    drive.cli("status", "set", STEP, "in-progress")  # As a flush that lost a race leaves it.
    assert "finished stopping pass" in stop(drive)
    assert _status(drive.cli, STEP) == "pending"
    assert "nothing to stop" in stop(drive)


def test_a_run_that_will_not_end_leaves_the_status_and_a_stop_again_finishes(drive):
    drive.cli("playbook", "set", STEP, "execute")
    drive.cli("agent", "run", STEP, "--playbook")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(supervisor, "end_orphaned_turn", lambda _record, _grace: False)
        said = stop(drive, expect=1)
    assert "still stopping" in said and "left as it was" in said
    assert _status(drive.cli, STEP) == "in-progress" and not drive.latest().over
    assert "it reads pending" in stop(drive)
    assert drive.latest().over


def test_a_pass_whose_preset_revision_this_build_lacks_is_stopped(drive, cli_library):
    from dplanner.cli.lookup import find_step
    from dplanner.domain.store import LibraryStore

    drive.cli("playbook", "set", STEP, "execute")
    drive.cli("agent", "run", STEP, "--playbook")
    supervisor.update(
        drive.plan,
        drive.latest().run,
        lambda r: replace(r, settings={**(r.settings or {}), "revision": 999}),
    )
    store = LibraryStore(cli_library)
    try:
        assert engine.stoppable(drive.plan, find_step(store.load(), STEP))
    finally:
        store.close()
    assert "execute attempt 1 was not started" in stop(drive)
    assert drive.latest().over and _status(drive.cli, STEP) == "pending"


# -- the review's second round ---------------------------------------------------------------------


@PROCESS_ENVIRONMENTS
@pytest.mark.parametrize("pidfds", [True, False], ids=["pidfd", "stamp"])
def test_a_process_whose_identity_changed_since_the_scan_is_not_signalled(
    allow_spawn, monkeypatch, pidfds
):
    """Between the scan and the signal the pid found carrying the run may have been reused:
    the stranger holding it now, or a process whose start no longer matches, is left alone."""
    import errno
    import os
    import sys

    from tests.launching import orphaned_turn

    allow_spawn(Path(sys.executable))
    if not pidfds:

        def no_pidfds(_pid):
            raise OSError(errno.ENOSYS, "no pidfds")

        monkeypatch.setattr(os, "pidfd_open", no_pidfds)
    run = "20261008T120000Z-reuse"
    with orphaned_turn() as stranger, orphaned_turn(run) as carrier:
        reused = replace(carrier, started=carrier.started + "0")
        monkeypatch.setattr(supervisor, "carrying_run", lambda _run: [stranger, reused])
        supervisor._end_run(run, None, 0, hard=True)
        time.sleep(0.2)
        assert is_live(stranger) and is_live(carrier)
        monkeypatch.setattr(supervisor, "carrying_run", lambda _run: [carrier])
        supervisor._end_run(run, None, 0, hard=False)
        deadline = time.monotonic() + 5
        while is_live(carrier) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not is_live(carrier) and is_live(stranger)


@PROCESS_ENVIRONMENTS
def test_the_search_never_finds_the_caller_or_its_ancestors(allow_spawn):
    """A stop given from a shell carrying the run — a person's, or a turn's own — ends that
    run's other processes, never the shell it was given from."""
    import os
    import subprocess
    import sys

    from dplanner.core.process import RUN_ENV

    allow_spawn(Path(sys.executable))
    run = "20261008T120000Z-lineage"
    search = (
        "import json; from dplanner.modules.agent_supervisor.supervisor import carrying_run; "
        f"print(json.dumps([s.pid for s in carrying_run({run!r})]))"
    )
    shell = (
        "import json, os, subprocess, sys\n"
        "sibling = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"found = subprocess.run([sys.executable, '-c', {search!r}], capture_output=True,\n"
        "                       text=True, check=True).stdout\n"
        "sibling.kill()\n"
        "print(json.dumps({'shell': os.getpid(), 'sibling': sibling.pid,\n"
        "                  'found': json.loads(found)}))\n"
    )
    done = subprocess.run([sys.executable, "-c", shell], capture_output=True, text=True,
                          check=True, env={**os.environ, RUN_ENV: run})  # fmt: skip
    said = json.loads(done.stdout)
    assert said["found"] == [said["sibling"]]


def test_a_pass_something_else_fenced_is_finished_by_a_stop(drive):
    """A run fenced for another reason before any stop — a takeover — keeps that reason, so a
    stop's leftover reconciliation cannot ask why the pass halted, only whether it has."""
    drive.cli("playbook", "set", STEP, "execute")
    drive.cli("agent", "run", STEP, "--playbook")
    run = drive.latest().run
    supervisor.fence(drive.plan, run, "kettle-actual", "taken over")
    assert supervisor.settle_fenced(drive.plan, run, 1.0)
    assert drive.latest().over and _status(drive.cli, STEP) == "in-progress"
    assert (drive.latest().fence or {}).get("why") == "taken over"
    assert "finished stopping pass" in stop(drive)
    assert _status(drive.cli, STEP) == "pending"
    assert "nothing to stop" in stop(drive)


# -- the landing review (S23) ----------------------------------------------------------------------


def _squad_pass(drive, playbook: str) -> claims.Claim:
    """A pass of ``playbook`` run by a squad member, its first stage — the plan — done."""
    drive.cli("claim", "take", STEP, "--callsign", "osprey", "--project", "widget")
    drive.cli("playbook", "set", STEP, playbook)
    drive.play({"lines": [INIT, result("A plan", session="s")]})
    drive.cli("agent", "run", STEP, "--playbook", "--callsign", "osprey-1")
    drive.supervise()
    (claim,) = claims.records(drive.plan)
    return claim


def _leave(drive, claim: claims.Claim, how: str) -> None:
    if how == "end":
        drive.cli("--project", "widget", "claim", "end", claim.id, "--why", "cleared")
    else:
        drive.cli("--project", "widget", "claim", "release", STEP, "--why", "cleared")


@pytest.mark.parametrize("how", ["end", "release"])
def test_a_claim_ended_while_its_pass_waits_at_a_gate_halts_the_pass(drive, how):
    """The gate's answer would launch the execute stage as nobody's run: the claim's leaving
    withdraws it, and an advance afterwards launches nothing."""
    claim = _squad_pass(drive, "plan-person-execute")
    drive.advance()
    gate = drive.asked()
    _leave(drive, claim, how)
    withdrawn = questions.find(drive.plan, gate.id)
    assert withdrawn is not None and withdrawn.state == questions.WITHDRAWN
    launched = len(drive.started)
    drive.cli("--project", "Widget", "question", "answer", gate.short, "Pass", expect=1)
    assert "withdrawn" in drive.advance()
    assert len(drive.started) == launched


@pytest.mark.parametrize("how", ["end", "release"])
def test_a_claim_ended_between_stages_halts_the_pass(drive, how):
    claim = _squad_pass(drive, "plan-execute-person")  # The execute is due, not launched.
    _leave(drive, claim, how)
    launched = len(drive.started)
    assert "was stopped: cleared" in drive.advance()
    assert len(drive.started) == launched and questions.records(drive.plan) == []


def test_a_launch_racing_a_stop_waits_for_its_plan_write_and_follow_ups(drive, monkeypatch):
    """A launch let in once the pass has halted — before the stop has reset the step and
    released its claim — would have its new pass's step set back to pending and its squad's
    claim released: the stop keeps the step's launch lock until both are done."""
    drive.cli("claim", "take", STEP, "--callsign", "osprey", "--project", "widget")
    drive.cli("playbook", "set", STEP, "execute")
    drive.cli("agent", "run", STEP, "--playbook", "--callsign", "osprey-1")
    first = drive.latest()
    halt, raced = engine.stop, []

    def then_a_launch(*args, **kwargs):
        done = halt(*args, **kwargs)
        raced.append(
            drive.cli("agent", "run", STEP, "--playbook", "--callsign", "osprey-1", expect=1)
        )
        return done

    monkeypatch.setattr("dplanner.modules.step_playbook.cli.stop", then_a_launch)
    report = json.loads(drive.cli("playbook", "stop", STEP, "--json"))
    assert "being launched right now" in raced[0]
    assert report["stopped"] and report["released"] and drive.latest().run == first.run
    monkeypatch.setattr("dplanner.modules.step_playbook.cli.stop", halt)

    drive.cli("claim", "take", STEP, "--callsign", "osprey", "--project", "widget")
    drive.cli("agent", "run", STEP, "--playbook", "--callsign", "osprey-1")
    assert drive.latest().pass_ != first.pass_ and not drive.latest().over
    assert _status(drive.cli, STEP) == "in-progress"
    assert drive.latest().step in claims.read_holdings(drive.plan, now_stamp())
