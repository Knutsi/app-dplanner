"""What a step's passes did, read back for the person reviewing them: ``history.history``
over runs and questions written to a plan directory, and ``passes.choices`` — what *Accept*
and *Send Back* mean for a pass now."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from tests.modules.agent_supervisor.test_supervisor import INIT, result
from tests.modules.step_playbook.test_passes import CHANGED, PASSED, gate, run, settings

from dplanner.domain import ledger, questions
from dplanner.domain.model import Step
from dplanner.modules.agent_claude import harness as claude
from dplanner.modules.agent_supervisor.supervisor import PLAN_FILE
from dplanner.modules.github import aspect as github
from dplanner.modules.step_playbook.engine import facts_of
from dplanner.modules.step_playbook.history import ANSWER, REVIEW, WORK, history
from dplanner.planning import status

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)
REVIEWED = "plan-execute-review-self"


def write(project_dir: Path, step: Step, *entries, pass_id: str = "P", preset: str = REVIEWED):
    """The entries as one pass of ``step`` left them, its settings on the first."""
    for index, entry in enumerate(entries):
        pinned = settings(preset).to_json() if index == 0 else None
        if isinstance(entry, ledger.LedgerRecord):
            ledger.write(project_dir, replace(entry, step=step.id, pass_=pass_id, settings=pinned))
        else:
            questions.write(
                project_dir,
                replace(entry, step=step.id, pass_=pass_id, settings=dict(pinned or {})),
            )


def reviewed(at_review: bool = True) -> Step:
    step = Step(title="The tab")
    if at_review:
        step.module_data[status.MODULE_ID] = {"status": "ready-for-review"}
    return step


def test_a_pass_straight_through_reads_as_its_work_and_its_verdict(tmp_path):
    step = reviewed()
    write(
        tmp_path,
        step,
        replace(run("plan"), summary="The plan"),
        replace(run("execute"), summary="Built the tab\n\nAnd its tests."),
        run("review", verdict=PASSED),
    )
    (only,) = history(tmp_path, step.id, facts_of(step), NOW)
    assert [e.kind for e in only.events] == [WORK, WORK, REVIEW]
    assert only.summary == "Built the tab\n\nAnd its tests."
    assert only.events[2].outcome == "pass" and only.events[2].summary == "Good"
    assert only.standing.phrase == "Waits for you · ready for review"
    # Through, with no PR: a person's look — Accept sets the step done, Send Back a round.
    assert only.choices.gate is None and not only.choices.accept and not only.choices.send_back


def test_findings_carry_the_implementers_reason_where_it_declined_one(tmp_path):
    step = reviewed()
    planned, executed = run("plan"), run("execute")
    review = run("review", verdict=CHANGED)
    fix = replace(
        run("execute"),
        attempt=2,
        summary="Fixed most",
        declined=({"finding": {"run": review.run, "index": 0}, "reason": "not a race"},),
    )
    write(tmp_path, step, planned, executed, review, fix, run("review", verdict=PASSED))
    (only,) = history(tmp_path, step.id, facts_of(step), NOW)
    flagged = only.events[2]
    assert flagged.kind == REVIEW and flagged.outcome == "changes"
    (finding,) = flagged.findings
    assert (finding.severity, finding.where, finding.text) == ("high", "a.py:3", "A race")
    assert finding.declined == "not a race"
    assert only.summary == "Fixed most"


def test_gate_answers_say_who_gave_them_and_a_changes_note_is_a_finding(tmp_path):
    step = reviewed()
    first = run("execute")
    person = gate("person", "Changes: the empty state says nothing")
    fixed = run("execute")
    coordinator = questions.answered(
        gate("coordinator"),
        {"?": "Pass"},
        {"kind": "coordinator", "name": "kettle"},
        NOW.isoformat(),
    )
    write(tmp_path, step, first, person, fixed, coordinator, preset="execute")
    events = history(tmp_path, step.id, facts_of(step), NOW)[0].events
    asked_person, asked_coordinator = (e for e in events if e.kind == ANSWER)
    assert asked_person.outcome == "Changes"
    assert [f.text for f in asked_person.findings] == ["the empty state says nothing"]
    assert (asked_coordinator.who, asked_coordinator.outcome) == ("kettle", "Pass")
    assert not asked_coordinator.findings


def test_passes_read_latest_first(tmp_path):
    step = reviewed()
    write(tmp_path, step, run("execute"), pass_id="old", preset="execute")
    write(tmp_path, step, run("execute"), pass_id="new", preset="execute")
    assert [each.pass_id for each in history(tmp_path, step.id, facts_of(step), NOW)] == [
        "new",
        "old",
    ]


def test_an_older_runs_summary_is_read_back_from_its_own_stream_here(tmp_path):
    """A run from before the summary was recorded: its typed final message, else its final
    text, from the stream this machine keeps — and nothing at all when neither is here."""
    config = tmp_path / "config"
    step = reviewed()
    planned, typed, prose, gone = run("plan"), run("execute"), run("execute"), run("execute")
    typed_said = {"outcome": "done", "summary": "From the schema", "question": "", "declined": []}
    for record, line in ((typed, result(typed=typed_said)), (prose, result("Plain words."))):
        directory = ledger.run_dir(record.run, config)
        directory.mkdir(parents=True)
        (directory / "turn-1.jsonl").write_text(f"{INIT}\n{line}\n", encoding="utf-8")
    plan_dir = ledger.run_dir(planned.run, config)
    plan_dir.mkdir(parents=True)
    (plan_dir / PLAN_FILE).write_text("1. Do it", encoding="utf-8")
    write(tmp_path, step, planned, typed, prose, gone, preset="execute")
    events = history(tmp_path, step.id, facts_of(step), NOW, (claude.HARNESS,), config)[0].events
    assert [e.summary for e in events] == ["1. Do it", "From the schema", "Plain words.", ""]


def test_what_accept_and_send_back_mean_follows_where_the_pass_stands(tmp_path):
    working = reviewed(at_review=False)
    write(tmp_path, working, run("execute", end="", over=False), preset="execute")
    choices = history(tmp_path, working.id, facts_of(working), NOW)[0].choices
    assert choices.accept == choices.send_back == "the pass is still at work"

    asked = reviewed()
    write(tmp_path, asked, run("execute"), gate("person"), preset="plan-execute-person")
    choices = history(tmp_path, asked.id, facts_of(asked), NOW)[0].choices
    assert choices.gate is not None and not choices.accept and not choices.send_back

    open_pr = reviewed()
    open_pr.module_data[github.MODULE_ID] = github.write(
        github.GithubRefs(branch="b", pr_number=7, pr_state=github.PR_OPEN)
    )
    write(tmp_path, open_pr, run("execute"), preset="execute")
    choices = history(tmp_path, open_pr.id, facts_of(open_pr), NOW)[0].choices
    assert choices.accept == "its PR is open — merging it sets the step done"
    assert not choices.send_back

    done = reviewed()
    done.module_data[status.MODULE_ID] = {"status": "done"}
    write(tmp_path, done, run("execute"), preset="execute")
    assert (
        history(tmp_path, done.id, facts_of(done), NOW)[0].choices.send_back == "the step is done"
    )
