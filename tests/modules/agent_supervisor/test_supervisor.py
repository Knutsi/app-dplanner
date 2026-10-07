"""The run supervisor against a fake agent CLI it really runs: recorded streams played back
turn by turn, hangs, runaways and crashes — never a real agent CLI, never a model API.

The fake (``fake_agent.py``) is a Python script the harness's argv runs with this
interpreter, so ``allow_spawn`` lets exactly that interpreter through; the stream readers
and the classifier are the real Claude harness's."""

import json
import os
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from dplanner.core.process import stamp_of
from dplanner.domain import ledger
from dplanner.domain.headless import TurnSpec
from dplanner.domain.ledger import LedgerRecord, Turn
from dplanner.modules.agent_claude import harness as claude
from dplanner.modules.agent_supervisor import supervisor
from dplanner.modules.agent_supervisor.supervisor import (
    Guards,
    RefusedError,
    Session,
    supervise,
)

FAKE = Path(__file__).parent / "fake_agent.py"
TURNS = Path(__file__).parent.parent.parent / "fixtures" / "agent_turns"
RUN = "20261007T101500Z-9c1e44ab"
GUARDS = Guards(
    wall={"plan": 20.0, "execute": 20.0, "review": 20.0},
    runaway=200,
    backoff=(0.01, 0.01, 0.01),
    grace=2.0,
    poll=0.05,
)
SESSION = "11111111-2222-3333-4444-555555555555"


def recorded(name: str) -> list[str]:
    record = json.loads((TURNS / f"{name}.json").read_text(encoding="utf-8"))
    return [*record["stdout_head"], *record["stdout_tail"]]


def result(text: str = "Done.", session: str = SESSION) -> str:
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "session_id": session,
            "result": text,
            "usage": {"input_tokens": 3, "cache_read_input_tokens": 40, "output_tokens": 5},
        }
    )


INIT = json.dumps({"type": "system", "subtype": "init", "session_id": SESSION, "model": "m-1"})


class Rig:
    """A project with one headless run, a fake agent and the specs each turn was given."""

    def __init__(self, tmp_path: Path, stage: str = "execute") -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.plan = tmp_path / "plan"
        self.config = tmp_path / "config"
        self.run_dir = ledger.run_dir(RUN, self.config)
        self.script = tmp_path / "script.json"
        self.specs: list[TurnSpec] = []
        record = LedgerRecord(
            run=RUN,
            project="p1",
            step="s1",
            harness="claude",
            launched="2026-10-07T10:15:00+00:00",
            directory=str(tmp_path),
            mode=ledger.HEADLESS,
            stage=stage,
            attempt=1,
        )
        ledger.write(self.plan, record)
        headless = replace(claude.HEADLESS, command=self._command, stall=0.6)
        self.harnesses = (replace(claude.HARNESS, headless=headless),)

    def _command(self, spec: TurnSpec) -> list[str]:
        self.specs.append(spec)
        return [sys.executable, str(FAKE), str(self.script), "--", spec.prompt]

    def play(self, *turns: dict[str, object]) -> None:
        self.script.write_text(json.dumps(list(turns)), encoding="utf-8")

    def supervise(self, **options: str) -> str:
        return supervise(
            self.plan, RUN, self.harnesses, guards=GUARDS, config=self.config, **options
        )

    @property
    def record(self) -> LedgerRecord:
        found = ledger.find(self.plan, RUN)
        assert found is not None
        return found

    def ends(self) -> list[tuple[str, str]]:
        return [(turn.end, turn.why) for turn in self.record.turns]


@pytest.fixture
def rig(tmp_path, allow_spawn) -> Rig:
    allow_spawn(Path(sys.executable))
    return Rig(tmp_path)


# -- how a turn ends, and what follows ----------------------------------------------------------


