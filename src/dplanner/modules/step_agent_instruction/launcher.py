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

**Which terminal opens is the same shape.** ``TERMINALS`` is one table of the known
terminals per platform — Ghostty, iTerm and Terminal on macOS; Ghostty, Windows Terminal
and the Command Prompt on Windows; Ghostty, kitty, Alacritty, foot, GNOME Terminal, Konsole
and xterm on Linux — each with the command that opens it on the wrapper script and a probe
saying whether it is installed. The settings dropdown lists the table and pre-fills the
editable template; *Automatic* is the first installed row, which is the platform's own
default terminal. One table, two readers, so the dropdown can never offer a terminal the
launch would not find.

**tmux is the last row, never the first.** A DPlanner started from a shell inside tmux
inherits ``$TMUX``, and while tmux led the table Automatic opened every agent as a tmux
window in whatever session tmux called current — inside a terminal window the person was
using, and a different one each time. A desktop application's agent belongs in a desktop
terminal; tmux is what Automatic reaches for only when no terminal is installed (a session
over ssh), and what the dropdown offers to anyone who wants it. Ghostty's ``-e`` runs the
command in a fresh process with its own window — it forces ``gtk-single-instance=false``
— so a Ghostty row never lands in a split or a tab of a window already in use.

**The shell reports back through its run directory.** The wrapper script is the one
process that knows when the agent ends, so it writes two files beside the prompt: the
shell's facts on start (``shell``: tty, pid, tmux pane, terminal program, window title —
what a later *Show Agent Terminal* needs to find the window again — the run's session id,
and once it is in place the directory it works in and the command that resumes it) and
the agent's exit status when it ends (``exit``; ``closed`` when the terminal was shut on
it). The agent-run module watches for the second and clears the step's chip; nothing here
depends on the terminal, so the report works with every row of the table. On a non-zero
exit the window stays open on a *Press Enter* line, with the resume command above it, so
a crash can be read — and picked up again — before it is gone.

**The briefing never rides in argv.** The agent's opening prompt is one line pointing at
``prompt.md`` (:func:`opening_prompt`); the briefing itself is read from the file. Handed
over as an argument, the whole briefing was every agent's command line — and one agent's
``pkill -f "Web.Host"``, aimed at its own dev server, matched the words of every other
agent's briefing and killed four of them mid-task. A command line that carries only a
path cannot be matched by anything the project is about; it also stays under the
platform's argument limit and readable in ``ps``. The run directory is outside the
checkout, and Claude Code asks before reading outside its working directories, so the
preset hands it over as one (``--add-dir {run_dir}``) and the read asks nothing. The
flag takes a list, so it sits before another option and never before ``{prompt}``,
which it would swallow. :func:`new_run_dir` resolves the path: the permission check
compares a file's resolved path, and macOS's ``/var`` is a symlink where Windows's
Temp is often a short name.

**The agent is a top-level session.** :func:`spawn` hands the terminal an environment
with the session markers an agent CLI sets in its shells taken out
(:func:`scrubbed_environment`): with them in place a nested ``claude`` makes itself a
*child* of the session that set them — no transcript of its own, ended when the parent's
turn ends — which is how a DPlanner started from an agent's shell took every agent it
launched down with it. ``entry.py`` refuses to open a window from such a shell; the scrub
is the second line, for a window that got its environment some other way. The list is
what Claude Code itself sets per shell and scrubs before a standalone session
(``SESSION_MARKERS``); user configuration under the same prefix (``CLAUDE_CONFIG_DIR``,
``CLAUDE_CODE_USE_BEDROCK``) is the person's, not a session's, and stays. The Claude
preset also names the run's session (``--session-id``, minted per launch): the id is what
``claude --resume`` takes, so an agent that died can be picked up where it stopped.

