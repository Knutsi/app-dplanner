"""Getting DPlanner onto this machine, as one act.

Three things have to be in place before DPlanner is usable: the ``dplanner`` command on
PATH, a launcher in the applications menu, and the agent skill an agent reads. Each had its
own verb, and two of them a dialog of their own, and they drifted — a machine with the
command and a skill from a build three weeks old is the ordinary case, and no surface could
see it, because no surface asked more than one of the three questions. So there is
one reader that answers for all three (:func:`items`), one writer that brings all three up to
date (:func:`apply`), and the verbs ``install all``, ``install status`` and ``install
remove`` over them. ``desktop …`` and ``skill …`` stay exactly as they were: the pieces the
one act is made of, for when one of them is what you mean.

:func:`items` **runs no subprocess** — the window refreshes on it and the checklist will
probe with it, and neither can afford a process. :func:`apply` may, because it is called
from a ``TaskRunner`` body or from a CLI run, and it never stops at a failure: each piece
reports its own line, so a machine ends up as current as it can be rather than as current as
its first problem allowed.

Two rules keep the command safe, and both are about not shadowing an install somebody else
made. **A worktree build never repoints it** — ``uv tool install --editable`` pointing into
a branch's scratch checkout breaks when the worktree goes, and every agent now works in one.
**A ``dplanner`` uv did not install is left alone** — a pipx install, a system package or a
venv is somebody's decision, and a second copy beside it is a puzzle nobody asked for. In
both cases the row says so; nothing is done silently.

Removing takes out the launcher and the skill and leaves the command, because ``uv tool
uninstall dplanner`` uninstalls the program that is running it. The command's line names
that command instead, composed from the same argv the installer would use.
"""

import shlex
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from dplanner.cli.command import CliCommand, CliRegistry
from dplanner.cli.desktop import (
    Launcher,
    Runner,
    launcher_for,
    missing_executable_hint,
    normalised,
    window_executable,
)
from dplanner.cli.desktop import status as launcher_status
from dplanner.cli.main import PROG
from dplanner.cli.skill import install as write_skill
from dplanner.cli.skill import status as skill_status
from dplanner.cli.skill import target_dir
from dplanner.cli.skill import uninstall as remove_skill
from dplanner.core.storage.locations import main_checkout
from dplanner.domain.aspects import AspectSpec
from dplanner.identity import APP_NAME

COMMAND = "command"
LAUNCHER = "launcher"
SKILL = "skill"

LABELS = {
    COMMAND: f"{PROG} command",
    LAUNCHER: "Desktop launcher",
    SKILL: "Agent skill",
}

# Worst first: what the one button and the one summary read from.
_SEVERITY = ("missing", "stale", "installed")

Which = Callable[[str], str | None]


@dataclass(frozen=True)
class Item:
    """One of the three, as every surface reads it."""

    id: str
    label: str
    state: str  # "installed", "stale" or "missing" — desktop.py's and skill.py's word.
    where: Path | None  # Where it is, or where it would go.
    note: str  # The line under the label: what it opens, why it is stale, what is missing.


@dataclass(frozen=True)
class Outcome:
    """What happened to one of the three when the one act ran."""

    id: str
    ok: bool
    line: str


# -- the commands uv is asked to run ----------------------------------------------------------


