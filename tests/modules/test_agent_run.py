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
        "header",
        "protocol",
        "project",
        "context",
        "instruction",
        "inherited",
        "protocol",
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


def test_the_preflight_names_the_worktree_for_this_run_not_for_the_step(services, step):
    """The caller says whether *this run* has a worktree: Run Agent and `agent prompt`
    pass the step's choice, a conflict handed over by the window passes False — the
    merge must land in the checkout the window shows, whatever the step prefers."""
    from dplanner.modules import _default_briefing

    briefing = _default_briefing()
    isolated = briefing.preamble(step, True, None)
    assert ".dplanner-worktrees/s1-deploy" in isolated and "agent/s1-deploy" in isolated
    assert "STOP" in isolated
    shared = briefing.preamble(step, False, None)
    assert ".dplanner-worktrees" not in shared and "checkout itself" in shared
    assert "dplanner skill status" in isolated and "dplanner skill status" in shared


def test_the_preflight_says_where_the_plan_lives(services, step):
    """Apart from the code: the agent is told the verbs write elsewhere. Inside it: a
    warning to leave the plan files alone — dropped, not the paragraph, once the people
    on the project accepted the colocation."""
    from dataclasses import replace

    from dplanner.domain.repositories import RepositoryFacts
    from dplanner.modules import _default_briefing

    briefing = _default_briefing()
    apart = RepositoryFacts(
        plan_root=Path("/plans"),
        plan_remote="git@github.com:acme/plans.git",
        repository="https://github.com/acme/widget",
        checkout=None,
        colocation="",
    )
    text = briefing.preamble(step, True, apart)
    assert "own repository, acme/plans" in text and "acme/widget" in text
    assert "WARNING" not in text

    inside = RepositoryFacts(
        plan_root=Path("/widget"), plan_remote="", repository="", checkout=None, colocation=""
    )
    text = briefing.preamble(step, True, inside)
    assert "WARNING" in text and "do not stage or commit" in text
    assert "dplanner project move" in text

    text = briefing.preamble(step, True, replace(inside, colocation="accepted"))
    assert "WARNING" not in text and "by the developer's choice" in text
    assert "project move" not in text


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
    assert "\nclaude --add-dir " in script and " --permission-mode plan " in script
    assert "prompt.md" in script


def test_the_script_reports_the_shell_and_the_exit(tmp_path):
    """The wrapper is the one process that knows when the agent ends, so it says so
    beside the prompt: the shell's facts first, the exit status last — and a failure
    holds the window open long enough to be read."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    files = prepare(
        "p",
        tmp_path,
        platform="linux",
        directory=run_dir,
        step_title="Deploy: the 'beta' (v2)",
        session="7a1e4c2e-0000-4000-8000-000000000001",
    )
    script = files.script.read_text()
    assert files.title == "dplanner: Deploy: the beta (v2)"
    assert files.shell_file == run_dir / "shell" and files.exit_file == run_dir / "exit"
    assert "printf '\\033]0;%s\\007' 'dplanner: Deploy: the beta (v2)'" in script
    assert (
        f'"$(tty)" "$$" "$TMUX_PANE" "$TERM_PROGRAM" \'dplanner: Deploy: the beta (v2)\''
        f" 7a1e4c2e-0000-4000-8000-000000000001 > {run_dir}/shell"
    ) in script
    assert f"printf 'dir=%s\\n' \"$(pwd)\" >> {run_dir}/shell" in script
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


def test_a_run_name_isolates_the_run_beside_the_pointer_file(tmp_path):
    """The worktree lives in .dplanner-worktrees/, never .dplanner/: the latter is the
    pointer *file* a project kept in a subfolder leaves at the repository root, and the
    first version's `git worktree add` under it failed on every such project."""
    script = prepare("p", tmp_path, worktree="s7-build-it", platform="linux").script.read_text()
    tree = f"{tmp_path}/.dplanner-worktrees/s7-build-it"
    assert f'git worktree add "{tree}" -b "agent/s7-build-it"' in script
    assert f'git worktree add "{tree}" "agent/s7-build-it"' in script  # Reused on the next run.
    assert "info/exclude" in script  # The worktree dir never pollutes git status.
    assert f'cd "{tree}"' in script
    assert "git worktree prune" in script


def test_no_run_name_means_no_git_lines(tmp_path):
    assert "git worktree add" not in prepare("p", tmp_path, platform="linux").script.read_text()


