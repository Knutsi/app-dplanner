"""Run Agent: the assembled briefing, the cross-platform launch, and the fallback."""

import json
from pathlib import Path

import pytest

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
    source = "p/modules/x/assets/ab12.png"
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
    assert "\nclaude --permission-mode plan" in script
    assert "prompt.md" in script


def test_the_script_reports_the_shell_and_the_exit(tmp_path):
    """The wrapper is the one process that knows when the agent ends, so it says so
    beside the prompt: the shell's facts first, the exit status last — and a failure
    holds the window open long enough to be read."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    files = prepare(
        "p", tmp_path, platform="linux", directory=run_dir, step_title="Deploy: the 'beta' (v2)"
    )
    script = files.script.read_text()
    assert files.title == "dplanner: Deploy: the beta (v2)"
    assert files.shell_file == run_dir / "shell" and files.exit_file == run_dir / "exit"
    assert "printf '\\033]0;%s\\007' 'dplanner: Deploy: the beta (v2)'" in script
    assert (
        f'"$(tty)" "$$" "$TMUX_PANE" "$TERM_PROGRAM" \'dplanner: Deploy: the beta (v2)\''
        f" > {run_dir}/shell"
    ) in script
    assert f"trap 'echo closed > {run_dir}/exit; exit 129' HUP" in script
    assert f'echo "$code" > {run_dir}/exit' in script
    assert "read -r _" in script
    assert "exec " not in script  # A replaced shell could not report the exit.


def test_the_windows_script_reports_the_same_two_files(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    files = prepare("p", tmp_path, platform="win32", directory=run_dir, step_title="Deploy")
    script = files.script.read_text()
    assert "title dplanner: Deploy" in script
    assert f"Set-Content -Path '{run_dir / 'shell'}'" in script and "'pid=' + $PID" in script
    assert "exit $LASTEXITCODE" in script
    assert f'>"{run_dir / "exit"}" echo %code%' in script
    assert "pause" in script


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
    assert "\nmy-agent \"$(cat" in script


def test_the_presets_cover_the_known_agents():
    from dplanner.modules.step_agent_instruction.launcher import PRESETS

    assert [preset.id for preset in PRESETS] == ["claude", "codex", "opencode"]
    assert all("{prompt}" in preset.command for preset in PRESETS)


def test_picking_a_terminal_prefills_its_command(app):
    """The same dropdown-over-field as the agent: the rows are this platform's known
    terminals, marked when not installed, and Automatic is the empty template."""
    from PySide6.QtWidgets import QComboBox, QLineEdit

    from dplanner.modules.step_agent_instruction.settings_page import build_page, launch_command

    page = build_page(None, platform="darwin")
    combo = page.findChild(QComboBox, "AgentTerminalCombo")
    edit = page.findChild(QLineEdit, "AgentLaunchCommandEdit")
    assert combo is not None and edit is not None
    labels = [combo.itemText(i) for i in range(combo.count())]
    assert labels[1] == "Terminal" and labels[-1] == "Automatic"
    assert any(label.startswith("iTerm") for label in labels)
    assert combo.currentText() == "Automatic"  # Untouched means the platform's default.
    terminal = labels.index("Terminal")
    combo.setCurrentIndex(terminal)
    combo.activated.emit(terminal)
    assert edit.text() == "open -a Terminal {script}"
    assert launch_command() == "open -a Terminal {script}"


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
        shell_file=tmp_path / "shell",
        exit_file=tmp_path / "exit",
        title="dplanner: Deploy",
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
    """The platform's own default terminal, whatever else is installed: Automatic
    behaves the way the machine does, and the dropdown is where Ghostty or iTerm is."""
    command = resolve_command(
        "", fake_files(tmp_path), Path("/work"), platform="darwin",
        which=lambda _name: None, env={}, app_exists=lambda _name: True,
    )
    assert command is not None and command[:3] == ["open", "-a", "Terminal"]


def test_the_terminal_table_is_one_per_platform_and_probes_installs():
    from dplanner.modules.step_agent_instruction.launcher import is_installed, terminals_for

    assert [p.label for p in terminals_for("darwin")] == [
        "tmux (new window)", "Terminal", "iTerm", "Ghostty",
    ]
    assert [p.id for p in terminals_for("win32")] == ["wt", "cmd", "ghostty-win"]
    assert terminals_for("linux")[0].id == "tmux" and "ghostty" in [
        p.id for p in terminals_for("linux")
    ]
    ghostty_mac = next(p for p in terminals_for("darwin") if p.id == "ghostty-mac")
    none = lambda _n: None  # noqa: E731 - a stand-in for shutil.which
    assert is_installed(ghostty_mac, which=none, env={}, app_exists=lambda n: n == "Ghostty")
    assert not is_installed(ghostty_mac, which=none, env={}, app_exists=lambda _n: False)
    tmux = terminals_for("linux")[0]
    assert is_installed(tmux, which=lambda _n: None, env={"TMUX": "x"})
    assert not is_installed(tmux, which=lambda _n: "/usr/bin/tmux", env={})


def test_a_template_never_puts_a_windows_path_through_shlex(tmp_path):
    """Placeholders are substituted per token after the split, so a backslash in the
    script's path survives — shlex would have eaten it."""
    files = LaunchFiles(
        directory=tmp_path,
        prompt_file=tmp_path / "prompt.md",
        script=Path(r"C:\Users\me\run.cmd"),
        shell_file=tmp_path / "shell",
        exit_file=tmp_path / "exit",
        title="dplanner: Deploy",
    )
    template = 'wt -d {workdir} cmd /k {script} --title "{title}"'
    command = resolve_command(template, files, Path(r"C:\work"), platform="win32")
    assert command == [
        "wt", "-d", r"C:\work", "cmd", "/k", r"C:\Users\me\run.cmd", "--title", "dplanner: Deploy",
    ]


