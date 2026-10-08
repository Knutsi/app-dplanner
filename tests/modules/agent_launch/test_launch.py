"""``dplanner agent run``: the launch the window's Run Agent makes, from a terminal — headless
under a supervisor or in the profile's terminal — and the lost turns a machine picks up.

Nothing here starts a supervisor or a terminal for real: ``start_detached`` and the
terminal's spawn are captured, and the one run driven end to end goes through the fake
agent CLI, as the supervisor's own tests do."""

import json
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from dplanner.domain import ledger, questions
from dplanner.domain.headless import LimitWindow, TurnEnd
from dplanner.domain.ledger import LedgerRecord, Turn
from dplanner.domain.model import Step
from dplanner.modules.agent_claude import harness as claude
from dplanner.modules.agent_launch import launcher
from dplanner.modules.agent_launch.workflows import run_agent
from dplanner.modules.agent_supervisor import limits, supervisor
from dplanner.planning.status import MODULE_ID as STATUS_ID
from dplanner.planning.status import Status, stored, write


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


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
    # The supervisor here is a stub, so the run never got a turn: the second launch picks
    # that one up again — its step is still claimed — and starts no other.
    assert started == [(plan, run), (plan, run)]


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


# -- Kettle Watch round 1 -------------------------------------------------------------------


def test_two_launches_of_one_step_at_once_start_one_run(cli, plan, monkeypatch):
    """The first launch holds the step's launch lock from its first check to its start; the
    second, arriving while the first is starting, is refused rather than racing it."""
    import threading

    starting, release = threading.Event(), threading.Event()
    started: list[str] = []

    def slow_start(_project_dir, run, **_kw):
        starting.set()
        release.wait(10)
        started.append(run)

    monkeypatch.setattr(supervisor, "start_detached", slow_start)
    first: list[str] = []
    racing = threading.Thread(target=lambda: first.append(cli("agent", "run", "Build it")))
    racing.start()
    try:
        assert starting.wait(10)
        said = cli("agent", "run", "Build it", expect=1)
    finally:
        release.set()
        racing.join(10)
    assert "is being launched right now" in said
    assert len(started) == 1 and first and len(ledger.records(plan)) == 1


def test_a_refused_flush_starts_nothing_and_takes_the_record_back(cli, plan, started, monkeypatch):
    """The claim is written before the run starts: a flush another writer refused leaves no
    run started and no record behind."""
    from dplanner.domain.store import LibraryStore, StaleWorkspaceError

    def stale(self, marks):
        raise StaleWorkspaceError("the plan changed underneath")

    monkeypatch.setattr(LibraryStore, "flush", stale)
    said = cli("agent", "run", "Build it", expect=1)
    assert "nothing was written" in said
    assert not started and ledger.records(plan) == []
    monkeypatch.undo()
    assert _status(cli, "Build it") == "pending"


def test_a_failed_start_withdraws_the_claim_it_wrote(cli, plan, monkeypatch):
    def refuse(_project_dir, _run, **_kw):
        raise OSError(2, "No such file or directory")

    monkeypatch.setattr(supervisor, "start_detached", refuse)
    said = cli("agent", "run", "Build it", expect=1)
    assert "no run started" in said and "back where it was" in said
    assert ledger.records(plan) == [] and _status(cli, "Build it") == "pending"


def test_a_launch_interrupted_before_its_start_is_started_or_dropped(tmp_path, started):
    """A record with no turn and no supervisor: started while its step is still claimed,
    deleted once nobody claims it — and left alone while its launch still holds the lock."""
    plan = tmp_path / "plan"
    kept, dropped, busy = (f"20261007T101500Z-0000000{n}" for n in (1, 2, 3))
    for run, step in ((kept, "s-claimed"), (dropped, "s-free"), (busy, "s-launching")):
        ledger.write(plan, replace(_headless(run), step=step))
    with supervisor.launching("p1", "s-launching"):
        found = supervisor.revive([plan], claimed=lambda record: record.step != "s-free")
    assert found == [kept] and started == [(plan, kept)]
    assert {record.run for record in ledger.records(plan)} == {kept, busy}


