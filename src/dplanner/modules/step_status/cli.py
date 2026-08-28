"""``dplanner status …`` — say where a step stands.

This is how an agent reports back: ``dplanner status set '<step>' done`` when it finishes,
``blocked`` when it cannot continue. ``status list`` is the project's board — every step
grouped by status, each group in the order the work can be done.
"""

from argparse import ArgumentParser, Namespace

from dplanner.cli import CliCommand, CliContext
from dplanner.cli.lookup import find_project, find_step, project_arg, step_arg
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.ordering import placed
from dplanner.modules.step_status.aspect import MODULE_ID, STATUSES, read, write


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("status", "set"),
            summary="Say where a step stands; setting it pending removes the file.",
            configure=_configure_set,
            run=_set,
            examples=("dplanner status set 'Read the spec' done",),
        ),
        CliCommand(
            path=("status", "show"),
            summary="Where one step stands.",
            configure=step_arg,
            run=_show,
            examples=("dplanner status show 'Read the spec'",),
        ),
        CliCommand(
            path=("status", "clear"),
            summary="Back to pending, leaving no file behind.",
            configure=step_arg,
            run=_clear,
            examples=("dplanner status clear 'Read the spec'",),
        ),
        CliCommand(
            path=("status", "list"),
            summary="A project's steps grouped by status, in working order.",
            configure=project_arg,
            run=_list,
            examples=("dplanner status list discovery",),
        ),
    ]


def _configure_set(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument("state", choices=STATUSES, help="where the step stands")


def _set(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step)
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(args.state)))
    context.report({"step": step.id, "status": args.state}, f"{step.title}: {args.state}")
    return 0


def _show(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step)
    status = read(step)
    context.report({"step": step.id, "status": status}, f"{step.title}: {status}")
    return 0


def _clear(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step)
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, {}))
    context.report({"step": step.id, "status": "pending"}, f"{step.title}: pending")
    return 0


def _list(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    order = placed(context.library, project)
    grouped = {status: [p.step for p in order if read(p.step) == status] for status in STATUSES}
    data = {
        "project": project.id,
        "statuses": {
            status: [{"id": step.id, "title": step.title} for step in steps]
            for status, steps in grouped.items()
        },
    }
    lines = []
    for status, steps in grouped.items():
        if not steps:
            continue
        lines.append(f"{status} ({len(steps)}):")
        lines.extend(f"  {step.title or 'Untitled step'}" for step in steps)
    context.report(data, "\n".join(lines) if lines else "No steps yet.")
    return 0