def test_an_unusable_template_answers_none(tmp_path):
    assert resolve_command("myterm {nonsense}", fake_files(tmp_path), Path("/w"), "linux") is None


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
def step(services, make_project):
    from dplanner.domain.commands import AddNodeCommand
    from dplanner.domain.model import Step

    project = make_project("Discovery")
    step = Step(title="Deploy")
    AddNodeCommand(project.id, step).redo(services.document)
    return step


def select(services, step):
    from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri

    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("step", step.id)),)
    )


def test_without_the_aspect_the_action_is_greyed_with_the_reason(services, step):
    """Present, not hidden: a greyed entry that says what to do beats a missing one."""
    select(services, step)
    state = services.actions.spec("agent.run").state(services.context.current())
    assert state.visible and not state.enabled
    assert state.label is not None and "agent step" in state.label


def test_an_agent_step_with_nothing_to_brief_it_is_greyed_with_the_reason(services, step):
    """The aspect alone is not a briefing: no description, no instruction, no standing
    instruction means nothing to launch with, and the label says which to write."""
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.step_agent_instruction.aspect import MODULE_ID, write_state

    services.undo.push(SetModuleDataCommand(step.id, MODULE_ID, write_state(True)))
    select(services, step)
    state = services.actions.spec("agent.run").state(services.context.current())
    assert state.visible and not state.enabled
    assert state.label is not None and "describe" in state.label


def test_a_described_agent_step_is_runnable_without_a_separate_instruction(services, step):
    """The description is the instructions: mark plus prose is a complete briefing."""
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.step_agent_instruction.aspect import MODULE_ID, write_state

    services.undo.push(SetModuleDataCommand(step.id, MODULE_ID, write_state(True)))
    services.document.set_text(step.id, "step_description", "What this step is.")
    select(services, step)
    state = services.actions.spec("agent.run").state(services.context.current())
    assert state.enabled


def test_without_a_repository_the_reason_says_so(services, step, library_repo):
    """A project whose folder lost its repository: greyed, and the label explains."""
    import shutil

    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    shutil.rmtree(library_repo / ".git")
    select(services, step)
    state = services.actions.spec("agent.run").state(services.context.current())
    assert state.visible and not state.enabled
    assert state.label is not None and "git repository" in state.label


