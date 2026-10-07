"""A launch nobody watches: Run Agent with every question a person answers taken out.

Its intent is on disk before the shell is spawned and gone once the claim is, the claim is
made whatever *On launch* says, and a refusal is a sentence — never a dialog.
"""

from dataclasses import replace

import pytest

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.framework.user_config import set_global
from dplanner.modules.agent_launch import launcher
from dplanner.modules.agent_launch.intents import LaunchIntents
from dplanner.modules.agent_launch.settings_page import START_IN_PROGRESS_KEY
from dplanner.planning.agent import MODULE_ID as AGENT_ID
from dplanner.planning.status import Status
from dplanner.planning.status import stored as status_of


@pytest.fixture
def launch(services, tmp_path):
    """The agent module, recording its intents under this test's own directory."""
    module = next(m for m in services.modules if m.id == "agent_launch")
    module._deps = replace(module._deps, intents=LaunchIntents(tmp_path / "intents"))
    return module


@pytest.fixture
def step(services, make_project):
    project = make_project("Discovery", legacy=True)
    step = Step(title="Build the parser")
    AddNodeCommand(project.id, step).redo(services.document)
    services.document.set_text(step.id, AGENT_ID, "Carry it out.")
    return step


def test_the_intent_is_on_disk_at_the_spawn_and_gone_once_the_claim_is(
    services, launch, step, monkeypatch
):
    set_global(AGENT_ID, START_IN_PROGRESS_KEY, False)  # The claim is made all the same.
    intents = launch._deps.intents
    at_spawn: list[list[str]] = []
    monkeypatch.setattr(launcher, "resolve_command", lambda *a, **k: ["fake-term"])
    monkeypatch.setattr(
        launcher, "spawn", lambda *_a, **_k: at_spawn.append([i.step for i in intents.pending()])
    )
    assert launch.launch_unattended(step.id) == ""
    assert at_spawn == [[step.id]]
    assert intents.pending() == []
    assert status_of(services.document.step(step.id)) is Status.IN_PROGRESS


def test_no_terminal_is_a_sentence_and_leaves_no_intent_and_no_claim(
    services, launch, step, monkeypatch
):
    import dplanner.modules.agent_launch.module as agent_module

    def no_dialog(*_args, **_kwargs):
        raise AssertionError("an unattended launch opened a dialog")

    monkeypatch.setattr(launcher, "resolve_command", lambda *a, **k: None)
    monkeypatch.setattr(agent_module, "PromptFallbackDialog", no_dialog)
    said = launch.launch_unattended(step.id)
    assert said.startswith("no terminal opened")
    assert launch._deps.intents.pending() == []
    assert status_of(services.document.step(step.id)) is Status.PENDING


def test_a_named_harness_runs_through_the_first_profile_running_it(launch, step, monkeypatch):
    """A playbook's role names a harness, and the launch takes the first profile whose agent
    command runs it — not the default, which may be the very agent whose work is judged."""
    from dplanner.modules.agent_launch.profiles import Profile, write_profiles

    write_profiles(
        [
            Profile("Mine", "", "first {script}"),
            Profile("Codex", "codex {prompt}", "second {script}"),
        ]
    )
    opened: list[str] = []

    def resolve(template, *_args, **_kwargs):
        opened.append(template)
        return ["fake-term"]

    monkeypatch.setattr(launcher, "resolve_command", resolve)
    monkeypatch.setattr(launcher, "spawn", lambda *_a, **_k: None)
    assert launch.launch_unattended(step.id, harness="codex") == ""
    assert opened == ["second {script}"]


def test_a_harness_no_profile_runs_is_refused_never_swapped_for_the_default(launch, step):
    from dplanner.modules.agent_launch.profiles import Profile, write_profiles

    write_profiles([Profile("Mine", "", "first {script}")])
    said = launch.launch_unattended(step.id, harness="codex")
    assert said.startswith("no launch profile runs Codex")
    assert launch._deps.intents.pending() == []
