"""``dplanner question ask|list|answer|escalate``: the door an agent asks through, and the
verbs that answer it — run in-process against a project with one headless run."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from tests.platforms import set_home

from dplanner.domain import ledger, questions
from dplanner.domain.ledger import LedgerRecord
from dplanner.domain.questions import Question
from dplanner.modules.agent_supervisor import supervisor
from dplanner.modules.step_agent_run.aspect import MODULE_ID

RUN = "20261007T101500Z-9c1e44ab"


@pytest.fixture
def project(cli, workspace, tmp_path, monkeypatch):
    """A project with a step, a headless run on it, and a home of the test's own."""
    set_home(monkeypatch, tmp_path / "home")
    cli("project", "create", "Discovery")
    monkeypatch.setenv("DPLANNER_PROJECT", "Discovery")  # As the supervisor sets it.
    cli("step", "add", "Discovery", "Read the spec")
    project_dir = workspace / "discovery"
    meta = json.loads((project_dir / "project.dproj").read_text(encoding="utf-8"))
    step = json.loads(cli("step", "show", "Read the spec", "--json"))
    ledger.write(
        project_dir,
        LedgerRecord(
            run=RUN,
            project=meta["id"],
            step=step["id"],
            harness="claude",
            launched="2026-10-07T10:15:00+00:00",
            mode=ledger.HEADLESS,
            stage="execute",
            callsign="kettle-three",
        ),
    )
    return project_dir


def test_asking_from_a_headless_run_records_the_question_on_it(cli, project, monkeypatch):
    monkeypatch.setenv("DPLANNER_RUN", RUN)
    said = cli(
        "question", "ask", "Keep both?", "--choice", "Keep both=Two clocks", "--choice", "Absorb"
    )
    (question,) = questions.records(project)
    assert f"Recorded as {question.short}" in said and "End your turn" in said
    assert (question.run, question.kind, question.by["callsign"]) == (
        RUN,
        "decision",
        "kettle-three",
    )
    assert question.questions[0]["options"] == [
        {"label": "Keep both", "description": "Two clocks"},
        {"label": "Absorb", "description": ""},
    ]

    cli("question", "ask", "Or neither?")
    states = sorted(q.state for q in questions.records(project))
    assert states == ["open", "withdrawn"]  # Asking again withdraws the first.


def test_asking_from_a_terminal_says_it_needs_input_and_records_nothing(cli, project, workspace):
    said = cli("question", "ask", "Keep both?", "--step", "Read the spec")
    assert "in a terminal" in said and questions.records(project) == []
    entry = workspace / "discovery" / "steps" / "read-the-spec" / "modules" / f"{MODULE_ID}.json"
    assert json.loads(entry.read_text(encoding="utf-8"))["state"] == "needs-input"
    assert "--step" in cli("question", "ask", "Keep both?", expect=1)


def test_a_plan_approval_carries_its_plan_as_the_body(cli_stdin, project, monkeypatch):
    monkeypatch.setenv("DPLANNER_RUN", RUN)
    cli_stdin(
        "question",
        "ask",
        "Approve?",
        "--kind",
        "plan-approval",
        "--body-file",
        "-",
        stdin="1. Do it",
    )
    (question,) = questions.records(project)
    assert (question.kind, question.body) == ("plan-approval", "1. Do it")


def test_listing_answering_and_escalating(cli, project, monkeypatch):
    monkeypatch.setenv("DPLANNER_RUN", RUN)
    cli("question", "ask", "Keep both?", "--choice", "Keep both", "--choice", "Absorb")
    (question,) = questions.records(project)
    listed = cli("question", "list", "--open")
    assert question.short in listed and "S1" in listed and "Keep both?" in listed

    monkeypatch.setenv("DPLANNER_RUN", "20261007T120000Z-c0c0c0c0")  # The coordinator's run.
    assert "escalated" in cli("question", "escalate", question.short, "--why", "a product call")
    assert stored(project, question.id).escalated["by"]["kind"] == "coordinator"
    monkeypatch.delenv("DPLANNER_RUN")  # A person's own shell.
    said = cli("question", "answer", question.short, "absorb", "--by", "Knut")
    # The run has not parked on it yet, so nothing is resumed — the answer waits in the file.
    assert "not parked on it" in said
    answered = stored(project, question.id)
    assert answered.answer["answers"] == {"Keep both?": "Absorb"}
    assert answered.answer["by"] == {"kind": "person", "name": "Knut"}
    assert "already answered" in cli("question", "answer", question.short, "Keep both", expect=1)
    assert cli("question", "list", "--open").count(question.short) == 1  # Answered, unconsumed.
    assert "no question" in cli("question", "answer", "Q-zzzz", "x", expect=1)


