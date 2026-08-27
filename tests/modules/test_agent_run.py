"""Run Agent: the assembled briefing, the cross-platform launch, and the fallback."""

import json
from io import StringIO
from pathlib import Path

import pytest

from dplanner.cli.command import CliRegistry
from dplanner.cli.main import run
from dplanner.core.storage.local import LocalStorage
from dplanner.domain.seed import create_product
from dplanner.modules import default_cli_commands, default_module_formats
from dplanner.modules.step_agent_instruction import launcher
from dplanner.modules.step_agent_instruction.launcher import (
    LaunchFiles,
    prepare,
    resolve_command,
)
from dplanner.modules.step_agent_instruction.prompt import PromptPart, assemble

# -- assembly ----------------------------------------------------------------------------------


def test_the_prompt_carries_instruction_context_and_epilogue():
    assembled = assemble(
        step_title="Deploy",
        project_title="Discovery",
        instruction="Ship it.",
        parts=[PromptPart(heading="Set up CI", body="Keys in vault.", files=("a/b.png",))],
        epilogue="Report back.",
    )
    text = assembled.text
    assert "# Step: Deploy" in text
    assert "## Instructions" in text and "Ship it." in text
    assert '### From "Set up CI"' in text and "Keys in vault." in text
    assert "- a/b.png" in text
    assert "## When you are done" in text and "Report back." in text
    assert assembled.files == ("a/b.png",)


def test_an_empty_context_leaves_no_empty_section():
    assembled = assemble("Deploy", "Discovery", "Ship it.", [], "")
    assert "Context handed forward" not in assembled.text
    assert "When you are done" not in assembled.text


# -- prepare -----------------------------------------------------------------------------------


def test_prepare_writes_prompt_and_executable_script(tmp_path):
    files = prepare("the prompt", tmp_path, platform="linux")
    assert files.prompt_file.read_text() == "the prompt"
    assert files.script.name == "run.sh"
    assert files.script.stat().st_mode & 0o100
    assert str(tmp_path) in files.script.read_text()
    assert "dplanner-agent-" in str(files.directory)


def test_prepare_writes_a_cmd_wrapper_on_windows(tmp_path):
    files = prepare("the prompt", tmp_path, platform="win32")
    assert files.script.name == "run.cmd"
    assert str(tmp_path) in files.script.read_text()


# -- resolution --------------------------------------------------------------------------------


def fake_files(tmp_path) -> LaunchFiles:
    return LaunchFiles(
        directory=tmp_path,
        prompt_file=tmp_path / "prompt.md",
        script=tmp_path / "run.sh",
    )


def test_a_settings_template_wins_outright(tmp_path):
    command = resolve_command(
        "myterm --run {script} --cd {workdir}",
        fake_files(tmp_path),
        Path("/work"),
        platform="linux",
        which=lambda _name: None,
        env={},
    )
    assert command == ["myterm", "--run", str(tmp_path / "run.sh"), "--cd", "/work"]


def test_inside_tmux_a_new_window_is_the_default(tmp_path):
    command = resolve_command(
        "", fake_files(tmp_path), Path("/work"), platform="linux",
        which=lambda _name: None, env={"TMUX": "/tmp/tmux-1000/default,42,0"},
    )
    assert command is not None and command[:2] == ["tmux", "new-window"]


def test_the_first_terminal_found_wins(tmp_path):
    command = resolve_command(
        "", fake_files(tmp_path), Path("/work"), platform="linux",
        which=lambda name: "/usr/bin/kitty" if name == "kitty" else None, env={},
    )
    assert command is not None and command[0] == "kitty"


def test_macos_opens_terminal_app(tmp_path):
    command = resolve_command(
        "", fake_files(tmp_path), Path("/work"), platform="darwin",
        which=lambda _name: None, env={},
    )
    assert command is not None and command[:3] == ["open", "-a", "Terminal"]


def test_windows_prefers_windows_terminal(tmp_path):
    command = resolve_command(
        "", fake_files(tmp_path), Path("C:/work"), platform="win32",
        which=lambda name: "wt" if name == "wt" else None, env={},
    )
    assert command is not None and command[0] == "wt"


def test_nothing_found_answers_none_not_an_error(tmp_path):
    command = resolve_command(
        "", fake_files(tmp_path), Path("/work"), platform="linux",
        which=lambda _name: None, env={},
    )
    assert command is None


# -- the action --------------------------------------------------------------------------------


@pytest.fixture
def step(services):
    from dplanner.domain.commands import AddNodeCommand
    from dplanner.domain.model import Project, Step

    product = services.document
    project = Project(title="Discovery")
    AddNodeCommand(product.id, project).redo(product)
    step = Step(title="Deploy")
    AddNodeCommand(project.id, step).redo(product)
    return step


def select(services, step):
    from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri

    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("step", step.id)),)
    )


def test_without_an_instruction_the_action_is_hidden(services, step):
    select(services, step)
    state = services.actions.spec("agent.run").state(services.context.current())
    assert not state.visible


def test_without_a_checkout_the_reason_is_in_the_label(services, step):
    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    select(services, step)
    state = services.actions.spec("agent.run").state(services.context.current())
    assert not state.enabled
    assert state.label is not None and "checkout" in state.label


def test_running_spawns_a_terminal_in_the_checkout(services, step, tmp_path, monkeypatch):
    services.document.set_field(services.document.id, "checkout", str(tmp_path))
    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    select(services, step)

    calls: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(launcher, "spawn", lambda cmd, cwd: calls.append((cmd, cwd)))
    monkeypatch.setattr(
        launcher, "resolve_command", lambda *a, **k: ["fake-term", "-e", "run.sh"]
    )
    services.actions.run("agent.run", services.context.current())
    ((command, cwd),) = calls
    assert command[0] == "fake-term"
    assert cwd == tmp_path


# -- the CLI -----------------------------------------------------------------------------------


def test_agent_prompt_carries_handoffs_and_the_epilogue(tmp_path):
    root = tmp_path / "widget"
    create_product(LocalStorage(root))
    registry = CliRegistry()
    registry.register_all(default_cli_commands())

    def cli(*argv, stdin=""):
        import sys

        out, err = StringIO(), StringIO()
        if stdin:
            real = sys.stdin
            sys.stdin = StringIO(stdin)
        try:
            code = run(
                registry, default_module_formats(), ["--workspace", str(root), *argv], out, err
            )
        finally:
            if stdin:
                sys.stdin = real
        assert code == 0, err.getvalue() + out.getvalue()
        return out.getvalue()

    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Set up CI")
    cli("step", "add", "Discovery", "Deploy", "--after", "Set up CI")
    cli("agent", "set", "Deploy", "--file", "-", stdin="Ship it.")
    cli("handoff", "set", "Set up CI", "--file", "-", stdin="Keys in vault.")

    shown = json.loads(cli("agent", "prompt", "Deploy", "--json"))
    assert "Ship it." in shown["prompt"]
    assert 'From "Set up CI"' in shown["prompt"]
    assert "Keys in vault." in shown["prompt"]
    assert "dplanner status set 'Deploy' done" in shown["prompt"]
    assert shown["root"] == str(root)