**A worktree is prepared by the script, and a worktree that cannot be prepared stops the
run.** When the step asks for one (its agent aspect's ``worktree``, on by default), the
wrapper puts the agent in :data:`WORKTREES_DIR`/``<run name>`` on the ``agent/<run name>``
branch — created on the first run, reused on the next — so parallel agents never trample
one checkout, and the branch is the reviewable result. The run name is
:func:`run_name`: the step's key, its ticket and its title, made safe for a ref, so the
branch says which step it is and a person can find it in ``git branch``. The directory is
excluded through ``.git/info/exclude`` (local, never versioned). **If git cannot make the
worktree, the script says why and exits 1 instead of carrying on in the main checkout** —
the first version swallowed the error, and two agents launched into "fresh worktrees" did
their work on the same branch. The directory is deliberately not ``.dplanner/``: that name
is the pointer *file* a project kept in a subfolder leaves at the repository root, and a
file is where the old path failed.

The prompt and the wrapper script go to a per-run temp directory, never the workspace — a
prompt file inside the workspace would dirty it and end up in version control.

Resolution order for the terminal: the user's command template from settings, else the
first installed preset, else ``None`` — and ``None`` is an answer, not an error: the caller
falls back to showing the assembled prompt.
"""

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from dplanner.core.fsio import slugify

# Where a step's worktree lives, under the repository root. A sibling of the `.dplanner`
# pointer file, never inside it — see the module docstring.
WORKTREES_DIR = ".dplanner-worktrees"
BRANCH_PREFIX = "agent/"

# The names the wrapper script reports under, beside the prompt. The exit file holds the
# agent's status, or the word ``closed`` when the terminal was shut on it (the POSIX
# script's HUP trap) — the reader takes any non-number as that.
SHELL_FILE = "shell"
EXIT_FILE = "exit"

# A run name is a branch name's last component, so it keeps to what git's ref rules allow
# everywhere: letters, digits, `.`, `_` and `-`, none of them doubled up or at an end.
RUN_NAME_MAX = 60


def ref_safe(text: str) -> str:
    """``text`` as one component of a git ref: nothing a ref rule refuses, and nothing a
    shell would quote — the run name is written into three script dialects verbatim."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", text)
    safe = re.sub(r"[-.]{2,}", "-", safe).strip("-.")
    return safe[:RUN_NAME_MAX].rstrip("-.")


def run_name(step_key: str, ticket_key: str, title: str) -> str:
    """What a step's worktree and branch are called: ``<key>-<ticket>-<slug>``.

    The key first, so ``git branch`` and the worktrees directory sort by step; the ticket
    beside it when the step has one, so the branch answers the tracker too; the title's
    slug last, for the person reading the list. Every part is optional, and a step with
    none of them is still a run — ``step`` — rather than an empty name.
    """
    parts = [step_key.lower(), ref_safe(ticket_key), slugify(title, fallback="")]
    return ref_safe("-".join(part for part in parts if part)) or "step"


def worktree_path(workdir: Path, name: str) -> Path:
    return workdir / WORKTREES_DIR / name


def branch_name(name: str) -> str:
    return f"{BRANCH_PREFIX}{name}"


@dataclass(frozen=True)
class AgentPreset:
    id: str
    label: str
    # The command the wrapper runs; {prompt} becomes the opening line (quoted),
    # {session} the run's session id and {run_dir} the run's directory (quoted).
    command: str
    # How a run of this agent is picked up again, over the same {session}; "" when the
    # agent has no way to name a session up front.
    resume: str = ""
    # The command texts earlier versions shipped for this preset. The settings store the
    # picked preset's *text*, so a machine that picked it before the command changed
    # holds the old one: read as this preset, it runs the current command and resumes.
    superseded: tuple[str, ...] = ()


# The dropdown's rows, first is the default. Every command opens an *interactive* session
# seeded with the briefing; Claude Code also starts in plan mode, so the developer approves
# the plan before anything changes.
PRESETS: tuple[AgentPreset, ...] = (
    AgentPreset(
        "claude",
        "Claude Code",
        # The run directory is an additional working directory, so reading the briefing
        # asks nothing. `--add-dir` takes a list: an option follows it, never {prompt}.
        "claude --add-dir {run_dir} --permission-mode plan --session-id {session} {prompt}",
        resume="claude --resume {session}",
        superseded=(
            "claude --permission-mode plan --session-id {session} {prompt}",
            "claude --permission-mode plan {prompt}",
            "claude --permission-mode plan",
        ),
    ),
    AgentPreset("codex", "Codex", "codex {prompt}"),
    AgentPreset("opencode", "OpenCode", "opencode --prompt {prompt}"),
)

DEFAULT_AGENT_COMMAND = PRESETS[0].command


