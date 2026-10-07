"""``dplanner agent run``: the launch the window's Run Agent makes, from a terminal — headless
under a supervisor or in the profile's terminal — and the lost turns a machine picks up.

Nothing here starts a supervisor or a terminal for real: ``start_detached`` and the
terminal's spawn are captured, and the one run driven end to end goes through the fake
agent CLI, as the supervisor's own tests do."""

import json
import subprocess
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from dplanner.domain import ledger
from dplanner.domain.ledger import LedgerRecord, Turn
from dplanner.domain.model import Step
from dplanner.modules.agent_launch import launcher
from dplanner.modules.agent_launch.workflows import run_agent
from dplanner.modules.agent_supervisor import supervisor
from dplanner.planning.status import MODULE_ID as STATUS_ID
from dplanner.planning.status import Status, stored, write

URL = "https://github.com/acme/widget"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def code(tmp_path):
    """The project's code: a repository of its own with one commit, no remote."""
    from dplanner.core.storage.locations import init_repo

    repo = init_repo(tmp_path / "code")
    _git(repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q",
         "--allow-empty", "-m", "start")  # fmt: skip
    return repo


@pytest.fixture
def plan(cli, code, tmp_path, workspace):
    """A project whose code is ``code``, with one briefed agent step, "Build it"."""
    cli("project", "create", "Widget")
    cli("location", "add", "widget", "--role", "code", "--repository", URL,
        "--checkout", str(code))  # fmt: skip
    brief = tmp_path / "brief.md"
    brief.write_text("Build the widget.\n", encoding="utf-8")
    cli("step", "add", "widget", "Build it", "--agent")
    cli("describe", "set", "Build it", "--file", str(brief))
    return workspace / "widget"


@pytest.fixture
def started(monkeypatch):
    """Every supervisor a launch would have started, as (project dir, run)."""
    calls: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        supervisor,
        "start_detached",
        lambda project_dir, run, **_kw: calls.append((project_dir, run)),
    )
    return calls


def _noted(spawned: list[Path], cwd: Path) -> str:
    """A terminal that opened: where, and no refusal."""
    spawned.append(cwd)
    return ""


def _status(cli, title: str) -> str:
    return str(json.loads(cli("status", "show", title, "--json"))["status"])


def test_a_headless_launch_writes_the_run_before_its_supervisor_and_claims_the_step(
    cli, plan, code, started
):
    said = json.loads(cli("agent", "run", "Build it", "--json"))
    run = said["run"]
    tree = code / ".dplanner-worktrees" / "s1-build-it"
    assert said["mode"] == "headless" and said["workdir"] == str(tree)
    assert said["branch"] == "agent/s1-build-it"
    assert _git(tree, "branch", "--show-current") == "agent/s1-build-it"
    record = ledger.find(plan, run)
    assert record is not None and record.headless and not record.turns
    assert (record.stage, record.attempt, record.harness) == ("execute", 1, "claude")
    assert record.session and record.directory == str(tree.resolve())
    prompt = ledger.run_dir(run) / "prompt.md"
    assert "Build the widget." in prompt.read_text(encoding="utf-8")
    assert record.prompt_chars == len(prompt.read_text(encoding="utf-8"))
    assert started == [(plan, run)]
    assert _status(cli, "Build it") == "in-progress"


def test_a_step_with_a_headless_run_not_over_is_never_launched_twice(cli, plan, started):
    run = json.loads(cli("agent", "run", "Build it", "--json"))["run"]
    said = cli("agent", "run", "Build it", expect=1)
    assert f"already has a headless run, {run}" in said and "agent supervise" in said
    assert len(started) == 1