def test_every_turn_reaches_the_library_project_and_run_it_was_launched_with(
    tmp_path, allow_spawn, monkeypatch
):
    from tests.modules.agent_supervisor.test_supervisor import INIT, Rig, result

    from dplanner.domain.library_file import LIBRARY_ENV

    allow_spawn(Path(sys.executable))
    rig = Rig(tmp_path)
    rig.play({"lines": [INIT, result()]})
    seen: list[dict[str, str]] = []
    spawn = supervisor._spawn

    def watched(argv, cwd, env, err):
        seen.append(dict(env))
        return spawn(argv, cwd, env, err)

    monkeypatch.setattr(supervisor, "_spawn", watched)
    library = tmp_path / "chosen-library.json"
    rig.supervise(library=library)
    ((env,),) = [seen]
    assert env[LIBRARY_ENV] == str(library)
    assert (env["DPLANNER_PROJECT"], env["DPLANNER_RUN"]) == ("p1", rig.record.run)


def test_the_supervisor_is_started_on_the_library_of_its_launch(
    cli, plan, monkeypatch, cli_library
):
    argv: list[list[str]] = []
    monkeypatch.setattr(supervisor, "spawn_detached", lambda command: argv.append(command))
    cli("agent", "run", "Build it")
    ((command,),) = [argv]
    assert command[command.index("--library") + 1] == str(cli_library)
    assert command.index("--library") < command.index("agent")


def _launch_module(services):
    from dplanner.modules.agent_launch.module import AgentLaunchModule

    return next(m for m in services.modules if isinstance(m, AgentLaunchModule))


def _said(services, monkeypatch) -> list[str]:
    words: list[str] = []
    monkeypatch.setattr(services.window, "show_status", lambda text, _ms=0: words.append(text))
    return words


def test_a_branch_plan_that_refuses_refuses_the_launch(services, step_of, monkeypatch):
    """Two stretches that do not nest give a plan with a refusal and nothing else: the
    shared gate refuses it, rather than launching from the default branch."""
    from dplanner.planning.branches import BranchPlan

    module = _launch_module(services)
    plan = BranchPlan(refusal="it sits on two stretches that do not nest")
    monkeypatch.setattr(module, "_deps", replace(module._deps, branch_plan=lambda *_a: plan))
    step_of("Deploy")
    state = services.actions.spec("agent.run").state(services.context.current())
    assert not state.enabled and state.label == f"Run Agent — {plan.refusal}"


def test_the_window_refuses_a_step_another_launch_holds(services, step_of, monkeypatch):
    step = step_of("Deploy")
    words = _said(services, monkeypatch)
    project = services.document.project_of(step.id).id
    with supervisor.launching(project, step.id):
        services.actions.run("agent.run", services.context.current())
    assert words == ["No agent launched — “Deploy”: it is being launched right now"]


def test_the_window_refuses_a_step_whose_headless_run_is_not_over(services, step_of, monkeypatch):
    step = step_of("Deploy")
    module = _launch_module(services)
    project_dir = module._deps.project_dir(step.id)
    run = "20261007T101500Z-0000000a"
    ledger.write(project_dir, replace(_headless(run), step=step.id))
    words = _said(services, monkeypatch)
    services.actions.run("agent.run", services.context.current())
    assert words == [
        f"No agent launched — “Deploy”: its headless run {run} is not over — resume it instead"
    ]


def test_a_claim_the_window_cannot_save_starts_nothing(services, step_of, monkeypatch):
    module = _launch_module(services)
    monkeypatch.setattr(module, "_deps", replace(module._deps, flush=lambda: False))
    spawned: list[Path] = []
    monkeypatch.setattr(launcher, "resolve_command", lambda *_a, **_k: ["fake-term"])
    monkeypatch.setattr(launcher, "spawn", lambda _cmd, cwd, **_kw: _noted(spawned, cwd))
    step = step_of("Deploy")
    words = _said(services, monkeypatch)
    services.actions.run("agent.run", services.context.current())
    assert not spawned and stored(step) is Status.PENDING
    assert ledger.records(module._deps.project_dir(step.id)) == []
    assert words == [
        "No agent launched on “Deploy” — its claim could not be saved — save the plan,"
        " then run it again"
    ]