def current_command(agent_command: str) -> str:
    """The command a stored setting means: a text a preset shipped earlier is that
    preset's current command, and blank is the default."""
    command = agent_command.strip() or DEFAULT_AGENT_COMMAND
    for preset in PRESETS:
        if command in preset.superseded:
            return preset.command
    return command


def resume_command(agent_command: str, session: str) -> str:
    """How this run is picked up again, or "" for an agent whose resume is unknown.

    Known only for a preset's own command — a custom command may name ``{session}`` for
    an agent whose resume syntax nothing here knows, and a hint that guesses is worse
    than none.
    """
    command = current_command(agent_command)
    preset = next((preset for preset in PRESETS if preset.command == command), None)
    if preset is None or not preset.resume or "{session}" not in command:
        return ""
    return preset.resume.replace("{session}", session)


def new_session() -> str:
    """A run's session id: a UUID, which is what ``claude --session-id`` accepts."""
    return str(uuid.uuid4())


def opening_prompt(prompt_file: Path) -> str:
    """The one line the agent starts with — a pointer at the briefing, never the briefing.

    See the module docstring: the whole briefing in argv was what one agent's ``pkill
    -f`` matched on every other. Nothing the project is about appears in this line.
    """
    return f"Read your briefing in {prompt_file} in full, then follow it."


@dataclass(frozen=True)
class TerminalPreset:
    id: str
    label: str
    platform: str  # "linux" | "darwin" | "win32", as ``sys.platform`` starts.
    # How it opens on the wrapper: {script}, {workdir} and {title} are substituted per token.
    command: str
    # How to tell it is installed: a binary on PATH, ``app:<Name>`` for a macOS bundle,
    # ``env:<VAR>`` for a session fact (inside tmux), "" for always.
    probe: str = ""


# Per platform, in the order Automatic tries them: the platform's own default terminal
# first, so an untouched setting behaves the way the machine does, and tmux last — see
# the module docstring for why it is never first. Every Ghostty row opens a new window:
# `-e` on Linux and Windows is a fresh process, `open -n` on macOS a fresh instance.
TERMINALS: tuple[TerminalPreset, ...] = (
    TerminalPreset("ghostty", "Ghostty", "linux", "ghostty -e {script}", "ghostty"),
    TerminalPreset("kitty", "kitty", "linux", "kitty {script}", "kitty"),
    TerminalPreset("alacritty", "Alacritty", "linux", "alacritty -e {script}", "alacritty"),
    TerminalPreset("foot", "foot", "linux", "foot {script}", "foot"),
    TerminalPreset(
        "gnome-terminal", "GNOME Terminal", "linux", "gnome-terminal -- {script}", "gnome-terminal"
    ),
    TerminalPreset("konsole", "Konsole", "linux", "konsole -e {script}", "konsole"),
    TerminalPreset("xterm", "xterm", "linux", "xterm -e {script}", "xterm"),
    TerminalPreset(
        "tmux", "tmux (new window)", "linux", "tmux new-window -c {workdir} {script}", "env:TMUX"
    ),
    TerminalPreset("terminal", "Terminal", "darwin", "open -a Terminal {script}"),
    TerminalPreset("iterm", "iTerm", "darwin", "open -a iTerm {script}", "app:iTerm"),
    TerminalPreset(
        "ghostty-mac", "Ghostty", "darwin", "open -na Ghostty --args -e {script}", "app:Ghostty"
    ),
    TerminalPreset(
        "tmux-mac",
        "tmux (new window)",
        "darwin",
        "tmux new-window -c {workdir} {script}",
        "env:TMUX",
    ),
    TerminalPreset("wt", "Windows Terminal", "win32", "wt -d {workdir} cmd /k {script}", "wt"),
    TerminalPreset("cmd", "Command Prompt", "win32", 'cmd /c start "" cmd /k {script}'),
    TerminalPreset("ghostty-win", "Ghostty", "win32", "ghostty -e {script}", "ghostty"),
)
MAC_APP_DIRS = ("/Applications", "~/Applications", "/System/Applications/Utilities")


def terminals_for(platform: str = sys.platform) -> tuple[TerminalPreset, ...]:
    return tuple(preset for preset in TERMINALS if platform.startswith(preset.platform))


