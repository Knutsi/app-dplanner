"""``dplanner wait …`` — make a step hold what requires it, until a day or for working days.

A wait is a step's aspect, like a milestone's label: ``wait set`` marks the step and says for
how long, ``wait clear`` makes it an ordinary step again and shelves the wait. Neither
reshapes the graph — what requires the step still does — so neither reads the topology first.
"""

from argparse import ArgumentParser, Namespace
from datetime import date

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_step, step_arg
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.schedule import Wait
from dplanner.domain.shelf import turn_off
from dplanner.modules.step_wait.aspect import MODULE_ID, read, words, write


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("wait", "set"),
            summary="Make a step a wait: what requires it starts on a day, or after working days.",
            configure=_configure_set,
            run=_set,
            examples=(
                "dplanner wait set 'Hardware arrives' --until 2026-11-04",
                "dplanner wait set 'Review period' --days 3",
            ),
        ),
        CliCommand(
            path=("wait", "clear"),
            summary="A step is no longer a wait; how long it held is kept on the shelf.",
            configure=step_arg,
            run=_clear,
            examples=("dplanner wait clear 'Review period'",),
        ),
    ]


def _configure_set(parser: ArgumentParser) -> None:
    step_arg(parser)
    held = parser.add_mutually_exclusive_group(required=True)
    held.add_argument(
        "--until",
        metavar="YYYY-MM-DD",
        help="the first day what requires the step may start",
    )
    held.add_argument(
        "--days",
        type=float,
        help="working days what requires the step waits once it is reached",
    )


def _set(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    if args.until is not None:
        try:
            wait = Wait(until=date.fromisoformat(args.until))
        except ValueError as error:
            raise CliError(f"--until is a date, YYYY-MM-DD: {args.until!r}") from error
    else:
        if args.days < 0:
            raise CliError("--days is how many working days, 0 or more")
        wait = Wait(days=args.days)
    entry = write(wait)
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, entry))
    today = context.clock.today()
    context.report({"step": step.id} | entry, f"{step.title}: waits {words(wait, today)}")
    return 0


def _clear(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    if read(step) is None:
        # Already clear is success — state-clearing verbs must survive batches.
        context.report({"step": step.id}, f"{step.title}: not a wait")
        return 0
    context.apply(turn_off(step.id, MODULE_ID, label="Remove Wait"))
    context.report({"step": step.id}, f"{step.title}: no longer a wait")
    return 0