def _run(command: list[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _which(name: str) -> str | None:
    return shutil.which(name)


def install_command() -> list[str]:
    """The command that puts ``dplanner`` on PATH, as argv.

    From a source checkout that is an editable tool install, which tracks the checkout
    instead of freezing a copy.
    """
    root = Path(__file__).resolve().parents[3]
    if (root / "pyproject.toml").is_file():
        return ["uv", "tool", "install", "--editable", str(root)]
    return ["uv", "tool", "install", PROG]


def tool_bin_command() -> list[str]:
    """The command that prints where ``uv tool install`` puts executables, as argv.

    Asked once per act, before anything is written: it says which ``dplanner`` uv owns, and
    which ``dpw`` the desktop launcher should open — the one beside the installed command
    rather than the one beside whatever build is running, a checkout's ``.venv`` often
    enough."""
    return ["uv", "tool", "dir", "--bin"]


def uninstall_command() -> list[str]:
    """The command that takes the installed ``dplanner`` tool back out, as argv."""
    return ["uv", "tool", "uninstall", PROG]


def path_hint() -> str | None:
    """None when ``dplanner`` resolves on PATH; otherwise the command that puts it there.

    The skill tells agents to run ``dplanner``, so a machine where that command does not
    resolve has half an install.
    """
    if _which(PROG) is not None:
        return None
    return shlex.join(install_command())


def worktree_warning(root: Path | None = None) -> str | None:
    """A caution when the editable install would track a git worktree, else None.

    A worktree is often temporary — a branch's scratch checkout — and an editable install
    pointing into one breaks the moment the worktree is removed. The warning names the main
    checkout when the worktree's ``.git`` file says where it is.
    """
    if root is None:
        root = Path(__file__).resolve().parents[3]
    gitfile = root / ".git"
    if not gitfile.is_file():  # A directory means a main checkout; a file marks a worktree.
        return None
    message = (
        f"This build runs from a git worktree ({root}) — the installed command would "
        "break when the worktree is removed."
    )
    main = main_checkout(root)
    if main != root:
        message += (
            f" Consider installing from the main checkout:  uv tool install --editable {main}"
        )
    return message


def _command_item(which: Which) -> Item:
    """The command is ``installed`` or ``missing``: whether the one on PATH came from this
    build cannot be told without running it, and a status read may not."""
    found = which(PROG)
    if found is None:
        return Item(
            COMMAND,
            LABELS[COMMAND],
            "missing",
            None,
            f"Not on PATH — agents and terminals cannot run {PROG}.",
        )
    return Item(
        COMMAND,
        LABELS[COMMAND],
        "installed",
        Path(found),
        f"Resolves at {found} — installing again refreshes it.",
    )


def _launcher_item(launcher: Launcher, executable: Path | None) -> Item:
    state = launcher_status(launcher, executable)
    target = launcher.target()
    if state == "missing":
        note = f"{APP_NAME} is not in this desktop's applications menu."
    elif state == "stale":
        note = f"Opens {target}, and this build's is {executable or 'nowhere to be found'}."
    else:
        note = f"Opens {target}."
    return Item(LAUNCHER, LABELS[LAUNCHER], state, launcher.path, note)


def _skill_item(files: dict[str, str], directory: Path) -> Item:
    state = skill_status(files, directory)
    if state == "missing":
        note = "Not installed — an agent has nothing telling it how to drive DPlanner."
    elif state == "stale":
        note = "Installed from another build — updating rewrites it from this one."
    else:
        note = "Matches this build."
    return Item(SKILL, LABELS[SKILL], state, directory, note)


def items(
    files: dict[str, str],
    *,
    launcher: Launcher | None = None,
    directory: Path | None = None,
    which: Which | None = None,
) -> tuple[Item, ...]:
    """What this machine has of DPlanner, in install order. No subprocess runs."""
    which = which if which is not None else _which
    launcher = launcher if launcher is not None else launcher_for()
    directory = directory if directory is not None else target_dir(user=True)
    return (
        _command_item(which),
        _launcher_item(launcher, window_executable()),
        _skill_item(files, directory),
    )


def summary(read: Sequence[Item]) -> str:
    """The worst of the three — what one button and one line answer for all of them."""
    for state in _SEVERITY:
        if any(item.state == state for item in read):
            return state
    return "installed"


def bin_dir(run: Runner | None = None) -> Path | None:
    """Where ``uv tool install`` puts executables, or None when uv cannot say — uv's own
    answer rather than a guess at its directory layout."""
    run = run if run is not None else _run
    try:
        result = run(tool_bin_command())
    except OSError:  # No uv on this machine.
        return None
    said = result.stdout.strip()
    # uv answers with a literal `..` (`~/.local/share/../bin`); `command_refusal` compares
    # this against the directory `which` found the command in.
    return normalised(Path(said)) if result.returncode == 0 and said else None


def command_refusal(where: Path | None, uv_bin: Path | None) -> str | None:
    """Why the command must be left alone, or None when it is ours to write.

    Both cases are somebody else's install we would shadow: a temporary worktree the
    editable install would point into, and a ``dplanner`` uv never put there.
    """
    warning = worktree_warning()
    if warning is not None:
        return f"Left alone — {warning[0].lower()}{warning[1:]}"
    if where is None:  # Nothing on PATH: nothing to shadow.
        return None
    if uv_bin is not None and where.parent == uv_bin:
        return None
    return (
        f"Left alone — {where} was not installed by uv, and installing beside it would "
        f"leave two. Take it out first, or update it the way it was installed."
    )


def _install_command_piece(uv_bin: Path | None, which: Which, run: Runner) -> Outcome:
    found = which(PROG)
    refusal = command_refusal(Path(found) if found else None, uv_bin)
    if refusal is not None:
        return Outcome(COMMAND, True, f"{LABELS[COMMAND]}: {refusal}")
    argv = install_command()
    try:
        result = run(argv)
    except OSError as error:
        return Outcome(COMMAND, False, f"{LABELS[COMMAND]}: {shlex.join(argv)} — {error}")
    said = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        # uv's own words when it has any; otherwise the command and what it exited with.
        why = said or f"{shlex.join(argv)} exited with {result.returncode}"
        return Outcome(COMMAND, False, f"{LABELS[COMMAND]}: {why}")
    lines = [f"{LABELS[COMMAND]}: installed", said]
    return Outcome(COMMAND, True, "\n".join(line for line in lines if line))


def _install_launcher_piece(launcher: Launcher, uv_bin: Path | None) -> Outcome:
    executable = window_executable([uv_bin] if uv_bin is not None else [])
    if executable is None:
        return Outcome(LAUNCHER, False, f"{LABELS[LAUNCHER]}: {missing_executable_hint()}")
    try:
        launcher.write(executable)
    except OSError as error:
        return Outcome(
            LAUNCHER, False, f"{LABELS[LAUNCHER]}: could not write {launcher.path} — {error}"
        )
    return Outcome(LAUNCHER, True, f"{LABELS[LAUNCHER]}: {launcher.path}, opening {executable}")


def _install_skill_piece(files: dict[str, str], directory: Path) -> Outcome:
    try:
        write_skill(files, directory)
    except OSError as error:
        return Outcome(SKILL, False, f"{LABELS[SKILL]}: could not write {directory} — {error}")
    return Outcome(SKILL, True, f"{LABELS[SKILL]}: {directory}")


def apply(
    files: dict[str, str],
    *,
    launcher: Launcher | None = None,
    directory: Path | None = None,
    run: Runner | None = None,
    which: Which | None = None,
) -> list[Outcome]:
    """Bring all three up to date, in install order, reporting each rather than stopping.

    The command first: it is what puts ``dpw`` where the launcher will point.
    """
    run = run if run is not None else _run
    which = which if which is not None else _which
    launcher = launcher if launcher is not None else launcher_for()
    directory = directory if directory is not None else target_dir(user=True)
    uv_bin = bin_dir(run)
    return [
        _install_command_piece(uv_bin, which, run),
        _install_launcher_piece(launcher, uv_bin),
        _install_skill_piece(files, directory),
    ]


def remove(
    files: dict[str, str],
    *,
    launcher: Launcher | None = None,
    directory: Path | None = None,
) -> list[Outcome]:
    """Take out the launcher and the skill; name the command's own uninstall, never run it.

    ``uv tool uninstall dplanner`` uninstalls the program running the verb — a deliberate act
    of its own, and one line the reader can copy.
    """
    launcher = launcher if launcher is not None else launcher_for()
    directory = directory if directory is not None else target_dir(user=True)
    removed_launcher = launcher.remove()
    removed_files = remove_skill(files, directory)
    return [
        Outcome(
            COMMAND,
            True,
            f"{LABELS[COMMAND]}: left alone — {shlex.join(uninstall_command())} takes it out",
        ),
        Outcome(
            LAUNCHER,
            True,
            f"{LABELS[LAUNCHER]}: {launcher.path}"
            if removed_launcher
            else f"{LABELS[LAUNCHER]}: nothing installed",
        ),
        Outcome(
            SKILL,
            True,
            f"{LABELS[SKILL]}: {directory}"
            if removed_files
            else f"{LABELS[SKILL]}: nothing installed",
        ),
    ]


def report_lines(outcomes: Sequence[Outcome]) -> str:
    return "\n".join(outcome.line for outcome in outcomes)


def commands(aspects: Sequence[AspectSpec], registry: CliRegistry) -> list[CliCommand]:
    """The one act's verbs: all, status, remove.

    They take the registry the skill is rendered from, the way ``skill``'s verbs do — the
    composition root closes the loop and nothing here goes looking.
    """
    from argparse import Namespace

    from dplanner.cli.command import CliContext
    from dplanner.cli.skill import generate

    def files() -> dict[str, str]:
        return generate(registry, aspects)

    def do_all(context: CliContext, _args: Namespace) -> int:
        outcomes = apply(files())
        context.report(
            {
                "installed": [
                    {"item": outcome.id, "ok": outcome.ok, "said": outcome.line}
                    for outcome in outcomes
                ]
            },
            report_lines(outcomes),
        )
        return 0 if all(outcome.ok for outcome in outcomes) else 1

    def do_status(context: CliContext, _args: Namespace) -> int:
        read = items(files())
        context.report(
            {
                "status": summary(read),
                "items": [
                    {
                        "item": item.id,
                        "status": item.state,
                        "where": None if item.where is None else str(item.where),
                        "note": item.note,
                    }
                    for item in read
                ],
            },
            "\n".join(f"{item.state:<10} {item.label}\n           {item.note}" for item in read),
        )
        return 0

    def do_remove(context: CliContext, _args: Namespace) -> int:
        outcomes = remove(files())
        context.report(
            {
                "removed": [
                    {"item": outcome.id, "ok": outcome.ok, "said": outcome.line}
                    for outcome in outcomes
                ]
            },
            report_lines(outcomes),
        )
        return 0

    return [
        CliCommand(
            path=("install", "all"),
            summary=(
                f"Install or update the {PROG} command, the desktop launcher and the agent skill."
            ),
            run=do_all,
            needs_library=False,
            examples=(f"{PROG} install all",),
        ),
        CliCommand(
            path=("install", "status"),
            summary="What this machine has of DPlanner: the command, the launcher and the skill.",
            run=do_status,
            needs_library=False,
            examples=(f"{PROG} install status", f"{PROG} install status --json"),
        ),
        CliCommand(
            path=("install", "remove"),
            summary="Take out the desktop launcher and the agent skill.",
            run=do_remove,
            needs_library=False,
            examples=(f"{PROG} install remove",),
        ),
    ]
