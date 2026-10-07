"""The run supervisor against a fake agent CLI it really runs: recorded streams played back
turn by turn, hangs, runaways and crashes — never a real agent CLI, never a model API.

The fake (``fake_agent.py``) is a Python script the harness's argv runs with this
interpreter, so ``allow_spawn`` lets exactly that interpreter through; the stream readers
and the classifier are the real Claude harness's."""

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from dplanner.core.process import process_alive, stamp_of
from dplanner.domain import ledger, questions
from dplanner.domain.headless import TurnSpec
from dplanner.domain.ledger import LedgerRecord, Turn
from dplanner.domain.questions import Question
from dplanner.modules.agent_claude import harness as claude
from dplanner.modules.agent_questions import inbox
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
    with supervisor.supervising(rig.run_dir):  # Let go of: the next supervisor may start.
        pass


def test_a_question_in_prose_parks_on_a_question_record_and_words_given_withdraw_it(rig):
    rig.play({"lines": recorded("claude-asked-prose-1")}, {"lines": [result()]})
    said = rig.supervise()
    assert "parked" in said and rig.record.parked and rig.ends() == [("asked", "prose")]
    (question,) = questions.records(rig.plan)
    assert f"on {question.short}" in said
    assert (question.kind, question.state, question.run) == ("decision", "open", RUN)
    assert rig.record.turns[0].question == question.id
    assert question.text == rig.record.turns[0].reason
    asked_in = rig.record.session

    with pytest.raises(RefusedError, match="--prompt"):
        rig.supervise()
    with pytest.raises(RefusedError, match=r"cannot resume on its answer.*open"):
        rig.supervise(prompt="answer")
    assert rig.supervise(prompt="answer", text="Keep both") == f"run {RUN} is done"
    resumed = rig.specs[-1]
    assert resumed.resume and resumed.session == asked_in and resumed.prompt == "Keep both"
    assert [turn.prompt for turn in rig.record.turns] == ["launch", "answer"]
    # Words handed straight to the supervisor: the card no longer stands.
    assert stored(rig.plan, question.id).state == "withdrawn"


def test_a_question_asked_through_the_door_is_answered_consumed_and_resumes_the_session(rig):
    rig.play(
        {
            "ask": {"plan": str(rig.plan), "question": "Keep both records?"},
            "lines": recorded("claude-ask-door"),
        },
        {"lines": [result()]},
    )
    rig.supervise()
    assert rig.ends() == [("asked", "record")]
    (question,) = questions.records(rig.plan)
    first = rig.record.turns[0]
    assert (first.question, first.reason) == (question.id, "Keep both records?")

    resumed: list[tuple[object, ...]] = []
    done = inbox.answer(
        rig.plan,
        question.id,
        "Keep both",
        {"kind": "person", "name": "Knut"},
        machine="",
        config=rig.config,
        resume=lambda *args, **kwargs: resumed.append((*args, kwargs)),
    )
    assert resumed == [(rig.plan, RUN, {"prompt": "answer"})] and "resumes with it" in done.said

    assert rig.supervise(prompt="answer") == f"run {RUN} is done"
    answered = stored(rig.plan, question.id)
    assert answered.state == "consumed" and answered.consumed["turn"] == 2
    second = rig.record.turns[1]
    assert second.consumed == {"question": question.id, "answer": answered.answer["id"]}
    assert rig.specs[-1].resume and rig.specs[-1].prompt == questions.answer_text(answered)
    assert "Keep both" in rig.specs[-1].prompt


def test_every_park_stands_on_a_question_of_its_kind(rig, tmp_path):
    rig.play({"lines": recorded("claude-limit"), "exit": 1})
    rig.supervise()
    (limit,) = questions.records(rig.plan)
    assert limit.kind == "limit" and limit.resets == rig.record.turns[0].resets

    denied = Rig(tmp_path / "denied")
    denied.play({"lines": recorded("claude-denied-1")})
    denied.supervise()
    (permission,) = questions.records(denied.plan)
    assert permission.kind == "permission" and permission.body == denied.record.turns[0].reason

    runaway = Rig(tmp_path / "runaway")
    runaway.play({"lines": [INIT], "spam": True})
    runaway.supervise()
    (blocked,) = questions.records(runaway.plan)
    assert blocked.kind == "blocked" and "runaway" not in blocked.text  # Words, not a code.


def test_a_resume_that_is_no_answer_withdraws_the_question_it_parked_on(rig):
    rig.play({"lines": recorded("claude-asked-prose-1")}, {"lines": [result()]})
    rig.supervise()
    (question,) = questions.records(rig.plan)
    rig.supervise(prompt="continue")
    withdrawn = stored(rig.plan, question.id)
    assert withdrawn.state == "withdrawn" and "continue" in withdrawn.withdrawn["why"]