def test_a_step_renamed_while_its_worktree_is_prepared_is_not_launched(
    services, step_of, monkeypatch, qtbot
):
    """The briefing would name the new worktree while the agent stood in the old one."""
    from dplanner.domain.commands import SetFieldCommand

    module = _launch_module(services)
    monkeypatch.setattr(module, "_deps", replace(module._deps, tasks=services.tasks))
    spawned: list[Path] = []
    monkeypatch.setattr(launcher, "resolve_command", lambda *_a, **_k: ["fake-term"])
    monkeypatch.setattr(launcher, "spawn", lambda _cmd, cwd, **_kw: _noted(spawned, cwd))
    step = step_of("Deploy")
    words = _said(services, monkeypatch)
    services.actions.run("agent.run", services.context.current())
    services.undo.push(SetFieldCommand(step.id, "title", "Deploy it"))  # While git works.
    qtbot.waitUntil(lambda: any("renamed" in said for said in words), timeout=10_000)
    assert not spawned and stored(step) is Status.PENDING


def test_an_unreadable_profiles_file_is_never_written_over(cli, plan, started):
    from dplanner.modules import agent_harnesses
    from dplanner.modules.agent_launch.profiles import (
        Profile,
        UnreadableProfilesError,
        adopt,
        problem,
        profiles_file,
        seed_profiles,
        write_profiles,
    )

    path = profiles_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")
    assert "cannot be read" in problem()
    assert seed_profiles(agent_harnesses()) == [] and not adopt([], True, "claude", "")
    with pytest.raises(UnreadableProfilesError):
        write_profiles([Profile("Mine")])
    assert path.read_text(encoding="utf-8") == "{ not json"
    assert "the agent profiles cannot be read" in cli("agent", "run", "Build it", expect=1)
    assert not started


def test_the_window_says_the_profiles_cannot_be_read(app, request):
    from dplanner.modules.agent_launch.module import PROFILES_NOTICE
    from dplanner.modules.agent_launch.profiles import profiles_file

    path = profiles_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[]", encoding="utf-8")
    services = request.getfixturevalue("services")
    (notice,) = [n for n in services.window.notices.notices() if n.id == PROFILES_NOTICE]
    assert "is not a profiles file" in notice.words
    assert path.read_text(encoding="utf-8") == "[]"  # Not seeded over.


# -- Kettle Watch round 2 -------------------------------------------------------------------


def test_revive_never_deletes_a_launch_another_caller_has_just_made(
    cli, plan, cli_library, started
):
    """B read the step pending before A saved its claim. After A started and let go of its
    lock, and before A's supervisor took its own, B's revive must not delete A's run: it
    reads the claim from disk inside the step's lock, and even an unclaimed run with no turn
    is left alone inside the grace."""
    run = json.loads(cli("agent", "run", "Build it", "--json"))["run"]  # A, its record turnless.
    assert started == [(plan, run)]
    stale = supervisor.revive([plan], claimed=lambda _record: False)  # B's old model.
    assert stale == [] and ledger.find(plan, run) is not None  # Inside the grace: kept.
    on_disk = supervisor.revive([plan], library=cli_library)  # The claim A saved.
    assert on_disk == [run] and started == [(plan, run), (plan, run)]
    held = ledger.run_dir(run)
    with supervisor.supervising(held):  # A's supervisor has its lock now.
        assert supervisor.revive([plan], claimed=lambda _record: False, grace=0) == []
    assert ledger.find(plan, run) is not None
    assert supervisor.revive([plan], claimed=lambda _record: False, grace=0) == []
    assert ledger.find(plan, run) is None  # Unclaimed, unheld, past the grace: dropped.


