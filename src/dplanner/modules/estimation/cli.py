"""``dplanner estimate …`` — set, clear and total up estimates."""

from argparse import ArgumentParser, Namespace

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project, find_step
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.modules.step_estimation.aspect import (
    CONFIDENCES,
    MODULE_ID,
    Estimate,
    read,
    write,
)


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("estimate", "set"),
            summary="Say how many days a step is thought to take.",
            configure=_configure_set,
            run=_set,
            examples=("dplanner estimate set 'Read the spec' --days 3 --confidence low",),
        ),
        CliCommand(
            path=("estimate", "clear"),
            summary="Remove a step's estimate, leaving no file behind.",
            configure=_one_step,
            run=_clear,
            examples=("dplanner estimate clear 'Read the spec'",),
        ),
        CliCommand(
            path=("estimate", "rollup"),
            summary="Total a project's estimates, and count what is still unestimated.",
            configure=_one_project,
            run=_rollup,
            examples=("dplanner estimate rollup discovery",),
        ),
    ]


def _one_step(parser: ArgumentParser) -> None:
    parser.add_argument("step", help="step id, folder name, or part of its title")


def _one_project(parser: ArgumentParser) -> None:
    parser.add_argument("project", help="project id, folder name, or part of its title")


def _configure_set(parser: ArgumentParser) -> None:
    _one_step(parser)
    parser.add_argument("--days", type=float, required=True, help="working days")
    parser.add_argument("--confidence", choices=CONFIDENCES, default="", help="how sure")


def _set(context: CliContext, args: Namespace) -> int:
    if args.days < 0:
        raise CliError("an estimate cannot be negative")
    step = find_step(context.product, args.step)
    entry = write(Estimate(days=args.days, confidence=args.confidence))
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, entry))
    context.report({"step": step.id} | entry, f"{step.title}: {args.days:g} days")
    return 0


def _clear(context: CliContext, args: Namespace) -> int:
    step = find_step(context.product, args.step)
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, {}))
    context.report({"step": step.id}, f"{step.title}: estimate cleared")
    return 0


def _rollup(context: CliContext, args: Namespace) -> int:
    """A total, plus how much of it is a guess.

    The count of unestimated steps is not decoration: a total that silently treats them as
    zero understates the plan, and the person reading it has no way to tell.
    """
    project = find_project(context.product, args.project)
    estimates = [read(step) for step in project.steps]
    total = sum(estimate.days for estimate in estimates if estimate is not None)
    missing = sum(1 for estimate in estimates if estimate is None)
    data = {
        "project": project.id,
        "days": total,
        "steps": len(project.steps),
        "unestimated": missing,
    }
    tail = f", {missing} unestimated" if missing else ""
    context.report(data, f"{project.title}: {total:g} days over {len(project.steps)} steps{tail}")
    return 0
