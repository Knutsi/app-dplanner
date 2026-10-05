"""The window launches what the plan made due — once, within the cap, from one window.

Agents report through the CLI, so here they are a second store over the same library file
writing their statuses, and the window takes the change in through its real watcher. The
launcher's settle runs with coalescing on (``set_immediate(False)`` and ``flush_all()``),
as it does in the application: a pass run *inside* the adoption that woke it would find the
plan still changed underneath and its claim unforwarded to autosave, so the suite's usual
inline settle is exactly the case the launcher must never meet.
"""

import pytest
from PySide6.QtWidgets import QLabel

from dplanner.domain.commands import (
    AddNodeCommand,
    SetEdgesCommand,
    SetFieldCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import Step
from dplanner.domain.store import LibraryStore
from dplanner.domain.workflow import Daemon
from dplanner.framework.user_config import set_global
from dplanner.modules.agent_launch import launcher
from dplanner.modules.agent_launch.auto_launch import (
    ANOTHER_WINDOW,
    INTERRUPTED,
    NOTICE_ID,
    LaunchLocks,
)
from dplanner.modules.agent_launch.intents import LaunchIntent
from dplanner.modules.agent_launch.settings_page import AUTO_LAUNCH_KEY, MAX_AGENTS_KEY
from dplanner.modules.auto_progress.aspect import MODULE_ID as AUTO_PROGRESS_ID
from dplanner.modules.auto_progress.aspect import write as write_flags
from dplanner.modules.step_agent_run.aspect import MODULE_ID as RUN_ID
from dplanner.modules.step_agent_run.aspect import asks_person
from dplanner.modules.step_agent_run.aspect import read as run_state
from dplanner.modules.step_agent_run.aspect import write as write_run
from dplanner.modules.step_review.aspect import MODULE_ID as ROUNDS_ID
from dplanner.modules.step_review.aspect import last, opened, said
from dplanner.planning.agent import MODULE_ID as AGENT_ID
from dplanner.planning.review import MODULE_ID as REVIEW_ID
from dplanner.planning.review import ReviewSettings
from dplanner.planning.review import write as write_review
from dplanner.planning.status import MODULE_ID as STATUS_ID
from dplanner.planning.status import Status
from dplanner.planning.status import stored as status_of
from dplanner.planning.status import write as write_status

SETTINGS_SECTION = "step_agent_instruction.launch"


def module(services, module_id):
    return next(m for m in services.modules if m.id == module_id)


def fake_terminal(monkeypatch):
    """Every command a terminal was asked to open, and no terminal."""
    opened_for: list[str] = []
    real_prepare = launcher.prepare

    def prepare(text, workdir, **kwargs):
        opened_for.append(kwargs.get("agent_command", ""))
        return real_prepare(text, workdir, **kwargs)

    monkeypatch.setattr(launcher, "prepare", prepare)
    monkeypatch.setattr(launcher, "resolve_command", lambda *a, **k: ["fake-term"])
    monkeypatch.setattr(launcher, "spawn", lambda cmd, cwd, **_kw: None)
    return opened_for


def launch_when_due(services):
    """The switch on, and the settle coalesced as the application runs it."""
    set_global(AGENT_ID, AUTO_LAUNCH_KEY, True)
    services.debounce.set_immediate(False)


def settle(services):
    services.debounce.flush_all()


def status_line(services):
    return services.window.statusBar().currentMessage()


def by_title(library, title):
    return next(
        step for project in library.projects for step in project.steps if step.title == title
    )


def another_writer(library_file, *titles, word="ready-for-review"):
    """What three agents' ``status set`` amount to: a second store, the statuses, a flush."""
    store = LibraryStore(library_file)
    library = store.load()
    marks: set[tuple[str, str]] = set()
    library.dirty.connect(lambda owner, aspect: marks.add((owner, aspect)))
    for title in titles:
        step = by_title(library, title)
        SetModuleDataCommand(step.id, STATUS_ID, write_status(Status(word), today=_today())).redo(
            library
        )
    store.flush(marks)


def _today():
    from datetime import date

    return date(2026, 9, 27)


def take_in(services):
    """The watcher's tick: the other writer's change adopted in place, then the settle."""
    module(services, "library_watch")._watcher._check()
    settle(services)


def agent_step(services, project, title, *, status="pending"):
    step = Step(title=title)
    AddNodeCommand(project.id, step).redo(services.document)
    services.document.set_text(step.id, AGENT_ID, f"Carry out {title}.")
    SetModuleDataCommand(step.id, STATUS_ID, write_status(Status(status), today=_today())).redo(
        services.document
    )
    return step


@pytest.fixture
def plan(services, make_project):
    """A1, A2 and A3 at work in parallel, and C collecting all three over auto-progress
    links — every one an agent step with a briefing — on disk, so the window starts clean."""
    project = make_project("Discovery", legacy=True)
    steps = {
        title: agent_step(services, project, title, status="in-progress")
        for title in ("A1", "A2", "A3")
    }
    collector = steps["C"] = agent_step(services, project, "C")
    sources = [steps[title].id for title in ("A1", "A2", "A3")]
    SetEdgesCommand(collector.id, "requires", sources).redo(services.document)
    SetModuleDataCommand(collector.id, AUTO_PROGRESS_ID, write_flags(sources)).redo(
        services.document
    )
    services.autosave.flush_now()
    return steps


# -- exactly once ------------------------------------------------------------------------------


def test_three_sources_reaching_review_at_once_launch_their_collector_once(
    services, plan, library_file, monkeypatch
):
    opened_for = fake_terminal(monkeypatch)
    launch_when_due(services)
    another_writer(library_file, "A1", "A2", "A3")
    take_in(services)

    assert len(opened_for) == 1
    collector = services.document.step(plan["C"].id)
    assert status_of(collector) is Status.IN_PROGRESS and run_state(collector) == "launched"
    on_disk = by_title(LibraryStore(library_file).load(), "C")  # Flushed now, not later.
    assert status_of(on_disk) is Status.IN_PROGRESS and run_state(on_disk) == "launched"
    assert "Launched the agent on" in status_line(services)
    # The next settle, whatever woke it, finds nothing due.
    services.undo.push(SetFieldCommand(plan["A1"].id, "title", "A1, renamed"))
    settle(services)
    assert len(opened_for) == 1


def test_sources_reaching_review_one_tick_apart_launch_it_on_the_last(
    services, plan, library_file, monkeypatch
):
    opened_for = fake_terminal(monkeypatch)
    launch_when_due(services)
    for title in ("A1", "A2"):
        another_writer(library_file, title)
        take_in(services)
    assert opened_for == []
    another_writer(library_file, "A3")
    take_in(services)
    assert len(opened_for) == 1


def test_with_the_switch_off_nothing_is_launched(services, plan, library_file, monkeypatch):
    opened_for = fake_terminal(monkeypatch)
    services.debounce.set_immediate(False)
    another_writer(library_file, "A1", "A2", "A3")
    take_in(services)
    assert opened_for == []
    assert status_of(services.document.step(plan["C"].id)) is Status.PENDING


# -- a launch is an external effect ------------------------------------------------------------


def test_the_intent_is_on_disk_when_the_shell_is_spawned_and_gone_once_the_claim_is(
    services, plan, library_file, launch_locks, monkeypatch
):
    fake_terminal(monkeypatch)
    intents = LaunchLocks(launch_locks).for_library(library_file).intents
    at_spawn: list[list[str]] = []
    monkeypatch.setattr(
        launcher,
        "spawn",
        lambda *_a, **_k: at_spawn.append([each.step for each in intents.pending()]),
    )
    launch_when_due(services)
    another_writer(library_file, "A1", "A2", "A3")
    take_in(services)
    assert at_spawn == [[plan["C"].id]]
    assert intents.pending() == []


def interrupted_launch(launch_locks, library_file, step, run_dir, *, shell_started):
    """What a window that died mid-launch leaves behind: the intent, and the shell file only
    when the spawn got as far as starting the wrapper script."""
    run_dir.mkdir()
    if shell_started:
        (run_dir / launcher.SHELL_FILE).write_text("pid=1\n", encoding="utf-8")
    intents = LaunchLocks(launch_locks).for_library(library_file).intents
    intents.record(LaunchIntent(step.id, "20261004T000000Z-crashed", run_dir, Daemon(), "now"))
    return intents


def test_a_crash_between_intent_and_spawn_is_refused_never_retried_blind(
    services, plan, library_file, launch_locks, monkeypatch, tmp_path
):
    opened_for = fake_terminal(monkeypatch)
    intents = interrupted_launch(
        launch_locks, library_file, plan["C"], tmp_path / "run", shell_started=False
    )
    launch_when_due(services)
    another_writer(library_file, "A1", "A2", "A3")
    take_in(services)

    assert opened_for == []
    assert status_of(services.document.step(plan["C"].id)) is Status.PENDING
    assert INTERRUPTED in status_line(services)
    assert [each.step for each in intents.pending()] == [plan["C"].id]
    # A person answering for the step — its briefing touched — lets the next pass launch it.
    services.document.set_text(plan["C"].id, AGENT_ID, "Carry out C, again.")
    settle(services)
    assert len(opened_for) == 1
    assert intents.pending() == []


def a_fresh_launcher(services):
    """What a restart or a reload builds: an AutoLauncher that has refused nothing yet."""
    from dplanner.modules.agent_launch.auto_launch import AutoLauncher

    agents = next(m for m in services.modules if hasattr(m, "launch_due"))
    return AutoLauncher(agents._deps, agents.launch_due)


def test_an_interrupted_launch_is_refused_again_by_a_window_built_later(
    services, plan, library_file, launch_locks, monkeypatch, tmp_path
):
    opened_for = fake_terminal(monkeypatch)
    interrupted_launch(launch_locks, library_file, plan["C"], tmp_path / "run", shell_started=False)
    launch_when_due(services)
    another_writer(library_file, "A1", "A2", "A3")
    take_in(services)
    a_fresh_launcher(services)._pass()
    assert opened_for == []
    assert status_of(services.document.step(plan["C"].id)) is Status.PENDING


def test_a_shell_slow_to_start_is_claimed_once_it_has(
    services, plan, library_file, launch_locks, monkeypatch, tmp_path
):
    opened_for = fake_terminal(monkeypatch)
    run_dir = tmp_path / "run"
    intents = interrupted_launch(
        launch_locks, library_file, plan["C"], run_dir, shell_started=False
    )
    launch_when_due(services)
    another_writer(library_file, "A1", "A2", "A3")
    take_in(services)
    assert INTERRUPTED in status_line(services)

    (run_dir / launcher.SHELL_FILE).write_text("pid=1\n", encoding="utf-8")
    a_fresh_launcher(services)._pass()
    assert opened_for == []
    assert status_of(by_title(LibraryStore(library_file).load(), "C")) is Status.IN_PROGRESS
    assert intents.pending() == []


def test_a_late_shell_keeps_its_intent_until_its_claim_is_saved(
    services, plan, library_file, launch_locks, monkeypatch, tmp_path
):
    """The pass's own claim is no person answering: with the save held back the intent
    stays, so a window that died now would claim the run rather than launch it again."""
    opened_for = fake_terminal(monkeypatch)
    run_dir = tmp_path / "run"
    intents = interrupted_launch(
        launch_locks, library_file, plan["C"], run_dir, shell_started=False
    )
    launch_when_due(services)
    another_writer(library_file, "A1", "A2", "A3")
    take_in(services)

    services.autosave.pause()
    (run_dir / launcher.SHELL_FILE).write_text("pid=1\n", encoding="utf-8")
    module(services, "agent_launch").settle_launches()
    settle(services)
    assert status_of(by_title(LibraryStore(library_file).load(), "C")) is Status.PENDING
    assert [each.step for each in intents.pending()] == [plan["C"].id]

    services.autosave.resume()
    a_fresh_launcher(services)._pass()  # The restart: it claims, saves and forgets.
    assert opened_for == []
    assert status_of(by_title(LibraryStore(library_file).load(), "C")) is Status.IN_PROGRESS
    assert intents.pending() == []


def test_a_launch_beside_an_interrupted_one_does_not_forget_it(
    services, plan, library_file, launch_locks, monkeypatch, tmp_path
):
    opened_for = fake_terminal(monkeypatch)
    project = next(each for each in services.document.projects if plan["C"] in each.steps)
    beside = agent_step(services, project, "D")
    SetEdgesCommand(beside.id, "requires", [plan["A1"].id]).redo(services.document)
    SetModuleDataCommand(beside.id, AUTO_PROGRESS_ID, write_flags([plan["A1"].id])).redo(
        services.document
    )
    services.autosave.flush_now()
    intents = interrupted_launch(
        launch_locks, library_file, plan["C"], tmp_path / "run", shell_started=False
    )
    launch_when_due(services)
    another_writer(library_file, "A1", "A2", "A3")
    take_in(services)

    assert len(opened_for) == 1
    assert status_of(services.document.step(beside.id)) is Status.IN_PROGRESS
    assert [each.step for each in intents.pending()] == [plan["C"].id]


def test_a_crash_between_spawn_and_claim_claims_the_run_and_launches_nothing(
    services, plan, library_file, launch_locks, monkeypatch, tmp_path
):
    opened_for = fake_terminal(monkeypatch)
    intents = interrupted_launch(
        launch_locks, library_file, plan["C"], tmp_path / "run", shell_started=True
    )
    launch_when_due(services)
    another_writer(library_file, "A1", "A2", "A3")
    take_in(services)

    assert opened_for == []
    on_disk = by_title(LibraryStore(library_file).load(), "C")
    assert status_of(on_disk) is Status.IN_PROGRESS
    assert intents.pending() == []


# -- the cap -----------------------------------------------------------------------------------


def test_over_the_live_cap_it_waits_and_launches_when_a_run_ends(
    services, plan, library_file, monkeypatch, tmp_path
):
    opened_for = fake_terminal(monkeypatch)
    set_global(AGENT_ID, MAX_AGENTS_KEY, 1)
    launch_when_due(services)
    run = tmp_path / "run"
    run.mkdir()
    tracker = module(services, RUN_ID)
    tracker.track(plan["A1"].id, str(run / "shell"), str(run / "exit"))
    services.autosave.flush_now()

    another_writer(library_file, "A1", "A2", "A3")
    take_in(services)
    assert opened_for == []
    assert "“C” is due and has to wait for an agent slot — 1 of 1 running" in status_line(services)

    (run / "exit").write_text("0\n", encoding="utf-8")
    tracker.check()  # The run ended: a slot, with or without a change to the plan.
    settle(services)
    assert len(opened_for) == 1


# -- one window --------------------------------------------------------------------------------


def settings_note(services):
    section = next(s for s in services.settings_sections.sections() if s.id == SETTINGS_SECTION)
    page = section.factory(None)
    try:
        label = page.findChild(QLabel, "AgentAutoLaunchNote")
        return label.text() if label is not None and not label.isHidden() else ""
    finally:
        page.deleteLater()


def test_a_window_without_the_lock_launches_nothing_and_its_page_says_so(
    services, plan, library_file, launch_locks, monkeypatch
):
    opened_for = fake_terminal(monkeypatch)
    other_window = LaunchLocks(launch_locks).for_library(library_file)
    assert other_window.take() == ""
    launch_when_due(services)
    another_writer(library_file, "A1", "A2", "A3")
    take_in(services)
    assert opened_for == []
    assert settings_note(services) == ANOTHER_WINDOW[:1].upper() + ANOTHER_WINDOW[1:] + "."

    other_window.release()  # That window closed: the next settle here takes the lock.
    module(services, "library_watch")._on_changed()
    settle(services)
    assert len(opened_for) == 1
    assert settings_note(services) == ""


def test_a_reload_keeps_the_hold(session, services, plan, library_file, launch_locks):
    launch_when_due(services)
    settle(services)
    assert settings_note(services) == ""
    session.reload()
    assert LaunchLocks(launch_locks).for_library(library_file).take() == ANOTHER_WINDOW
    assert settings_note(session.services) == ""


# -- never over a plan it has not seen ---------------------------------------------------------


def test_it_stands_down_while_the_plan_changed_underneath_and_the_watcher_wakes_it(
    services, plan, library_file, monkeypatch
):
    opened_for = fake_terminal(monkeypatch)
    launch_when_due(services)
    another_writer(library_file, "A1", "A2", "A3")
    module(services, "library_watch")._watcher._check()
    monkeypatch.setattr(services.repo, "changed_underneath", lambda: True)
    settle(services)
    assert opened_for == []
    assert "not taken in yet" in status_line(services)

    monkeypatch.undo()
    opened_for = fake_terminal(monkeypatch)
    # A refresh that took in nothing — no model signal at all — still wakes it.
    module(services, "library_watch")._on_changed()
    settle(services)
    assert len(opened_for) == 1


# -- a refusal is a sentence, and it is not repeated ------------------------------------------


def test_no_terminal_is_said_once_with_no_dialog_and_retried_when_the_step_changes(
    services, plan, library_file, monkeypatch
):
    import dplanner.modules.agent_launch.module as agent_module

    asked: list[str] = []

    def no_terminal(*_args, **_kwargs):
        asked.append("terminal")
        return None

    def no_dialog(*_args, **_kwargs):
        raise AssertionError("an unattended launch opened a dialog")

    monkeypatch.setattr(launcher, "resolve_command", no_terminal)
    monkeypatch.setattr(agent_module, "PromptFallbackDialog", no_dialog)
    launch_when_due(services)
    another_writer(library_file, "A1", "A2", "A3")
    take_in(services)
    assert asked == ["terminal"]
    assert "Could not launch the agent on" in status_line(services)
    assert "no terminal opened" in status_line(services)
    assert status_of(services.document.step(plan["C"].id)) is Status.PENDING

    services.undo.push(SetFieldCommand(plan["A1"].id, "title", "A1, renamed"))
    settle(services)
    assert asked == ["terminal"]  # Not the step that was refused: not asked again.
    services.document.set_text(plan["C"].id, AGENT_ID, "Carry out C, with the terminal fixed.")
    settle(services)
    assert asked == ["terminal", "terminal"]


# -- a review's turn ---------------------------------------------------------------------------


@pytest.fixture
def review(services, make_project):
    """W under review by R, R's findings posted, W's agent gone and R's still there."""
    project = make_project("Discovery", legacy=True)
    work = agent_step(services, project, "W", status="in-progress")
    reviewer = agent_step(services, project, "R", status="in-progress")
    library = services.document
    SetModuleDataCommand(reviewer.id, REVIEW_ID, write_review(ReviewSettings())).redo(library)
    SetEdgesCommand(reviewer.id, "requires", [work.id]).redo(library)
    SetModuleDataCommand(reviewer.id, RUN_ID, write_run("working")).redo(library)
    SetModuleDataCommand(
        reviewer.id, ROUNDS_ID, opened(reviewer, work.id, "2026-09-27T10:00:00+00:00")
    ).redo(library)
    posted = said(
        reviewer, work.id, findings="The parser drops a line.", posted="2026-09-27T10:05:00+00:00"
    )
    SetModuleDataCommand(reviewer.id, ROUNDS_ID, posted).redo(library)
    services.autosave.flush_now()
    return work, reviewer


def test_the_side_with_the_turn_is_relaunched_once_and_its_status_left_alone(
    services, review, monkeypatch
):
    opened_for = fake_terminal(monkeypatch)
    work, reviewer = review
    launch_when_due(services)
    module(services, "agent_launch").settle_launches()
    settle(services)
    assert len(opened_for) == 1
    held = last(services.document.step(reviewer.id), work.id)
    assert held is not None and held.party_turn_launched == held.posted
    assert status_of(services.document.step(work.id)) is Status.IN_PROGRESS
    # Its relaunched agent died without a word: once per round is once.
    SetModuleDataCommand(work.id, RUN_ID, {}).redo(services.document)
    settle(services)
    assert len(opened_for) == 1


def subject_in_review(services, make_project, agent):
    project = make_project("Discovery", legacy=True)
    work = agent_step(services, project, "W", status="ready-for-review")
    reviewer = agent_step(services, project, "R")
    library = services.document
    SetModuleDataCommand(reviewer.id, REVIEW_ID, write_review(ReviewSettings(agent=agent))).redo(
        library
    )
    SetEdgesCommand(reviewer.id, "requires", [work.id]).redo(library)
    services.autosave.flush_now()
    return reviewer


def test_a_review_is_launched_through_a_profile_running_its_own_agent(
    services, make_project, monkeypatch
):
    opened_for = fake_terminal(monkeypatch)
    subject_in_review(services, make_project, "codex")
    launch_when_due(services)
    module(services, "agent_launch").settle_launches()
    settle(services)
    assert len(opened_for) == 1 and opened_for[0].startswith("codex")


def test_a_review_naming_an_agent_no_profile_runs_is_refused_with_that_reason(
    services, make_project, monkeypatch
):
    opened_for = fake_terminal(monkeypatch)
    reviewer = subject_in_review(services, make_project, "gemini")
    launch_when_due(services)
    module(services, "agent_launch").settle_launches()
    settle(services)
    assert opened_for == []
    assert "no launch profile runs gemini" in status_line(services)
    assert status_of(services.document.step(reviewer.id)) is Status.PENDING


# -- plan mode ---------------------------------------------------------------------------------


def auto_launch_notice(services):
    return next((n for n in services.window.notices.notices() if n.id == NOTICE_ID), None)


def test_an_agent_launched_into_plan_mode_is_said_to_wait_for_you(
    services, plan, library_file, monkeypatch
):
    fake_terminal(monkeypatch)
    launch_when_due(services)
    another_writer(library_file, "A1", "A2", "A3")
    take_in(services)
    collector = services.document.step(plan["C"].id)
    assert asks_person(collector)  # The Claude preset starts in plan mode.
    notice = auto_launch_notice(services)
    assert notice is not None and notice.action == "Show Terminal"
    assert notice.words.endswith("“C” started in plan mode and waits for you to approve its plan")

    # Its plan approved, the agent says it is working: nobody is waited on any more.
    SetModuleDataCommand(collector.id, RUN_ID, write_run("working")).redo(services.document)
    settle(services)
    assert auto_launch_notice(services) is None
    assert not asks_person(services.document.step(collector.id))