def test_a_failed_start_holds_the_lock_until_its_withdrawal_is_written(cli, plan, monkeypatch):
    """Released any earlier, another launch could find the step claimed and start beneath a
    withdrawal that then writes it back to pending."""
    from dplanner.domain.store import LibraryStore

    shown = json.loads(cli("step", "show", "Build it", "--json"))
    project, step = shown["project"], shown["id"]

    def refuse(_project_dir, _run, **_kw):
        raise OSError(2, "No such file or directory")

    flushes: list[bool] = []
    flush = LibraryStore.flush

    def watched(self, marks):
        try:
            with supervisor.launching(project, step):
                flushes.append(False)  # Free: nobody holds the step.
        except BlockingIOError:
            flushes.append(True)  # Held by the launch writing this.
        return flush(self, marks)

    monkeypatch.setattr(supervisor, "start_detached", refuse)
    monkeypatch.setattr(LibraryStore, "flush", watched)
    cli("agent", "run", "Build it", expect=1)
    assert flushes[-2:] == [True, True]  # The claim's flush, then the withdrawal's.
    with supervisor.launching(project, step):  # And let go once the rollback is written.
        pass


def test_the_window_saves_before_it_starts_even_a_step_already_in_progress(
    services, step_of, monkeypatch
):
    from dplanner.planning.status import status_command

    module = _launch_module(services)
    monkeypatch.setattr(module, "_deps", replace(module._deps, flush=lambda: False))
    spawned: list[Path] = []
    monkeypatch.setattr(launcher, "resolve_command", lambda *_a, **_k: ["fake-term"])
    monkeypatch.setattr(launcher, "spawn", lambda _cmd, cwd, **_kw: _noted(spawned, cwd))
    step = step_of("Deploy")
    status_command(step, Status.IN_PROGRESS, today=date(2026, 10, 7)).redo(services.document)
    services.actions.run("agent.run", services.context.current())
    assert not spawned and ledger.records(module._deps.project_dir(step.id)) == []
    assert stored(step) is Status.IN_PROGRESS  # Its own claim, never withdrawn by a launch.


def test_a_relative_library_reaches_every_turn_as_an_absolute_path(
    tmp_path, allow_spawn, monkeypatch
):
    """A turn runs in its worktree, where a relative path names nothing."""
    from tests.modules.agent_supervisor.test_supervisor import INIT, Rig, result

    from dplanner.domain.library_file import LIBRARY_ENV

    allow_spawn(Path(sys.executable))
    rig = Rig(tmp_path)
    rig.play({"lines": [INIT, result()]})
    seen: list[str] = []
    spawn = supervisor._spawn

    def watched(argv, cwd, env, err):
        seen.append(env[LIBRARY_ENV])
        return spawn(argv, cwd, env, err)

    monkeypatch.setattr(supervisor, "_spawn", watched)
    monkeypatch.chdir(tmp_path)
    rig.supervise(library=Path("mine.json"))
    assert seen == [str(tmp_path.resolve() / "mine.json")]


def test_a_step_another_squad_holds_is_never_launched(cli, plan, started):
    cli("claim", "take", "Build it", "--callsign", "osprey", "--project", "widget")
    said = cli("agent", "run", "Build it", "--anyway", expect=1)
    assert "held by squad osprey" in said and "--callsign" in said
    said = cli("agent", "run", "Build it", "--callsign", "kettle-two", expect=1)
    assert "held by squad osprey" in said
    assert started == []


def test_a_member_of_the_holding_squad_launches_under_its_claim(cli, plan, started):
    from dplanner.domain import claims

    cli("claim", "take", "Build it", "--callsign", "kettle", "--project", "widget")
    run = json.loads(cli("agent", "run", "Build it", "--callsign", "Kettle-Two", "--json"))["run"]
    record = ledger.find(plan, run)
    (claim,) = claims.records(plan)
    assert record is not None and (record.callsign, record.claim) == ("kettle-two", claim.id)