def test_a_terminal_launch_opens_the_profiles_terminal_in_the_worktree(
    cli, plan, code, started, monkeypatch
):
    spawned: list[Path] = []
    monkeypatch.setattr(launcher, "template_refusal", lambda _template: "")
    monkeypatch.setattr(launcher, "resolve_command", lambda *_a, **_k: ["fake-term"])
    monkeypatch.setattr(launcher, "spawn", lambda _cmd, cwd, **_kw: _noted(spawned, cwd))
    said = json.loads(cli("agent", "run", "Build it", "--terminal", "--json"))
    tree = code / ".dplanner-worktrees" / "s1-build-it"
    assert said["mode"] == "terminal" and spawned == [tree] and not started
    record = ledger.find(plan, said["run"])
    assert record is not None and not record.headless  # A terminal run stays format 1.
    assert _status(cli, "Build it") == "in-progress"


def test_a_run_that_does_not_start_takes_its_record_back_and_claims_nothing(cli, plan, monkeypatch):
    def refuse(_project_dir, _run, **_kw):
        raise OSError(2, "No such file or directory")

    monkeypatch.setattr(supervisor, "start_detached", refuse)
    said = cli("agent", "run", "Build it", expect=1)
    assert "the supervisor did not start" in said
    assert ledger.records(plan) == []
    assert _status(cli, "Build it") == "pending"


def test_unfinished_prerequisites_refuse_until_anyway(cli, plan, tmp_path, started):
    cli("step", "add", "widget", "Ship it", "--agent", "--after", "Build it")
    cli("describe", "set", "Ship it", "--file", str(tmp_path / "brief.md"))
    said = cli("agent", "run", "Ship it", expect=1)
    assert "waits on work not done yet" in said and "Build it" in said and "--anyway" in said
    assert not started
    cli("agent", "run", "Ship it", "--anyway")
    assert len(started) == 1


def test_what_cannot_run_is_refused_with_a_sentence(cli, plan, started):
    from dplanner.modules.agent_launch.profiles import Profile, write_profiles

    cli("step", "add", "widget", "Write it down")
    assert "mark the step as an agent step first" in cli("agent", "run", "Write it down", expect=1)
    assert "no launch profile is called 'Nope'" in cli(
        "agent", "run", "Build it", "--profile", "Nope", expect=1
    )
    write_profiles([Profile("Mine", "my-agent {prompt}")])
    assert "only a known agent runs headless" in cli("agent", "run", "Build it", expect=1)
    assert not started


def test_the_claim_is_a_change_and_nothing_when_the_step_already_says_so():
    step = Step(title="Build it")
    change = run_agent(step, today=date(2026, 10, 7))
    assert change.command is not None and not change.follow_ups
    step.module_data[STATUS_ID] = write(Status.IN_PROGRESS, today=date(2026, 10, 7))
    assert run_agent(step, today=date(2026, 10, 7)).command is None
    # A launch on a step that reads done means the work resumed.
    step.module_data[STATUS_ID] = write(Status.DONE, today=date(2026, 10, 7))
    assert run_agent(step, today=date(2026, 10, 7)).command is not None


def test_a_launched_record_is_one_the_supervisor_drives_to_its_end(cli, plan, started, allow_spawn):
    """End to end, the supervisor really running: the record ``agent run`` wrote is a run
    the fake agent plays a turn in, in the worktree, opened by the briefing's pointer."""
    from tests.modules.agent_supervisor.test_supervisor import FAKE, GUARDS, INIT, result

    from dplanner.modules.agent_claude import harness as claude

    allow_spawn(Path(sys.executable))
    run = json.loads(cli("agent", "run", "Build it", "--json"))["run"]
    script = plan.parent / "script.json"
    script.write_text(json.dumps([{"lines": [INIT, result()]}]), encoding="utf-8")
    prompts: list[str] = []

    def command(spec):
        prompts.append(spec.prompt)
        return [sys.executable, str(FAKE), str(script), "--", spec.prompt]

    harness = replace(claude.HARNESS, headless=replace(claude.HEADLESS, command=command))
    assert supervisor.supervise(plan, run, (harness,), guards=GUARDS) == f"run {run} is done"
    record = ledger.find(plan, run)
    assert record is not None and record.over and [t.end for t in record.turns] == ["done"]
    assert prompts == [
        f"Read your briefing in {ledger.run_dir(run) / 'prompt.md'} in full, then follow it."
    ]


