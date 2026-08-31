"""``dplanner check …`` — the step type that gathers every test it waits on.

Only ``set`` and ``clear``: what a check *gathers* is ``dplanner scope show``, one verb over
every kind of collector, because a check, a feature and a release are the same walk asked
with a different stopping rule. A third near-copy of that report here is exactly what the
cross-feature verb in ``cli/scopes.py`` exists to prevent.
"""

from argparse import Namespace

from dplanner.cli import CliCommand, CliContext
from dplanner.cli.lookup import find_step, step_arg
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.modules.step_check.aspect import MODULE_ID, read, write


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("check", "set"),
            summary="Mark a step as a check: it gathers every test it waits on.",
            configure=step_arg,
            run=_set,
            examples=("dplanner check set 'Pre-release check'",),
        ),
        CliCommand(
            path=("check", "clear"),
            summary="A step is no longer a check; leaves no file behind.",
            configure=step_arg,
            run=_clear,
            examples=("dplanner check clear 'Pre-release check'",),
        ),
    ]


def _set(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    if read(step):
        # Already set is success — state-setting verbs must survive batches.
        context.report({"step": step.id, "check": True}, f"{step.title}: already a check")
        return 0
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(True)))
    context.report({"step": step.id, "check": True}, f"{step.title}: is a check")
    return 0


def _clear(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    if not read(step):
        context.report({"step": step.id, "check": False}, f"{step.title}: not a check")
        return 0
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, {}))
    context.report({"step": step.id, "check": False}, f"{step.title}: no longer a check")
    return 0