def test_a_done_turn_ends_the_run_with_its_stream_teed_and_its_usage_counted(rig):
    rig.play({"lines": [INIT, result()]})
    assert rig.supervise() == f"run {RUN} is done"
    record = rig.record
    assert record.over and record.exit == 0 and record.session == SESSION
    (turn,) = record.turns
    assert (turn.n, turn.prompt, turn.end, turn.exit) == (1, "launch", "done", 0)
    assert turn.pid and turn.pid_started and turn.ended
    assert record.models() == {"m-1": record.tokens} and record.tokens.cached == 40
    stream = rig.run_dir / "turn-1.jsonl"
    assert stream.read_text(encoding="utf-8").splitlines() == [INIT, result()]
    # The launch names a fresh session and points at the briefing, never carries it.
    (spec,) = rig.specs
    assert not spec.resume and spec.session  # Minted for Claude, which names its own.
    assert (
        spec.prompt == f"Read your briefing in {rig.run_dir / 'prompt.md'} in full, then follow it."
    )
    assert not (rig.run_dir / supervisor.LOCK_FILE).exists()


def test_a_question_parks_the_run_and_the_answer_resumes_its_session(rig):
    rig.play({"lines": recorded("claude-asked-prose-1")}, {"lines": [result()]})
    said = rig.supervise()
    assert "parked" in said and rig.record.parked and rig.ends() == [("asked", "prose")]
    assert rig.record.turns[0].reason  # The question, until it is a record of its own.
    asked_in = rig.record.session

    with pytest.raises(RefusedError, match="--prompt"):
        rig.supervise()
    with pytest.raises(RefusedError, match="--text"):
        rig.supervise(prompt="answer")
    assert rig.supervise(prompt="answer", text="Keep both") == f"run {RUN} is done"
    resumed = rig.specs[-1]
    assert resumed.resume and resumed.session == asked_in and resumed.prompt == "Keep both"
    assert [turn.prompt for turn in rig.record.turns] == ["launch", "answer"]


def test_a_limit_and_a_dead_login_park_without_a_retry(rig, tmp_path):
    rig.play({"lines": recorded("claude-limit"), "exit": 1})
    rig.supervise()
    assert rig.ends() == [("limit", "")] and rig.record.parked

    other = Rig(tmp_path / "other")
    other.play({"lines": recorded("probes/claude-noauth"), "exit": 1})
    other.supervise()
    assert other.ends() == [("failed", "login")] and len(other.specs) == 1


def test_a_hang_is_killed_and_retried_in_the_same_session(rig):
    rig.play({"lines": [INIT], "hold": 30}, {"lines": [result()]})
    assert rig.supervise() == f"run {RUN} is done"
    assert rig.ends() == [("failed", "hang"), ("done", "")]
    assert [turn.prompt for turn in rig.record.turns] == ["launch", "retry"]
    assert rig.specs[1].resume and rig.specs[1].session == SESSION