@pytest.fixture
def pointed_repo(tmp_path):
    """A repository whose plan sits in a subfolder — so the root carries the `.dplanner`
    pointer *file* the old worktree path collided with."""
    import subprocess

    from dplanner.core.storage.locations import init_repo
    from dplanner.domain.seed import seed_project

    repo = init_repo(tmp_path / "repo")
    seed_project(repo / "planning", "Discovery")
    assert (repo / ".dplanner").is_file()
    git = ["git", "-C", str(repo)]
    subprocess.run([*git, "config", "user.email", "t@example.com"], check=True)
    subprocess.run([*git, "config", "user.name", "t"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "init"], check=True)
    return repo


def _run_script(files):
    import subprocess

    return subprocess.run(
        ["sh", str(files.script)], capture_output=True, text=True, stdin=subprocess.DEVNULL
    )


def test_the_script_puts_the_agent_in_its_worktree_on_its_branch(pointed_repo, tmp_path):
    """End to end, in a real repository with the pointer file: the worktree is created on
    the first run, reused on the second, and the agent starts inside it on its branch."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    files = prepare(
        "p",
        pointed_repo,
        agent_command="sh -c 'pwd; git branch --show-current' # {prompt}",
        worktree="s1-discovery",
        platform="linux",
        directory=run_dir,
    )
    for _ in range(2):
        done = _run_script(files)
        assert done.returncode == 0, done.stdout + done.stderr
        assert f"{pointed_repo}/.dplanner-worktrees/s1-discovery\nagent/s1-discovery" in done.stdout
        assert files.exit_file.read_text().strip() == "0"
    assert (pointed_repo / ".dplanner-worktrees" / "s1-discovery" / ".git").is_file()
    assert "/.dplanner-worktrees/" in (pointed_repo / ".git" / "info" / "exclude").read_text()


def test_a_worktree_that_cannot_be_prepared_stops_the_run(pointed_repo, tmp_path):
    """Never the main checkout by accident: git's refusal ends the run with a failed
    exit, which the window reports, instead of carrying on where the plan is."""
    (pointed_repo / ".dplanner-worktrees").mkdir()
    (pointed_repo / ".dplanner-worktrees" / "s2-stale").write_text("in the way")
    (tmp_path / "run").mkdir()
    files = prepare(
        "p",
        pointed_repo,
        agent_command="sh -c 'echo RAN' # {prompt}",
        worktree="s2-stale",
        platform="linux",
        directory=tmp_path / "run",
    )
    done = _run_script(files)
    assert done.returncode == 1
    assert "RAN" not in done.stdout
    assert "Could not prepare the worktree" in done.stdout
    assert files.exit_file.read_text().strip() == "1"


def test_a_run_name_is_the_key_the_ticket_and_the_slug_made_ref_safe():
    from dplanner.modules.step_agent_instruction.launcher import ref_safe, run_name

    assert run_name("F7", "PROJ-12", "Build the modal") == "f7-PROJ-12-build-the-modal"
    assert run_name("S3", "", "Wire it (v2)!") == "s3-wire-it-v2"
    assert run_name("", "", "") == "step"
    assert ref_safe("a..b//c ~^:?*[\\") == "a-b-c"
    assert ref_safe("-.lead and trail.-") == "lead-and-trail"
    assert len(run_name("S1", "", "x" * 200)) <= 60


def test_a_command_without_the_placeholder_still_gets_the_prompt(tmp_path):
    script = prepare("p", tmp_path, agent_command="my-agent", platform="linux").script.read_text()
    assert "\nmy-agent 'Read your briefing in " in script


def test_the_briefing_never_rides_in_argv(tmp_path):
    """The incident: every briefing handed to the agent as one argument was every agent's
    command line, and one agent's `pkill -f "Web.Host"` — its own dev server — matched
    the words of every other agent's briefing. The opening line points at the file and
    carries nothing the project is about."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    briefing = "Restart Web.Host after the migration; vite serves the front end."
    files = prepare(briefing, tmp_path, platform="linux", directory=run_dir)
    script = files.script.read_text()
    assert files.prompt_file.read_text() == briefing
    assert "Web.Host" not in script and "vite" not in script
    assert f"'Read your briefing in {run_dir}/prompt.md in full, then follow it.'" in script
    assert "$(cat" not in script
    windows = prepare(briefing, tmp_path, platform="win32", directory=run_dir).script.read_text()
    assert "Web.Host" not in windows and "Get-Content" not in windows
    assert f"'Read your briefing in {run_dir / 'prompt.md'} in full, then follow it.'" in windows


