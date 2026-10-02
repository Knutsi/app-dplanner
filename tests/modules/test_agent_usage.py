"""What agent runs consumed: harvested into the project's ledger by anybody — the wrapper's
`dplanner usage harvest`, the window when it sees a shell end, the sweep — and said by the
Agents browser, the Agent tab and the CLI's verbs."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests.conftest import TEST_MACHINE
from tests.modules.test_agent_readers import _rollout, _token_count

from dplanner.domain import ledger
from dplanner.domain.agents import AgentUsage, Tokens
from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules import agent_harnesses
from dplanner.modules.agent_claude import harness as claude
from dplanner.modules.step_agent_run import aspect, harvest, usage

HARNESSES = agent_harnesses()
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _transcript(config: Path, session: str, directory: Path, **counts: int) -> None:
    path = claude.transcript_path(session, str(directory), config)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "type": "assistant",
        "requestId": "r1",
        "message": {"id": "m1", "model": "claude-opus-5-5", "usage": counts},
    }
    path.write_text(json.dumps(line))


def _launched(
    plan: Path,
    run: str,
    harness: str,
    directory: Path,
    session: str = "",
    machine: str = "",
    launched: datetime = NOW - timedelta(hours=1),
) -> ledger.LedgerRecord:
    record = harvest.launch_record(
        run=run,
        project="p1",
        step="s1",
        harness=harness,
        directory=directory,
        session=session,
        launched=launched.isoformat(),
        machine=machine,
    )
    ledger.write(plan, record)
    return record


# -- the harvest, with no window at all ----------------------------------------------------------


def test_a_run_is_harvested_by_its_id_with_no_window_and_no_run_directory(tmp_path, monkeypatch):
    """What the wrapper script does when the agent exits: the launch record says which
    session, and the vendor's records say the rest."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    plan, tree = tmp_path / "plan", tmp_path / "tree"
    _launched(plan, "r1", "claude", tree, session="s-1")
    _transcript(tmp_path / "claude", "s-1", tree, input_tokens=7, output_tokens=3)

    record = harvest.harvest_run([plan], "r1", HARNESSES, code=0, ended=True)
    assert record is not None and record.tokens == Tokens(7, 0, 3)
    assert record.exit == 0 and record.ended and record.harvested
    assert ledger.find(plan, "r1") == record
    assert harvest.harvest_run([plan], "nobody", HARNESSES) is None


def test_a_harvest_never_writes_away_an_end_another_process_wrote(tmp_path):
    """The window's sweep read the record before the wrapper said the agent exited; its
    write keeps the exit."""
    plan = tmp_path / "plan"
    stale = _launched(plan, "r1", "claude", tmp_path)
    harvest.end(plan, "r1", 0, "2026-10-01T11:30:00+00:00")
    harvest.store(plan, stale)
    stored = ledger.find(plan, "r1")
    assert stored is not None and stored.ended == "2026-10-01T11:30:00+00:00"


