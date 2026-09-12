"""The agent-usage ledger: the aspect, the window recording a run's tokens when its shell
ends, the Agents browser and the Agent tab showing them, and the CLI's verbs."""

import json
from pathlib import Path

import pytest

from dplanner.domain.agents import Usage
from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Project, Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.agent_claude import harness as claude
from dplanner.modules.step_agent_run import aspect, usage

# -- the aspect, with no application at all ----------------------------------------------------


def test_absence_reads_as_nothing_recorded():
    step = Step(title="A")
    assert usage.rows(step) == [] and usage.totals(step) is None and usage.summary(step) == ""


def test_rows_accumulate_and_a_session_recorded_twice_is_one_row():
    step = Step(title="A")
    step.module_data[usage.MODULE_ID] = usage.with_row(
        step, usage.row_for("claude", "s1", Usage(1000, 100), "2026-09-11T10:00:00+00:00")
    )
    step.module_data[usage.MODULE_ID] = usage.with_row(
        step, usage.row_for("codex", "t1", Usage(500, 50), "2026-09-11T11:00:00+00:00")
    )
    step.module_data[usage.MODULE_ID] = usage.with_row(
        step, usage.row_for("claude", "s1", Usage(1200, 120), "2026-09-11T12:00:00+00:00")
    )
    assert [(r["harness"], r["input"]) for r in usage.rows(step)] == [
        ("codex", 500),
        ("claude", 1200),
    ]
    assert usage.totals(step) == Usage(1700, 170)
    assert usage.summary(step) == "tokens: 1.7k in · 170 out"
    assert usage.words(Usage(2_500_000, 12)) == "2.5M in · 12 out"


def test_a_row_this_build_cannot_read_is_skipped():
    step = Step(title="A")
    step.module_data[usage.MODULE_ID] = {"runs": [{"input": "many"}, {"input": 3, "output": 4}, 7]}
    assert usage.totals(step) == Usage(3, 4)


def test_a_pasted_step_carries_no_usage():
    step = Step(title="A")
    step.module_data[usage.MODULE_ID] = {"runs": [{"input": 3, "output": 4}]}
    usage.forget_for_paste(Project(title="P"), [step])
    assert usage.MODULE_ID not in step.module_data


# -- the window: recorded when the shell ends --------------------------------------------------


def module(services):
    return next(m for m in services.modules if m.id == aspect.MODULE_ID)


@pytest.fixture
def step(services, make_project):
    project = make_project("Discovery")
    step = Step(title="Deploy")
    AddNodeCommand(project.id, step).redo(services.document)
    services.autosave.flush_now()
    return step


def _transcript(config: Path, session: str, directory: str, **counts: int) -> None:
    path = claude.transcript_path(session, directory, config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "assistant", "message": {"id": "m1", "usage": counts}}))