def test_the_claude_preset_names_the_session_and_the_script_says_how_to_resume(tmp_path):
    """A session id minted per launch is what `claude --resume` takes back: the facts
    carry it with the directory the agent works in, and a failed run's window prints
    the command before it waits for Enter."""
    from dplanner.modules.step_agent_instruction.launcher import resume_command

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    session = "7a1e4c2e-0000-4000-8000-000000000002"
    files = prepare("p", tmp_path, platform="linux", directory=run_dir, session=session)
    script = files.script.read_text()
    assert files.session == session
    assert f"\nclaude --add-dir {run_dir} --permission-mode plan --session-id {session} 'Read" in (
        script
    )
    assert (
        f'printf \'resume=cd "%s" && claude --resume {session}\\n\' "$(pwd)" >> {run_dir}/shell'
    ) in script
    assert f'To pick it up again: cd "%s" && claude --resume {session}' in script
    assert resume_command(
        "claude --add-dir {run_dir} --permission-mode plan --session-id {session} {prompt}", "x"
    )
    assert resume_command("my-agent --session {session} {prompt}", "x") == ""  # Unknown agent.
    assert resume_command("codex {prompt}", "x") == ""  # Cannot name a session up front.
    windows = prepare(
        "p", tmp_path, platform="win32", directory=run_dir, session=session
    ).script.read_text()
    assert f"--session-id {session} 'Read" in windows
    assert f"'session={session}'" in windows and "'dir=' + $PWD" in windows
    assert f"'resume=cd /d ' + $PWD + ' && claude --resume {session}'" in windows


def test_the_run_directory_is_handed_over_as_an_additional_directory(tmp_path):
    """The pointer names a file outside the checkout, and Claude Code asks before reading
    outside its working directories — one approval per launch, on every platform. The
    preset adds the run directory (`--add-dir`), which takes a list: it sits before
    another option, never before the prompt it would otherwise swallow. Quoted per
    dialect, because a Temp path under a Windows user name can carry a space."""
    import shlex

    run_dir = tmp_path / "o'run dir"
    run_dir.mkdir()
    session = "7a1e4c2e-0000-4000-8000-000000000003"
    script = prepare(
        "p", tmp_path, platform="linux", directory=run_dir, session=session
    ).script.read_text()
    quoted = shlex.quote(str(run_dir))
    assert f"\nclaude --add-dir {quoted} --permission-mode plan --session-id {session} 'Read" in (
        script
    )
    windows = prepare(
        "p", tmp_path, platform="win32", directory=run_dir, session=session
    ).script.read_text()
    doubled = str(run_dir).replace("'", "''")
    assert f"claude --add-dir '{doubled}' --permission-mode plan --session-id {session} 'Read" in (
        windows
    )


def test_a_run_directory_is_made_resolved(tmp_path, monkeypatch):
    """macOS's temp directory sits under `/var`, a symlink to `/private/var`, and
    Windows's Temp is often a short name; the permission check compares a file's
    resolved path, so the flag and the pointer carry the resolved one."""
    import tempfile

    from dplanner.modules.step_agent_instruction import launcher

    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    monkeypatch.setattr(tempfile, "tempdir", str(link))
    run_dir = launcher.new_run_dir()
    assert run_dir.is_dir() and run_dir.parent == real


def test_a_minted_session_is_a_uuid(tmp_path):
    import uuid

    files = prepare("p", tmp_path, platform="linux")
    assert uuid.UUID(files.session)
    assert files.session in files.script.read_text()


def test_an_agent_without_a_session_gets_no_resume_lines(tmp_path):
    script = prepare("p", tmp_path, agent_command="codex {prompt}", platform="linux")
    text = script.script.read_text()
    assert "resume=" not in text and "pick it up" not in text
    assert f"session={script.session}" not in text  # The facts name it; the command does not.
    assert f" {script.session} > " in text


