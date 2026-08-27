"""Launching an agent in a terminal, on whatever platform this is.

The launch is a **peer process, not a task**: the user owns the terminal from the moment it
opens, so nothing here reports to the task centre — tracking it would promise cancel and
progress the application cannot honestly deliver. The spawn is detached
(``start_new_session``) so closing DPlanner never takes the agent down with it.

The prompt and a wrapper script go to a per-run temp directory, never the workspace — a
prompt file inside the workspace would dirty it and end up in version control.

Resolution order: the user's command template from settings, else a platform table, else
``None`` — and ``None`` is an answer, not an error: the caller falls back to showing the
assembled prompt.
"""

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

CLAUDE_COMMAND = "claude --permission-mode plan"

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


@dataclass(frozen=True)
class LaunchFiles:
    directory: Path
    prompt_file: Path
    script: Path


def prepare(prompt_text: str, workdir: Path, platform: str = sys.platform) -> LaunchFiles:
    """Write the prompt and a wrapper script to a fresh temp directory."""
    directory = Path(tempfile.mkdtemp(prefix="dplanner-agent-"))
    prompt_file = directory / "prompt.md"
    prompt_file.write_text(prompt_text)
    if platform.startswith("win"):
        script = directory / "run.cmd"
        script.write_text(
            "@echo off\r\n"
            f'cd /d "{workdir}"\r\n'
            f"powershell -NoExit -Command \"{CLAUDE_COMMAND}"
            f" (Get-Content -Raw '{prompt_file}')\"\r\n"
        )
    else:
        script = directory / "run.sh"
        script.write_text(
            f'#!/bin/sh\ncd "{workdir}"\nexec {CLAUDE_COMMAND} "$(cat \'{prompt_file}\')"\n'
        )
        script.chmod(0o755)
    return LaunchFiles(directory=directory, prompt_file=prompt_file, script=script)


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


def spawn(command: list[str], workdir: Path) -> None:
    """Start the terminal, detached: its life is the user's, not the application's."""
    subprocess.Popen(
        command,
        cwd=workdir,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