def test_an_answer_refuses_to_resume_a_run_another_machine_launched(rig):
    rig.play({"lines": recorded("claude-asked-prose-1")})
    rig.supervise()
    ledger.write(rig.plan, replace(rig.record, machine="elsewhere", host="knut-laptop"))
    (question,) = questions.records(rig.plan)
    resumed: list[object] = []
    done = inbox.answer(
        rig.plan,
        question.id,
        "Keep both",
        {"kind": "person", "name": "Knut"},
        machine="here",
        config=rig.config,
        resume=lambda *args, **kwargs: resumed.append(args),
    )
    assert not resumed and "knut-laptop" in done.said
    assert stored(rig.plan, question.id).state == "answered"


def test_an_answer_given_before_the_turn_ends_parks_on_it_and_resumes_at_once(rig):
    """Finding 3: answered while the asking process was still exiting."""
    ask = {"plan": str(rig.plan), "question": "Keep both?", "answered": "Absorb"}
    rig.play({"ask": ask, "lines": [INIT, result("Ending my turn.")]}, {"lines": [result()]})
    assert rig.supervise() == f"run {RUN} is done"
    (question,) = questions.records(rig.plan)
    first, second = rig.record.turns
    assert (first.end, first.question) == ("asked", question.id)
    assert second.prompt == "answer" and second.consumed["question"] == question.id
    assert question.state == "consumed" and "Absorb" in rig.specs[-1].prompt


def _answer_the_park(rig: Rig) -> Question:
    (question,) = [q for q in questions.records(rig.plan) if q.state == "open"]
    person = {"kind": "person", "name": "Knut"}
    given = questions.answers_for(question, "Keep both")
    answered = questions.answered(question, given, person, question.asked)
    questions.write(rig.plan, answered)
    return answered


def test_an_answer_given_while_the_supervisor_lets_go_is_still_delivered(rig, monkeypatch):
    """Finding 4: the nudge the answer gave was refused by the supervisor letting go."""
    rig.play({"lines": recorded("claude-asked-prose-1")}, {"lines": [result()]})
    drive = supervisor._drive
    calls: list[str] = []

    def then_answer(*args: object) -> str:
        said = drive(*args)  # type: ignore[arg-type]
        if not calls:
            calls.append(said)
            _answer_the_park(rig)
        return said

    monkeypatch.setattr(supervisor, "_drive", then_answer)
    assert rig.supervise() == f"run {RUN} is done"
    assert [turn.prompt for turn in rig.record.turns] == ["launch", "answer"]


def test_a_resume_claimed_but_never_started_is_started_and_never_consumed_twice(rig, monkeypatch):
    """Finding 5: the claim is on disk before the process is, and recovery spawns it."""
    rig.play({"lines": recorded("claude-asked-prose-1")}, {"lines": [result()]})
    rig.supervise()
    question = _answer_the_park(rig)

    def crash(*_: object) -> None:
        raise SystemExit("the machine went down")

    monkeypatch.setattr(supervisor, "_spawn", crash)
    with pytest.raises(SystemExit):
        rig.supervise(prompt="answer")
    claimed = rig.record.turns[-1]
    assert (claimed.n, claimed.prompt, claimed.pid, claimed.end) == (2, "answer", 0, "")
    assert stored(rig.plan, question.id).state == "consumed"

    monkeypatch.undo()
    assert rig.supervise() == f"run {RUN} is done"
    assert [turn.n for turn in rig.record.turns] == [1, 2]
    assert stored(rig.plan, question.id).consumed["turn"] == 2
    assert "Keep both" in rig.specs[-1].prompt


def test_the_claim_rereads_the_run_under_its_locks(rig, monkeypatch):
    """Finding 6: another machine's run, and a fence landing after the opening's check."""
    rig.play({"lines": recorded("claude-asked-prose-1")}, {"lines": [result()]})
    rig.supervise()
    question = _answer_the_park(rig)
    ledger.write(rig.plan, replace(rig.record, machine="elsewhere", host="knut-laptop"))
    with pytest.raises(RefusedError, match="knut-laptop launched it"):
        rig.supervise(prompt="answer")
    ledger.write(rig.plan, replace(rig.record, machine=""))

    machine_id = ledger.machine_id

    def fenced_meanwhile(directory: Path | None = None) -> str:
        supervisor.fence(rig.plan, RUN, "a takeover", "taken over", rig.config)
        return machine_id(directory)

    monkeypatch.setattr(ledger, "machine_id", fenced_meanwhile)
    with pytest.raises(RefusedError, match="fenced"):
        rig.supervise(prompt="answer")
    assert stored(rig.plan, question.id).state == "answered"
    assert len(rig.record.turns) == 1 and len(rig.specs) == 1


