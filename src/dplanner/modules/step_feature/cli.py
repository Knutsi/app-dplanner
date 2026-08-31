"""``dplanner feature …`` — mark the steps that collect the work behind them.

``feature list`` prints them in the order the work lands, the same walk every other order
comes from. What a feature *gathers* is not here: that is ``dplanner scope show``, one verb
over every kind of collector, because a check, a feature and a milestone are one derivation
asked three ways.
"""

from argparse import Namespace

from dplanner.cli import CliCommand, CliContext
from dplanner.cli.lookup import find_project, find_step, project_arg, step_arg
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.ordering import placed
from dplanner.modules.step_feature.aspect import MODULE_ID, read, write


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("feature", "set"),
            summary="Mark a step as a feature: it collects the work behind it.",
            configure=step_arg,
            run=_set,
            examples=("dplanner feature set 'Bulk import'",),
        ),
        CliCommand(
            path=("feature", "clear"),
            summary="A step is no longer a feature; leaves no file behind.",
            configure=step_arg,
            run=_clear,
            examples=("dplanner feature clear 'Bulk import'",),
        ),
        CliCommand(
            path=("feature", "list"),
            summary="A project's features, in the order the work lands.",
            configure=project_arg,
            run=_list,
            examples=("dplanner feature list discovery",),
        ),
    ]


def _set(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    if read(step):
        # Already set is success — state-setting verbs must survive batches.
        context.report({"step": step.id, "feature": True}, f"{step.title}: already a feature")
        return 0
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(True)))
    context.report({"step": step.id, "feature": True}, f"{step.title}: is a feature")
    return 0


def _clear(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    if not read(step):
        # Already clear is success — state-clearing verbs must survive batches.
        context.report({"step": step.id, "feature": False}, f"{step.title}: not a feature")
        return 0
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, {}))
    context.report({"step": step.id, "feature": False}, f"{step.title}: no longer a feature")
    return 0


def _list(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    features = [place for place in placed(context.library, project) if read(place.step)]
    data = {
        "project": project.id,
        "features": [
            {"index": place.index, "id": place.step.id, "title": place.step.title}
            for place in features
        ],
    }
    lines = [f"{place.index:>3}  {place.step.title or 'Untitled step'}" for place in features]
    context.report(data, "\n".join(lines) if lines else "No features marked yet.")
    return 0