def test_each_projects_own_repository_root_is_the_workdir(
    services, make_project, step, tmp_path, monkeypatch
):
    """Two projects, two repositories: a step's agent runs in its own project's repo root."""
    from dplanner.core.storage.locations import init_repo
    from dplanner.domain.commands import AddNodeCommand
    from dplanner.domain.model import Step
    from dplanner.domain.seed import seed_project

    second_repo = init_repo(tmp_path / "second")
    directory = seed_project(second_repo / "satellite", "Satellite")
    satellite = services.repo.attach(directory)
    services.document.add_child(services.document.id, satellite)
    other = Step(title="Wire the antenna")
    AddNodeCommand(satellite.id, other).redo(services.document)
    services.document.set_text(other.id, "step_agent_instruction", "Ship it.")
    select(services, other)

    calls: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(launcher, "spawn", lambda cmd, cwd: calls.append((cmd, cwd)))
    monkeypatch.setattr(launcher, "resolve_command", lambda *a, **k: ["fake-term"])
    services.actions.run("agent.run", services.context.current())
    ((_command, cwd),) = calls
    assert cwd == second_repo


def _agent_section(services):
    spec = next(
        s
        for s in services.inspector_sections.sections()
        if s.id == "step_agent_instruction.tab"
    )
    return spec.factory()


def test_the_agent_tab_has_the_trigger_following_the_action_state(services, step, library_repo):
    import shutil

    select(services, step)
    section = _agent_section(services)
    section.show_target(step.id)
    assert not section.run_button.isEnabled()
    assert "agent step" in section.run_button.toolTip()

    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    section.show_target(step.id)  # A reselect re-evaluates, as the panel does.
    assert section.run_button.isEnabled()

    shutil.rmtree(library_repo / ".git")  # The project's folder loses its repository.
    section.show_target(step.id)
    assert not section.run_button.isEnabled()
    assert "git repository" in section.run_button.toolTip()
    section.dispose()


def test_typing_the_first_instruction_arms_the_button(services, step):
    select(services, step)
    section = _agent_section(services)
    section.show_target(step.id)
    assert not section.run_button.isEnabled()
    section.edit.setPlainText("Ship it.")  # Through the binding: the model now has it.
    assert section.run_button.isEnabled()
    section.dispose()


def test_the_order_view_selection_reaches_run_agent(services, step, monkeypatch):
    """No coupling needed: the order tab publishes the step, the action reads the context."""
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


def test_the_button_runs_the_same_action(services, step, monkeypatch):
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


def test_running_spawns_a_terminal_in_the_projects_repo_root(
    services, step, library_repo, monkeypatch
):
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
    assert cwd == library_repo


def test_a_successful_launch_stamps_the_run_state(services, step, monkeypatch):
    """The stamp records an external fact, so it never lands on the undo stack."""
    from dplanner.modules.step_agent_run.aspect import launched, read

    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    select(services, step)
    monkeypatch.setattr(launcher, "spawn", lambda cmd, cwd: None)
    monkeypatch.setattr(launcher, "resolve_command", lambda *a, **k: ["fake-term"])
    services.actions.run("agent.run", services.context.current())
    assert read(step) == "launched"
    assert launched(step)
    assert not services.undo.can_undo()


def test_the_prompt_fallback_does_not_stamp(services, step, monkeypatch):
    """No shell was started, so nothing claims one was."""
    import dplanner.modules.step_agent_instruction.module as agent_module
    from dplanner.modules.step_agent_run.aspect import read

    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    select(services, step)
    monkeypatch.setattr(launcher, "resolve_command", lambda *a, **k: None)

    class SilentDialog:
        def __init__(self, *args):
            pass

        def exec(self):
            return 0

    monkeypatch.setattr(agent_module, "PromptFallbackDialog", SilentDialog)
    services.actions.run("agent.run", services.context.current())
    assert read(step) == ""


