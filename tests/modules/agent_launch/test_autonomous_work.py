"""*Step ▸ Autonomous Work ▸ Local ▸ <profile>*: one terminal on the coordinator's briefing
over the selection, the squad word left to the coordinator and nothing claimed by the window.

No terminal opens for real: the spawn is captured, as Run Agent's tests capture it."""

import shlex
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMenu

from dplanner.domain import claims, ledger
from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step, now_stamp
from dplanner.framework.action_menu import build_menu
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.agent_launch import launcher
from dplanner.modules.agent_launch.module import AgentLaunchModule
from dplanner.modules.agent_launch.settings_page import max_agents


@pytest.fixture
def project(make_project):
    return make_project("Discovery", legacy=True)


def _step(services, project, title: str, *, agent: bool = True) -> Step:
    step = Step(title=title)
    AddNodeCommand(project.id, step).redo(services.document)
    if agent:
        services.document.set_text(step.id, "step_agent_instruction", f"Ship {title}.")
    found: Step = services.document.step(step.id)
    return found


def _select(services, *steps: Step) -> None:
    services.context.set_scope(
        SCOPE_SELECTION, tuple(ContextNode(selection_uri("step", s.id)) for s in steps)
    )


def _state(services):
    return services.actions.spec("agent.coordinate").state(services.context.current())


def _module(services, monkeypatch, **deps) -> AgentLaunchModule:
    module = next(m for m in services.modules if isinstance(m, AgentLaunchModule))
    monkeypatch.setattr(module, "_deps", replace(module._deps, tasks=None, **deps))
    return module


def _launches(monkeypatch, refusal: str = ""):
    """Every launch the real ``prepare`` wrote, and where each terminal opened."""
    made: list[launcher.LaunchFiles] = []
    opened: list[Path] = []
    real = launcher.prepare

    def capture(*args, **kwargs):
        made.append(real(*args, **kwargs))
        return made[-1]

    def spawn(_command, cwd, **_kw):
        opened.append(cwd)
        return refusal

    monkeypatch.setattr(launcher, "prepare", capture)
    monkeypatch.setattr(launcher, "spawn", spawn)
    monkeypatch.setattr(launcher, "resolve_command", lambda *a, **k: ["fake-term"])
    return made, opened


def test_a_selection_needs_one_agent_step_of_one_project_and_says_what_is_missing(
    services, project, make_project
):
    assert not _state(services).enabled  # Nothing chosen.
    milestone = _step(services, project, "Release", agent=False)
    _select(services, milestone)
    state = _state(services)
    assert not state.enabled and "no agent step" in (state.label or "")

    work = _step(services, project, "Build")
    _select(services, milestone, work)
    assert _state(services).enabled  # A lasso catching a person's step is still a squad.

    elsewhere = _step(services, make_project("Billing", legacy=True), "Invoice")
    _select(services, work, elsewhere)
    assert "one project at a time" in (_state(services).label or "")


def test_a_squad_has_at_most_nineteen_members(services, project):
    _select(services, *(_step(services, project, f"Step {n}") for n in range(20)))
    state = _state(services)
    assert not state.enabled and "at most 19 agent steps a squad" in (state.label or "")


def test_a_profile_whose_terminal_is_missing_is_greyed_with_its_reason(
    services, project, monkeypatch
):
    monkeypatch.setattr(launcher, "template_refusal", lambda _template: "no terminal here")
    _select(services, _step(services, project, "Build"))
    assert _state(services).label == "Autonomous Work — no terminal here"


def test_the_coordinator_is_briefed_on_the_selection_and_chooses_its_own_word(
    services, project, library_repo, monkeypatch
):
    module = _module(services, monkeypatch)
    build = _step(services, project, "Build")
    release = _step(services, project, "Release", agent=False)
    project_dir = module._deps.project_dir(build.id)
    assert project_dir is not None
    running = claims.claimed(
        project.id, "anvil", [build.id], now_stamp(), worker={"machine": ledger.machine_id()}
    )
    claims.write(project_dir, running)
    made, opened = _launches(monkeypatch)
    _select(services, build, release)
    services.actions.run("agent.coordinate", services.context.current())

    assert opened == [library_repo]  # The code checkout: the coordinator makes no worktree.
    (files,) = made
    prompt = files.prompt_file.read_text(encoding="utf-8")
    assert prompt.index("## Choose your squad word") < prompt.index("## Before you start")
    assert "Running now: anvil." in prompt
    assert f"at most {max_agents()} runs live at once" in prompt
    assert "Release — pending · a person's step, which waits on a person" in prompt
    assert "`<word>-two`" in prompt and "`<word>-three`" not in prompt
    script = files.script.read_text(encoding="utf-8")
    assert f"export DPLANNER_PROJECT={shlex.quote(project.id)}" in script
    assert "DPLANNER_CALLSIGN" not in script  # The coordinator names itself once it chose.
    assert claims.records(project_dir) == [running]  # The window claims nothing.
    message = services.window.statusBar().currentMessage()
    assert message.startswith("A coordinator is choosing its squad word for 1 agent step")


def test_nothing_launches_over_a_plan_that_could_not_be_saved(services, project, monkeypatch):
    _module(services, monkeypatch, flush=lambda: False)
    made, opened = _launches(monkeypatch)
    _select(services, _step(services, project, "Build"))
    services.actions.run("agent.coordinate", services.context.current())
    assert made == [] and opened == []
    assert "could not be saved" in services.window.statusBar().currentMessage()


def test_a_terminal_that_does_not_open_hands_the_briefing_over(services, project, monkeypatch):
    import dplanner.modules.agent_launch.module as agent_module

    shown: list[str] = []

    class Fallback:
        def __init__(self, text, *_args, **_kwargs):
            shown.append(text)

        def exec(self):
            return 0

    monkeypatch.setattr(agent_module, "PromptFallbackDialog", Fallback)
    _module(services, monkeypatch)
    _launches(monkeypatch, refusal="the multiplexer refused")
    _select(services, _step(services, project, "Build"))
    services.actions.run("agent.coordinate", services.context.current())
    (text,) = shown
    assert "## Choose your squad word" in text


def test_the_step_menu_offers_local_and_every_profile_under_autonomous_work(services, project):
    _select(services, _step(services, project, "Build"))
    menu = build_menu(services.actions, services.context, "Step", services.window, group="agent")
    try:
        children = {action.text(): action.menu() for action in menu.actions()}
        autonomous = children["Autonomous Work"]
        assert isinstance(autonomous, QMenu)
        autonomous.aboutToShow.emit()
        (entry,) = autonomous.actions()
        local = entry.menu()
        assert entry.text() == "&Local" and isinstance(local, QMenu)
        entries = [action.text() for action in local.actions() if not action.isSeparator()]
        assert entries[0].endswith("(default)") and local.actions()[0].isEnabled()
        assert entries[-1] == "&Manage Agent Profiles…"
    finally:
        menu.deleteLater()
