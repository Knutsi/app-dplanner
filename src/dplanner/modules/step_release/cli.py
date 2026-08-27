"""``dplanner release …`` — mark the steps that are release points.

``release list`` prints the labels in the order the work can be done: a one-glance roadmap,
derived from the same walk every other order comes from.
"""

from argparse import ArgumentParser, Namespace

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project, find_step
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.ordering import placed
from dplanner.modules.step_release.aspect import MODULE_ID, read, write


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("release", "set"),
            summary="Mark a step as a release point, with a label.",
            configure=_configure_set,
            run=_set,
            examples=("dplanner release set 'Ship the beta' --label MVP",),
        ),
        CliCommand(
            path=("release", "clear"),
            summary="A step is no longer a release point; leaves no file behind.",
            configure=_one_step,
            run=_clear,
            examples=("dplanner release clear 'Ship the beta'",),
        ),
        CliCommand(
            path=("release", "list"),
            summary="A project's release points, in the order the work lands.",
            configure=_one_project,
            run=_list,
            examples=("dplanner release list discovery",),
        ),
    ]


def _one_step(parser: ArgumentParser) -> None:
    parser.add_argument("step", help="step id, folder name, or part of its title")


def _one_project(parser: ArgumentParser) -> None:
    parser.add_argument("project", help="project id, folder name, or part of its title")


def _configure_set(parser: ArgumentParser) -> None:
    _one_step(parser)
    parser.add_argument("--label", required=True, help="what to call it: MVP, v1.0, v2")


def _set(context: CliContext, args: Namespace) -> int:
    entry = write(args.label)
    if not entry:
        raise CliError("a release needs a label")
    step = find_step(context.product, args.step)
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, entry))
    context.report({"step": step.id} | entry, f"{step.title}: release {args.label.strip()}")
    return 0


def _clear(context: CliContext, args: Namespace) -> int:
    step = find_step(context.product, args.step)
    if not read(step):
        raise CliError(f"{step.title!r} is not a release")
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, {}))
    context.report({"step": step.id}, f"{step.title}: no longer a release")
    return 0


def _list(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    releases = [
        (place, read(place.step)) for place in placed(context.product, project) if read(place.step)
    ]
    data = {
        "project": project.id,
        "releases": [
            {"index": place.index, "id": place.step.id, "title": place.step.title, "label": label}
            for place, label in releases
        ],
    }
    lines = [
        f"{place.index:>3}  {label:<8}  {place.step.title or 'Untitled step'}"
        for place, label in releases
    ]
    context.report(data, "\n".join(lines) if lines else "No releases marked yet.")
    return 0