def test_a_run_stages_attached_images_beside_the_prompt(services, step, monkeypatch):
    """The agent runs in the repository, so the prompt must reference copies it can reach."""
    from dplanner.domain.assets import attach

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


# -- the Type toggles --------------------------------------------------------------------------


def test_the_agent_toggle_marks_and_unmarks_the_step(services, step):
    from dplanner.modules.step_agent_instruction.aspect import enabled

    select(services, step)
    context = services.context.current()
    spec = services.actions.spec("agent.toggle")
    assert spec.menu == "Step" and spec.submenu == "Type"
    assert spec.state(context).checked is False

    services.actions.run("agent.toggle", context)
    assert enabled(step) and spec.state(context).checked is True
    services.actions.run("agent.toggle", context)  # No text: no confirm needed.
    assert not enabled(step)
    services.undo.undo()
    assert enabled(step)


def test_toggling_agent_off_confirms_and_drops_the_text_as_one_undo_step(
    services, step, monkeypatch
):
    import dplanner.modules.step_agent_instruction.module as agent_module
    from dplanner.modules.step_agent_instruction.aspect import enabled

    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    asked = []

    def yes(*args: object) -> bool:
        asked.append(args)
        return True

    monkeypatch.setattr(agent_module, "confirm", yes)
    select(services, step)
    services.actions.run("agent.toggle", services.context.current())
    assert asked and not enabled(step)
    assert step.module_text.get("step_agent_instruction", "") == ""
    services.undo.undo()
    assert enabled(step)
    assert step.module_text["step_agent_instruction"] == "Ship it."


def test_the_ticket_toggle_adds_the_empty_aspect_and_clears_it(services, step, monkeypatch):
    import dplanner.modules.step_ticket.module as ticket_module
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.step_ticket.aspect import MODULE_ID, Ticket, enabled, write

    select(services, step)
    context = services.context.current()
    spec = services.actions.spec("ticket.toggle")
    assert spec.state(context).checked is False

    services.actions.run("ticket.toggle", context)
    assert enabled(step) and spec.state(context).checked is True

    # Off with no reference filled in: no confirm, entry gone.
    asked = []

    def yes(*args: object) -> bool:
        asked.append(args)
        return True

    monkeypatch.setattr(ticket_module, "confirm", yes)
    services.actions.run("ticket.toggle", context)
    assert not asked and not enabled(step)

    # Off with a reference: asks first, and undo restores it.
    services.undo.push(SetModuleDataCommand(step.id, MODULE_ID, write(Ticket(key="WID-14"))))
    services.actions.run("ticket.toggle", context)
    assert asked and not enabled(step)
    services.undo.undo()
    assert step.module_data[MODULE_ID]["key"] == "WID-14"


# -- the CLI -----------------------------------------------------------------------------------


def test_agent_prompt_carries_handoffs_and_the_epilogue(cli_stdin, workspace):
    cli_stdin("project", "create", "Discovery")
    cli_stdin("step", "add", "Discovery", "Set up CI")
    cli_stdin("step", "add", "Discovery", "Deploy", "--after", "Set up CI")
    cli_stdin("agent", "set", "Deploy", "--file", "-", stdin="Ship it.")
    cli_stdin("handoff", "set", "Set up CI", "--file", "-", stdin="Keys in vault.")

    shown = json.loads(cli_stdin("agent", "prompt", "Deploy", "--json"))
    assert "Ship it." in shown["prompt"]
    assert 'From "Set up CI"' in shown["prompt"]
    assert "Keys in vault." in shown["prompt"]
    assert "dplanner status set 'Deploy' done" in shown["prompt"]
    assert "dplanner agent-state set 'Deploy' plan-for-review" in shown["prompt"]
    assert "dplanner agent-state clear 'Deploy'" in shown["prompt"]
    # The preflight comes first: no skill, no work.
    assert "dplanner skill status" in shown["prompt"]
    assert shown["prompt"].index("skill status") < shown["prompt"].index("Ship it.")
    assert shown["root"] == str(workspace / "discovery")
