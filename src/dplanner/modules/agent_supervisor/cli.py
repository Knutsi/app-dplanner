"""``dplanner agent supervise <run>``: the run supervisor, as the process a launch detaches.

It opens no library: a process that lives for hours must not hold the store, and its run's
record is outside the plan's files anyway. It finds the run's project from ``--project-dir``
— what :func:`~.supervisor.start_detached` passes — or else from the library file's rows.
"""

from argparse import ArgumentParser, Namespace
from pathlib import Path

from dplanner.cli.command import CliCommand, CliContext, CliError
from dplanner.cli.discovery import find_library
from dplanner.domain import ledger
from dplanner.domain.agents import AgentHarness
from dplanner.domain.library_file import read_library_file, resolve_library_path
from dplanner.modules.agent_supervisor import limits
from dplanner.modules.agent_supervisor.supervisor import PROMPTS, RefusedError, supervise


def _configure(parser: ArgumentParser) -> None:
    parser.add_argument("run", help="the run's id, as its ledger record names it")
    parser.add_argument("--project-dir", help="the project directory whose ledger holds it")
    parser.add_argument(
        "--prompt", choices=tuple(PROMPTS), default="", help="why a parked run resumes"
    )
    parser.add_argument("--text", default="", help="the words it resumes with: the answer")


def commands(*, harnesses: tuple[AgentHarness, ...]) -> list[CliCommand]:
    def run(context: CliContext, args: Namespace) -> int:
        project_dir = _project_dir(args)
        try:
            said = supervise(
                project_dir,
                args.run,
                harnesses,
                prompt=args.prompt,
                text=args.text,
                library=resolve_library_path(args.library),
            )
        except RefusedError as error:
            raise CliError(str(error)) from error
        context.report({"run": args.run, "said": said}, said)
        return 0

    def show_limits(context: CliContext, args: Namespace) -> int:
        threshold = limits.hold_at()
        known = limits.accounts()
        rows, lines = [], [f"new headless launches wait at {threshold:.0%} of a window"]
        for harness in harnesses:
            account = known.get(harness.id, limits.Account(harness.id))
            held = limits.hold(harness.id, harness.label, threshold)
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