def test_a_run_may_not_answer_its_own_question(cli, project, monkeypatch):
    monkeypatch.setenv("DPLANNER_RUN", RUN)
    cli("question", "ask", "May I skip the tests?", "--choice", "Yes", "--choice", "No")
    (question,) = questions.records(project)
    said = cli("question", "answer", question.short, "Yes", expect=1)
    assert "your own run's question" in said
    assert stored(project, question.id).state == "open"


def _person_gate(project: Path) -> Question:
    gate = replace(
        questions.asked("p", "s", "2026-10-07T10:00:00+00:00", [questions.one("Ship it?")]),
        purpose="gate",
        stage="person",
    )
    questions.write(project, gate)
    return gate


def test_an_agent_cannot_answer_a_person_gate_or_say_it_is_a_person(cli, project, monkeypatch):
    gate = _person_gate(project)
    monkeypatch.setenv("DPLANNER_RUN", "20261007T120000Z-c0c0c0c0")  # Inside some run.
    assert "escalates it" in cli("question", "answer", gate.short, "yes", expect=1)
    with pytest.raises(SystemExit):  # There is no flag to claim to be a person.
        cli("question", "answer", gate.short, "yes", "--as", "person")
    assert stored(project, gate.id).state == "open"


def test_an_agent_shell_with_no_run_is_still_the_coordinator(cli, project, monkeypatch):
    gate = _person_gate(project)
    monkeypatch.setenv("CLAUDECODE", "1")  # Claude Code's shell marker, no run named.
    assert "escalates it" in cli("question", "answer", gate.short, "yes", expect=1)
    monkeypatch.delenv("CLAUDECODE")
    assert "parks no run" in cli("question", "answer", gate.short, "yes")


def stored(project_dir: Path, question_id: str) -> Question:
    found = questions.find(project_dir, question_id)
    assert found is not None
    return found


def test_agent_retry_answers_the_limit_a_run_is_held_on(cli, project):
    record = ledger.find(project, RUN)
    assert record is not None
    question = questions.asked(
        record.project,
        record.step,
        "2026-10-07T10:20:00+00:00",
        [questions.one("Out of usage.", "Usage limit", [(questions.RETRY_NOW, "")])],
        kind=questions.LIMIT,
        run=RUN,
    )
    questions.write(project, question)
    held = ledger.Turn(n=1, prompt="launch", started="…", end="limit", question=question.id)
    # Launched elsewhere: the answer waits for that machine, and nothing is started here.
    ledger.write(project, replace(record, machine="elsewhere", host="box").with_turns((held,)))

    said = cli("agent", "retry", "Read the spec", "--by", "Knut")
    assert "resumes when box, which launched it, sees the answer" in said
    answered = stored(project, question.id)
    assert answered.answer["answers"] == {"Out of usage.": questions.RETRY_NOW}
    assert "parked on no open question" in cli("agent", "retry", RUN, expect=1)


def test_agent_retry_refuses_a_step_with_no_parked_run(cli, project):
    assert "has no parked headless run" in cli("agent", "retry", "Read the spec", expect=1)


def test_an_answer_and_a_retry_resume_the_run_with_the_library_named(
    cli, project, cli_library, monkeypatch
):
    """`--library` named an alternate library; the supervisor an answer or Retry now started
    resolved the default one, so the resumed run's `dplanner` calls reached another plan."""
    started: list[list[str]] = []
    monkeypatch.setattr(supervisor, "spawn_detached", started.append)
    record = ledger.find(project, RUN)
    assert record is not None
    library = str(cli_library.expanduser().resolve())
    for kind, words, verb in (
        (questions.DECISION, "Keep both", ("question", "answer")),
        (questions.LIMIT, questions.RETRY_NOW, ("agent", "retry")),
    ):
        question = questions.asked(
            record.project,
            record.step,
            "2026-10-07T10:20:00+00:00",
            [questions.one("Which?", "Ask", [(words, "")])],
            kind=kind,
            run=RUN,
        )
        questions.write(project, question)
        held = ledger.Turn(n=1, prompt="launch", started="…", end="asked", question=question.id)
        ledger.write(project, record.with_turns((held,)))
        target = question.id if verb[0] == "question" else RUN
        cli(*verb, target, *([words] if verb[0] == "question" else []), "--by", "Knut")
        argv = started.pop()
        assert argv[argv.index("supervise") + 1] == RUN
        assert argv[argv.index("--library") + 1] == library