def test_an_ended_run_reads_its_tokens_back_and_records_them_on_the_step(
    services, step, tmp_path, monkeypatch
):
    """The shell ends; the harness that ran it is asked for its record of the session;
    the row lands on the step off the undo stack, the status bar and the browser say it."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    session = "3f1c0b8e-0000-4000-8000-000000000009"
    tree = tmp_path / "tree"
    _transcript(tmp_path / "claude", session, str(tree), input_tokens=12000, output_tokens=345)
    runs = module(services)
    runs.track(step.id, str(tmp_path / "shell"), str(tmp_path / "exit"), "claude", session)
    (tmp_path / "shell").write_text(f"pid=1\nsession={session}\ndir={tree}\n")
    services.autosave.flush_now()
    (tmp_path / "exit").write_text("0\n")
    runs.check()
    assert usage.totals(services.document.step(step.id)) == Usage(12000, 345)
    assert not services.undo.can_undo()
    assert "12.0k in · 345 out" in services.window.statusBar().currentMessage()
    runs._open_browser()
    (row,) = runs._browser._rows.values()
    assert row.status.text().endswith("12.0k in · 345 out")


def test_a_harness_that_mints_its_own_id_is_found_and_becomes_resumable(
    services, step, tmp_path, monkeypatch
):
    """Codex named no session up front: its record is found by directory and start time,
    the id is kept on the run, and the browser offers `codex resume <id>`."""
    from tests.modules.test_agent_harnesses import _rollout, _token_count

    from dplanner.modules.agent_codex import harness as codex

    home = tmp_path / "codex"
    monkeypatch.setenv("CODEX_HOME", str(home))
    tree = tmp_path / "tree"
    runs = module(services)
    runs.track(step.id, str(tmp_path / "shell"), str(tmp_path / "exit"), "codex", "")
    from datetime import datetime

    (run,) = runs.runs()
    started = datetime.fromisoformat(run.launched)
    thread = "00000000-0000-4000-8000-0000000000ee"
    _rollout(home, started, thread, str(tree), [_token_count(input_tokens=700, output_tokens=30)])
    assert codex.codex_home() == home
    (tmp_path / "shell").write_text(f"pid=1\ndir={tree}\n")
    services.autosave.flush_now()
    (tmp_path / "exit").write_text("0\n")
    runs.check()
    (ended,) = runs.runs()
    assert ended.session == thread
    assert runs._resume_of(ended) == f'cd "{tree}" && codex resume {thread}'
    assert usage.totals(services.document.step(step.id)) == Usage(700, 30)


def test_a_run_with_no_record_ends_as_before(services, step, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    runs = module(services)
    runs.track(step.id, str(tmp_path / "shell"), str(tmp_path / "exit"), "claude", "s")
    services.autosave.flush_now()
    (tmp_path / "exit").write_text("0\n")
    runs.check()
    assert runs.runs()[0].outcome == "finished"
    assert usage.totals(services.document.step(step.id)) is None
    # A session named up front still resumes, record or no record.
    assert runs._resume_of(runs.runs()[0]) == "claude --resume s"


def test_the_agent_tab_says_what_the_step_has_consumed(services, step, tmp_path, monkeypatch):
    from dplanner.modules.step_agent_instruction.aspect import MODULE_ID as AGENT_ID
    from dplanner.modules.step_agent_instruction.aspect import write_state

    services.document.set_module_data(step.id, AGENT_ID, write_state(True))
    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("step", step.id)),))
    spec = next(
        s for s in services.inspector_sections.sections() if s.id == "step_agent_instruction.tab"
    )
    section = spec.factory()
    section.show_target(step.id)
    assert section.usage_note.text() == ""
    usage.record(services.document, step.id, usage.row_for("claude", "s", Usage(3000, 200)))
    section.show_target(step.id)
    assert section.usage_note.text() == "tokens: 3.0k in · 200 out"
    section.dispose()


# -- the CLI ----------------------------------------------------------------------------------


def test_usage_show_list_and_record(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy", "--agent")
    assert "no agent run recorded" in cli("usage", "show", "S1")
    assert "no agent run recorded" in cli("usage", "list", "discovery")

    out = cli("usage", "record", "S1", "--agent", "codex", "--input", "12000", "--output", "800")
    assert "recorded 12.0k in · 800 out" in out
    session = "3f1c0b8e-0000-4000-8000-000000000042"
    _transcript(
        tmp_path / "claude", session, str(tmp_path / "tree"), input_tokens=5, output_tokens=7
    )
    out = cli(
        "usage",
        "record",
        "S1",
        "--agent",
        "claude",
        "--session",
        session,
        "--dir",
        str(tmp_path / "tree"),
    )
    assert "recorded 5 in · 7 out" in out
    shown = json.loads(cli("usage", "show", "S1", "--json"))
    assert [(r["harness"], r["input"]) for r in shown["runs"]] == [("codex", 12000), ("claude", 5)]
    assert (shown["input"], shown["output"]) == (12005, 807)
    listed = json.loads(cli("usage", "list", "discovery", "--json"))
    assert listed["input"] == 12005 and listed["steps"][0]["title"] == "Deploy"
    text = cli("usage", "show", "S1")
    assert "total: 12.0k in · 807 out over 2 runs" in text

    err = cli("usage", "record", "S1", "--agent", "claude", "--input", "1", expect=1)
    assert "both --input and --output" in err
    err = cli("usage", "record", "S1", "--agent", "claude", "--session", "nope", expect=1)
    assert "no Claude Code record found" in err
