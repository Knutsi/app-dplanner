"""*Open Session*: a person takes a headless run's session — refused while a turn on it runs,
fenced as taken over when parked, its pass halted and every run on the session stopped first
under the step's launch lock, and never resumed by a supervisor afterwards."""

import shlex
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.modules.step_playbook.test_passes import next_of
from tests.modules.step_playbook.test_passes import run as stage_run

from dplanner.core.fsio import os_lock
from dplanner.domain import claims, ledger, questions
from dplanner.domain.ledger import LedgerRecord, Turn
from dplanner.domain.model import now_stamp
from dplanner.domain.workflow import Release
from dplanner.modules.agent_claude import harness as claude
from dplanner.modules.agent_codex import harness as codex
from dplanner.modules.agent_opencode import harness as opencode
from dplanner.modules.agent_supervisor import supervisor, takeover
from dplanner.modules.agent_supervisor.supervisor import RefusedError
from dplanner.modules.step_playbook import engine
from dplanner.modules.step_playbook.passes import GATE, PASS, Halted

HARNESSES = (claude.HARNESS, codex.HARNESS, opencode.HARNESS)
SESSION = "11111111-2222-3333-4444-555555555555"
AT = "2026-10-08T10:00:00+00:00"


def take(plan: Path, run: str, config: Path | None = None, **given) -> tuple[list[str], Path]:
    """``take_over`` as the verb calls it: the engine's halt, and a release nobody holds."""
    given = {"halt": engine.halt_pass, "release": lambda _plan, _release: False, **given}
    return takeover.take_over(plan, run, "knut", HARNESSES, config=config, **given)


def stored(plan: Path, run: str) -> LedgerRecord:
    found = ledger.find(plan, run)
    assert found is not None
    return found


def run_record(config: Path, workdir: Path, *turns: Turn, harness: str = "claude") -> LedgerRecord:
    return LedgerRecord(
        run=ledger.new_run_id(datetime(2026, 10, 8, 10, tzinfo=UTC)),
        project="p1",
        step="s1",
        harness=harness,
        launched=AT,
        machine=ledger.machine_id(config),
        directory=str(workdir),
        session=SESSION,
        mode=ledger.HEADLESS,
        stage="execute",
        attempt=1,
        turns=turns,
    )


def parked(plan: Path, config: Path, workdir: Path, harness: str = "claude") -> LedgerRecord:
    """A run parked on a question it asked."""
    asked = questions.asked("p1", "s1", AT, [questions.one("Keep both?")])
    turn = Turn(n=1, prompt="launch", started=AT, ended=AT, end="asked")
    record = run_record(config, workdir, harness=harness)
    asked = replace(asked, run=record.run)
    questions.write(plan, asked)
    record = record.with_turns([replace(turn, question=asked.id)])
    ledger.write(plan, record)
    return record


def test_a_running_turn_is_refused_with_the_way_to_look_at_it(tmp_path):
    record = run_record(tmp_path, tmp_path, Turn(n=1, prompt="launch", started=AT, pid=1))
    ledger.write(tmp_path / "plan", record)
    assert takeover.open_session_refusal(record, HARNESSES, tmp_path) == takeover.RUNNING
    with pytest.raises(RefusedError, match="Follow it, or Stop Playbook first"):
        take(tmp_path / "plan", record.run, tmp_path)
    assert stored(tmp_path / "plan", record.run).fence is None


def test_another_machines_run_and_a_run_without_a_session_are_refused(tmp_path):
    ended = Turn(n=1, prompt="launch", started=AT, ended=AT, end="asked")
    record = run_record(tmp_path, tmp_path, ended)
    there = replace(record, machine="elsewhere", host="laptop")
    assert takeover.open_session_refusal(there, HARNESSES, tmp_path) == "it ran on laptop"
    sessionless = replace(record, session="")
    assert "never recorded a session" in takeover.open_session_refusal(
        sessionless, HARNESSES, tmp_path
    )
    unstarted = run_record(tmp_path, tmp_path)
    assert takeover.open_session_refusal(unstarted, HARNESSES, tmp_path) == "it has not started yet"


def test_a_parked_run_is_fenced_as_taken_over_and_its_question_withdrawn(tmp_path):
    plan, config = tmp_path / "plan", tmp_path / "config"
    record = parked(plan, config, tmp_path)
    argv, directory = take(plan, record.run, config)
    assert argv == shlex.split(claude.HARNESS.resume.replace("{session}", SESSION))
    assert directory == tmp_path
    after = stored(plan, record.run)
    assert after.fence is not None and after.over
    assert (after.fence["why"], after.fence["by"]) == (ledger.TAKEN_OVER, "knut")
    assert all(q.state == questions.WITHDRAWN for q in questions.of_run(plan, record.run))


def test_a_run_taken_over_is_never_resumed_afterwards(tmp_path, monkeypatch):
    """Even an answer that lands after the takeover starts nothing: the run is over."""
    plan, config = tmp_path / "plan", tmp_path / "config"
    record = parked(plan, config, tmp_path)
    take(plan, record.run, config)
    (question,) = questions.of_run(plan, record.run)
    late = replace(question, state=questions.ANSWERED, answer={"answers": {"q": "Yes"}})
    questions.write(plan, late)
    started: list[str] = []
    monkeypatch.setattr(supervisor, "start_detached", lambda _d, run, *a, **k: started.append(run))
    assert not supervisor.answer_waiting(plan, record.run)
    assert supervisor.revive([plan], config, claimed=lambda _r: True) == []
    assert started == []


