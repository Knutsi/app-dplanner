"""The playbook engine end to end: ``agent run --playbook`` starts a pass, each stage's run is
driven by the real supervisor over the fake agent CLI with scripted endings, and ``playbook
advance`` — what the supervisor and an answer start on their own — moves the pass on.

Nothing is started for real: ``start_detached`` is captured (``started``), the supervisor runs
in-process, and the detached advance it would start is recorded (``advanced``). Never a real
agent CLI, never a model API: the fake plays recorded-shape streams through Claude's readers.
"""

import json
import subprocess
import sys
from contextlib import ExitStack
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests.modules.agent_supervisor.test_supervisor import FAKE, GUARDS, INIT, result

from dplanner.domain import ledger, questions
from dplanner.domain.headless import TurnSpec
from dplanner.domain.ledger import LedgerRecord
from dplanner.modules.agent_claude import harness as claude
from dplanner.modules.agent_supervisor import supervisor
from dplanner.modules.github import cli as github_cli
from dplanner.modules.step_playbook.passes import Settings
from dplanner.planning.status import Status, stored

HEAD = "agent/s1-build-it"

CHANGES = {
    "outcome": "changes",
    "summary": "One race",
    "findings": [
        {"severity": "high", "file": "a.py", "line": 3, "text": "A race", "evidence": "read, then"}
    ],
}
PASSES = {"outcome": "pass", "summary": "Good", "findings": []}