def test_an_automatic_retry_withdraws_what_the_failed_turn_asked(rig):
    """Finding 7: the question a crashed turn asked does not stand beside the retry."""
    ask = {"plan": str(rig.plan), "question": "Keep both?"}
    rig.play({"ask": ask, "lines": [INIT], "hold": 30}, {"lines": [result()]})
    assert rig.supervise() == f"run {RUN} is done"
    assert rig.ends() == [("failed", "hang"), ("done", "")]
    (question,) = questions.records(rig.plan)
    assert question.withdrawn["why"] == "the run went on by itself"


def test_the_card_is_written_before_the_parked_ending(rig, monkeypatch):
    """Finding 8: a crash writing the park leaves a card, never a parked run with none."""
    rig.play({"lines": recorded("claude-asked-prose-1")})
    write = ledger.write

    def crash_on_the_park(project_dir: Path, record: LedgerRecord) -> bool:
        if record.turns and record.turns[-1].end == "asked":
            raise OSError("disk full")
        return write(project_dir, record)

    monkeypatch.setattr(ledger, "write", crash_on_the_park)
    with pytest.raises(OSError):
        rig.supervise()
    assert [q.kind for q in questions.records(rig.plan)] == ["decision"]


def test_starting_mends_a_park_with_no_card_and_an_end_with_cards_standing(rig):
    """Finding 8: what a supervisor that died between two writes left behind."""
    asked = Turn(n=1, prompt="launch", started="…", ended="…", end="asked", reason="Why?")
    ledger.write(rig.plan, rig.record.with_turns((asked,)))
    with pytest.raises(RefusedError, match="--prompt"):
        rig.supervise()
    (card,) = questions.records(rig.plan)
    assert (card.text, rig.record.turns[0].question) == ("Why?", card.id)

    ledger.write(rig.plan, rig.record.ended_at("2026-10-07T11:00:00+00:00", 0))
    with pytest.raises(RefusedError, match="is over"):
        rig.supervise()
    assert stored(rig.plan, card.id).state == "withdrawn"


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
        rig.plan, rig.config, record, rig.harnesses[0], rig.harnesses[0].headless, GUARDS
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


def test_a_turn_still_running_is_refused(rig):
    me = stamp_of(os.getpid())
    assert me is not None
    live = Turn(n=1, prompt="launch", started="…", pid=me.pid, boot=me.boot, pid_started=me.started)
    ledger.write(rig.plan, rig.record.with_turns((live,)))
    with pytest.raises(RefusedError, match="still running"):
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


# -- one supervisor, and nothing left running --------------------------------------------------