@pytest.mark.parametrize("harness", [codex.HARNESS, opencode.HARNESS])
def test_each_harness_resumes_through_its_own_template(tmp_path, harness):
    plan, config = tmp_path / "plan", tmp_path / "config"
    record = parked(plan, config, tmp_path, harness=harness.id)
    argv, _directory = take(plan, record.run, config)
    assert argv == shlex.split(harness.resume.replace("{session}", SESSION))


def test_a_run_that_is_over_is_opened_without_a_fence(tmp_path):
    plan, config = tmp_path / "plan", tmp_path / "config"
    done = Turn(n=1, prompt="launch", started=AT, ended=AT, end="done")
    record = replace(run_record(config, tmp_path, done), ended=AT)
    ledger.write(plan, record)
    take(plan, record.run, config)
    assert stored(plan, record.run).fence is None


def test_the_argv_runs_this_build_on_this_library(tmp_path):
    argv = takeover.open_session_argv(tmp_path / "lib.json", tmp_path, "R1")
    assert argv[-5:] == ["agent", "open-session", "R1", "--project-dir", str(tmp_path)]


# -- a pass's session, taken whole ----------------------------------------------------------------


def of_pass(record: LedgerRecord, workdir: Path, claim: str = "") -> LedgerRecord:
    """A run of pass ``P`` on :data:`SESSION`, this machine's."""
    return replace(
        record, machine=ledger.machine_id(), directory=str(workdir), session=SESSION, claim=claim
    )


def pass_entries(plan: Path) -> list[object]:
    return list(engine._latest_entries(plan, "s1"))


def test_an_ended_rows_session_is_taken_from_the_later_run_writing_it(tmp_path):
    """The pass's plan run ended, and its execute run went on in the same session: opening the
    plan's row stops the execute run first, so the person is the session's only writer."""
    plan = tmp_path / "plan"
    planned = of_pass(stage_run("plan"), tmp_path)
    asked = replace(
        questions.asked("p1", "s1", AT, [questions.one("Keep both?")]), pass_="P", stage="execute"
    )
    executing = of_pass(stage_run("execute", end="asked", over=False), tmp_path)
    (turn,) = executing.turns
    executing = executing.with_turns([replace(turn, question=asked.id)])
    questions.write(plan, replace(asked, run=executing.run))
    ledger.write(plan, planned)
    ledger.write(plan, executing)

    argv, _directory = take(plan, planned.run)

    assert argv == shlex.split(claude.HARNESS.resume.replace("{session}", SESSION))
    after = stored(plan, executing.run)
    assert after.over and after.fence is not None and after.fence["why"] == ledger.TAKEN_OVER
    assert all(q.state == questions.WITHDRAWN for q in questions.of_run(plan, executing.run))


def test_an_ended_row_whose_session_runs_a_turn_is_refused_and_nothing_is_fenced(tmp_path):
    plan = tmp_path / "plan"
    planned = of_pass(stage_run("plan"), tmp_path)
    executing = of_pass(stage_run("execute", end="", over=False), tmp_path)
    ledger.write(plan, planned)
    ledger.write(plan, executing)
    with pytest.raises(RefusedError, match="Follow it, or Stop Playbook first"):
        take(plan, planned.run)
    assert stored(plan, executing.run).fence is None


def test_an_answer_racing_the_takeover_launches_nothing_into_the_session(tmp_path):
    """The plan ended and its gate waits; the person answers it as the takeover begins. The
    takeover holds the step's launch lock — which the advance the answer starts waits for —
    and withdraws the answered gate, so that advance finds the pass halted."""
    plan = tmp_path / "plan"
    planned = of_pass(stage_run("plan"), tmp_path)
    ledger.write(plan, planned)
    waiting = questions.asked(
        "p1", "s1", now_stamp(), [questions.one("?")], pass_="P", stage="person", purpose=GATE
    )
    questions.write(plan, waiting)
    locked: list[bool] = []

    def answered_meanwhile(*halting: object) -> tuple[str, ...]:
        questions.update(
            plan,
            waiting.id,
            lambda q: questions.answered(q, {"?": PASS}, {"kind": "person"}, now_stamp()),
        )
        try:
            with supervisor.launching("p1", "s1"):
                locked.append(False)
        except BlockingIOError:
            locked.append(True)
        return engine.halt_pass(*halting)  # type: ignore[arg-type]

    take(plan, planned.run, halt=answered_meanwhile)

    assert locked == [True]
    (gate,) = questions.records(plan)
    assert gate.state == questions.WITHDRAWN
    assert isinstance(next_of("plan-person-execute", *pass_entries(plan)), Halted)


def test_a_takeover_that_timed_out_is_finished_by_asking_again(tmp_path):
    """The first attempt fenced the run and gave up waiting for its supervisor, releasing
    nothing; the supervisor then ended the run. The second finds the run over, and still
    releases the step from the squad whose run it was."""
    plan = tmp_path / "plan"
    claim = claims.claimed("p1", "kettle-two", ["s1"], now_stamp(), worker={"machine": "m"})
    claims.write(plan, claim)
    executing = of_pass(stage_run("execute", end="asked", over=False), tmp_path, claim.id)
    ledger.write(plan, executing)
    released: list[Release] = []

    def release(_plan: Path, follow_up: Release) -> bool:
        released.append(follow_up)
        return True

    supervising = ledger.run_dir(executing.run) / supervisor.LOCK_FILE
    supervising.parent.mkdir(parents=True)
    with os_lock(supervising, wait=False), pytest.raises(RefusedError, match="still stopping"):
        take(plan, executing.run, release=release, wait=0.0)
    assert released == []
    assert supervisor.settle_fenced(plan, executing.run, 0.0)  # Its supervisor, ending it.
    assert stored(plan, executing.run).over

    take(plan, executing.run, release=release)

    assert released == [Release("p1", "s1", "taken over")]
