"""Launching an agent in a terminal, on whatever platform this is.

The launch is a **peer process, not a task**: the user owns the terminal from the moment it
opens, so nothing here reports to the task centre — tracking it would promise cancel and
progress the application cannot honestly deliver. The spawn is detached
(``start_new_session``) so closing DPlanner never takes the agent down with it. The session
is interactive on purpose — the developer is the human in the loop, and the agent's opening
prompt is the step's briefing, not its orders.

**Which agent runs is a harness, not a lookup.** Every function here that needs to know
an agent CLI takes the tuple of :class:`~dplanner.domain.agents.AgentHarness` the
composition root assembles from the provider modules (``agent_claude``, ``agent_codex``,
``agent_opencode``): each carries a working invocation, so the settings page offers a
dropdown that pre-fills an editable command instead of a bare field the user would have
to research, and the first harness is the default. ``{prompt}`` in the command becomes
the opening line (quoted); a command without the placeholder gets it appended.

**Which terminal opens is a table.** ``TERMINALS`` is one table of the known terminals
and multiplexers per platform — Ghostty, iTerm, Terminal and WezTerm on macOS; Ghostty,
Windows Terminal and the Command Prompt on Windows; Ghostty, kitty, Alacritty, foot,
GNOME Terminal, Konsole, xterm and WezTerm on Linux; and the multiplexers, herdr, zellij
and tmux, which add a pane to something already running rather than opening a window —
each with the command that opens it on the wrapper script and a probe saying whether it
is installed. The settings dropdown lists the table and pre-fills the editable template;
*Automatic* is the first installed row, which is the platform's own default terminal.
One table, two readers, so the dropdown can never offer a terminal the launch would not
find.

**A multiplexer that needs two calls writes them as one template.** herdr creates a
workspace with one call that prints the pane it made, and runs a command into that pane
with a second. Its row is ``herdr workspace create … && herdr pane run {pane} --command
{script}``: :func:`spawn` runs the stages in turn, and ``{pane}`` in a later stage is the
pane the earlier one printed (a ``pane_id`` in its JSON, else its output). The ``&&`` is
what a person would type, and it keeps a two-call terminal a row like any other.

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
with every harness's shell markers taken out (:func:`scrubbed_environment`): with them in
place a nested ``claude`` makes itself a *child* of the session that set them — no
transcript of its own, ended when the parent's turn ends — which is how a DPlanner started
from an agent's shell took every agent it launched down with it. ``entry.py`` refuses to
open a window from such a shell; the scrub is the second line, for a window that got its
environment some other way. Which names mark a shell is each harness's own fact
(``agent_claude/harness.py`` has the list read off the binary); a harness that names its
session up front (``{session}``, minted per launch) is one whose run can be picked up
again by that id, and one that mints its own id is found afterwards by its ``report``.

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

from dplanner.cli.discovery import PROJECT_ENV
from dplanner.core.fsio import slugify

# Where a step's worktree lives, under the repository root: a sibling of the `.dplanner`
# index file, never inside it — see the module docstring. Declared beside that file, since
# the plan repository scan has to know to skip it.
from dplanner.core.storage.pointer import WORKTREES_DIR as WORKTREES_DIR
from dplanner.domain.agents import AgentHarness, harness_for_command

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


def current_command(agent_command: str, harnesses: tuple[AgentHarness, ...]) -> str:
    """The command a stored setting means: a text a harness shipped earlier is that
    harness's current command, and blank is the first harness's."""
    command = agent_command.strip()
    if not command:
        return harnesses[0].command if harnesses else ""
    harness = harness_for_command(harnesses, command)
    return harness.command if harness is not None else command


def harness_of(agent_command: str, harnesses: tuple[AgentHarness, ...]) -> AgentHarness | None:
    """The harness a command runs, or None for a custom command nothing here knows.

    Known only for a harness's own command text — a custom command may name ``{session}``
    for an agent whose resume syntax nothing here knows, and a hint that guesses is worse
    than none.
    """
    return harness_for_command(harnesses, current_command(agent_command, harnesses))


def resume_command(agent_command: str, session: str, harnesses: tuple[AgentHarness, ...]) -> str:
    """How this run is picked up again, or "" for an agent whose resume is unknown or
    whose session is not named up front."""
    harness = harness_of(agent_command, harnesses)
    if harness is None or not harness.resume or not harness.names_session:
        return ""
    return harness.resume.replace("{session}", session)


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
    # A multiplexer adds a pane to something already running rather than opening a
    # window of its own — which is what makes it the right home for several agents
    # launched at once, and what keeps it out of Automatic's first choices.
    multiplexer: bool = False


# Per platform, in the order Automatic tries them: the platform's own default terminal
# first, so an untouched setting behaves the way the machine does, and tmux last — see
# the module docstring for why it is never first. Every Ghostty row opens a new window:
# `-e` on Linux and Windows is a fresh process, `open -n` on macOS a fresh instance.
HERDR_COMMAND = (
    "herdr workspace create --cwd {workdir} --label {title} --no-focus"
    " && herdr pane run {pane} --command {script}"
)
ZELLIJ_COMMAND = "zellij run --name {title} --cwd {workdir} --close-on-exit -- {script}"
TMUX_COMMAND = "tmux new-window -c {workdir} {script}"


def _multiplexers(platform: str, script: str = "{script}") -> tuple[TerminalPreset, ...]:
    """The multiplexer rows one platform gets, in Automatic's order: herdr, which is
    built for exactly this, then zellij and tmux, which only answer inside a session."""
    suffix = "" if platform == "linux" else f"-{platform[:3]}"
    rows = [
        TerminalPreset(
            f"herdr{suffix}",
            "herdr",
            platform,
            HERDR_COMMAND.replace("{script}", script),
            "herdr",
            multiplexer=True,
        )
    ]
    if platform != "win32":
        rows += [
            TerminalPreset(
                f"zellij{suffix}",
                "zellij (new pane)",
                platform,
                ZELLIJ_COMMAND,
                "env:ZELLIJ",
                multiplexer=True,
            ),
            TerminalPreset(
                f"tmux{suffix}",
                "tmux (new window)",
                platform,
                TMUX_COMMAND,
                "env:TMUX",
                multiplexer=True,
            ),
        ]
    return tuple(rows)


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
        "wezterm", "WezTerm", "linux", "wezterm start --cwd {workdir} -- {script}", "wezterm"
    ),
    *_multiplexers("linux"),
    TerminalPreset("terminal", "Terminal", "darwin", "open -a Terminal {script}"),
    TerminalPreset("iterm", "iTerm", "darwin", "open -a iTerm {script}", "app:iTerm"),
    TerminalPreset(
        "ghostty-mac", "Ghostty", "darwin", "open -na Ghostty --args -e {script}", "app:Ghostty"
    ),
    TerminalPreset(
        "wezterm-mac", "WezTerm", "darwin", "wezterm start --cwd {workdir} -- {script}", "wezterm"
    ),
    *_multiplexers("darwin"),
    TerminalPreset("wt", "Windows Terminal", "win32", "wt -d {workdir} cmd /k {script}", "wt"),
    TerminalPreset("cmd", "Command Prompt", "win32", 'cmd /c start "" cmd /k {script}'),
    TerminalPreset("ghostty-win", "Ghostty", "win32", "ghostty -e {script}", "ghostty"),
    *_multiplexers("win32"),
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


def _agent_line(
    agent_command: str,
    prompt_expansion: str,
    session: str,
    run_dir: str,
    harnesses: tuple[AgentHarness, ...],
) -> str:
    """The command with the opening prompt, the session and the run directory
    substituted; the prompt is appended when no placeholder names it."""
    command = current_command(agent_command, harnesses)
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
    agent_command: str = "",
    worktree: str = "",
    platform: str = sys.platform,
    directory: Path | None = None,
    step_title: str = "",
    session: str = "",
    project_id: str = "",
    harnesses: tuple[AgentHarness, ...] = (),
) -> LaunchFiles:
    """Write the prompt and a wrapper script to ``directory``, or a fresh temp directory.

    ``worktree`` is a run name (:func:`run_name`); when non-empty the script prepares
    :func:`worktree_path` on :func:`branch_name` and moves into it before starting — or
    stops with git's reason when it cannot. Empty means the checkout itself. ``session``
    is the run's session id, minted here when not given. ``project_id`` is exported into
    the shell as ``$DPLANNER_PROJECT``, so every ``dplanner`` call the agent makes is
    scoped to its project — two projects may plan the code repository it works in.
    ``harnesses`` is what ``agent_command`` is read against: blank means the first one.
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
        files.script.write_text(
            _windows_script(files, workdir, agent_command, worktree, project_id, harnesses)
        )
    else:
        files.script.write_text(
            _posix_script(files, workdir, agent_command, worktree, project_id, harnesses)
        )
        files.script.chmod(0o755)
    return files