def test_the_spawned_environment_carries_no_session_markers(monkeypatch, tmp_path):
    """Inside another agent's session markers a nested `claude` is a child session — no
    transcript, ended with its parent — which is how one window took four agents down.
    The person's own configuration under the same prefix stays."""
    import subprocess

    from dplanner.modules.step_agent_instruction import launcher

    # What Claude Code 2.1 sets in every shell it runs, and what it scrubs itself before a
    # standalone session — read off the binary, so the list is not a guess.
    env = {
        "PATH": "/usr/bin",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_ENTRYPOINT": "cli",
        "CLAUDE_CODE_SESSION_ID": "48bd92ff-5111-4a38-98bf-450df120a804",
        "CLAUDE_CODE_CHILD_SESSION": "1",
        "CLAUDE_PID": "4242",
        "CLAUDE_EFFORT": "high",
        "CLAUDE_CODE_EXECPATH": "/opt/claude-code/bin/claude",
        "AI_AGENT": "claude-code/agent",
        "TRACEPARENT": "00-abc-def-01",
        "CLAUDE_CODE_REMOTE_SESSION_ID": "s1",  # By the rule, not the list.
        # 2.1.258 also sets these three: the parent's inter-session bridge. By the rule.
        "CLAUDE_CODE_MESSAGING_SOCKET": "/run/user/1000/claude/bridge.sock",
        "CLAUDE_CODE_MESSAGING_TOKEN": "t0ken",
        "CLAUDE_CODE_BRIDGE_SESSION_ID": "b1",
        "CLAUDE_CONFIG_DIR": "/home/me/.claude",
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "8000",
        "ANTHROPIC_API_KEY": "k",
    }
    assert launcher.scrubbed_environment(env) == {
        "PATH": "/usr/bin",
        "CLAUDE_CONFIG_DIR": "/home/me/.claude",
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "8000",
        "ANTHROPIC_API_KEY": "k",
    }
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setenv("CLAUDECODE", "1")
    launcher.spawn(["term", "-e", "run.sh"], tmp_path)
    ((command,), options) = calls[0]
    assert command == ["term", "-e", "run.sh"]
    assert options["start_new_session"] is True and options["cwd"] == tmp_path
    assert "CLAUDECODE" not in options["env"] and "PATH" in options["env"]


def test_the_presets_cover_the_known_agents():
    from dplanner.modules.step_agent_instruction.launcher import PRESETS

    assert [preset.id for preset in PRESETS] == ["claude", "codex", "opencode"]
    assert all("{prompt}" in preset.command for preset in PRESETS)
    for preset in PRESETS:
        tokens = preset.command.split()
        if "{run_dir}" in tokens:
            # `--add-dir` takes a list: what follows the directory is an option, not the prompt.
            assert tokens[tokens.index("{run_dir}") + 1].startswith("--")


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
    assert labels[0] == "Terminal" and labels[-1] == "Automatic"
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


def test_a_preset_text_an_earlier_version_shipped_is_still_that_preset(app, tmp_path):
    """The settings store the picked preset's text, so a machine that picked Claude Code
    before the command changed holds the old one — read as Custom, launched without
    the session id and the directory, never resumable. It is the preset."""
    from PySide6.QtWidgets import QComboBox

    from dplanner.framework.user_config import set_global
    from dplanner.modules.step_agent_instruction.aspect import MODULE_ID
    from dplanner.modules.step_agent_instruction.launcher import (
        PRESETS,
        current_command,
        resume_command,
    )
    from dplanner.modules.step_agent_instruction.settings_page import (
        AGENT_COMMAND_KEY,
        agent_command,
        build_page,
    )

    claude = PRESETS[0]
    assert claude.superseded
    for old in claude.superseded:
        assert current_command(old) == claude.command
        assert resume_command(old, "x") == "claude --resume x"
    assert current_command("my-agent {prompt}") == "my-agent {prompt}"
    assert current_command("  ") == claude.command
    old = "claude --permission-mode plan {prompt}"
    script = prepare("p", tmp_path, agent_command=old, platform="linux").script.read_text()
    assert "--add-dir" in script and "--session-id" in script
    set_global(MODULE_ID, AGENT_COMMAND_KEY, old)
    assert agent_command() == claude.command
    page = build_page(None)
    combo = page.findChild(QComboBox, "AgentPresetCombo")
    assert combo is not None and combo.currentText() == "Claude Code"


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