def test_an_account_near_its_limit_holds_a_headless_launch_with_the_reason(cli, plan, started):
    soon = datetime.now(UTC) + timedelta(hours=2)
    key = limits.account_of(claude.HARNESS)
    window = LimitWindow("five_hour", 0.97, soon)
    limits.record_turn(key, "earlier", [window], TurnEnd.DONE, None, datetime.now(UTC))
    said = cli("agent", "run", "Build it", expect=1)
    assert "Claude Code is at 97% of its five-hour window" in said
    assert started == [] and _status(cli, "Build it") != "in-progress"
    limits.set_hold_at(0.98)  # The person's threshold, not the default, decides.
    assert json.loads(cli("agent", "run", "Build it", "--json"))["mode"] == "headless"


def test_a_machine_picks_up_its_runs_waiting_for_a_reset_or_holding_an_answer(tmp_path, started):
    """A run waiting for its reset, and one parked on an answer nobody delivered — the
    clock's or a person's, of any kind — get a supervisor again; a park still waiting on a
    person does not."""
    plan = tmp_path / "plan"
    reset = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    parks = (
        ("20261007T101500Z-00000011", questions.LIMIT, "limit", reset, "open"),
        ("20261007T101500Z-00000012", questions.LIMIT, "limit", reset, "answered"),
        ("20261007T101500Z-00000013", questions.LIMIT, "limit", "", "open"),  # A person's.
        ("20261007T101500Z-00000014", questions.DECISION, "asked", "", "answered"),
        ("20261007T101500Z-00000015", questions.DECISION, "asked", "", "open"),  # A person's.
    )
    for run, kind, end, resets, state in parks:
        question = replace(
            questions.asked("p1", "s1", "2026-10-07T10:16:00+00:00", [questions.one("Out?")],
                            kind=kind, run=run, resets=resets),
            state=state,
        )  # fmt: skip
        questions.write(plan, question)
        turn = Turn(n=1, prompt="launch", started="…", end=end, ended="…", resets=resets,
                    question=question.id)  # fmt: skip
        ledger.write(plan, _headless(run, turn))
    woken = ["20261007T101500Z-00000011", "20261007T101500Z-00000012", "20261007T101500Z-00000014"]
    assert supervisor.revive([plan]) == woken
    assert started == [(plan, run) for run in woken]


# -- Kettle Watch round 1 on S18: ownership in the one launch -------------------------------


def _hold(project_dir: Path, project: str, step: str, squad: str) -> None:
    """``squad``'s live claim on ``step``, as a coordinator's ``claim take`` writes it."""
    from dplanner.domain import claims
    from dplanner.domain.model import now_stamp

    claims.write(project_dir, claims.claimed(project, squad, [step], now_stamp(), worker={}))


def test_the_window_never_launches_a_step_another_squad_holds(services, step_of, monkeypatch):
    spawned: list[Path] = []
    monkeypatch.setattr(launcher, "resolve_command", lambda *_a, **_k: ["fake-term"])
    monkeypatch.setattr(launcher, "spawn", lambda _cmd, cwd, **_kw: _noted(spawned, cwd))
    step = step_of("Deploy")
    project = services.document.project_of(step.id)
    project_dir = services.repo.project_dir(project.id)
    _hold(project_dir, project.id, step.id, "osprey")
    services.actions.run("agent.run", services.context.current())
    assert spawned == [] and ledger.records(project_dir) == []
    assert stored(step) is not Status.IN_PROGRESS


def test_the_window_rereads_ownership_just_before_it_starts(services, step_of, monkeypatch):
    """A squad takes the step while its worktree is prepared: nothing starts."""
    from dplanner.modules.agent_launch import launch

    spawned: list[Path] = []
    monkeypatch.setattr(launcher, "resolve_command", lambda *_a, **_k: ["fake-term"])
    monkeypatch.setattr(launcher, "spawn", lambda _cmd, cwd, **_kw: _noted(spawned, cwd))
    step = step_of("Deploy")
    project = services.document.project_of(step.id)
    project_dir = services.repo.project_dir(project.id)
    real = launch.place

    def taken_meanwhile(*args, **kwargs):
        _hold(project_dir, project.id, step.id, "osprey")
        return real(*args, **kwargs)

    monkeypatch.setattr(launch, "place", taken_meanwhile)
    services.actions.run("agent.run", services.context.current())
    assert spawned == [] and ledger.records(project_dir) == []