def _posix_script(
    files: LaunchFiles,
    workdir: Path,
    agent_command: str,
    worktree: str,
    project_id: str = "",
    harnesses: tuple[AgentHarness, ...] = (),
) -> str:
    title = shlex.quote(files.title)
    shell, exit_file = shlex.quote(str(files.shell_file)), shlex.quote(str(files.exit_file))
    resume = resume_command(agent_command, files.session, harnesses)
    lines = [
        "#!/bin/sh",
        # The title first, so the window is findable from its first frame; then the facts.
        f"printf '\\033]0;%s\\007' {title}",
        f"printf 'tty=%s\\npid=%s\\npane=%s\\nprogram=%s\\ntitle=%s\\nsession=%s\\n'"
        f' "$(tty)" "$$" "$TMUX_PANE" "$TERM_PROGRAM" {title} {files.session} > {shell}',
        # The multiplexer's own name for this pane, when one hosts it — what a later
        # Show Agent Terminal selects. Each variable is empty outside its multiplexer.
        "printf 'herdr_workspace=%s\\nherdr_tab=%s\\nwezterm_pane=%s\\n'"
        f' "$HERDR_WORKSPACE_ID" "$HERDR_TAB_ID" "$WEZTERM_PANE" >> {shell}',
        # The terminal closed on the agent: say so rather than reporting its signal.
        f"trap 'echo closed > {exit_file}; exit 129' HUP",
        f'cd "{workdir}"',
    ]
    if project_id:
        lines.append(f"export {PROJECT_ENV}={shlex.quote(project_id)}")
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
            harnesses,
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