def is_installed(
    preset: TerminalPreset,
    which: Callable[[str], str | None] = shutil.which,
    env: Mapping[str, str] = os.environ,
    app_exists: Callable[[str], bool] | None = None,
) -> bool:
    """Whether the preset's probe finds it on this machine."""
    probe = preset.probe
    if not probe:
        return True
    if probe.startswith("env:"):
        return bool(env.get(probe[4:]))
    if probe.startswith("app:"):
        return (app_exists or _mac_app_exists)(probe[4:])
    return which(probe) is not None


def _mac_app_exists(name: str) -> bool:
    return any((Path(d).expanduser() / f"{name}.app").is_dir() for d in MAC_APP_DIRS)


@dataclass(frozen=True)
class LaunchFiles:
    directory: Path
    prompt_file: Path
    script: Path
    # What the wrapper reports: the shell's facts on start, the agent's status on exit.
    shell_file: Path
    exit_file: Path
    title: str  # The terminal window's title, as the script sets it.
    session: str = ""  # The run's session id, as the agent command names it.


def new_run_dir() -> Path:
    """A fresh per-run directory for the prompt, the wrapper and any staged assets.

    Resolved, because the agent is handed it as an additional directory and the
    permission check compares a file's resolved path: macOS's temp directory sits under
    ``/var``, a symlink to ``/private/var``, and Windows's Temp is often a short name.
    """
    return Path(tempfile.mkdtemp(prefix="dplanner-agent-")).resolve()


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


def _agent_line(agent_command: str, prompt_expansion: str, session: str, run_dir: str) -> str:
    """The command with the opening prompt, the session and the run directory
    substituted; the prompt is appended when no placeholder names it."""
    command = current_command(agent_command)
    if "{prompt}" not in command:
        command += " {prompt}"
    return (
        command.replace("{prompt}", prompt_expansion)
        .replace("{session}", session)
        .replace("{run_dir}", run_dir)
    )


def window_title(step_title: str) -> str:
    """The terminal's title: plain enough to sit inside any shell's quoting.

    Every character a shell, cmd or AppleScript could read as syntax is dropped, so the
    title is written verbatim into three script dialects and searched for later by the
    focus provider without an escaping rule for each.
    """
    plain = re.sub(r"[^\w .,:()\-]+", "", step_title, flags=re.UNICODE).strip()
    return f"dplanner: {plain[:60] or 'agent'}"


def prepare(
    prompt_text: str,
    workdir: Path,
    agent_command: str = DEFAULT_AGENT_COMMAND,
    worktree: str = "",
    platform: str = sys.platform,
    directory: Path | None = None,
    step_title: str = "",
    session: str = "",
) -> LaunchFiles:
    """Write the prompt and a wrapper script to ``directory``, or a fresh temp directory.

    ``worktree`` is a run name (:func:`run_name`); when non-empty the script prepares
    :func:`worktree_path` on :func:`branch_name` and moves into it before starting — or
    stops with git's reason when it cannot. Empty means the checkout itself. ``session``
    is the run's session id, minted here when not given.
    """
    if directory is None:
        directory = new_run_dir()
    prompt_file = directory / "prompt.md"
    prompt_file.write_text(prompt_text)
    files = LaunchFiles(
        directory=directory,
        prompt_file=prompt_file,
        script=directory / ("run.cmd" if platform.startswith("win") else "run.sh"),
        shell_file=directory / SHELL_FILE,
        exit_file=directory / EXIT_FILE,
        title=window_title(step_title),
        session=session or new_session(),
    )
    if platform.startswith("win"):
        files.script.write_text(_windows_script(files, workdir, agent_command, worktree))
    else:
        files.script.write_text(_posix_script(files, workdir, agent_command, worktree))
        files.script.chmod(0o755)
    return files