# -- picking up lost turns ------------------------------------------------------------------


def _headless(run: str, *turns: Turn, machine: str = "", ended: str = "") -> LedgerRecord:
    record = LedgerRecord(
        run=run,
        project="p1",
        step="s1",
        harness="claude",
        launched="2026-10-07T10:15:00+00:00",
        machine=machine or ledger.machine_id(),
        mode=ledger.HEADLESS,
        stage="execute",
        attempt=1,
        ended=ended,
    )
    return record.with_turns(turns)


def test_a_machine_picks_up_its_lost_turns_and_nothing_else(tmp_path, started):
    running = Turn(n=1, prompt="launch", started="2026-10-07T10:15:01+00:00", pid=1)
    finished = replace(running, end="asked", ended="2026-10-07T10:20:00+00:00")
    plan = tmp_path / "plan"
    for record in (
        _headless("20261007T101500Z-00000001", running),  # Lost: picked up.
        _headless("20261007T101500Z-00000002", finished),  # Parked: a person's.
        _headless("20261007T101500Z-00000003", finished, ended="2026-10-07T10:20:00+00:00"),
        _headless("20261007T101500Z-00000004", running, machine="elsewhere"),
        _headless("20261007T101500Z-00000005", running),  # Its supervisor is alive.
        _headless("20261007T101500Z-00000006"),  # Launched, never started: a person's.
    ):
        ledger.write(plan, record)
    held = ledger.run_dir("20261007T101500Z-00000005")
    held.mkdir(parents=True)
    with supervisor.supervising(held):
        assert supervisor.revive([plan]) == ["20261007T101500Z-00000001"]
    assert started == [(plan, "20261007T101500Z-00000001")]


def test_a_supervisor_is_this_build_never_whatever_is_on_path(tmp_path, monkeypatch):
    """A run launched from a branch's build is supervised by that build."""
    argv: list[list[str]] = []
    monkeypatch.setattr(supervisor, "spawn_detached", lambda command: argv.append(command))
    supervisor.start_detached(tmp_path, "r1", prompt="answer", text="Keep both")
    assert argv == [
        [sys.executable, "-m", "dplanner", "agent", "supervise", "r1", "--project-dir",
         str(tmp_path), "--prompt", "answer", "--text", "Keep both"]
    ]  # fmt: skip


# -- the window ------------------------------------------------------------------------------


def test_the_window_prepares_worktrees_on_a_task_then_opens_the_terminals(
    services, step_of, library_repo, monkeypatch, qtbot
):
    """A fetch is network, so it runs on a task; the terminal opens once it is there."""
    from dplanner.modules.agent_launch.module import AgentLaunchModule

    module = next(m for m in services.modules if isinstance(m, AgentLaunchModule))
    monkeypatch.setattr(module, "_deps", replace(module._deps, tasks=services.tasks))
    spawned: list[Path] = []
    monkeypatch.setattr(launcher, "resolve_command", lambda *_a, **_k: ["fake-term"])
    monkeypatch.setattr(launcher, "spawn", lambda _cmd, cwd, **_kw: _noted(spawned, cwd))
    step = step_of("Deploy")
    services.actions.run("agent.run", services.context.current())
    tree = library_repo / ".dplanner-worktrees" / "s1-deploy"
    qtbot.waitUntil(lambda: spawned == [tree], timeout=10_000)
    assert stored(step) is Status.IN_PROGRESS


@pytest.fixture
def step_of(services, make_project):
    """A briefed agent step in a plan kept beside its code, selected."""
    from tests.modules.agent_launch.test_agent_run import select

    from dplanner.domain.commands import AddNodeCommand

    def make(title: str) -> Step:
        project = make_project("Discovery", legacy=True)
        step = Step(title=title)
        AddNodeCommand(project.id, step).redo(services.document)
        services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
        select(services, step)
        return step

    return make
