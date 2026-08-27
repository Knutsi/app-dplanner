"""Launching an agent in a terminal, on whatever platform this is.

The launch is a **peer process, not a task**: the user owns the terminal from the moment it
opens, so nothing here reports to the task centre — tracking it would promise cancel and
progress the application cannot honestly deliver. The spawn is detached
(``start_new_session``) so closing DPlanner never takes the agent down with it. The session
is interactive on purpose — the developer is the human in the loop, and the agent's opening
prompt is the step's briefing, not its orders.

**Which agent runs is a preset, not a lookup.** ``PRESETS`` carries the known agent CLIs —
Claude Code, Codex, OpenCode — each with a working invocation, so the settings page offers
a dropdown that pre-fills an editable command instead of a bare field the user would have
to research. ``{prompt}`` in the command becomes the briefing (quoted, from the prompt
file); a command without the placeholder gets it appended.

**The step gets a worktree when it can.** When the checkout is a git repository (and the
setting is on), the wrapper script puts the agent in ``.dplanner/worktrees/<step>`` on an
``agent/<step>`` branch — created on the first run, reused on the next — so parallel agents
never trample one checkout, and the branch is the reviewable result. The directory is
excluded via ``.git/info/exclude`` (local, never versioned).

The prompt and the wrapper script go to a per-run temp directory, never the workspace — a
prompt file inside the workspace would dirty it and end up in version control.

Resolution order for the terminal: the user's command template from settings, else a
platform table, else ``None`` — and ``None`` is an answer, not an error: the caller falls
back to showing the assembled prompt.
"""

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

WORKTREES_DIR = ".dplanner/worktrees"


@dataclass(frozen=True)
class AgentPreset:
    id: str
    label: str
    # The command the wrapper execs; {prompt} becomes the briefing text, quoted.
    command: str


# The dropdown's rows, first is the default. Every command opens an *interactive* session
# seeded with the briefing; Claude Code also starts in plan mode, so the developer approves
# the plan before anything changes.
PRESETS: tuple[AgentPreset, ...] = (
    AgentPreset("claude", "Claude Code", "claude --permission-mode plan {prompt}"),
    AgentPreset("codex", "Codex", "codex {prompt}"),
    AgentPreset("opencode", "OpenCode", "opencode --prompt {prompt}"),
)

DEFAULT_AGENT_COMMAND = PRESETS[0].command


@dataclass(frozen=True)
class LaunchFiles:
    directory: Path
    prompt_file: Path
    script: Path


def new_run_dir() -> Path:
    """A fresh per-run directory for the prompt, the wrapper and any staged assets."""
    return Path(tempfile.mkdtemp(prefix="dplanner-agent-"))


def stage_assets(
    directory: Path,
    paths: Sequence[str],
    read: Callable[[str], bytes | None],
) -> dict[str, str]:
    """Copy workspace assets beside the prompt; original path -> absolute staged path.

    The agent runs in the checkout, not the workspace, so a workspace-relative path in the
    prompt would point at nothing it can reach. Asset names are content-addressed, so a
    basename collision means identical bytes and the flat copy is safe. An unreadable path
    maps to itself — a broken attachment stays visible in the prompt instead of vanishing.
    """
    staged: dict[str, str] = {}
    assets_dir = directory / "assets"
    for path in paths:
        data = read(path)
        if data is None:
            staged[path] = path
            continue
        assets_dir.mkdir(exist_ok=True)
        target = assets_dir / Path(path).name
        target.write_bytes(data)
        staged[path] = str(target)
    return staged


def _agent_line(agent_command: str, prompt_expansion: str) -> str:
    """The command with the briefing substituted; appended when no placeholder names it."""
    command = agent_command.strip() or DEFAULT_AGENT_COMMAND
    if "{prompt}" not in command:
        command += " {prompt}"
    return command.replace("{prompt}", prompt_expansion)