def _posix_script(files: LaunchFiles, workdir: Path, agent_command: str, worktree: str) -> str:
    title = shlex.quote(files.title)
    shell, exit_file = shlex.quote(str(files.shell_file)), shlex.quote(str(files.exit_file))
    resume = resume_command(agent_command, files.session)
    lines = [
        "#!/bin/sh",
        # The title first, so the window is findable from its first frame; then the facts.
        f"printf '\\033]0;%s\\007' {title}",
        f"printf 'tty=%s\\npid=%s\\npane=%s\\nprogram=%s\\ntitle=%s\\nsession=%s\\n'"
        f' "$(tty)" "$$" "$TMUX_PANE" "$TERM_PROGRAM" {title} {files.session} > {shell}',
        # The terminal closed on the agent: say so rather than reporting its signal.
        f"trap 'echo closed > {exit_file}; exit 129' HUP",
        f'cd "{workdir}"',
    ]
    if worktree:
        tree = worktree_path(workdir, worktree)
        branch = branch_name(worktree)
        lines += [
            # A registration whose directory is gone would refuse the add; prune is safe.
            "git worktree prune >/dev/null 2>&1",
            'exclude="$(git rev-parse --git-common-dir)/info/exclude"',
            f"grep -qxF '/{WORKTREES_DIR}/' \"$exclude\" 2>/dev/null"
            f" || echo '/{WORKTREES_DIR}/' >> \"$exclude\"",
            f'if [ ! -e "{tree}" ]; then',
            # One attempt, one honest error: reuse the branch when it exists.
            f'  if git show-ref --verify --quiet "refs/heads/{branch}"; then',
            f'    git worktree add "{tree}" "{branch}"',
            "  else",
            f'    git worktree add "{tree}" -b "{branch}"',
            "  fi",
            "fi",
            # A linked worktree is marked by a `.git` file; anything else is not one.
            f'if [ ! -f "{tree}/.git" ]; then',
            f"  printf '\\nCould not prepare the worktree {tree}"
            f" on branch {branch}. Press Enter to close.\\n'",
            "  read -r _",
            f"  echo 1 > {exit_file}",
            "  exit 1",
            "fi",
            f'cd "{tree}"',
        ]
    # In place now: where the agent works, and how to pick this run up again from there.
    lines.append(f"printf 'dir=%s\\n' \"$(pwd)\" >> {shell}")
    if resume:
        lines.append(f'printf \'resume=cd "%s" && {resume}\\n\' "$(pwd)" >> {shell}')
    lines += [
        _agent_line(
            agent_command,
            shlex.quote(opening_prompt(files.prompt_file)),
            files.session,
            shlex.quote(str(files.directory)),
        ),
        "code=$?",
        f'echo "$code" > {exit_file}',
        'if [ "$code" -ne 0 ]; then',
        "  printf '\\nThe agent exited with status %s.\\n' \"$code\"",
    ]
    if resume:
        lines.append(f'  printf \'To pick it up again: cd "%s" && {resume}\\n\' "$(pwd)"')
    lines += [
        "  printf 'Press Enter to close.\\n'",
        "  read -r _",
        "fi",
        'exit "$code"',
    ]
    return "\n".join(lines) + "\n"


def _powershell_quoted(text: str) -> str:
    """A PowerShell single-quoted string: only the quote itself needs doubling."""
    return "'" + text.replace("'", "''") + "'"


def _windows_script(files: LaunchFiles, workdir: Path, agent_command: str, worktree: str) -> str:
    lines = ["@echo off", f"title {files.title}", f'cd /d "{workdir}"']
    if worktree:
        tree = worktree_path(workdir, worktree)
        branch = branch_name(worktree)
        lines += [
            "git worktree prune >nul 2>&1",
            f'if not exist "{tree}" (',
            f'  git show-ref --verify --quiet "refs/heads/{branch}"',
            f'  if errorlevel 1 (git worktree add "{tree}" -b "{branch}")'
            f' else (git worktree add "{tree}" "{branch}")',
            ")",
            f'if not exist "{tree}\\.git" (',
            f"  echo Could not prepare the worktree {tree} on branch {branch}.",
            "  pause",
            f'  >"{files.exit_file}" echo 1',
            "  exit /b 1",
            ")",
            f'cd /d "{tree}"',
        ]
    agent = _agent_line(
        agent_command,
        _powershell_quoted(opening_prompt(files.prompt_file)),
        files.session,
        _powershell_quoted(str(files.directory)),
    )
    resume = resume_command(agent_command, files.session)
    # PowerShell writes the facts (it is the process whose pid outlives the agent's start
    # and dies with the window) and carries the agent's exit status back out to cmd. Only
    # single quotes inside: the whole command sits in cmd's double quotes.
    rows = [
        "'pid=' + $PID",
        f"'title={files.title}'",
        f"'session={files.session}'",
        "'dir=' + $PWD",
    ]
    if resume:
        rows.append(f"'resume=cd /d ' + $PWD + ' && {resume}'")
    facts = (
        f"Set-Content -Path '{files.shell_file}'"
        f" -Value ({' + [Environment]::NewLine + '.join(rows)})"
    )
    lines += [
        f'powershell -Command "{facts}; {agent}; exit $LASTEXITCODE"',
        "set code=%ERRORLEVEL%",
        # Redirection first: `echo 0> file` would read as redirecting handle 0.
        f'>"{files.exit_file}" echo %code%',
        'if not "%code%"=="0" (',
        "  echo The agent exited with status %code%.",
    ]
    if resume:
        lines.append(f"  echo To pick it up again: cd /d %CD% ^&^& {resume}")
    lines += [
        "  pause",
        ")",
    ]
    return "\r\n".join(lines) + "\r\n"