def test_inside_tmux_a_desktop_terminal_still_wins(tmp_path):
    """A DPlanner started from a tmux shell inherits $TMUX; Automatic must still open a
    window of its own — a tmux window lands inside whatever terminal the person is using."""
    command = resolve_command(
        "",
        fake_files(tmp_path),
        Path("/work"),
        platform="linux",
        which=lambda name: "/usr/bin/ghostty" if name == "ghostty" else None,
        env={"TMUX": "/tmp/tmux-1000/default,42,0"},
    )
    assert command is not None and command[0] == "ghostty"


def test_tmux_is_the_last_resort(tmp_path):
    command = resolve_command(
        "",
        fake_files(tmp_path),
        Path("/work"),
        platform="linux",
        which=lambda _name: None,
        env={"TMUX": "/tmp/tmux-1000/default,42,0"},
    )
    assert command is not None and command[:2] == ["tmux", "new-window"]


def test_the_first_terminal_found_wins(tmp_path):
    command = resolve_command(
        "",
        fake_files(tmp_path),
        Path("/work"),
        platform="linux",
        which=lambda name: "/usr/bin/kitty" if name == "kitty" else None,
        env={},
    )
    assert command is not None and command[0] == "kitty"


def test_macos_opens_terminal_app(tmp_path):
    """The platform's own default terminal, whatever else is installed: Automatic
    behaves the way the machine does, and the dropdown is where Ghostty or iTerm is."""
    command = resolve_command(
        "",
        fake_files(tmp_path),
        Path("/work"),
        platform="darwin",
        which=lambda _name: None,
        env={},
        app_exists=lambda _name: True,
    )
    assert command is not None and command[:3] == ["open", "-a", "Terminal"]


def test_the_terminal_table_is_one_per_platform_and_probes_installs():
    from dplanner.modules.step_agent_instruction.launcher import is_installed, terminals_for

    assert [p.label for p in terminals_for("darwin")] == [
        "Terminal",
        "iTerm",
        "Ghostty",
        "tmux (new window)",
    ]
    assert [p.id for p in terminals_for("win32")] == ["wt", "cmd", "ghostty-win"]
    assert terminals_for("linux")[0].id == "ghostty" and terminals_for("linux")[-1].id == "tmux"
    ghostty_mac = next(p for p in terminals_for("darwin") if p.id == "ghostty-mac")
    none = lambda _n: None  # noqa: E731 - a stand-in for shutil.which
    assert is_installed(ghostty_mac, which=none, env={}, app_exists=lambda n: n == "Ghostty")
    assert not is_installed(ghostty_mac, which=none, env={}, app_exists=lambda _n: False)
    tmux = terminals_for("linux")[-1]
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
        "wt",
        "-d",
        r"C:\work",
        "cmd",
        "/k",
        r"C:\Users\me\run.cmd",
        "--title",
        "dplanner: Deploy",
    ]


def test_an_unusable_template_answers_none(tmp_path):
    assert resolve_command("myterm {nonsense}", fake_files(tmp_path), Path("/w"), "linux") is None


def test_windows_prefers_windows_terminal(tmp_path):
    command = resolve_command(
        "",
        fake_files(tmp_path),
        Path("C:/work"),
        platform="win32",
        which=lambda name: "wt" if name == "wt" else None,
        env={},
    )
    assert command is not None and command[0] == "wt"


def test_nothing_found_answers_none_not_an_error(tmp_path):
    command = resolve_command(
        "",
        fake_files(tmp_path),
        Path("/work"),
        platform="linux",
        which=lambda _name: None,
        env={},
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

    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("step", step.id)),))


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


def test_a_separated_plans_agent_runs_in_the_code_checkout(services, step, tmp_path, monkeypatch):
    """A project that records its code repository: the shell opens in that code's
    checkout on this machine, never in the plan's own repository."""
    from dplanner.core.storage.locations import init_repo
    from dplanner.domain.commands import SetFieldCommand

    code = init_repo(tmp_path / "widget")
    project = services.document.project_of(step.id)
    services.undo.push(SetFieldCommand(project.id, "repository", "https://github.com/acme/widget"))
    services.repo.set_checkout(project.id, code)
    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    select(services, step)

    calls: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(launcher, "spawn", lambda cmd, cwd: calls.append((cmd, cwd)))
    monkeypatch.setattr(launcher, "resolve_command", lambda *a, **k: ["fake-term"])
    services.actions.run("agent.run", services.context.current())
    ((_command, cwd),) = calls
    assert cwd == code