def prepare(
    prompt_text: str,
    workdir: Path,
    agent_command: str = DEFAULT_AGENT_COMMAND,
    worktree: str = "",
    platform: str = sys.platform,
    directory: Path | None = None,
) -> LaunchFiles:
    """Write the prompt and a wrapper script to ``directory``, or a fresh temp directory.

    ``worktree`` is a slug; when non-empty and the workdir is a git repository, the script
    moves into ``.dplanner/worktrees/<slug>`` (branch ``agent/<slug>``) before starting.
    """
    if directory is None:
        directory = new_run_dir()
    prompt_file = directory / "prompt.md"
    prompt_file.write_text(prompt_text)
    if platform.startswith("win"):
        script = directory / "run.cmd"
        script.write_text(_windows_script(workdir, prompt_file, agent_command, worktree))
    else:
        script = directory / "run.sh"
        script.write_text(_posix_script(workdir, prompt_file, agent_command, worktree))
        script.chmod(0o755)
    return LaunchFiles(directory=directory, prompt_file=prompt_file, script=script)


def _posix_script(workdir: Path, prompt_file: Path, agent_command: str, worktree: str) -> str:
    lines = ["#!/bin/sh", f'cd "{workdir}"']
    if worktree:
        tree = f"{workdir}/{WORKTREES_DIR}/{worktree}"
        lines += [
            "if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then",
            '  exclude="$(git rev-parse --git-common-dir)/info/exclude"',
            f"  grep -qxF '/{WORKTREES_DIR.split('/')[0]}/' \"$exclude\" 2>/dev/null"
            f" || echo '/{WORKTREES_DIR.split('/')[0]}/' >> \"$exclude\"",
            f'  git worktree add "{tree}" -b "agent/{worktree}" >/dev/null 2>&1'
            f' || git worktree add "{tree}" "agent/{worktree}" >/dev/null 2>&1 || true',
            f'  if [ -d "{tree}" ]; then cd "{tree}"; fi',
            "fi",
        ]
    lines.append("exec " + _agent_line(agent_command, f'"$(cat \'{prompt_file}\')"'))
    return "\n".join(lines) + "\n"


def _windows_script(workdir: Path, prompt_file: Path, agent_command: str, worktree: str) -> str:
    lines = ["@echo off", f'cd /d "{workdir}"']
    if worktree:
        tree = str(workdir / ".dplanner" / "worktrees" / worktree)
        lines += [
            "git rev-parse --is-inside-work-tree >nul 2>&1 && ("
            f'git worktree add "{tree}" -b "agent/{worktree}" >nul 2>&1'
            ")",
            f'if exist "{tree}" cd /d "{tree}"',
        ]
    agent = _agent_line(agent_command, f"(Get-Content -Raw '{prompt_file}')")
    lines.append(f'powershell -NoExit -Command "{agent}"')
    return "\r\n".join(lines) + "\r\n"


def resolve_command(
    template: str,
    files: LaunchFiles,
    workdir: Path,
    platform: str = sys.platform,
    which: Callable[[str], str | None] = shutil.which,
    env: Mapping[str, str] = os.environ,
) -> list[str] | None:
    """The command that opens a terminal running the script, or None when nothing can.

    A non-empty ``template`` — from settings — wins outright: it is substituted with
    ``{script}``, ``{prompt_file}`` and ``{workdir}`` and split like a shell would.
    """
    if template.strip():
        filled = template.format(
            script=files.script, prompt_file=files.prompt_file, workdir=workdir
        )
        return shlex.split(filled)
    script = str(files.script)
    if platform.startswith("linux"):
        if env.get("TMUX"):
            return ["tmux", "new-window", "-c", str(workdir), script]
        for terminal, args in _LINUX_TERMINALS:
            if which(terminal):
                return [terminal, *args, script]
        preferred = env.get("TERMINAL", "")
        if preferred and which(preferred):
            return [preferred, "-e", script]
        return None
    if platform == "darwin":
        return ["open", "-a", "Terminal", script]
    if platform.startswith("win"):
        if which("wt"):
            return ["wt", "-d", str(workdir), "cmd", "/k", script]
        return ["cmd", "/c", "start", "", "cmd", "/k", script]
    return None


# First found wins; the args are how each one is told what to run.
_LINUX_TERMINALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ghostty", ("-e",)),
    ("kitty", ()),
    ("alacritty", ("-e",)),
    ("foot", ()),
    ("gnome-terminal", ("--",)),
    ("konsole", ("-e",)),
    ("xterm", ("-e",)),
)


def spawn(command: list[str], workdir: Path) -> None:
    """Start the terminal, detached: its life is the user's, not the application's."""
    subprocess.Popen(
        command,
        cwd=workdir,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
