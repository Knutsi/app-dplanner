"""``dplanner layout …`` — the graph's named layouts, from the command line.

The same command objects the window pushes, so an apply here is undoable in a tab open on
the same product. ``save`` upserts rather than refusing a collision: an agent re-running a
script should converge, and the window's Save-As prompt covers the human case.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project, find_step
from dplanner.domain.commands import Command
from dplanner.domain.model import Project, Step
from dplanner.modules.project_editor.layouts import (
    apply_layout_commands,
    delete_layout_command,
    position_commands,
    read_layouts,
    rename_layout_command,
    save_layout_command,
    snapshot,
)
from dplanner.modules.project_editor.sorts import (
    layered_down,
    layered_flow,
    radial,
    spine,
    timeline,
)

SORT_NAMES = ("flow", "down", "spine", "timeline", "radial")


def commands(days_for: Callable[[Step], float | None]) -> list[CliCommand]:
    def _sort(context: CliContext, args: Namespace) -> int:
        project = find_project(context.product, args.project)
        if not project.steps:
            raise CliError("the project has no steps to arrange")
        center = None
        if args.center is not None:
            if args.algorithm != "radial":
                raise CliError("--center only means something to the radial sort")
            center = find_step(context.product, args.center).id
        placed = {
            "flow": lambda: layered_flow(context.product, project),
            "down": lambda: layered_down(context.product, project),
            "spine": lambda: spine(context.product, project),
            "timeline": lambda: timeline(context.product, project, days_for=days_for),
            "radial": lambda: radial(context.product, project, center=center),
        }[args.algorithm]()
        moves: list[Command] = position_commands(placed, label=f"Sort {args.algorithm}")
        for command in moves:
            context.apply(command)
        context.report(
            {"project": project.id, "algorithm": args.algorithm, "moved": len(moves)},
            f"{args.algorithm}: {len(moves)} steps arranged",
        )
        return 0

    return [
        CliCommand(
            path=("layout", "sort"),
            summary="Arrange the graph with one of the sort algorithms.",
            configure=_sort_args,
            run=_sort,
            examples=(
                "dplanner layout sort discovery spine",
                'dplanner layout sort discovery radial --center "read the spec"',
            ),
        ),
        CliCommand(
            path=("layout", "list"),
            summary="The saved layouts of a project's graph.",
            configure=_one_project,
            run=_list,
            examples=("dplanner layout list discovery --json",),
        ),
        CliCommand(
            path=("layout", "save"),
            summary="Snapshot the graph's current arrangement under a name.",
            configure=_project_and_name,
            run=_save,
            examples=('dplanner layout save discovery "release plan"',),
        ),
        CliCommand(
            path=("layout", "apply"),
            summary="Put every step back where a saved layout had it.",
            configure=_project_and_name,
            run=_apply,
            examples=('dplanner layout apply discovery "release plan"',),
        ),
        CliCommand(
            path=("layout", "rename"),
            summary="Give a saved layout a new name.",
            configure=_rename_args,
            run=_rename,
            examples=('dplanner layout rename discovery "release plan" "v2 plan"',),
        ),
        CliCommand(
            path=("layout", "delete"),
            summary="Forget a saved layout. The graph itself is untouched.",
            configure=_project_and_name,
            run=_delete,
            examples=('dplanner layout delete discovery "release plan"',),
        ),
    ]


def _one_project(parser: ArgumentParser) -> None:
    parser.add_argument("project", help="project id, folder name, or part of its title")


def _project_and_name(parser: ArgumentParser) -> None:
    _one_project(parser)
    parser.add_argument("name", help="the layout's name")


def _rename_args(parser: ArgumentParser) -> None:
    _one_project(parser)
    parser.add_argument("old", help="the layout's current name")
    parser.add_argument("new", help="what to call it instead")


def _sort_args(parser: ArgumentParser) -> None:
    _one_project(parser)
    parser.add_argument("algorithm", choices=SORT_NAMES, help="how to arrange the graph")
    parser.add_argument(
        "--center", help="radial only: the step to fan out from (default: most connected)"
    )


def _named(project: Project, name: str) -> None:
    layouts = read_layouts(project)
    if name in layouts:
        return
    if layouts:
        known = ", ".join(sorted(layouts))
        raise CliError(f"no layout named {name!r} — this project has: {known}")
    raise CliError(f"no layout named {name!r} — this project has no saved layouts")


def _list(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    layouts = read_layouts(project)
    data = {
        "project": project.id,
        "layouts": [
            {"name": name, "steps": len(snap.steps), "regions": len(snap.regions)}
            for name, snap in sorted(layouts.items())
        ],
    }
    if not layouts:
        context.report(data, "no saved layouts")
        return 0
    lines = [
        f"{name}  ({len(snap.steps)} steps)" for name, snap in sorted(layouts.items())
    ]
    context.report(data, "\n".join(lines))
    return 0


def _save(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    name = args.name.strip()
    if not name:
        raise CliError("a layout needs a name")
    said = "updated" if name in read_layouts(project) else "created"
    context.apply(save_layout_command(project, name, snapshot(context.product, project)))
    context.report({"project": project.id, "name": name, "result": said}, f"{name}: {said}")
    return 0


def _apply(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    _named(project, args.name)
    moves = apply_layout_commands(context.product, project, args.name)
    for command in moves:
        context.apply(command)
    context.report(
        {"project": project.id, "name": args.name, "moved": len(moves)},
        f"{args.name}: applied",
    )
    return 0


def _rename(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    _named(project, args.old)
    new = args.new.strip()
    if not new:
        raise CliError("a layout needs a name")
    if new != args.old and new in read_layouts(project):
        raise CliError(f"a layout named {new!r} already exists")
    context.apply(rename_layout_command(project, args.old, new))
    context.report({"project": project.id, "old": args.old, "new": new}, f"{args.old} → {new}")
    return 0


def _delete(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    _named(project, args.name)
    context.apply(delete_layout_command(project, args.name))
    context.report({"project": project.id, "name": args.name}, f"{args.name}: deleted")
    return 0