def gone(pid: int, within: float = 5.0) -> bool:
    """Whether the process whose pid the fake wrote is gone — and reaped by whoever owns it
    now, which for an orphan is init, a moment after it died."""
    deadline = time.monotonic() + within
    while process_alive(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


def test_two_supervisors_started_at_once_one_is_refused(rig):
    start = threading.Barrier(2)
    outcomes: list[str] = []
    release = threading.Event()

    def contend() -> None:
        start.wait()
        try:
            with supervisor.supervising(rig.run_dir):
                outcomes.append("held")
                release.wait(5)
        except RefusedError:
            outcomes.append("refused")
            release.set()

    threads = [threading.Thread(target=contend) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert sorted(outcomes) == ["held", "refused"]


def test_a_live_supervisor_is_refused_whatever_its_lock_file_says(rig):
    with supervisor.supervising(rig.run_dir):
        (rig.run_dir / supervisor.LOCK_FILE).write_text("")  # Caught before it wrote a pid.
        with pytest.raises(RefusedError, match="already supervised"):
            rig.supervise()


def test_a_dead_supervisors_lock_is_free_at_once(rig):
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys, time; from pathlib import Path;"
            " from dplanner.modules.agent_supervisor.supervisor import supervising;"
            " cm = supervising(Path(sys.argv[1])); cm.__enter__(); print('held', flush=True);"
            " time.sleep(60)",
            str(rig.run_dir),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
        with (
            pytest.raises(RefusedError, match="already supervised"),
            supervisor.supervising(rig.run_dir),
        ):
            pass
    finally:
        holder.kill()
        holder.wait()
    with supervisor.supervising(rig.run_dir):
        pass


def test_the_turns_whole_group_ends_even_a_child_that_ignores_sigterm(rig, tmp_path):
    child = tmp_path / "child.pid"
    rig.play({"lines": [INIT], "child": str(child), "hold": 30})
    supervise(
        rig.plan,
        RUN,
        rig.harnesses,
        guards=replace(GUARDS, backoff=(), grace=0.5),
        config=rig.config,
    )
    assert rig.ends() == [("failed", "hang")]
    assert gone(int(child.read_text()))


def test_a_stream_closed_early_does_not_stop_the_guards(rig):
    rig.play({"lines": [INIT], "close_stdout": True, "hold": 30})
    supervise(rig.plan, RUN, rig.harnesses, guards=replace(GUARDS, backoff=()), config=rig.config)
    assert rig.ends() == [("failed", "hang")]


def test_what_the_cli_says_while_it_is_killed_is_still_read(rig):
    rig.play({"lines": [INIT], "on_term": [result("Interrupted.")], "hold": 30})
    supervise(rig.plan, RUN, rig.harnesses, guards=replace(GUARDS, backoff=()), config=rig.config)
    assert rig.ends() == [("failed", "hang")]
    assert rig.record.tokens.cached == 40  # The totals the SIGTERM handler printed.
    assert result("Interrupted.") in (rig.run_dir / "turn-1.jsonl").read_text(encoding="utf-8")


def test_a_ledger_that_cannot_be_written_ends_the_turn_and_says_so(rig, monkeypatch):
    rig.play({"lines": [INIT], "hold": 30})
    real = ledger.write
    failed: list[bool] = []

    def disk_full_once(project_dir: Path, record: LedgerRecord) -> bool:
        if record.turns and record.turns[-1].pid and not record.turns[-1].end and not failed:
            failed.append(True)
            raise OSError("No space left on device")
        return real(project_dir, record)

    monkeypatch.setattr(ledger, "write", disk_full_once)
    with pytest.raises(OSError, match="No space"):
        rig.supervise()
    assert rig.ends() == [("failed", "supervisor-error")]
    assert gone(rig.record.turns[0].pid)


def test_a_stream_that_cannot_be_teed_ends_the_turn_and_says_so(rig, tmp_path, monkeypatch):
    pid = tmp_path / "agent.pid"
    rig.play({"lines": [INIT], "pidfile": str(pid), "hold": 30})

    def disk_full(*_: object) -> None:
        raise OSError("No space left on device")

    monkeypatch.setattr(Session, "_heard", disk_full)
    with pytest.raises(OSError, match="No space"):
        rig.supervise()
    assert rig.ends() == [("failed", "supervisor-error")]
    assert gone(int(pid.read_text()))


# -- the record: one writer at a time, and an end written with its turn ------------------------


def test_a_fence_landing_between_the_supervisors_read_and_write_is_kept(rig, monkeypatch):
    real = ledger.write
    fencing: list[threading.Thread] = []

    def fence_meanwhile(project_dir: Path, record: LedgerRecord) -> bool:
        if not fencing:
            # A takeover fences while the supervisor holds its read of the record.
            fencing.append(
                threading.Thread(
                    target=supervisor.fence,
                    args=(rig.plan, RUN, "a takeover", "taken over", rig.config),
                )
            )
            fencing[0].start()
            time.sleep(0.3)
        return real(project_dir, record)

    monkeypatch.setattr(ledger, "write", fence_meanwhile)
    rig.play({"lines": [INIT, result()]})
    rig.supervise()
    fencing[0].join(5)
    assert rig.record.fence is not None and rig.record.fence["by"] == "a takeover"


def test_a_turn_that_ends_the_run_is_written_with_the_runs_end(rig, monkeypatch):
    real = ledger.write
    written: list[LedgerRecord] = []

    def kept(project_dir: Path, record: LedgerRecord) -> bool:
        written.append(record)
        return real(project_dir, record)

    monkeypatch.setattr(ledger, "write", kept)
    rig.play({"lines": [INIT, result()]})
    rig.supervise()
    assert rig.record.over
    assert not [r for r in written if r.last_turn and r.last_turn.end == "done" and not r.over]


@pytest.mark.parametrize(("end", "said"), [("done", "is done"), ("stopped", "was stopped")])
def test_a_run_whose_last_turn_ended_it_is_ended_never_resumed(rig, end, said):
    last = Turn(n=1, prompt="launch", started="…", ended="…", end=end, exit=0)
    ledger.write(rig.plan, rig.record.with_turns((last,)))
    rig.play({"lines": [result()]})
    assert rig.supervise(prompt="retry") == f"run {RUN} {said}"
    assert rig.record.over and rig.specs == []


def stored(project_dir: Path, question_id: str) -> Question:
    found = questions.find(project_dir, question_id)
    assert found is not None
    return found