def done(declined: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {"outcome": "done", "summary": "Did it", "question": "", "declined": declined or []}


class Driver:
    """The pass's runs, driven one at a time: the fake agent plays its script in order."""

    def __init__(self, cli, plan: Path, started, advanced) -> None:
        self.cli, self.plan, self.started, self.advanced = cli, plan, started, advanced
        self.script = plan.parent / "script.json"
        self.specs: list[TurnSpec] = []
        headless = replace(claude.HEADLESS, command=self._command)
        self.harnesses = (replace(claude.HARNESS, headless=headless),)

    def _command(self, spec: TurnSpec) -> list[str]:
        self.specs.append(spec)
        return [sys.executable, str(FAKE), str(self.script), "--", spec.prompt]

    def play(self, *turns: dict[str, object]) -> None:
        self.script.write_text(json.dumps(list(turns)), encoding="utf-8")

    def latest(self) -> LedgerRecord:
        run = self.started[-1][1]
        record = ledger.find(self.plan, run)
        assert record is not None
        return record

    def supervise(self) -> LedgerRecord:
        """Drive the latest run to its end, as its detached supervisor would."""
        record = self.latest()
        told: list[str] = []
        supervisor.supervise(
            self.plan,
            record.run,
            self.harnesses,
            guards=GUARDS,
            advance=lambda _dir, finished: told.append(finished.step),
        )
        self.advanced.extend(told)
        return self.latest()

    def advance(self, step: str = "Build it") -> str:
        return str(self.cli("playbook", "advance", step))

    def answer(self, question: questions.Question, given: str) -> str:
        return str(self.cli("--project", "Widget", "question", "answer", question.short, given))

    def asked(self) -> questions.Question:
        found = [q for q in questions.records(self.plan) if q.pass_]
        return found[-1]

    def prompt(self, record: LedgerRecord) -> str:
        return (ledger.run_dir(record.run) / "prompt.md").read_text(encoding="utf-8")


@pytest.fixture
def advanced(monkeypatch):
    """Every detached `playbook advance` the supervisor or an answer would have started."""
    told: list[str] = []
    monkeypatch.setattr(supervisor, "spawn_detached", lambda argv, **_k: told.append(argv[-1]))
    return told


@pytest.fixture
def drive(cli, plan, started, advanced, allow_spawn):
    allow_spawn(Path(sys.executable))
    return Driver(cli, plan, started, advanced)


def _status(cli, title: str) -> str:
    return str(json.loads(cli("status", "show", title, "--json"))["status"])


def test_a_pass_plans_executes_and_loops_back_to_its_session_until_review_passes(drive):
    drive.cli("playbook", "set", "Build it", "plan-execute-review-self")
    drive.play(
        {"lines": [INIT, result("## Plan\n\nAdd the lock.", session="plan-s")]},
        {"lines": [INIT, result(typed=done(), session="plan-s")]},
        {"lines": [INIT, result(typed=CHANGES, session="review-1")]},
        {
            "lines": [
                INIT,
                result(typed=done([{"finding": 1, "reason": "It cannot race"}]), session="plan-s"),
            ]
        },
        {"lines": [INIT, result(typed=PASSES, session="review-2")]},
    )
    said = json.loads(drive.cli("agent", "run", "Build it", "--playbook", "--json"))
    assert said["step"] and _status(drive.cli, "Build it") == "in-progress"

    plan = drive.latest()
    assert (plan.stage, plan.attempt, plan.playbook) == ("plan", 1, "plan-execute-review-self")
    pinned = Settings.from_json(plan.settings)
    assert pinned is not None and pinned.preset == "plan-execute-review-self"
    assert "This is the plan stage" in drive.prompt(plan)
    assert "ready-for-review" not in drive.prompt(plan)  # The work's ending, not a plan's.
    assert drive.supervise().over and drive.advanced == [plan.step]
    assert (ledger.run_dir(plan.run) / supervisor.PLAN_FILE).read_text().startswith("## Plan")

    drive.advance()
    execute = drive.latest()
    assert (execute.stage, execute.attempt, execute.pass_) == ("execute", 1, plan.pass_)
    assert execute.settings is None  # Pinned once, on the pass's first record.
    assert "The plan is approved" in drive.prompt(execute) and "Add the lock." in drive.prompt(
        execute
    )
    drive.supervise()
    assert drive.specs[-1].resume and drive.specs[-1].session == "plan-s"

    drive.advance()
    review = drive.latest()
    assert (review.stage, review.attempt) == ("review", 1)
    assert "This is a review stage" in drive.prompt(review)
    assert drive.supervise().verdict == CHANGES
    assert not drive.specs[-1].resume  # A review is always a fresh session.

    drive.advance()
    fix = drive.latest()
    assert (fix.stage, fix.attempt, fix.session) == ("execute", 2, "plan-s")
    assert "Findings to address" in drive.prompt(fix) and "A race" in drive.prompt(fix)
    fixed = drive.supervise()
    assert drive.specs[-1].resume
    assert fixed.declined == (
        {"finding": {"run": review.run, "index": 0}, "reason": "It cannot race"},
    )

    drive.advance()
    second = drive.latest()
    assert (second.stage, second.attempt) == ("review", 2)
    assert "Declined: It cannot race" in drive.prompt(second)
    drive.supervise()

    runs = len(drive.started)
    assert "is through" in drive.advance()
    assert "is through" in drive.advance()  # Advancing again does nothing more.
    assert len(drive.started) == runs


def test_the_round_cap_asks_and_one_more_round_sends_a_fix_then_a_person_decides(drive):
    drive.cli("playbook", "set", "Build it", "review-only", "--rounds", "1")
    drive.play(
        {"lines": [INIT, result(typed=CHANGES, session="r1")]},
        {"lines": [INIT, result(typed=done(), session="f1")]},
        {"lines": [INIT, result(typed=PASSES, session="r2")]},
    )
    drive.cli("agent", "run", "Build it", "--playbook")
    assert drive.latest().stage == "review"
    drive.supervise()
    assert "round-cap" in drive.advance()
    capped = drive.asked()
    assert (capped.purpose, capped.kind, capped.stage) == ("round-cap", "decision", "review")
    assert "A race" in capped.body

    drive.advanced.clear()
    assert "its pass advances" in drive.answer(capped, "One more round")
    assert drive.advanced == [capped.step]
    drive.advance()
    fix = drive.latest()
    assert (fix.stage, fix.attempt, fix.session != "r1") == ("fix", 1, True)
    stored = questions.find(drive.plan, capped.id)
    assert stored is not None and stored.state == questions.CONSUMED
    assert stored.consumed["pass"] == fix.pass_

    drive.supervise()
    drive.advance()
    assert (drive.latest().stage, drive.latest().attempt) == ("review", 2)
    drive.supervise()
    assert "person asks" in drive.advance()
    person = drive.asked()
    assert (person.purpose, person.stage, person.kind) == ("gate", "person", "decision")
    drive.answer(person, "Pass")
    assert "is through" in drive.advance()


def test_a_spikes_plan_is_approved_by_a_person_and_the_step_is_done(drive):
    drive.cli("playbook", "set", "Build it", "spike")
    drive.play({"lines": [INIT, result("## Findings\n\nUse a lock.", session="s")]})
    drive.cli("agent", "run", "Build it", "--playbook")
    drive.supervise()
    drive.advance()
    approval = drive.asked()
    assert approval.kind == questions.PLAN_APPROVAL and "Use a lock." in approval.body
    drive.answer(approval, "Pass")
    assert "the step is done" in drive.advance()
    assert _status(drive.cli, "Build it") == "done"


def test_a_parked_stage_does_not_move_its_pass(drive):
    drive.cli("playbook", "set", "Build it", "execute")
    drive.play({"lines": [INIT], "exit": 1, "stderr": "Error: 401 Unauthorized — not logged in"})
    drive.cli("agent", "run", "Build it", "--playbook")
    record = drive.supervise()
    assert record.parked and drive.advanced == []
    assert "parked" in drive.advance()
    assert len(drive.started) == 1


def _to_progress(drive) -> None:
    """A plan-execute-progress pass driven up to its progress stage."""
    drive.cli("playbook", "set", "Build it", "plan-execute-progress")
    drive.play(
        {"lines": [INIT, result("A plan", session="s")]}, {"lines": [INIT, result(typed=done())]}
    )
    drive.cli("agent", "run", "Build it", "--playbook")
    drive.supervise()
    drive.advance()
    drive.supervise()


def test_progress_on_the_mainline_is_a_gate_only_a_person_answers(drive, monkeypatch):
    """The step is on no feature branch: the plan says its PR goes to the mainline, so nothing
    is merged — gh is never asked — and the gate is a person's, keeping its stage."""
    _to_progress(drive)
    monkeypatch.setattr(github_cli, "view_pr", lambda *_: pytest.fail("gh was asked"))
    assert "progress asks" in drive.advance()
    gate = drive.asked()
    assert (gate.stage, gate.purpose) == ("progress", "gate") and "mainline" in gate.text
    monkeypatch.setenv("DPLANNER_RUN", "the-coordinators-run")
    said = drive.cli("--project", "Widget", "question", "answer", gate.short, "Pass", expect=1)
    assert "person gate" in said
    monkeypatch.delenv("DPLANNER_RUN")
    drive.answer(gate, "Pass")
    assert "is through" in drive.advance()


def test_progress_that_cannot_merge_asks_on_a_blocked_card(drive, monkeypatch):
    _to_progress(drive)
    monkeypatch.setattr(
        github_cli, "accept_by_merge", lambda *_a, **_k: ("PR #4 goes into feature/y", False)
    )
    from dplanner.modules.agent_launch.cli import StageLauncher

    monkeypatch.setattr(StageLauncher, "merge_target", lambda *_: ("feature/x", HEAD))
    assert "could not go on" in drive.advance()
    card = drive.asked()
    assert (card.kind, card.purpose, card.stage) == ("blocked", "escalation", "progress")
    monkeypatch.setattr(github_cli, "accept_by_merge", lambda *_a, **_k: ("", False))
    drive.answer(card, "Retry now")
    assert "accepted on its branch" in drive.advance()


def test_a_held_account_parks_the_pass_on_a_limit_card_the_clock_answers(drive, monkeypatch):
    from dplanner.modules.agent_supervisor import limits
    from dplanner.modules.step_playbook import engine

    drive.cli("playbook", "set", "Build it", "plan-execute-person")
    drive.play(
        {"lines": [INIT, result("A plan", session="s")]}, {"lines": [INIT, result(typed=done())]}
    )
    drive.cli("agent", "run", "Build it", "--playbook")
    drive.supervise()
    reset = datetime.now(UTC) + timedelta(hours=2)
    monkeypatch.setattr(limits, "hold", lambda *_a, **_k: "Claude Code is at 97 %")
    monkeypatch.setattr(limits, "held_until", lambda *_a, **_k: reset)
    drive.advanced.clear()
    assert "could not go on" in drive.advance()
    card = drive.asked()
    assert (card.kind, card.purpose, card.stage) == ("limit", "escalation", "execute")
    assert card.resets == reset.isoformat() and len(drive.started) == 1
    assert drive.advanced == [str(drive.plan)]  # `playbook wake` waits for the reset.
    # The reset comes: the clock answers the card, and the pass advances on it.
    monkeypatch.setattr(limits, "hold", lambda *_a, **_k: "")
    monkeypatch.setattr(engine, "datetime", _Later(reset))
    drive.advanced.clear()
    said = engine.wake(drive.plan, card.id, sleep=lambda _s: None)
    assert "has reset" in said and drive.advanced == [card.step]
    answered = questions.find(drive.plan, card.id)
    assert answered is not None and answered.answer["by"]["kind"] == "clock"
    drive.advance()
    assert (drive.latest().stage, drive.latest().attempt) == ("execute", 1)


def test_a_role_no_profile_runs_any_more_blocks_until_retry_now(drive, monkeypatch):
    from dplanner.modules.agent_launch import cli as launch_cli

    drive.cli("playbook", "set", "Build it", "plan-execute-person")
    drive.play(
        {"lines": [INIT, result("A plan", session="s")]}, {"lines": [INIT, result(typed=done())]}
    )
    drive.cli("agent", "run", "Build it", "--playbook")
    drive.supervise()
    from dplanner.modules.agent_launch.launch import profile_for as real

    monkeypatch.setattr(launch_cli, "profile_for", lambda *_: None)
    assert "could not go on" in drive.advance()
    card = drive.asked()
    assert (card.kind, card.stage, card.resets) == ("blocked", "execute", "")
    assert "no launch profile runs claude" in card.text
    monkeypatch.setattr(launch_cli, "profile_for", real)
    drive.answer(card, "Retry now")
    drive.advance()
    assert drive.latest().stage == "execute" and len(drive.started) == 2


def test_a_step_with_a_pass_under_way_refuses_another(drive):
    drive.cli("playbook", "set", "Build it", "spike")
    drive.play({"lines": [INIT, result("A plan", session="s")]})
    drive.cli("agent", "run", "Build it", "--playbook")
    said = drive.cli("agent", "run", "Build it", "--playbook", expect=1)
    assert "has a playbook pass under way" in said and "is running" in said
    drive.supervise()
    drive.advance()  # The pass now waits on its person gate, with no run going.
    said = drive.cli("agent", "run", "Build it", "--playbook", expect=1)
    assert f"{drive.asked().short} waits for an answer" in said
    # One pass, one run: the second launch's revive picked the first run up again (its stub
    # supervisor never took it), and started nothing else.
    assert {run for _dir, run in drive.started} == {drive.latest().run}


def test_the_first_record_is_on_disk_before_the_claim_and_both_before_the_start(
    drive, cli_library, monkeypatch
):
    """S11's launch order: the run's record, then the claim saved, then the supervisor — so a
    crash between the claim and the start leaves a record with no turn that revive starts."""
    from dplanner.domain.store import LibraryStore

    seen: list[tuple[int, str]] = []

    def start_detached(project_dir, run, **_kw):
        plan_now = LibraryStore(cli_library).load()
        step = next(s for p in plan_now.projects for s in p.steps if s.title == "Build it")
        seen.append((len(ledger.records(project_dir)), str(stored(step))))

    monkeypatch.setattr(supervisor, "start_detached", start_detached)
    drive.cli("playbook", "set", "Build it", "spike")
    drive.cli("agent", "run", "Build it", "--playbook")
    assert seen == [(1, str(Status.IN_PROGRESS))]
    # The crash: a record, its claim, no start. A machine's start picks it up.
    (record,) = ledger.records(drive.plan)
    assert not record.turns and record.settings
    monkeypatch.setattr(supervisor, "start_detached", lambda d, run, **_k: seen.append((0, run)))
    assert supervisor.revive([drive.plan], library=cli_library) == [record.run]


def test_a_refused_flush_takes_the_passs_first_record_back(drive, monkeypatch):
    from dplanner.domain.store import LibraryStore, StaleWorkspaceError

    def stale(self, marks):
        raise StaleWorkspaceError("the plan changed underneath")

    drive.cli("playbook", "set", "Build it", "spike")
    monkeypatch.setattr(LibraryStore, "flush", stale)
    assert "nothing was written" in drive.cli("agent", "run", "Build it", "--playbook", expect=1)
    assert ledger.records(drive.plan) == [] and not drive.started


def test_a_later_stages_record_with_no_turn_is_started_by_revive_whatever_the_status(
    drive, cli_library, monkeypatch
):
    drive.cli("playbook", "set", "Build it", "review-only")
    drive.cli("status", "set", "Build it", "ready-for-review")
    drive.play({"lines": [INIT, result(typed=CHANGES, session="r1")]})
    drive.cli("agent", "run", "Build it", "--playbook")
    drive.supervise()
    drive.advance()  # The fix's record is written; say its supervisor never started.
    fix = drive.latest()
    assert fix.stage == "fix" and not fix.turns and fix.settings is None
    restarted: list[str] = []
    monkeypatch.setattr(supervisor, "start_detached", lambda _d, run, **_k: restarted.append(run))
    monkeypatch.setattr(supervisor, "_age", lambda _record: 10_000.0)
    supervisor.revive([drive.plan], library=cli_library)
    assert restarted == [fix.run] and ledger.find(drive.plan, fix.run) is not None


def test_a_first_review_with_no_turn_on_a_step_at_review_is_kept_and_started(
    drive, cli_library, monkeypatch
):
    """A pass begun at review takes no claim — the step stays Ready for review — so its first
    record, its supervisor not started yet, read as a launch that died before its claim: a
    new launch and ``revive`` both deleted it, and its pinned settings with it."""
    drive.cli("playbook", "set", "Build it", "review-only")
    drive.cli("status", "set", "Build it", "ready-for-review")
    drive.cli("agent", "run", "Build it", "--playbook")  # Its supervisor never ran.
    (first,) = ledger.records(drive.plan)
    assert first.stage == "review" and not first.turns and first.settings is not None
    said = drive.cli("agent", "run", "Build it", "--playbook", expect=1)
    assert "has a playbook pass under way" in said
    restarted: list[str] = []
    monkeypatch.setattr(supervisor, "start_detached", lambda _d, run, **_k: restarted.append(run))
    monkeypatch.setattr(supervisor, "_age", lambda _record: 10_000.0)
    supervisor.revive([drive.plan], library=cli_library)
    assert restarted == [first.run] and ledger.records(drive.plan) == [first]


def _died(owed) -> None:
    """What a process that died leaves undone: everything but its OS locks."""
    for undo in owed:
        if isinstance(getattr(undo, "__self__", None), ExitStack):
            undo()


class _Later:
    """``datetime`` as the engine reads it, a moment past ``reset``."""

    def __init__(self, reset: datetime) -> None:
        self._now = reset + timedelta(minutes=5)

    def now(self, tz=None) -> datetime:
        return self._now


def test_a_pass_needs_its_roles_runnable_and_a_playbook_to_run(drive):
    from dplanner.modules.agent_launch.profiles import Profile, write_profiles

    assert "has no playbook" in drive.cli("agent", "run", "Build it", "--playbook", expect=1)
    assert "a playbook runs headless" in drive.cli(
        "agent", "run", "Build it", "--playbook", "spike", "--terminal", expect=1
    )
    drive.cli("playbook", "set", "Build it", "plan-execute-review-other", "--reviewer", "codex")
    write_profiles([Profile("Claude", "")])
    said = drive.cli("agent", "run", "Build it", "--playbook", expect=1)
    assert "no launch profile runs the reviewer, codex" in said
    assert drive.started == [] and _status(drive.cli, "Build it") == "pending"


def test_work_already_under_review_starts_at_the_first_gate_and_is_not_claimed(drive):
    drive.cli("status", "set", "Build it", "ready-for-review")
    drive.cli("playbook", "set", "Build it", "plan-execute-person")
    drive.cli("agent", "run", "Build it", "--playbook")
    assert drive.started == []
    gate = drive.asked()
    assert (gate.stage, gate.purpose) == ("person", "gate") and gate.settings
    assert _status(drive.cli, "Build it") == "ready-for-review"


def test_a_pass_is_under_way_between_stages_until_it_has_ended(drive):
    """A finished stage waiting for its advance is still the pass's — and once a person
    stops it, the step is free for another."""
    drive.cli("playbook", "set", "Build it", "spike")
    drive.play({"lines": [INIT, result("A plan", session="s")]})
    drive.cli("agent", "run", "Build it", "--playbook")
    drive.supervise()  # The plan is done; its advance has not run.
    said = drive.cli("agent", "run", "Build it", "--playbook", expect=1)
    assert "has a playbook pass under way" in said and "person stage is due" in said
    drive.advance()
    drive.answer(drive.asked(), "Stop")
    assert "stopped the pass" in drive.advance()
    drive.play({"lines": [INIT, result("Another plan", session="s2")]})
    drive.cli("agent", "run", "Build it", "--playbook")
    assert len(drive.started) == 2


def test_a_retry_after_a_crash_before_the_claim_was_saved_recovers(drive, monkeypatch):
    """The first record was written, then the process died before its claim was flushed:
    nothing will ever start that run. Retrying launches the pass afresh instead of refusing it
    as one under way, and the dead record goes."""
    from dplanner.cli import discovery
    from dplanner.domain.store import LibraryStore, StaleWorkspaceError

    def crash(self, marks):
        raise StaleWorkspaceError("the process died here")

    drive.cli("playbook", "set", "Build it", "spike")
    with monkeypatch.context() as crashing:
        crashing.setattr(LibraryStore, "flush", crash)
        # A crash rolls nothing back — but the operating system frees its locks as the process
        # dies, which in this one process means closing the launch lock's ExitStack.
        crashing.setattr(discovery, "_unwind", _died)
        drive.cli("agent", "run", "Build it", "--playbook", expect=1)
    (orphan,) = ledger.records(drive.plan)
    assert orphan.pass_ and not orphan.turns and _status(drive.cli, "Build it") == "pending"
    assert not drive.started
    drive.cli("agent", "run", "Build it", "--playbook")
    (record,) = ledger.records(drive.plan)
    assert record.run != orphan.run and drive.started == [(drive.plan, record.run)]
    assert _status(drive.cli, "Build it") == "in-progress"


def test_every_stage_of_a_pass_runs_as_the_member_that_started_it(drive):
    drive.cli("playbook", "set", "Build it", "plan-execute-review-self")
    drive.cli("claim", "take", "Build it", "--callsign", "kettle", "--project", "widget")
    drive.play(
        {"lines": [INIT, result("## Plan\n\nAdd the lock.", session="plan-s")]},
        {"lines": [INIT, result(typed=done(), session="plan-s")]},
    )
    drive.cli("agent", "run", "Build it", "--playbook", "--callsign", "kettle-two")
    plan = drive.latest()
    assert plan.callsign == "kettle-two"
    assert "You are Kettle Two" in drive.prompt(plan)
    assert "`Callsign: kettle-two`" in drive.prompt(plan)
    drive.supervise()
    drive.advance()
    execute = drive.latest()
    assert execute.stage == "execute" and execute.callsign == "kettle-two"
    assert "You are Kettle Two, of the squad Kettle Actual coordinates" in drive.prompt(execute)


def test_a_landing_that_never_chose_lands_is_reviewed_and_waits_for_a_person_to_merge(
    drive, code, tmp_path, monkeypatch
):
    """A landing runs *Land* by default: its execute is briefed with the landing's own work,
    the other agent's review passes, and the person's pass ends the pass with nothing merged —
    the mainline is a person's to merge, so gh is never asked."""
    drive.cli("branch", "put", "Build it", "--branch", "feature/x")  # B2 cuts it, S3 lands it.
    origin = tmp_path / "origin.git"  # The landing's worktree is cut from a remote.
    for argv in (
        ["init", "-q", "--bare", str(origin)],
        ["-C", str(code), "remote", "add", "origin", str(origin)],
        ["-C", str(code), "push", "-q", "origin", "HEAD:refs/heads/main"],
        ["-C", str(code), "fetch", "-q", "origin"],
        ["-C", str(code), "remote", "set-head", "origin", "main"],
    ):
        subprocess.run(["git", *argv], check=True, capture_output=True)
    monkeypatch.setattr(github_cli, "view_pr", lambda *_: pytest.fail("gh was asked"))
    monkeypatch.setattr(github_cli, "accept_by_merge", lambda *_a, **_k: pytest.fail("merged"))
    drive.play(
        {"lines": [INIT, result(typed=done(), session="land")]},
        {"lines": [INIT, result(typed=PASSES, session="review")]},
    )
    drive.cli("agent", "run", "S3", "--playbook", "--anyway")
    execute = drive.supervise()
    assert (execute.stage, execute.settings["preset"]) == ("execute", "land")
    assert "Land the feature branch `feature/x`" in drive.prompt(execute)
    drive.advance("S3")
    assert drive.supervise().stage == "review"
    drive.advance("S3")
    gate = drive.asked()
    assert (gate.stage, gate.purpose) == ("person", "gate")
    drive.answer(gate, "Pass")
    said = drive.advance("S3")
    assert "is through" in said and "the step is done" not in said
    assert _status(drive.cli, "S3") != "done"


def test_a_claim_ended_while_an_advance_prepares_its_next_stage_launches_nothing(
    drive, monkeypatch
):
    """The claim's ending finds the launch lock busy with the advance and leaves it to it: the
    stage must then read the claim the pass started under as gone — a blocked card — never as
    no claim at all, which would launch it solo."""
    from dplanner.domain import claims
    from dplanner.domain.model import now_stamp
    from dplanner.modules.agent_supervisor import limits

    drive.cli("playbook", "set", "Build it", "plan-execute-person")
    drive.cli("claim", "take", "Build it", "--callsign", "kettle", "--project", "widget")
    drive.play({"lines": [INIT, result("A plan", session="s")]})
    drive.cli("agent", "run", "Build it", "--playbook", "--callsign", "kettle-two")
    claim = drive.latest().claim
    assert claim
    drive.supervise()

    def ended_meanwhile(*_a: object, **_k: object) -> str:
        by = {"kind": "person", "name": "test"}
        found = claims.find(drive.plan, claim)
        if found is not None and not found.ended:
            claims.update(drive.plan, claim, lambda c: claims.ended(c, by, "done", now_stamp()))
        return ""

    monkeypatch.setattr(limits, "hold", ended_meanwhile)
    assert "could not go on" in drive.advance()
    card = drive.asked()
    assert (card.kind, card.stage) == ("blocked", "execute")
    assert "has ended or no longer holds the step" in card.text
    assert len(drive.started) == 1 and ledger.records(drive.plan)[-1].stage == "plan"