def resolve_command(
    template: str,
    files: LaunchFiles,
    workdir: Path,
    platform: str = sys.platform,
    which: Callable[[str], str | None] = shutil.which,
    env: Mapping[str, str] = os.environ,
    app_exists: Callable[[str], bool] | None = None,
) -> list[str] | None:
    """The command that opens a terminal running the script, or None when nothing can.

    A non-empty ``template`` — from settings — wins outright. Otherwise the first installed
    preset for the platform, then ``$TERMINAL`` on Linux, then None.
    """
    values = {"script": str(files.script), "workdir": str(workdir), "title": files.title}
    if template.strip():
        return _fill(template, values)
    for preset in terminals_for(platform):
        if is_installed(preset, which, env, app_exists):
            return _fill(preset.command, values)
    if platform.startswith("linux"):
        preferred = env.get("TERMINAL", "")
        if preferred and which(preferred):
            return [preferred, "-e", str(files.script)]
    return None


def _fill(template: str, values: Mapping[str, str]) -> list[str] | None:
    """Split like a shell, then substitute per token — a Windows path never meets shlex.

    None for a template naming a placeholder that does not exist: an unusable template
    is the same answer as no terminal, and the caller's fallback delivers the prompt.
    """
    try:
        return [
            token.format_map(values) if "{" in token else token for token in shlex.split(template)
        ]
    except (KeyError, ValueError, IndexError):
        return None


# What an agent CLI's shell carries that says "you are inside a session". The names are
# the ones Claude Code sets in every shell it runs (CLAUDECODE, the parent's session id,
# the child-session flag that turns transcript persistence off, its pid, the effort, the
# agent flag) and the ones it scrubs itself before starting a session that must stand on
# its own (its exec path, the trace id) — read off the 2.1 binary, not guessed — plus
# whatever names a session, a parent, a child or the messaging bridge under the same
# prefix: a 2.1.258 shell also carries CLAUDE_CODE_MESSAGING_SOCKET and _TOKEN, the
# parent's inter-session bridge, and a bridge session id. Not the whole prefix:
# CLAUDE_CONFIG_DIR and CLAUDE_CODE_USE_BEDROCK are the person's configuration, and an
# agent launched without them cannot sign in.
SESSION_MARKERS = (
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_PID",
    "CLAUDE_EFFORT",
    "CLAUDE_CODE_EXECPATH",
    "AI_AGENT",
    "TRACEPARENT",
)
SESSION_MARKER_PREFIX = "CLAUDE_CODE_"
SESSION_MARKER_WORDS = ("SESSION", "PARENT", "CHILD", "MESSAGING")


def is_session_marker(name: str) -> bool:
    if name in SESSION_MARKERS:
        return True
    return name.startswith(SESSION_MARKER_PREFIX) and any(
        word in name for word in SESSION_MARKER_WORDS
    )


def scrubbed_environment(env: Mapping[str, str] = os.environ) -> dict[str, str]:
    """``env`` without the session markers, so the agent starts a session of its own.

    See the module docstring: inside another agent's session markers a nested ``claude``
    is a child session — no transcript, ended with its parent — and every agent launched
    from a window that inherited them died with the agent that had started the window.
    """
    return {name: value for name, value in env.items() if not is_session_marker(name)}


def spawn(command: list[str], workdir: Path) -> None:
    """Start the terminal, detached: its life is the user's, not the application's."""
    subprocess.Popen(
        command,
        cwd=workdir,
        env=scrubbed_environment(),
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
