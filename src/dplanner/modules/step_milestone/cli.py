"""``dplanner milestone …`` — mark the steps that are milestone points.

``milestone list`` prints the labels in the order the work can be done: a one-glance roadmap,
derived from the same walk every other order comes from.
"""

from argparse import ArgumentParser, Namespace

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project, find_step, project_arg, step_arg
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.ordering import placed
from dplanner.domain.shelf import shelved, turn_off, turn_on
from dplanner.modules.step_milestone.aspect import (
    MODULE_ID,
    next_milestone_label,
    project_labels,
    read,
    write,
)


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("milestone", "set"),
            summary="Mark a step as a milestone point, with a label.",
            configure=_configure_set,
            run=_set,
            examples=(
                "dplanner milestone set 'Ship the beta' --label MVP",
                "dplanner milestone set 'Ship the beta'",
            ),
        ),
        CliCommand(
            path=("milestone", "clear"),
            summary="A step is no longer a milestone point; the label is kept.",
            configure=step_arg,
            run=_clear,
            examples=("dplanner milestone clear 'Ship the beta'",),
        ),
        CliCommand(
            path=("milestone", "list"),
            summary="A project's milestone points, in the order the work lands.",
            configure=project_arg,
            run=_list,
            examples=("dplanner milestone list discovery",),
        ),
    ]


def _configure_set(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument(
        "--label",
        help="what to call it: MVP, v1.0, v2 (omitted: generated from the project's labels)",
    )


def _set(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step)
    if args.label is None and (kept := shelved(step, MODULE_ID)) is not None and not read(step):
        # No label asked for and one on the shelf: bring it back rather than generate.
        context.apply(turn_on(step, MODULE_ID, fresh={}, label="Add Milestone"))
        entry = kept[0]
        label = read(step)
    else:
        if args.label is None:
            project = context.library.project_of(step.id)
            label = next_milestone_label(project_labels(project, skip=step.id))
        else:
            label = args.label
        entry = write(label)
        if not entry:
            raise CliError("a milestone needs a label")
        context.apply(SetModuleDataCommand(step.id, MODULE_ID, entry))
    context.report({"step": step.id} | entry, f"{step.title}: milestone {label.strip()}")
    return 0


def _clear(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step)
    if not read(step):
        # Already clear is success — state-clearing verbs must survive batches.
        context.report({"step": step.id}, f"{step.title}: not a milestone")
        return 0
    context.apply(turn_off(step.id, MODULE_ID, label="Remove Milestone"))
    context.report({"step": step.id}, f"{step.title}: no longer a milestone")
    return 0


def _list(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    milestones = [
        (place, read(place.step)) for place in placed(context.library, project) if read(place.step)
    ]
    data = {
        "project": project.id,
        "milestones": [
            {"index": place.index, "id": place.step.id, "title": place.step.title, "label": label}
            for place, label in milestones
        ],
    }
    lines = [
        f"{place.index:>3}  {label:<8}  {place.step.title or 'Untitled step'}"
        for place, label in milestones
    ]
    context.report(data, "\n".join(lines) if lines else "No milestones marked yet.")
    return 0