def test_agent_run_rereads_ownership_under_the_lock_just_before_it_starts(
    cli, plan, started, monkeypatch
):
    """The claim is released while the worktree is prepared: the launch refuses, and its
    record is taken back."""
    from dplanner.modules.agent_claims import ownership
    from dplanner.modules.agent_launch import cli as launch_cli
    from dplanner.modules.agent_launch import launch

    cli("claim", "take", "Build it", "--callsign", "kettle", "--project", "widget")
    real = launch.place

    def released_meanwhile(*args, **kwargs):
        ownership.release(plan, _step_id(cli), {"kind": "person", "name": "Knut"}, "changed mind")
        return real(*args, **kwargs)

    monkeypatch.setattr(launch_cli, "place", released_meanwhile)
    said = cli("agent", "run", "Build it", "--callsign", "kettle-two", expect=1)
    assert "claim changed" in said
    assert started == [] and ledger.records(plan) == []


def test_a_fenced_run_does_not_hold_the_step_from_its_new_owner(cli, plan, started):
    from dplanner.domain import claims

    cli("claim", "take", "Build it", "--callsign", "osprey", "--project", "widget")
    first = json.loads(cli("agent", "run", "Build it", "--callsign", "osprey-1", "--json"))
    (old,) = claims.records(plan)
    # Gone quiet, on another machine: every agent-shell call here renews this machine's.
    claims.write(
        plan, replace(old, heartbeat="2026-10-01T00:00:00+00:00", worker={"machine": "elsewhere"})
    )
    started.clear()
    cli("claim", "take", "Build it", "--callsign", "kettle", "--project", "widget")
    old_run = ledger.find(plan, first["run"])
    assert old_run is not None and old_run.fence  # Taken over: the old run is fenced.
    again = json.loads(cli("agent", "run", "Build it", "--callsign", "kettle-two", "--json"))
    # The new run starts; the fenced one may be handed a supervisor too, by `revive`, which
    # reads the fence and ends it stopped — settled, never resumed.
    assert started[-1] == (plan, again["run"])


def test_a_fenced_run_still_live_here_is_stopped_before_the_step_launches(plan, cli, monkeypatch):
    from dplanner.modules.agent_launch import launch

    run = "20261007T101500Z-0000cccc"
    ledger.write(plan, _headless(run, Turn(n=1, prompt="launch", started="…")))
    supervisor.fence(plan, run, "kettle", "taken over")
    live = {run}
    signalled: list[str] = []
    monkeypatch.setattr(supervisor, "supervised", lambda directory: directory.name in live)

    def stop(project_dir, run_id, by, why, config=None):
        signalled.append(run_id)
        live.discard(run_id)  # The turn ends on SIGTERM; its supervisor lets go.

    monkeypatch.setattr(supervisor, "stop", stop)
    assert launch.stop_fenced(plan, "s1", wait=2) == "" and signalled == [run]
    stopped = ledger.find(plan, run)
    assert stopped is not None and stopped.over  # Its supervisor gone, the run is ended.
    stuck = "20261007T101500Z-0000dddd"
    ledger.write(plan, _headless(stuck, Turn(n=1, prompt="launch", started="…")))
    supervisor.fence(plan, stuck, "kettle", "taken over")
    live.add(stuck)
    monkeypatch.setattr(supervisor, "stop", lambda *_a, **_k: None)  # One that will not end.
    assert "still stopping" in launch.stop_fenced(plan, "s1", wait=0.3)
    assert launch.unfinished_run(plan, "s1") == ""  # Fenced: over, as far as a launch cares.


def test_a_fenced_run_on_another_machine_is_left_to_that_machine(plan):
    from dplanner.modules.agent_launch import launch

    run = "20261007T101500Z-0000ffff"
    parked = Turn(n=1, prompt="launch", started="…", ended="…", end="asked")
    ledger.write(plan, _headless(run, parked, machine="elsewhere"))
    supervisor.fence(plan, run, "kettle", "taken over")
    assert launch.stop_fenced(plan, "s1", wait=0.1) == ""
    record = ledger.find(plan, run)
    assert record is not None and not record.over  # Its own supervisor ends it there.


