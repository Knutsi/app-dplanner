"""The playbook engine end to end: ``agent run --playbook`` starts a pass, each stage's run is
driven by the real supervisor over the fake agent CLI with scripted endings, and ``playbook
advance`` — what the supervisor and an answer start on their own — moves the pass on.

Nothing is started for real: ``start_detached`` is captured (``started``), the supervisor runs
in-process, and the detached advance it would start is recorded (``advanced``). Never a real
agent CLI, never a model API: the fake plays recorded-shape streams through Claude's readers.
"""

import json
import sys
from dataclasses import replace
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
    monkeypatch.setattr(supervisor, "spawn_detached", lambda argv: told.append(argv[-1]))
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


def test_progress_accepts_on_its_branch_or_asks_a_person(drive, monkeypatch):
    drive.cli("playbook", "set", "Build it", "plan-execute-progress")
    drive.play(
        {"lines": [INIT, result("A plan", session="s")]}, {"lines": [INIT, result(typed=done())]}
    )
    drive.cli("agent", "run", "Build it", "--playbook")
    drive.supervise()
    drive.advance()
    drive.supervise()
    refusals = iter(["PR #4 goes into the default branch, which a person merges"])
    monkeypatch.setattr(github_cli, "accept_by_merge", lambda *_a, **_k: next(refusals))
    assert "progress asks" in drive.advance()
    gate = drive.asked()
    assert gate.stage == "progress" and "default branch" in gate.text
    drive.answer(gate, "Pass")
    assert "is through" in drive.advance()


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