def _windows_script(
    files: LaunchFiles,
    workdir: Path,
    agent_command: str,
    worktree: str,
    project_id: str = "",
    harnesses: tuple[AgentHarness, ...] = (),
) -> str:
    lines = ["@echo off", f"title {files.title}", f'cd /d "{workdir}"']
    if project_id:
        lines.append(f"set {PROJECT_ENV}={project_id}")
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
        harnesses,
    )
    resume = resume_command(agent_command, files.session, harnesses)
    # PowerShell writes the facts (it is the process whose pid outlives the agent's start
    # and dies with the window) and carries the agent's exit status back out to cmd. Only
    # single quotes inside: the whole command sits in cmd's double quotes.
    rows = [
        "'pid=' + $PID",
        f"'title={files.title}'",
        f"'session={files.session}'",
        "'herdr_workspace=' + $env:HERDR_WORKSPACE_ID",
        "'herdr_tab=' + $env:HERDR_TAB_ID",
        "'wezterm_pane=' + $env:WEZTERM_PANE",
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


def template_refusal(
    template: str,
    platform: str = sys.platform,
    which: Callable[[str], str | None] = shutil.which,
    env: Mapping[str, str] = os.environ,
    app_exists: Callable[[str], bool] | None = None,
) -> str:
    """Why a profile's terminal template cannot open anything right now, or "".

    A template that is a known row's command is judged by that row's probe — *herdr is
    not installed*, *not inside a tmux session* — before any step is asked about. A
    custom template is trusted, and so is Automatic: with nothing installed the launch
    falls back to handing the prompt over, which is an answer and not a refusal.
    """
    text = template.strip()
    if not text:
        return ""
    row = next((row for row in terminals_for(platform) if row.command == text), None)
    if row is None or is_installed(row, which, env, app_exists):
        return ""
    if row.probe.startswith("env:"):
        return f"not inside a {row.label.split(' ')[0]} session ({row.probe[4:]} is not set)"
    return f"{row.label} is not installed"


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
    values = {
        "script": str(files.script),
        "workdir": str(workdir),
        "title": files.title,
        "pane": "{pane}",  # Filled by :func:`spawn`, from the stage before it.
    }
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


def is_session_marker(name: str, harnesses: tuple[AgentHarness, ...]) -> bool:
    """Whether an environment variable of this name says "inside an agent's session" —
    for any of the harnesses this build knows."""
    return any(harness.marks(name) for harness in harnesses)


def scrubbed_environment(
    env: Mapping[str, str], harnesses: tuple[AgentHarness, ...]
) -> dict[str, str]:
    """``env`` without any harness's session markers, so the agent starts a session of
    its own.

    See the module docstring: inside another agent's session markers a nested ``claude``
    is a child session — no transcript, ended with its parent — and every agent launched
    from a window that inherited them died with the agent that had started the window.
    """
    return {name: value for name, value in env.items() if not is_session_marker(name, harnesses)}


STAGE_SEPARATOR = "&&"
_PANE_ID = re.compile(r'"pane_id"\s*:\s*"([^"]+)"')
STAGE_TIMEOUT_S = 20


def stages(command: list[str]) -> list[list[str]]:
    """The command split at its ``&&`` tokens: one stage per call the terminal needs."""
    result: list[list[str]] = [[]]
    for token in command:
        if token == STAGE_SEPARATOR:
            result.append([])
        else:
            result[-1].append(token)
    return [stage for stage in result if stage]


def pane_from(output: str) -> str:
    """The pane a stage printed: a ``pane_id`` in its JSON, else its last line."""
    match = _PANE_ID.search(output)
    if match:
        return match.group(1)
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def spawn(command: list[str], workdir: Path, harnesses: tuple[AgentHarness, ...] = ()) -> str:
    """Start the terminal, detached: its life is the user's, not the application's.

    A one-stage command is the terminal itself and is left running. A staged command
    (``&&``) is a multiplexer's protocol — each stage is run to completion and the pane
    it printed fills ``{pane}`` in the next — and the reason is returned when a stage
    fails, "" otherwise: a workspace that could not be created is no shell at all, and
    the caller must not record a run for it.
    """
    env = scrubbed_environment(os.environ, harnesses)
    staged = stages(command)
    if len(staged) <= 1:
        subprocess.Popen(
            command,
            cwd=workdir,
            env=env,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return ""
    pane = ""
    for stage in staged:
        argv = [token.replace("{pane}", pane) for token in stage]
        try:
            done = subprocess.run(
                argv,
                cwd=workdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=STAGE_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return f"{argv[0]} could not run: {error}"
        if done.returncode != 0:
            detail = (done.stderr or done.stdout).strip().splitlines()
            why = detail[-1] if detail else f"exit {done.returncode}"
            return f"{' '.join(argv[:3])} failed: {why}"
        pane = pane_from(done.stdout) or pane
    return ""
