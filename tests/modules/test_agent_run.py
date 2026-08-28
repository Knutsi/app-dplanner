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


def test_segments_reproduce_the_text_exactly_and_name_their_origins():
    """The coloured Prompt view renders segments — the invariant is that their
    concatenation IS the text, so the display can never differ from what is sent."""
    assembled = assemble(
        step_title="Deploy",
        project_title="Discovery",
        instruction="Ship it.",
        parts=[PromptPart(heading="Set up CI", body="Keys in vault.")],
        epilogue="Report back.",
        preamble="Check first.",
        project_instruction="House rules.",
        sections=[PromptPart(heading="Description", body="What it is.")],
    )
    assert "".join(segment.text for segment in assembled.segments) == assembled.text
    assert [segment.origin for segment in assembled.segments] == [
        "header", "protocol", "project", "context", "instruction", "inherited", "protocol",
    ]


def test_an_empty_context_leaves_no_empty_section():
    assembled = assemble("Deploy", "Discovery", "Ship it.", [], "")
    assert "Context handed forward" not in assembled.text
    assert "When you are done" not in assembled.text
    assert "Before you start" not in assembled.text


def test_the_preamble_opens_the_briefing_before_the_instructions():
    assembled = assemble("Deploy", "Discovery", "Ship it.", [], "", preamble="Check first.")
    assert assembled.text.index("Before you start") < assembled.text.index("Instructions")
    assert "Check first." in assembled.text


def test_the_project_instruction_opens_its_own_section_ahead_of_the_steps():
    assembled = assemble(
        "Deploy",
        "Discovery",
        "Ship it.",
        [],
        "",
        project_instruction="House rules.",
        project_files=("p/a.png",),
        instruction_files=("s/b.png",),
    )
    text = assembled.text
    assert "## Project instructions" in text and "House rules." in text
    assert text.index("Project instructions") < text.index("## Instructions")
    assert "- p/a.png" in text and "- s/b.png" in text


def test_no_project_instruction_leaves_no_section():
    assert "Project instructions" not in assemble("D", "P", "x", [], "").text


def test_referenced_files_keep_reading_order():
    assembled = assemble(
        "D",
        "P",
        "x",
        [PromptPart(heading="H", body="", files=("h/c.png",))],
        "",
        project_files=("p/a.png",),
        instruction_files=("s/b.png",),
    )
    assert assembled.files == ("p/a.png", "s/b.png", "h/c.png")


# -- staging -----------------------------------------------------------------------------------


def test_stage_assets_copies_beside_the_prompt(tmp_path):
    source = "projects/p/modules/x/assets/ab12.png"
    staged = launcher.stage_assets(tmp_path, [source], {source: b"png-bytes"}.get)
    target = Path(staged[source])
    assert target.parent == tmp_path / "assets"
    assert target.is_absolute()
    assert target.read_bytes() == b"png-bytes"


def test_an_unreadable_asset_stays_itself_in_the_prompt(tmp_path):
    staged = launcher.stage_assets(tmp_path, ["gone.png"], lambda _path: None)
    assert staged == {"gone.png": "gone.png"}
    assert not (tmp_path / "assets").exists()