def test_a_running_tool_holds_the_stall_clock_until_its_result(rig):
    use = {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest"}}
    done = {"type": "tool_result", "tool_use_id": "t1"}
    rig.play(
        {
            "lines": [INIT, json.dumps({"type": "assistant", "message": {"content": [use]}})],
            "hold": 1.5,  # Longer than the stall: a test suite at work, not a hang.
            "after": [json.dumps({"type": "user", "message": {"content": [done]}}), result()],
        }
    )
    rig.supervise()
    assert rig.ends() == [("done", "")]


def test_the_wall_clock_ends_a_tool_that_never_returns(rig):
    use = {"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}
    rig.play(
        {
            "lines": [INIT, json.dumps({"type": "assistant", "message": {"content": [use]}})],
            "hold": 30,
        }
    )
    guards = replace(GUARDS, wall={"execute": 1.0}, backoff=())
    supervise(rig.plan, RUN, rig.harnesses, guards=guards, config=rig.config)
    assert rig.ends() == [("failed", "timeout")]


def test_a_runaway_is_killed_and_parked_for_a_person(rig):
    rig.play({"lines": [INIT], "spam": True})
    assert "parked" in rig.supervise()
    assert rig.ends() == [("failed", "runaway")] and len(rig.specs) == 1


def test_three_retries_that_fail_park_the_run(rig):
    rig.play({"lines": [INIT], "hold": 30})
    assert "4 failures in a row" in rig.supervise()
    assert rig.ends() == [("failed", "hang")] * 4


def test_a_turn_waiting_on_its_own_work_is_told_to_continue(rig):
    rig.play(
        {"lines": [INIT, result("Started the suite. I'm waiting for the tests to finish.")]},
        {"lines": [result()]},
    )
    rig.supervise()
    assert rig.ends() == [("failed", "abandoned-wait"), ("done", "")]
    assert rig.specs[1].prompt == supervisor.PROMPTS["continue"]


def test_a_fence_written_during_a_turn_stops_the_run_instead_of_retrying_it(rig):
    path = ledger.path_for(rig.plan, rig.record)
    rig.play({"lines": [INIT], "hold": 30, "fence": str(path)}, {"lines": [result()]})
    assert rig.supervise() == f"run {RUN} was fenced"
    assert rig.record.over and rig.record.fence and len(rig.specs) == 1


def test_being_told_to_stop_ends_the_turn_and_the_run_stopped(rig):
    rig.play({"lines": [INIT], "hold": 30})
    record = rig.record
    session = Session(
        rig.plan, rig.run_dir, record, rig.harnesses[0], rig.harnesses[0].headless, GUARDS
    )
    (rig.run_dir).mkdir(parents=True)
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    ending = session.turn("launch", "", stop)
    assert session.next(ending, stop) == ("", f"run {RUN} was stopped")
    assert rig.ends() == [("stopped", "")] and rig.record.over


# -- what a supervisor finds when it starts ---------------------------------------------------


def test_a_turn_the_machine_lost_ends_lost_and_is_retried(rig):
    gone = Turn(
        n=1,
        prompt="launch",
        started="2026-10-07T10:15:01+00:00",
        pid=2**22 + 7,
        boot="b",
        pid_started="1",
    )
    ledger.write(rig.plan, rig.record.with_turns((gone,)))
    rig.play({"lines": [result()]})
    assert rig.supervise() == f"run {RUN} is done"
    assert rig.ends() == [("failed", "lost"), ("done", "")]


def test_a_turn_still_running_and_a_second_supervisor_are_refused(rig):
    me = stamp_of(os.getpid())
    assert me is not None
    live = Turn(n=1, prompt="launch", started="…", pid=me.pid, boot=me.boot, pid_started=me.started)
    ledger.write(rig.plan, rig.record.with_turns((live,)))
    with pytest.raises(RefusedError, match="still running"):
        rig.supervise()

    lock = rig.run_dir / supervisor.LOCK_FILE
    lock.write_text(json.dumps({"pid": me.pid, "boot": me.boot, "started": me.started}))
    with pytest.raises(RefusedError, match="already supervised"):
        rig.supervise()
    lock.write_text(json.dumps({"pid": 2**22 + 7, "boot": "gone", "started": "1"}))
    with pytest.raises(RefusedError, match="still running"):  # The stale lock was taken over.
        rig.supervise()


def test_a_run_that_is_over_or_not_headless_is_refused(rig):
    ledger.write(rig.plan, rig.record.ended_at("2026-10-07T11:00:00+00:00", 0))
    with pytest.raises(RefusedError, match="is over"):
        rig.supervise()
    ledger.write(rig.plan, replace(rig.record, mode="", ended=""))
    with pytest.raises(RefusedError, match="not a headless"):
        rig.supervise()


# -- what a stage leaves behind --------------------------------------------------------------


def test_a_plan_keeps_dplanners_own_copy_and_a_review_its_verdict(tmp_path, allow_spawn):
    allow_spawn(Path(sys.executable))
    plan = Rig(tmp_path / "plan-stage", stage="plan")
    plan.play({"lines": recorded("claude-plan")})
    plan.supervise()
    copy = plan.run_dir / supervisor.PLAN_FILE
    assert copy.read_text(encoding="utf-8").strip()

    review = Rig(tmp_path / "review-stage", stage="review")
    review.play({"lines": recorded("claude-review-typed")})
    review.supervise()
    verdict = review.record.verdict
    assert verdict is not None and verdict["outcome"] in ("pass", "changes")
