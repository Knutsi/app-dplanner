"""``dplanner agent-state …`` — how an agent reports where it stands, from inside its shell.

Run Agent stamps ``launched``; the agent moves the state along as it works —
``plan-for-review`` when its plan is ready, ``working`` while implementing,
``pending-approval`` while waiting on one — and clears it when the run ends
(``status set … done`` is the claim about the work; this is the claim about the shell).
"""

from argparse import ArgumentParser, Namespace

from dplanner.cli import CliCommand, CliContext
from dplanner.cli.lookup import find_step, step_arg
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.modules.step_agent_run.aspect import MODULE_ID, STATES, launched, read, write


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("agent-state", "set"),
            summary="Say where a launched agent stands on a step.",
            configure=_configure_set,
            run=_set,
            examples=("dplanner agent-state set 'Read the spec' plan-for-review",),
        ),
        CliCommand(
            path=("agent-state", "show"),
            summary="Where the agent on one step stands, and since when.",
            configure=step_arg,
            run=_show,
            examples=("dplanner agent-state show 'Read the spec'",),
        ),
        CliCommand(
            path=("agent-state", "clear"),
            summary="The run is over; leaves no file behind.",
            configure=step_arg,
            run=_clear,
            examples=("dplanner agent-state clear 'Read the spec'",),
        ),
    ]


def _configure_set(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument("state", choices=STATES, help="where the agent stands")


def _set(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step)
    # The original launch stamp survives as the state moves along.
    context.apply(
        SetModuleDataCommand(step.id, MODULE_ID, write(args.state, launched=launched(step)))
    )
    context.report({"step": step.id, "state": args.state}, f"{step.title}: {args.state}")
    return 0


def _show(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step)
    state = read(step)
    data = {"step": step.id, "state": state, "launched": launched(step)}
    context.report(data, f"{step.title}: {state}" if state else f"{step.title}: no agent run")
    return 0


def _clear(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step)
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, {}))
    context.report({"step": step.id, "state": ""}, f"{step.title}: no agent run")
    return 0
