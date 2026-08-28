"""``dplanner layout …`` and ``dplanner region …`` — arranging the graph from the command line.

The same command objects the window pushes, so an apply here is undoable in a tab open on
the same library. ``layout save`` upserts rather than refusing a collision: an agent
re-running a script should converge, and the window's Save-As prompt covers the human case.

``region add --steps`` is the agent's way in: it computes the rectangle that wraps those
steps where they sit, so an agent can name an area of the graph without reasoning about
canvas coordinates. ``--rect`` remains for placing one by hand.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from typing import Any

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project, find_step, project_arg
from dplanner.domain.commands import Command
from dplanner.domain.model import Project, Step
from dplanner.modules.project_editor.named_layouts import (
    apply_layout_commands,
    delete_layout_command,
    position_commands,
    read_layouts,
    rename_layout_command,
    save_layout_command,
    snapshot,
)
from dplanner.modules.project_editor.placement import positions
from dplanner.modules.project_editor.positions import NODE_H, NODE_W
from dplanner.modules.project_editor.regions import (
    TITLE_STRIP_H,
    Region,
    new_region,
    read_regions,
    set_regions_command,
)
from dplanner.modules.project_editor.sorts import (
    layered_down,
    layered_flow,
    radial,
    spine,
    timeline,
)

SORT_NAMES = ("flow", "down", "spine", "timeline", "radial")

# The air a wrapped region leaves around its steps; the top adds the title strip's height
# so the title never sits on a node.
WRAP_PAD = 32.0
WRAP_PAD_TOP = TITLE_STRIP_H + 24.0


def commands(days_for: Callable[[Step], float | None]) -> list[CliCommand]:
    def _sort(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        if not project.steps:
            raise CliError("the project has no steps to arrange")
        center = None
        if args.center is not None:
            if args.algorithm != "radial":
                raise CliError("--center only means something to the radial sort")
            center = find_step(context.library, args.center).id
        placed = {
            "flow": lambda: layered_flow(context.library, project),
            "down": lambda: layered_down(context.library, project),
            "spine": lambda: spine(context.library, project),
            "timeline": lambda: timeline(context.library, project, days_for=days_for),
            "radial": lambda: radial(context.library, project, center=center),
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
            configure=project_arg,
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
        CliCommand(
            path=("region", "list"),
            summary="The titled areas drawn behind a project's graph.",
            configure=project_arg,
            run=_region_list,
            examples=("dplanner region list discovery --json",),
        ),
        CliCommand(
            path=("region", "add"),
            summary="Draw a titled area behind the graph — around named steps, or at a rect.",
            configure=_region_add_args,
            run=_region_add,
            examples=(
                'dplanner region add discovery "Database setup" --steps schema migrate seed',
                'dplanner region add discovery "Finalize release" --rect 40 40 480 320',
            ),
        ),
        CliCommand(
            path=("region", "fit"),
            summary="Re-wrap a region around named steps — after a sort moved them.",
            configure=_region_fit_args,
            run=_region_fit,
            examples=('dplanner region fit discovery "Database setup" --steps schema seed',),
        ),
        CliCommand(
            path=("region", "rename"),
            summary="Give a region a new title.",
            configure=_region_rename_args,
            run=_region_rename,
            examples=('dplanner region rename discovery "Database setup" "Data layer"',),
        ),
        CliCommand(
            path=("region", "delete"),
            summary="Remove a region. The steps inside stay where they are.",
            configure=_region_args,
            run=_region_delete,
            examples=('dplanner region delete discovery "Database setup"',),
        ),
    ]


def _project_and_name(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("name", help="the layout's name")


def _rename_args(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("old", help="the layout's current name")
    parser.add_argument("new", help="what to call it instead")


def _sort_args(parser: ArgumentParser) -> None:
    project_arg(parser)
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
    project = find_project(context.library, args.project)
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
    project = find_project(context.library, args.project)
    name = args.name.strip()
    if not name:
        raise CliError("a layout needs a name")
    said = "updated" if name in read_layouts(project) else "created"
    context.apply(save_layout_command(project, name, snapshot(context.library, project)))
    context.report({"project": project.id, "name": name, "result": said}, f"{name}: {said}")
    return 0


def _apply(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    _named(project, args.name)
    moves = apply_layout_commands(context.library, project, args.name)
    for command in moves:
        context.apply(command)
    context.report(
        {"project": project.id, "name": args.name, "moved": len(moves)},
        f"{args.name}: applied",
    )
    return 0


def _rename(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
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
    project = find_project(context.library, args.project)
    _named(project, args.name)
    context.apply(delete_layout_command(project, args.name))
    context.report({"project": project.id, "name": args.name}, f"{args.name}: deleted")
    return 0


# -- regions -----------------------------------------------------------------------------------


def _region_add_args(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("title", help="what the area is about")
    parser.add_argument(
        "--steps",
        nargs="+",
        metavar="STEP",
        help="wrap these steps where they sit (ids, folder names, or unique title parts)",
    )
    parser.add_argument(
        "--rect",
        nargs=4,
        type=float,
        metavar=("X", "Y", "W", "H"),
        help="place it by hand instead, as canvas coordinates",
    )


def _region_args(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("region", help="region id, id prefix, or part of its title")


def _region_rename_args(parser: ArgumentParser) -> None:
    _region_args(parser)
    parser.add_argument("new", help="the new title")


def _region_fit_args(parser: ArgumentParser) -> None:
    _region_args(parser)
    parser.add_argument(
        "--steps",
        nargs="+",
        required=True,
        metavar="STEP",
        help="wrap these steps where they now sit",
    )


def _find_region(project: Project, needle: str) -> Region:
    """Exact id first, then a unique id prefix, then a unique partial title."""
    regions = read_regions(project)
    for region in regions:
        if region.id == needle:
            return region
    for candidates in (
        [r for r in regions if r.id.startswith(needle)],
        [r for r in regions if r.title == needle],
        [r for r in regions if needle.lower() in r.title.lower()],
    ):
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            listed = ", ".join(f"{r.id[:8]} ({r.title})" for r in candidates)
            raise CliError(f"{needle!r} is ambiguous — matches: {listed}")
    raise CliError(f"no region matches {needle!r}")


def _region_row(
    project: Project, region: Region, placed: dict[str, tuple[float, float]]
) -> dict[str, Any]:
    """One region with the steps it actually covers — the agent's verification loop.

    Membership is listed by title, not just counted, so a wrap that caught a step nobody
    named is visible in the report rather than a surprise on the canvas.
    """
    inside = [
        {"id": step.id, "title": step.title}
        for step in project.steps
        if region.contains_centre(*placed[step.id], NODE_W, NODE_H)
    ]
    return {
        "id": region.id,
        "title": region.title,
        "x": region.x,
        "y": region.y,
        "w": region.w,
        "h": region.h,
        "steps_inside": len(inside),
        "steps": inside,
    }


def _region_line(row: dict[str, Any]) -> str:
    count = row["steps_inside"]
    if not count:
        held = "empty"
    else:
        titles = ", ".join(step["title"] or "Untitled step" for step in row["steps"])
        held = f"{count} step{'s' if count != 1 else ''}: {titles}"
    return f"{row['id'][:8]}  {row['title']}  ({held})"


def _region_list(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    placed = positions(context.library, project)
    rows = [_region_row(project, region, placed) for region in read_regions(project)]
    data = {"project": project.id, "regions": rows}
    if not rows:
        context.report(data, "no regions")
        return 0
    context.report(data, "\n".join(_region_line(row) for row in rows))
    return 0


def _region_add(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    title = args.title.strip()
    if not title:
        raise CliError("a region needs a title")
    if bool(args.steps) == bool(args.rect):
        raise CliError("say where it goes — either --steps or --rect")
    if args.steps:
        x, y, w, h = _wrap_rect(context, project, args.steps)
    else:
        x, y, w, h = args.rect
        if w <= 0 or h <= 0:
            raise CliError("a region needs a positive width and height")
    region = new_region(title, x, y, w, h)
    context.apply(
        set_regions_command(project, [*read_regions(project), region], "Add Region")
    )
    placed = positions(context.library, project)
    row = _region_row(project, region, placed)
    context.report(row | {"project": project.id}, _region_line(row))
    return 0


def _wrap_rect(
    context: CliContext, project: Project, needles: list[str]
) -> tuple[float, float, float, float]:
    """The rectangle that wraps these steps where they sit, with air around them."""
    placed = positions(context.library, project)
    chosen = []
    for needle in needles:
        step = find_step(context.library, needle)
        if step.id not in placed:
            raise CliError(f"step {step.title!r} is not in this project")
        chosen.append(step)
    xs = [placed[step.id][0] for step in chosen]
    ys = [placed[step.id][1] for step in chosen]
    left = min(xs) - WRAP_PAD
    top = min(ys) - WRAP_PAD_TOP
    right = max(xs) + NODE_W + WRAP_PAD
    bottom = max(ys) + NODE_H + WRAP_PAD
    return left, top, right - left, bottom - top


def _region_fit(context: CliContext, args: Namespace) -> int:
    """Recompute the wrap, keeping the region's id — a delete-and-re-add would mint a new
    one and orphan the region's rect entries in every saved layout."""
    project = find_project(context.library, args.project)
    region = _find_region(project, args.region)
    x, y, w, h = _wrap_rect(context, project, args.steps)
    refitted = [
        r.moved_to(x, y).sized(w, h) if r.id == region.id else r
        for r in read_regions(project)
    ]
    context.apply(set_regions_command(project, refitted, "Fit Region"))
    placed = positions(context.library, project)
    row = _region_row(project, region.moved_to(x, y).sized(w, h), placed)
    context.report(row | {"project": project.id}, _region_line(row))
    return 0


def _region_rename(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    region = _find_region(project, args.region)
    new = args.new.strip()
    if not new:
        raise CliError("a region needs a title")
    renamed = [r.named(new) if r.id == region.id else r for r in read_regions(project)]
    context.apply(set_regions_command(project, renamed, "Rename Region"))
    context.report(
        {"project": project.id, "id": region.id, "title": new},
        f"{region.title} → {new}",
    )
    return 0


def _region_delete(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    region = _find_region(project, args.region)
    kept = [r for r in read_regions(project) if r.id != region.id]
    context.apply(set_regions_command(project, kept, "Delete Region"))
    context.report(
        {"project": project.id, "id": region.id}, f"{region.title or region.id}: deleted"
    )
    return 0
