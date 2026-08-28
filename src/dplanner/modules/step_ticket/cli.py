"""``dplanner ticket …`` — record where a step is tracked."""

from argparse import ArgumentParser, Namespace

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_step, step_arg
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.modules.step_ticket.aspect import FIELDS, MODULE_ID, Ticket, read, write


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("ticket", "set"),
            summary="Point a step at the issue that tracks it.",
            configure=_configure_set,
            run=_set,
            examples=("dplanner ticket set 'Read the spec' --system jira --key WID-14",),
        ),
        CliCommand(
            path=("ticket", "clear"),
            summary="Remove a step's ticket, leaving no file behind.",
            configure=step_arg,
            run=_clear,
            examples=("dplanner ticket clear 'Read the spec'",),
        ),
    ]


def _configure_set(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument("--system", default="", help="jira, github, linear…")
    parser.add_argument("--key", default="", help="the identifier people quote")
    parser.add_argument("--url", default="", help="a link straight to it")


def _set(context: CliContext, args: Namespace) -> int:
    ticket = Ticket(system=args.system, key=args.key, url=args.url)
    if ticket.is_empty():
        raise CliError(f"nothing to set — pass one of {', '.join('--' + f for f in FIELDS)}")
    step = find_step(context.library, args.step)
    entry = write(ticket)
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, entry))
    context.report({"step": step.id} | entry, f"{step.title}: {ticket.key or ticket.url}")
    return 0


def _clear(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step)
    if read(step) is None:
        raise CliError(f"{step.title!r} has no ticket")
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, {}))
    context.report({"step": step.id}, f"{step.title}: ticket cleared")
    return 0