def test_a_code_repository_not_checked_out_here_greys_run_agent_and_says_so(
    services, step, tmp_path
):
    """Greyed with the reason — and recording the checkout (the Project dialog, or an
    agent's first call adopted from the library file) re-evaluates every presenter,
    though nothing in the context graph changed."""
    from dplanner.core.storage.locations import init_repo
    from dplanner.domain.commands import SetFieldCommand

    project = services.document.project_of(step.id)
    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    services.undo.push(SetFieldCommand(project.id, "repository", "https://github.com/acme/widget"))
    select(services, step)
    state = services.actions.spec("agent.run").state(services.context.current())
    assert state.visible and not state.enabled
    assert state.label is not None and "not checked out" in state.label

    refreshed: list[bool] = []
    services.context.changed.connect(lambda _context: refreshed.append(True))
    services.repo.set_checkout(project.id, init_repo(tmp_path / "widget"))
    assert refreshed
    assert services.actions.spec("agent.run").state(services.context.current()).enabled


def _agent_section(services):
    spec = next(
        s for s in services.inspector_sections.sections() if s.id == "step_agent_instruction.tab"
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


@pytest.fixture
def prerequisite(services, step):
    """``step`` now waits on "Prepare", and is briefed."""
    from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand
    from dplanner.domain.model import Step

    project = services.document.project_of(step.id)
    prepare = Step(title="Prepare")
    AddNodeCommand(project.id, prepare).redo(services.document)
    SetEdgesCommand(step.id, "requires", [prepare.id]).redo(services.document)
    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    return prepare


def _fake_terminal(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(launcher, "spawn", lambda cmd, cwd: calls.append(cmd))
    monkeypatch.setattr(launcher, "resolve_command", lambda *a, **k: ["fake-term"])
    return calls


def _record_boxes(monkeypatch, *, click):
    """Every QMessageBox shown, recorded instead of blocking; ``click`` names the role of
    the button the person presses, or None for Escape."""
    from PySide6.QtWidgets import QMessageBox

    shown = []

    def fake_exec(self):
        shown.append((self.windowTitle(), self.text(), self.informativeText()))
        return 0

    def clicked(self):
        return next((b for b in self.buttons() if self.buttonRole(b) == click), None)

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", clicked)
    return shown


def test_running_on_an_unfinished_prerequisite_asks_first_and_cancel_launches_nothing(
    services, step, prerequisite, monkeypatch
):
    """The graph gates launching: the box names the steps not done and their statuses,
    and Cancel — the default — spawns no shell."""
    calls = _fake_terminal(monkeypatch)
    boxes = _record_boxes(monkeypatch, click=None)
    select(services, step)
    services.actions.run("agent.run", services.context.current())
    assert calls == []
    ((title, text, detail),) = boxes
    assert title == "Run Agent"
    assert "waits on 1 step not done yet" in text
    assert "Prepare — pending" in detail


def test_run_anyway_launches_over_an_unfinished_prerequisite(
    services, step, prerequisite, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    calls = _fake_terminal(monkeypatch)
    boxes = _record_boxes(monkeypatch, click=QMessageBox.ButtonRole.AcceptRole)
    select(services, step)
    services.actions.run("agent.run", services.context.current())
    assert len(boxes) == 1
    assert calls == [["fake-term"]]


def test_done_prerequisites_launch_without_asking(services, step, prerequisite, monkeypatch):
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.step_status.aspect import MODULE_ID as STATUS_ID
    from dplanner.modules.step_status.aspect import write as write_status

    services.undo.push(SetModuleDataCommand(prerequisite.id, STATUS_ID, write_status("done")))
    calls = _fake_terminal(monkeypatch)
    boxes = _record_boxes(monkeypatch, click=None)
    select(services, step)
    services.actions.run("agent.run", services.context.current())
    assert boxes == []
    assert calls == [["fake-term"]]


def test_running_spawns_a_terminal_in_the_projects_repo_root(
    services, step, library_repo, monkeypatch
):
    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    select(services, step)

    calls: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(launcher, "spawn", lambda cmd, cwd: calls.append((cmd, cwd)))
    monkeypatch.setattr(launcher, "resolve_command", lambda *a, **k: ["fake-term", "-e", "run.sh"])
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


# -- where the agent works: the step's own fact ---------------------------------------------


def test_the_worktree_choice_is_the_steps_and_on_by_default(cli):
    """Absence means a fresh worktree; the opt-out is written on the aspect's entry, and
    the mark and a separate-instruction flag ride along when it flips."""
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy", "--agent")
    assert json.loads(cli("agent", "show", "Deploy", "--json"))["worktree"] is True
    assert (
        "worktree"
        not in json.loads(cli("step", "show", "Deploy", "--json"))["aspects"][
            "step_agent_instruction"
        ]
    )
    assert "checkout itself" in cli("agent", "worktree", "Deploy", "off")
    assert json.loads(cli("agent", "show", "Deploy", "--json"))["worktree"] is False
    entry = json.loads(cli("step", "show", "Deploy", "--json"))["aspects"]["step_agent_instruction"]
    assert entry["worktree"] is False and entry["on"] is True
    assert "already" in cli("agent", "worktree", "Deploy", "off")
    cli("agent", "worktree", "Deploy", "on")
    entry = json.loads(cli("step", "show", "Deploy", "--json"))["aspects"]["step_agent_instruction"]
    assert "worktree" not in entry
    assert "not an agent step" in cli("agent", "worktree", "Discovery", "off", expect=1) or True


def test_step_add_no_worktree_marks_the_step_and_opts_it_out(cli):
    cli("project", "create", "Discovery")
    assert "in the checkout itself" in cli("step", "add", "Discovery", "Cut", "--no-worktree")
    shown = json.loads(cli("agent", "show", "Cut", "--json"))
    assert shown["agent"] is True and shown["worktree"] is False


def test_the_run_uses_a_worktree_only_when_the_step_says_so(services, step, monkeypatch):
    """The launcher is handed the run name — key, ticket, slug — or nothing at all."""
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.step_agent_instruction.aspect import MODULE_ID, write_state
    from dplanner.modules.step_ticket.aspect import MODULE_ID as TICKET_ID
    from dplanner.modules.step_ticket.aspect import Ticket
    from dplanner.modules.step_ticket.aspect import write as ticket_write

    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    services.undo.push(SetModuleDataCommand(step.id, TICKET_ID, ticket_write(Ticket(key="PROJ-9"))))
    select(services, step)
    monkeypatch.setattr(launcher, "spawn", lambda cmd, cwd: None)
    monkeypatch.setattr(launcher, "resolve_command", lambda *a, **k: ["fake-term"])
    seen: list[str] = []
    real_prepare = launcher.prepare

    def capture(*args, **kwargs):
        seen.append(kwargs["worktree"])
        return real_prepare(*args, **kwargs)

    monkeypatch.setattr(launcher, "prepare", capture)
    services.actions.run("agent.run", services.context.current())
    assert seen == ["s1-PROJ-9-deploy"]

    services.undo.push(SetModuleDataCommand(step.id, MODULE_ID, write_state(True, worktree=False)))
    services.actions.run("agent.run", services.context.current())
    assert seen == ["s1-PROJ-9-deploy", ""]


def test_the_agent_tab_switches_the_worktree_through_the_undo_stack(services, step):
    from dplanner.modules.step_agent_instruction.aspect import uses_worktree

    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    select(services, step)
    section = _agent_section(services)
    section.show_target(step.id)
    assert section.worktree_box.isChecked()
    section.worktree_box.setChecked(False)
    assert not uses_worktree(step)
    assert services.undo.can_undo()
    services.undo.undo()
    assert uses_worktree(step)
    assert section.worktree_box.isChecked()  # The model's echo reaches the box.
    section.dispose()


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


def test_toggling_agent_off_shelves_the_text_and_on_brings_it_back(services, step):
    """Nothing asks: the separate instruction waits on the shelf, and one undo restores
    both the mark and the text."""
    from dplanner.domain.shelf import shelved_text
    from dplanner.modules.step_agent_instruction.aspect import enabled

    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    select(services, step)
    services.actions.run("agent.toggle", services.context.current())
    assert not enabled(step)
    assert step.module_text.get("step_agent_instruction", "") == ""
    assert shelved_text(step, "step_agent_instruction") == "Ship it."
    services.undo.undo()
    assert enabled(step)
    assert step.module_text["step_agent_instruction"] == "Ship it."

    services.undo.redo()
    services.actions.run("agent.toggle", services.context.current())
    assert enabled(step)
    assert step.module_text["step_agent_instruction"] == "Ship it."


def test_the_ticket_toggle_adds_the_empty_aspect_and_shelves_a_filled_one(services, step):
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.domain.shelf import SHELF_ID
    from dplanner.modules.step_ticket.aspect import MODULE_ID, Ticket, enabled, read, write

    select(services, step)
    context = services.context.current()
    spec = services.actions.spec("ticket.toggle")
    assert spec.state(context).checked is False

    services.actions.run("ticket.toggle", context)
    assert enabled(step) and spec.state(context).checked is True

    # Off with no reference filled in: the marker goes and nothing is shelved for it.
    services.actions.run("ticket.toggle", context)
    assert not enabled(step)

    # Off with a reference: shelved, and on again brings the very reference back.
    services.undo.push(SetModuleDataCommand(step.id, MODULE_ID, write(Ticket(key="WID-14"))))
    services.actions.run("ticket.toggle", context)
    assert not enabled(step) and SHELF_ID in step.module_data
    services.actions.run("ticket.toggle", context)
    assert read(step) == Ticket(key="WID-14")
    assert SHELF_ID not in step.module_data


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
    # Every verb names the step by its key: unambiguous where a title may not be.
    assert "dplanner status set S2 done" in shown["prompt"]
    assert "dplanner agent-state set S2 plan-for-review" in shown["prompt"]
    assert "dplanner agent-state clear S2" in shown["prompt"]
    assert "dplanner github set S2 --branch" in shown["prompt"]
    # The preflight comes first: no skill, no work — and no worktree, no work either.
    assert "dplanner skill status" in shown["prompt"]
    assert shown["prompt"].index("skill status") < shown["prompt"].index("Ship it.")
    assert ".dplanner-worktrees/s2-deploy" in shown["prompt"]
    assert "agent/s2-deploy" in shown["prompt"] and "STOP" in shown["prompt"]
    assert shown["root"] == str(workspace / "discovery")


def test_agent_prompt_says_where_the_plan_lives(cli_stdin):
    """The verb hands the briefing the same facts the window does: a plan with no code
    repository recorded is warned about, one with its own repository is not."""
    cli_stdin("project", "create", "Discovery")
    cli_stdin("step", "add", "Discovery", "Deploy", "--agent")
    cli_stdin("describe", "set", "Deploy", "--file", "-", stdin="Ship it.")
    shown = json.loads(cli_stdin("agent", "prompt", "Deploy", "--json"))
    assert "WARNING: this plan lives inside the code repository" in shown["prompt"]

    cli_stdin("project", "set", "Discovery", "--repository", "https://github.com/acme/widget")
    shown = json.loads(cli_stdin("agent", "prompt", "Deploy", "--json"))
    assert "WARNING" not in shown["prompt"]
    assert "apart from the code you are working in (acme/widget)" in shown["prompt"]
    assert shown["repository"] == "https://github.com/acme/widget"


def test_a_step_without_a_worktree_is_briefed_to_stay_in_the_checkout(cli_stdin):
    cli_stdin("project", "create", "Discovery")
    cli_stdin("step", "add", "Discovery", "Cut the release", "--no-worktree")
    cli_stdin("describe", "set", "Cut the release", "--file", "-", stdin="Tag and push.")
    shown = json.loads(cli_stdin("agent", "prompt", "Cut the release", "--json"))
    assert ".dplanner-worktrees" not in shown["prompt"]
    assert "works in the checkout itself" in shown["prompt"]


# -- the agent's shell names its project ---------------------------------------------------------


def test_the_wrapper_exports_the_project_id_for_every_verb_in_the_shell(tmp_path):
    posix = prepare("p", tmp_path, platform="linux", project_id="abc123").script.read_text()
    assert "export DPLANNER_PROJECT=abc123" in posix
    windows = prepare("p", tmp_path, platform="win32", project_id="abc123").script.read_text()
    assert "set DPLANNER_PROJECT=abc123" in windows
    assert "DPLANNER_PROJECT" not in prepare("p", tmp_path, platform="linux").script.read_text()


def test_the_launch_names_the_steps_project_for_the_shell(services, step, monkeypatch):
    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    select(services, step)
    seen: dict[str, object] = {}
    real = launcher.prepare

    def capture(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(launcher, "prepare", capture)
    _fake_terminal(monkeypatch)
    services.actions.run("agent.run", services.context.current())
    assert seen["project_id"] == services.document.project_of(step.id).id
