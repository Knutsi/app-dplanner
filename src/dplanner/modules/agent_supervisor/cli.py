"""``dplanner agent supervise <run>``: the run supervisor, as the process a launch detaches.

It opens no library: a process that lives for hours must not hold the store, and its run's
record is outside the plan's files anyway. It finds the run's project from ``--project-dir``
— what :func:`~.supervisor.start_detached` passes — or else from the library file's rows.
"""

import getpass
import subprocess
import sys
from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from pathlib import Path

from dplanner.cli.command import CliCommand, CliContext, CliError
from dplanner.cli.discovery import find_library
from dplanner.domain import ledger
from dplanner.domain.agents import AgentHarness
from dplanner.domain.library_file import read_library_file, resolve_library_path
from dplanner.domain.workflow import Release
from dplanner.modules.agent_supervisor import limits
from dplanner.modules.agent_supervisor.follow import follow
from dplanner.modules.agent_supervisor.supervisor import (
    PROMPTS,
    RefusedError,
    advance_detached,
    supervise,
)
from dplanner.modules.agent_supervisor.takeover import HaltPass, take_over


def _configure(parser: ArgumentParser) -> None:
    parser.add_argument("run", help="the run's id, as its ledger record names it")
    parser.add_argument("--project-dir", help="the project directory whose ledger holds it")
    parser.add_argument(
        "--prompt", choices=tuple(PROMPTS), default="", help="why a parked run resumes"
    )
    parser.add_argument("--text", default="", help="the words it resumes with: the answer")


def _configure_run(parser: ArgumentParser) -> None:
    parser.add_argument("run", help="the run's id, as its ledger record names it")
    parser.add_argument("--project-dir", help="the project directory whose ledger holds it")


def commands(
    *,
    harnesses: tuple[AgentHarness, ...],
    release: Callable[[Path, Release], bool],
    halt: HaltPass,
) -> list[CliCommand]:
    def run(context: CliContext, args: Namespace) -> int:
        project_dir = _project_dir(args)
        library = resolve_library_path(args.library)
        try:
            said = supervise(
                project_dir,
                args.run,
                harnesses,
                prompt=args.prompt,
                text=args.text,
                library=library,
                # A playbook's stage that ended done hands its pass on, in a process of its own.
                advance=lambda _dir, record: advance_detached(record.step, library=library),
            )
        except RefusedError as error:
            raise CliError(str(error)) from error
        context.report({"run": args.run, "said": said}, said)
        return 0

    def follow_run(context: CliContext, args: Namespace) -> int:
        project_dir = _project_dir(args)
        try:
            follow(project_dir, args.run, harnesses, out=lambda line: print(line, flush=True))
        except RefusedError as error:
            raise CliError(str(error)) from error
        except KeyboardInterrupt:
            return 0  # The follower let go; the run goes on.
        if sys.stdin.isatty():
            input("Press Enter to close.")
        return 0

    def open_session(context: CliContext, args: Namespace) -> int:
        """Take the run's session from its pass and its squad (``take_over``), and run the
        harness's own resume in the directory it worked in, for as long as the person keeps it."""
        project_dir = _project_dir(args)
        try:
            argv, directory = take_over(
                project_dir, args.run, getpass.getuser(), harnesses, halt=halt, release=release
            )
        except RefusedError as error:
            raise CliError(str(error)) from error
        print(f"Opening {' '.join(argv)} in {directory}", flush=True)
        try:
            return subprocess.run(argv, cwd=directory, check=False).returncode
        except OSError as error:
            raise CliError(f"{argv[0]} could not run: {error}") from error

    def show_limits(context: CliContext, args: Namespace) -> int:
        threshold = limits.hold_at()
        known = limits.accounts()
        rows, lines = [], [f"new headless launches wait at {threshold:.0%} of a window"]
        for harness in harnesses:
            key = limits.account_of(harness)
            account = known.get(key, limits.Account(key))
            held = limits.hold(key, harness.label, threshold)
            windows = ", ".join(
                f"{w.name.replace('_', '-')} {w.used:.0%}"
                + (f" until {limits.clock(w.resets)}" if w.resets else "")
                for w in account.windows
            )
            rows.append({"harness": harness.id, "windows": windows, "held": held})
            lines.append(f"{harness.label}: {windows or 'nothing reported yet'}")
            if held:
                lines.append(f"  held — {held}")
        context.report({"hold_at": threshold, "accounts": rows}, "\n".join(lines))
        return 0

    return [
        CliCommand(
            path=("agent", "follow"),
            summary="watch a headless run's turns as they stream, read-only, until it is over",
            run=follow_run,
            configure=_configure_run,
            needs_library=False,
            examples=("dplanner agent follow 20261007T101500Z-9c1e44ab",),
        ),
        CliCommand(
            path=("agent", "open-session"),
            summary="take a parked or ended headless run's session into this terminal",
            run=open_session,
            configure=_configure_run,
            needs_library=False,
            examples=("dplanner agent open-session 20261007T101500Z-9c1e44ab",),
        ),
        CliCommand(
            path=("agent", "limits"),
            summary="each agent account's last-known usage, and whether launches wait on it",
            run=show_limits,
            needs_library=False,
            examples=("dplanner agent limits",),
        ),
        CliCommand(
            path=("agent", "supervise"),
            summary="drive a headless run turn by turn until it is over or parked",
            run=run,
            configure=_configure,
            needs_library=False,
            examples=(
                "dplanner agent supervise 20261007T101500Z-9c1e44ab",
                "dplanner agent supervise <run> --prompt answer --text 'Keep both'",
            ),
        ),
    ]


def _project_dir(args: Namespace) -> Path:
    if args.project_dir:
        return Path(args.project_dir)
    for directory in read_library_file(find_library(args.library)).projects:
        if ledger.find(directory, args.run) is not None:
            return directory
    raise CliError(f"no project in the library has a run {args.run}")