def test_prepare_writes_into_a_given_run_directory(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    files = prepare("p", tmp_path, platform="linux", directory=run_dir)
    assert files.directory == run_dir
    assert files.prompt_file == run_dir / "prompt.md"


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


def test_the_default_is_claude_code_in_plan_mode_interactively(tmp_path):
    script = prepare("p", tmp_path, platform="linux").script.read_text()
    assert "exec claude --permission-mode plan" in script
    assert "prompt.md" in script


def test_a_worktree_slug_isolates_the_run(tmp_path):
    script = prepare("p", tmp_path, worktree="build-it-abc123", platform="linux").script.read_text()
    assert f'git worktree add "{tmp_path}/.dplanner/worktrees/build-it-abc123"' in script
    assert '-b "agent/build-it-abc123"' in script
    assert "info/exclude" in script  # The worktree dir never pollutes git status.
    assert f'cd "{tmp_path}/.dplanner/worktrees/build-it-abc123"' in script


def test_no_worktree_slug_means_no_git_lines(tmp_path):
    assert "git worktree add" not in prepare("p", tmp_path, platform="linux").script.read_text()


def test_a_command_without_the_placeholder_still_gets_the_prompt(tmp_path):
    script = prepare("p", tmp_path, agent_command="my-agent", platform="linux").script.read_text()
    assert "exec my-agent \"$(cat" in script


def test_the_presets_cover_the_known_agents():
    from dplanner.modules.step_agent_instruction.launcher import PRESETS

    assert [preset.id for preset in PRESETS] == ["claude", "codex", "opencode"]
    assert all("{prompt}" in preset.command for preset in PRESETS)


def test_picking_a_preset_prefills_the_command(app):
    from PySide6.QtWidgets import QComboBox, QLineEdit

    from dplanner.modules.step_agent_instruction.launcher import PRESETS
    from dplanner.modules.step_agent_instruction.settings_page import agent_command, build_page

    page = build_page(None)
    combo = page.findChild(QComboBox, "AgentPresetCombo")
    edit = page.findChild(QLineEdit, "AgentCommandEdit")
    assert combo is not None and edit is not None
    codex = next(i for i in range(combo.count()) if combo.itemText(i) == "Codex")
    combo.setCurrentIndex(codex)
    combo.activated.emit(codex)
    assert edit.text() == PRESETS[1].command
    assert agent_command() == PRESETS[1].command


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


def test_without_an_instruction_the_action_is_greyed_with_the_reason(services, step):
    """Present, not hidden: a greyed entry that says what to do beats a missing one."""
    select(services, step)
    state = services.actions.spec("agent.run").state(services.context.current())
    assert state.visible and not state.enabled
    assert state.label is not None and "instruction" in state.label


def test_without_a_checkout_the_reason_names_both_places(services, step):
    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    select(services, step)
    state = services.actions.spec("agent.run").state(services.context.current())
    assert state.visible and not state.enabled
    assert state.label is not None and "project or the product" in state.label


def test_the_project_checkout_wins_over_the_products(services, step, tmp_path, monkeypatch):
    from dplanner.modules.project_repo.repo import MODULE_ID as REPO_ID
    from dplanner.modules.project_repo.repo import write_association

    product_dir = tmp_path / "mono"
    project_dir = tmp_path / "satellite"
    product_dir.mkdir()
    project_dir.mkdir()
    services.document.set_field(services.document.id, "checkout", str(product_dir))
    project = services.document.project_of(step.id)
    services.document.set_module_data(
        project.id, REPO_ID, write_association("", str(project_dir))
    )
    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    select(services, step)

    calls: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(launcher, "spawn", lambda cmd, cwd: calls.append((cmd, cwd)))
    monkeypatch.setattr(launcher, "resolve_command", lambda *a, **k: ["fake-term"])
    services.actions.run("agent.run", services.context.current())
    ((_command, cwd),) = calls
    assert cwd == project_dir

    # Clearing the project's association falls back to the product's.
    services.document.set_module_data(project.id, REPO_ID, {})
    services.actions.run("agent.run", services.context.current())
    assert calls[-1][1] == product_dir


def _agent_section(services):
    spec = next(
        s
        for s in services.inspector_sections.sections()
        if s.id == "step_agent_instruction.tab"
    )
    return spec.factory()


def test_the_agent_tab_has_the_trigger_following_the_action_state(services, step, tmp_path):
    select(services, step)
    section = _agent_section(services)
    section.show_target(step.id)
    assert not section.run_button.isEnabled()
    assert "instruction" in section.run_button.toolTip()

    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    section.show_target(step.id)  # A reselect re-evaluates, as the panel does.
    assert "checkout" in section.run_button.toolTip()

    services.document.set_field(services.document.id, "checkout", str(tmp_path))
    section.show_target(step.id)
    assert section.run_button.isEnabled()
    section.dispose()


def test_typing_the_first_instruction_arms_the_button(services, step, tmp_path):
    services.document.set_field(services.document.id, "checkout", str(tmp_path))
    select(services, step)
    section = _agent_section(services)
    section.show_target(step.id)
    assert not section.run_button.isEnabled()
    section.edit.setPlainText("Ship it.")  # Through the binding: the model now has it.
    assert section.run_button.isEnabled()
    section.dispose()


def test_the_order_view_selection_reaches_run_agent(services, step, tmp_path, monkeypatch):
    """No coupling needed: the order tab publishes the step, the action reads the context."""
    services.document.set_field(services.document.id, "checkout", str(tmp_path))
    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    project = services.document.project_of(step.id)
    tab = services.tabs.open("order", project.id)
    tab.table.selectRow(0)
    state = services.actions.spec("agent.run").state(services.context.current())
    assert state.enabled

    calls: list[list[str]] = []
    monkeypatch.setattr(launcher, "spawn", lambda cmd, cwd: calls.append(cmd))
    monkeypatch.setattr(launcher, "resolve_command", lambda *a, **k: ["fake-term"])
    services.actions.run("agent.run", services.context.current())
    assert calls == [["fake-term"]]


def test_the_button_runs_the_same_action(services, step, tmp_path, monkeypatch):
    services.document.set_field(services.document.id, "checkout", str(tmp_path))
    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    select(services, step)
    calls: list[list[str]] = []
    monkeypatch.setattr(launcher, "spawn", lambda cmd, cwd: calls.append(cmd))
    monkeypatch.setattr(launcher, "resolve_command", lambda *a, **k: ["fake-term"])
    section = _agent_section(services)
    section.show_target(step.id)
    section.run_button.click()
    assert calls == [["fake-term"]]
    section.dispose()


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


def test_a_run_stages_attached_images_beside_the_prompt(services, step, tmp_path, monkeypatch):
    """The agent runs in the checkout, so the prompt must reference copies it can reach."""
    from dplanner.domain.assets import attach

    services.document.set_field(services.document.id, "checkout", str(tmp_path))
    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    project = services.document.project_of(step.id)
    services.document.set_text(project.id, "step_agent_instruction", "House rules.")
    attach(services.repo.files(step.id, "step_agent_instruction"), b"step-bytes", "mock.png")
    attach(services.repo.files(project.id, "step_agent_instruction"), b"proj-bytes", "logo.png")
    select(services, step)

    monkeypatch.setattr(launcher, "spawn", lambda cmd, cwd: None)
    monkeypatch.setattr(launcher, "resolve_command", lambda *a, **k: ["fake-term"])
    captured = {}
    real_prepare = launcher.prepare

    def capture(*args, **kwargs):
        captured["files"] = real_prepare(*args, **kwargs)
        return captured["files"]

    monkeypatch.setattr(launcher, "prepare", capture)
    services.actions.run("agent.run", services.context.current())

    files = captured["files"]
    prompt = files.prompt_file.read_text()
    assert "House rules." in prompt
    assert prompt.index("House rules.") < prompt.index("Ship it.")
    staged = sorted((files.directory / "assets").iterdir())
    assert [path.read_bytes() for path in staged] in (
        [b"proj-bytes", b"step-bytes"],
        [b"step-bytes", b"proj-bytes"],
    )
    for path in staged:
        assert str(path) in prompt  # Absolute, inside the run dir — reachable from anywhere.


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
    # The preflight comes first: no skill, no work.
    assert "dplanner skill status" in shown["prompt"]
    assert shown["prompt"].index("skill status") < shown["prompt"].index("Ship it.")
    assert shown["root"] == str(root)
