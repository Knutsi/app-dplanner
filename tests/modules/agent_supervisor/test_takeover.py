"""*Open Session*: a person takes a headless run's session — refused while a turn runs, fenced
as taken over when parked, and never resumed by a supervisor afterwards."""

import shlex
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dplanner.domain import ledger, questions
from dplanner.domain.ledger import LedgerRecord, Turn
from dplanner.modules.agent_claude import harness as claude
from dplanner.modules.agent_codex import harness as codex
from dplanner.modules.agent_opencode import harness as opencode
from dplanner.modules.agent_supervisor import supervisor, takeover
from dplanner.modules.agent_supervisor.supervisor import RefusedError

HARNESSES = (claude.HARNESS, codex.HARNESS, opencode.HARNESS)
SESSION = "11111111-2222-3333-4444-555555555555"
AT = "2026-10-08T10:00:00+00:00"


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
        takeover.take_over(tmp_path / "plan", record.run, "knut", HARNESSES, tmp_path)
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
    argv, directory = takeover.take_over(plan, record.run, "knut", HARNESSES, config)
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
    takeover.take_over(plan, record.run, "knut", HARNESSES, config)
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
    argv, _directory = takeover.take_over(plan, record.run, "knut", HARNESSES, config)
    assert argv == shlex.split(harness.resume.replace("{session}", SESSION))


def test_a_run_that_is_over_is_opened_without_a_fence(tmp_path):
    plan, config = tmp_path / "plan", tmp_path / "config"
    done = Turn(n=1, prompt="launch", started=AT, ended=AT, end="done")
    record = replace(run_record(config, tmp_path, done), ended=AT)
    ledger.write(plan, record)
    takeover.take_over(plan, record.run, "knut", HARNESSES, config)
    assert stored(plan, record.run).fence is None


def test_the_argv_runs_this_build_on_this_library(tmp_path):
    argv = takeover.open_session_argv(tmp_path / "lib.json", tmp_path, "R1")
    assert argv[-5:] == ["agent", "open-session", "R1", "--project-dir", str(tmp_path)]
