"""*Step ▸ Run Playbook*: every preset over the chosen step, its own first and marked, each
greyed with its own reason — Run Agent's questions of the step, a role no profile runs, an
agent not usable here — and an entry starts a pass through the launch module."""

from dataclasses import dataclass, field, replace

import pytest

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.step_playbook.aspect import MODULE_ID, Choice, write
from dplanner.modules.step_playbook.module import ONE_AT_A_TIME, RUN_MENU_ID
from dplanner.modules.step_playbook.presets import PRESETS, Playbook, preset


def playbook(playbook_id: str) -> Playbook:
    found = preset(playbook_id)
    assert found is not None
    return found


@dataclass
class FakeLauncher:
    refusal: str = ""
    harnesses: tuple[str, ...] = ("claude", "codex")
    started: list[tuple[str, str]] = field(default_factory=list)
    stopped: list[str] = field(default_factory=list)

    def playbook_refusal(self, _step: Step) -> str:
        return self.refusal

    def runnable(self) -> tuple[str, ...]:
        return self.harnesses

    def implementer(self) -> str:
        return "claude"

    def start_playbook(self, step: Step, playbook_id: str) -> None:
        self.started.append((step.id, playbook_id))

    def stop_playbook(self, step: Step) -> None:
        self.stopped.append(step.id)


@dataclass
class FakeReadings:
    unusable: dict[str, str] = field(default_factory=dict)
    old: bool = False
    refreshed: int = 0

    def why_not(self, harness_ids) -> str:
        return next((self.unusable[h] for h in harness_ids if h in self.unusable), "")

    def stale(self) -> bool:
        return self.old

    def refresh_stale(self) -> None:
        self.refreshed += 1
        self.old = False


@pytest.fixture
def steps(services, make_project):
    project = make_project("Discovery")
    made = [Step(title="Build it"), Step(title="Ship it")]
    for step in made:
        AddNodeCommand(project.id, step).redo(services.document)
    return made


@pytest.fixture
def fakes(services, monkeypatch):
    """The module in the built window, handed a fake launch and a fake reading."""
    module = next(m for m in services.modules if m.id == MODULE_ID)
    launcher, readings = FakeLauncher(), FakeReadings()
    monkeypatch.setattr(
        module, "_deps", replace(module._deps, launcher=launcher, readings=readings)
    )
    return launcher, readings


def select(services, *steps):
    services.context.set_scope(
        SCOPE_SELECTION, tuple(ContextNode(selection_uri("step", s.id)) for s in steps)
    )


def entries(services):
    menu = services.window.dynamic_menubar.data_menu(RUN_MENU_ID)
    return [(a.text(), a.isEnabled()) for a in menu.actions()], menu


def test_the_steps_own_playbook_comes_first_and_an_entry_starts_its_pass(services, steps, fakes):
    launcher, _readings = fakes
    step = steps[0]
    step.module_data[MODULE_ID] = write(Choice(playbook("spike")))
    select(services, step)

    listed, menu = entries(services)
    others = [p.name for p in PRESETS if p.id != "spike"]
    assert listed == [("Spike (this step's)", True), *((name, True) for name in others)]
    menu.actions()[0].trigger()
    menu.actions()[1].trigger()
    assert launcher.started == [(step.id, "spike"), (step.id, PRESETS[0].id)]
    # The palette's verb is the step's own playbook.
    services.actions.run("playbook.run", services.context.current())
    assert launcher.started[-1] == (step.id, "spike")


def test_with_no_playbook_every_preset_is_offered_and_the_verb_says_where_to_pick(
    services, steps, fakes
):
    select(services, steps[0])
    listed, _menu = entries(services)
    assert listed == [(p.name, True) for p in PRESETS]
    state = services.actions.spec("playbook.run").state(services.context.current())
    assert not state.enabled and "no playbook" in state.label


def test_each_entry_is_greyed_with_its_own_reason(services, steps, fakes):
    launcher, readings = fakes
    select(services, steps[0])

    launcher.refusal = "mark the step as an agent step first (Agent, in Step Details)"
    listed, _menu = entries(services)
    assert {(label.partition(" — ")[2], on) for label, on in listed} == {(launcher.refusal, False)}

    launcher.refusal, launcher.harnesses = "", ()
    listed, _menu = entries(services)
    assert listed[0] == ("Execute — no launch profile runs claude headless", False)

    # An agent not usable here greys only what runs it: the other-agent review's reviewer.
    launcher.harnesses = ("claude", "codex")
    readings.unusable = {"codex": "signed out — `codex login`"}
    listed = dict(entries(services)[0])
    assert listed["Execute"]
    other = playbook("plan-execute-review-other")
    assert listed[f"{other.name} — signed out — `codex login`"] is False
    assert listed[playbook("plan-execute-review-self").name]


def test_a_selection_is_one_step_too_many(services, steps, fakes):
    select(services, *steps)
    listed, _menu = entries(services)
    assert listed == [(ONE_AT_A_TIME.capitalize(), False)]
    state = services.actions.spec("playbook.run").state(services.context.current())
    assert not state.enabled and state.label.endswith(ONE_AT_A_TIME)


def test_a_stale_reading_is_refreshed_when_the_menu_opens(services, steps, fakes, monkeypatch):
    _launcher, readings = fakes
    select(services, steps[0])
    module = next(m for m in services.modules if m.id == MODULE_ID)
    monkeypatch.setattr(module, "_deps", replace(module._deps, tasks=None))  # Inline, here.
    readings.old = True
    entries(services)
    assert readings.refreshed == 1 and not readings.stale()


def test_the_window_greys_by_run_agents_own_questions(services, steps):
    """Wired to the real launch: a step that is no agent step is refused as Run Agent is."""
    select(services, steps[0])
    listed, _menu = entries(services)
    assert all(not on and "mark the step as an agent step first" in label for label, on in listed)


# -- Stop Playbook ---------------------------------------------------------------------------


@pytest.fixture
def stopping(services, fakes, monkeypatch):
    """The module told what each step's pass has left to stop, and its confirmation recorded."""
    from dplanner.modules.step_playbook import module as playbook_module

    running: dict[str, str] = {}
    monkeypatch.setattr(playbook_module, "stoppable", lambda _dir, step: running.get(step.id, ""))
    asked: list[str] = []
    answer = [True]

    def confirm(_parent, title, question, **_kw) -> bool:
        asked.append(f"{title}: {question}")
        return answer[0]

    monkeypatch.setattr(playbook_module, "confirm", confirm)
    return running, asked, answer


def test_stop_playbook_is_greyed_with_its_reason_when_nothing_runs(services, steps, stopping):
    select(services, steps[0])
    state = services.actions.spec("playbook.stop").state(services.context.current())
    assert not state.enabled and state.label.endswith("no playbook pass runs or waits on it")
    select(services, *steps)
    state = services.actions.spec("playbook.stop").state(services.context.current())
    assert not state.enabled and state.label.endswith(ONE_AT_A_TIME)


def test_stop_playbook_names_what_runs_and_stops_only_once_confirmed(
    services, steps, fakes, stopping
):
    launcher, _readings = fakes
    running, asked, answer = stopping
    step = steps[0]
    running[step.id] = "pass P: run R is running"
    select(services, step)
    assert services.actions.spec("playbook.stop").state(services.context.current()).enabled
    answer[0] = False
    services.actions.run("playbook.stop", services.context.current())
    assert launcher.stopped == [] and "run R is running" in asked[0]
    answer[0] = True
    services.actions.run("playbook.stop", services.context.current())
    assert launcher.stopped == [step.id]