def _step_id(cli) -> str:
    return str(json.loads(cli("step", "show", "Build it", "--json", "--project", "widget"))["id"])


# -- Kettle Watch round 2 on S18: a turn that outlived its supervisor -----------------------


@pytest.fixture
def orphan(allow_spawn):
    """A turn's process that outlived its supervisor (``tests/launching.py``)."""
    from tests.launching import orphaned_turn

    allow_spawn(Path(sys.executable))
    with orphaned_turn() as stamp:
        yield stamp


def test_a_takeover_ends_the_turn_its_killed_supervisor_left_running(cli, plan, started, orphan):
    """The supervisor was killed and its turn survived; another squad takes the step over and
    launches. The surviving turn's group is ended before the new run starts."""
    from dplanner.core.process import is_live
    from dplanner.domain import claims

    stamp = orphan
    cli("claim", "take", "Build it", "--callsign", "osprey", "--project", "widget")
    first = json.loads(cli("agent", "run", "Build it", "--callsign", "osprey-1", "--json"))
    turn = Turn(n=1, prompt="launch", started="…", pid=stamp.pid, boot=stamp.boot,
                pid_started=stamp.started)  # fmt: skip
    supervisor.update(plan, first["run"], lambda record: replace(record, turns=(turn,)))
    (old,) = claims.records(plan)
    # Gone quiet, on another machine: every agent-shell call here renews this machine's.
    claims.write(
        plan, replace(old, heartbeat="2026-10-01T00:00:00+00:00", worker={"machine": "elsewhere"})
    )
    cli("claim", "take", "Build it", "--callsign", "kettle", "--project", "widget")
    assert is_live(stamp)  # A fence alone reaches no process with no supervisor.
    started.clear()
    again = json.loads(cli("agent", "run", "Build it", "--callsign", "kettle-two", "--json"))
    assert not is_live(stamp)  # Ended before the new run started.
    assert started[-1] == (plan, again["run"])


def test_a_turn_that_will_not_end_holds_the_step_with_the_reason(plan, orphan, monkeypatch):
    from dplanner.core.process import is_live
    from dplanner.modules.agent_launch import launch

    stamp = orphan
    run = "20261007T101500Z-0000eeee"
    turn = Turn(n=1, prompt="launch", started="…", pid=stamp.pid, boot=stamp.boot,
                pid_started=stamp.started)  # fmt: skip
    ledger.write(plan, _headless(run, turn))
    supervisor.fence(plan, run, "kettle", "taken over")
    monkeypatch.setattr(supervisor, "end_orphaned_turn", lambda _record, _grace: False)
    assert "still stopping" in launch.stop_fenced(plan, "s1", wait=0.1)
    assert is_live(stamp)


def test_a_dplanner_verb_is_this_build_on_the_library_it_names(tmp_path):
    from dplanner.modules.agent_supervisor.supervisor import dplanner_argv

    assert dplanner_argv(None, "playbook", "advance", "S1") == [
        sys.executable,
        "-m",
        "dplanner",
        "playbook",
        "advance",
        "S1",
    ]
    library = tmp_path / "lib.dplanner"
    assert dplanner_argv(library, "agent", "run")[3:] == [
        "--library",
        str(library.resolve()),
        "agent",
        "run",
    ]


def test_a_verb_run_to_its_end_says_its_last_line_and_a_refusal_without_the_prefix(
    allow_spawn,
):
    from dplanner.modules.agent_launch.launch import run_dplanner

    allow_spawn(Path(sys.executable))
    said = "print('one'); print('started as run r1')"
    assert run_dplanner([sys.executable, "-c", said]) == (0, "started as run r1")
    refused = "import sys; print('dplanner: a pass is under way', file=sys.stderr); sys.exit(1)"
    assert run_dplanner([sys.executable, "-c", refused]) == (1, "a pass is under way")