def test_the_sweep_reads_this_machines_due_runs_and_nothing_else(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    plan, tree = tmp_path / "plan", tmp_path / "tree"
    for session in ("live", "ended", "elsewhere", "ancient"):
        _transcript(tmp_path / "claude", session, tree, input_tokens=1, output_tokens=1)
    _launched(plan, "live", "claude", tree, session="live")
    _launched(plan, "ended", "claude", tree, session="ended")
    harvest.end(plan, "ended", 0, (NOW - timedelta(minutes=5)).isoformat())
    _launched(plan, "elsewhere", "claude", tree, session="elsewhere", machine="another")
    old = NOW - timedelta(days=harvest.SWEEP_DAYS + 1)
    _launched(plan, "ancient", "claude", tree, session="ancient", launched=old)

    assert harvest.anything_due([plan], TEST_MACHINE)
    assert harvest.sweep([plan], HARNESSES, TEST_MACHINE, NOW) == 2
    read = {r.run: bool(r.agents) for r in ledger.records(plan)}
    assert read == {"live": True, "ended": True, "elsewhere": False, "ancient": False}
    # Read since it ended, the ended run is done with; a live one is read on every sweep,
    # and a read that finds nothing new writes nothing.
    due = {r.run for r in ledger.records(plan) if harvest.due(r, TEST_MACHINE, NOW)}
    assert due == {"live"}
    assert harvest.sweep([plan], HARNESSES, TEST_MACHINE, NOW) == 0


def test_two_runs_in_one_checkout_take_two_sessions(tmp_path, monkeypatch):
    """Codex names no session up front: each run claims the earliest one nobody else owns,
    so a second launch in the same directory cannot swallow the first one's."""
    home = tmp_path / "codex"
    monkeypatch.setenv("CODEX_HOME", str(home))
    plan, tree = tmp_path / "plan", tmp_path / "tree"
    launched = NOW - timedelta(minutes=30)
    first, second = "0" * 35 + "1", "0" * 35 + "2"
    _rollout(
        home, launched + timedelta(seconds=5), first, str(tree), [_token_count(input_tokens=1)]
    )
    _rollout(
        home, launched + timedelta(seconds=9), second, str(tree), [_token_count(input_tokens=2)]
    )
    _launched(plan, "a", "codex", tree, launched=launched)
    _launched(plan, "b", "codex", tree, launched=launched)
    harvest.sweep([plan], HARNESSES, TEST_MACHINE, NOW)
    assert {r.run: r.session for r in ledger.records(plan)} == {"a": first, "b": second}


# -- the window ------------------------------------------------------------------------------------


def module(services):
    return next(m for m in services.modules if m.id == aspect.MODULE_ID)


@pytest.fixture
def step(services, make_project):
    project = make_project("Discovery")
    step = Step(title="Deploy")
    AddNodeCommand(project.id, step).redo(services.document)
    services.autosave.flush_now()
    return step


def _plan_of(services, step) -> Path:
    return Path(services.repo.project_dir(services.document.project_of(step.id).id))


def test_a_launch_writes_the_run_into_the_ledger_and_its_end_is_read_back(
    services, step, tmp_path, monkeypatch, qtbot
):
    """The shell ends; the window marks the record ended and sweeps; the tokens land in the
    project's ledger, off the undo stack, and the browser says them."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    session = "3f1c0b8e-0000-4000-8000-000000000009"
    tree = tmp_path / "tree"
    runs = module(services)
    runs.track(
        step.id,
        str(tmp_path / "shell"),
        str(tmp_path / "exit"),
        "claude",
        session,
        18_412,
        run="20261001T100000Z-00000001",
        workdir=tree,
    )
    plan = _plan_of(services, step)
    (launched,) = ledger.records(plan)
    assert (launched.step, launched.session, launched.machine) == (step.id, session, TEST_MACHINE)
    assert launched.directory == str(tree.resolve()) and not launched.agents

    _transcript(tmp_path / "claude", session, tree, input_tokens=12000, output_tokens=345)
    (tmp_path / "shell").write_text("pid=1\n")
    services.autosave.flush_now()
    (tmp_path / "exit").write_text("0\n")
    runs.check()

    def read() -> ledger.LedgerRecord | None:
        found = ledger.find(plan, launched.run)
        return found if found is not None and found.agents else None

    qtbot.waitUntil(lambda: read() is not None, timeout=5000)
    record = read()
    assert record is not None and record.exit == 0 and record.tokens == Tokens(12000, 0, 345)
    assert not services.undo.can_undo()
    runs._open_browser()
    runs._browser.show_ended.setChecked(True)  # The run is over, so the switch lists it.
    (row,) = runs._browser.rows()
    assert row.status.words().endswith("briefed 18.4k chars · 12.0k in · 0 cached · 345 out")


def test_a_run_whose_minted_session_was_found_resumes_by_it(services, step, tmp_path):
    """Codex named no session up front: a harvest found and claimed one, and the browser
    offers `codex resume <id>` from what the ledger recorded."""
    runs = module(services)
    runs.track(
        step.id,
        str(tmp_path / "shell"),
        str(tmp_path / "exit"),
        "codex",
        "",
        run="r-codex",
        workdir=tmp_path,
    )
    plan = _plan_of(services, step)
    found = ledger.find(plan, "r-codex")
    assert found is not None
    ledger.write(plan, replace(found, session="thread-1"))
    (tmp_path / "shell").write_text(f"pid=1\ndir={tmp_path}\n")
    (tmp_path / "exit").write_text("0\n")
    services.autosave.flush_now()
    runs.check()
    (ended,) = runs.runs()
    assert runs._resume_of(ended) == f'cd "{tmp_path}" && codex resume thread-1'


def test_the_agent_tab_says_what_the_step_has_consumed(services, step):
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
    project = services.document.project_of(step.id)
    ledger.write(
        _plan_of(services, step),
        ledger.LedgerRecord(
            run="r",
            project=project.id,
            step=step.id,
            harness="claude",
            launched="2026-10-01T10:00:00+00:00",
            agents=(AgentUsage("main", {"m": Tokens(3000, 90_000, 200)}),),
        ),
    )
    section.show_target(step.id)
    assert section.usage_note.text() == "tokens: 3.0k in · 90.0k cached · 200 out"
    section.dispose()


# -- the retired step aspect ----------------------------------------------------------------------


def test_usage_rows_kept_on_a_step_move_into_the_ledger_at_the_next_open(cli, workspace):
    """The aspect that kept usage before the ledger is absorbed: every open moves what is
    left on a step into a legacy record, once, and takes the step's entry away."""
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy")
    (step_file,) = list(workspace.rglob("step.json"))
    old = step_file.parent / "modules" / f"{usage.MODULE_ID}.json"
    old.parent.mkdir(exist_ok=True)
    row = {
        "harness": "claude",
        "session": "s1",
        "input": 1500,
        "output": 40,
        "details": {"cache_read": 1000},
        "ended": "2026-09-11T10:00:00+00:00",
    }
    old.write_text(json.dumps({"runs": [row]}))

    shown = json.loads(cli("usage", "show", "S1", "--json"))
    assert (shown["input"], shown["cached"], shown["output"]) == (500, 1000, 40)
    assert shown["runs"][0]["measurement"] == ledger.LEGACY
    assert not old.exists()
    cli("usage", "show", "S1")  # A second open finds nothing left to move.
    assert len(list(workspace.rglob("legacy-s1.json"))) == 1


# -- the CLI -------------------------------------------------------------------------------------


def test_usage_show_list_record_and_harvest(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy", "--agent")
    assert "no agent run recorded" in cli("usage", "show", "S1")
    assert "no agent run recorded" in cli("usage", "list", "discovery")

    out = cli("usage", "record", "S1", "--agent", "codex", "--input", "12000", "--output", "800")
    assert "recorded 12.0k in · 0 cached · 800 out" in out
    session, tree = "3f1c0b8e-0000-4000-8000-000000000042", tmp_path / "tree"
    _transcript(tmp_path / "claude", session, tree, input_tokens=5, output_tokens=7)
    out = cli(
        "usage", "record", "S1", "--agent", "claude", "--session", session, "--dir", str(tree)
    )
    assert "recorded 5 in · 0 cached · 7 out" in out
    shown = json.loads(cli("usage", "show", "S1", "--json"))
    assert sorted((r["harness"], r["input"]) for r in shown["runs"]) == [
        ("claude", 5),
        ("codex", 12000),
    ]
    assert (shown["input"], shown["output"]) == (12005, 807)
    claude_run = next(r for r in shown["runs"] if r["harness"] == "claude")
    assert claude_run["models"] == {"claude-opus-5-5": {"in": 5, "cached": 0, "out": 7}}
    listed = json.loads(cli("usage", "list", "discovery", "--json"))
    assert listed["input"] == 12005 and listed["steps"][0]["title"] == "Deploy"
    assert "total: 12.0k in · 0 cached · 807 out over 2 runs" in cli("usage", "show", "S1")

    # A harvest by id reads the same record again: the transcript grew, the record follows.
    _transcript(tmp_path / "claude", session, tree, input_tokens=50, output_tokens=70)
    harvested = json.loads(cli("usage", "harvest", "--run", claude_run["run"], "--json"))
    assert (harvested["input"], harvested["output"]) == (50, 70)
    assert "read back 0 runs" in cli("usage", "harvest", "--all")  # Adopted runs are ended.

    assert "name the run with --run" in cli("usage", "harvest", expect=1)
    assert "no run nobody" in cli("usage", "harvest", "--run", "nobody", expect=1)
    err = cli("usage", "record", "S1", "--agent", "claude", "--input", "1", expect=1)
    assert "both --input and --output" in err
    err = cli("usage", "record", "S1", "--agent", "claude", "--session", "nope", expect=1)
    assert "no Claude Code record found" in err
