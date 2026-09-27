"""``dplanner layout …`` and ``step duplicate`` — the graph editor's verbs.

The same command objects the window pushes, so an apply here is undoable in a tab open on
the same library. ``layout save`` upserts rather than refusing a collision: an agent
re-running a script should converge, and the window's Save-As prompt covers the human case.

``layout show``, ``layout shift``, ``layout contract`` and ``layout tidy`` are the agent's
eyes and hands on the canvas: the geometry measured on every read and never stored
(``geometry.py``), the Divide and Contract gestures as verbs building the very command the
canvas pushes, and the sixth sort (``sorts.tidy``) applied like the other five. None
reshapes the graph, so none reads the topology first. ``stack list`` says which chains the
canvas draws as one tall card (``stacks.py``).
"""

import math
from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Sequence
from typing import Any

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project, find_step, project_arg
from dplanner.domain.commands import Command, CompositeCommand
from dplanner.domain.model import Project, Step, StepId
from dplanner.modules.project_editor.clipboard import PastePolicy, clip, paste, write_files
from dplanner.modules.project_editor.geometry import (
    CONTRACT_LABEL,
    Axis,
    as_json,
    contract,
    direction,
    divide_command,
    lane_lines,
    map_text,
    measure,
    pitches,
    shift,
)
from dplanner.modules.project_editor.geometry import text as geometry_text
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
from dplanner.modules.project_editor.positions import GRID, snapped
from dplanner.modules.project_editor.sorts import (
    DEFAULT_AIR,
    H_GAP,
    H_PITCH,
    V_GAP,
    V_PITCH,
    layered_down,
    layered_flow,
    radial,
    spine,
    tidy,
    timeline,
)
from dplanner.modules.project_editor.stacks import broken_reason, pack, read_stacks

SORT_NAMES = ("flow", "down", "spine", "timeline", "radial")
TIDY_LABEL = "Tidy Layout"
MAP_LEGEND = (
    f"one cell = one column pitch ({H_PITCH:g}) by one row pitch ({V_PITCH:g}); "
    "cells are the lanes, a hole is an empty cell, a wide card spans cells"
)


def _no_key(_step: Step) -> str:
    return ""


def commands(
    days_for: Callable[[Step], float | None],
    *,
    paste_policies: Sequence[PastePolicy] = (),
    file_modules: Sequence[str] = (),
    key_of: Callable[[Step], str] = _no_key,
) -> list[CliCommand]:
    """``key_of`` is the step's readable key (``S7``) — the letter is the composition
    root's fact, handed over so the geometry report names steps the way every row does."""

    def _configure_duplicate(parser: ArgumentParser) -> None:
        parser.add_argument(
            "step", nargs="+", help="steps to copy: id, folder name, or part of a title"
        )
        parser.add_argument(
            "--into",
            metavar="PROJECT",
            help="the project the copies go into; default: the steps' own",
        )

    def _project_of_duplicate(context: CliContext, args: Namespace) -> Project:
        """The project the copies land in — what the topology gate asks about."""
        library = context.library
        if args.into:
            return find_project(library, args.into)
        return library.project_of(find_step(library, args.step[0], context.current).id)

    def _step_duplicate(context: CliContext, args: Namespace) -> int:
        """The window's Duplicate, as one transaction: the same clone command, the same
        policies, the attachments copied after it — see clipboard.py."""
        library = context.library
        originals = [find_step(library, needle, context.current) for needle in args.step]
        target = _project_of_duplicate(context, args)
        clips = clip(library, context.store.files, file_modules, [s.id for s in originals])
        command, copies = paste(
            library, target.id, clips, anchor=None, policies=paste_policies, verb="Duplicate"
        )
        context.apply(command)
        write_files(context.store.files, list(zip(copies, clips, strict=True)))
        pairs = list(zip(originals, copies, strict=True))
        context.report(
            {
                "project": target.id,
                "steps": [
                    {"id": copy.id, "title": copy.title, "from": original.id}
                    for original, copy in pairs
                ],
            },
            "\n".join(
                f"Duplicated {original.title!r} as {copy.id} in {target.title}"
                for original, copy in pairs
            ),
        )
        return 0

    def _sort(context: CliContext, args: Namespace) -> int:
        project = _arrangeable(context, args)
        center = None
        if args.center is not None:
            if args.algorithm != "radial":
                raise CliError("--center only means something to the radial sort")
            center = find_step(context.library, args.center, context.current).id
        placed = {
            "flow": lambda: layered_flow(context.library, project),
            "down": lambda: layered_down(context.library, project),
            "spine": lambda: spine(context.library, project),
            "timeline": lambda: timeline(context.library, project, days_for=days_for),
            "radial": lambda: radial(context.library, project, center=center),
        }[args.algorithm]()
        moves: list[Command] = position_commands(project, placed, label=f"Sort {args.algorithm}")
        for command in moves:
            context.apply(command)
        context.report(
            {"project": project.id, "algorithm": args.algorithm, "moved": len(moves)},
            f"{args.algorithm}: {len(moves)} steps arranged",
        )
        return 0

    def _show(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        geometry = measure(context.library, project, key_of=key_of)
        data: dict[str, Any] = {"project": project.id, **as_json(geometry)}
        if args.map:
            picture = map_text(geometry)
            data["map"] = picture
            context.report(data, f"{picture}\n{MAP_LEGEND}" if picture else "no steps")
            return 0
        context.report(data, geometry_text(geometry))
        return 0

    def _shift(context: CliContext, args: Namespace) -> int:
        """The Divide gesture from the terminal: the same side rule, the same command."""
        project = _arrangeable(context, args)
        axis, cut = _cut(args)
        by = _distance(args.by)
        # The rule moves blocks: a stack goes whole, by its frame, and naming one of its
        # members names the stack.
        packing = pack(project)
        placed = packing.blocks(positions(context.library, project))
        only: set[StepId] | None = None
        if args.steps:
            only = set()
            for needle in args.steps:
                step = find_step(context.library, needle, context.current)
                if project.step(step.id) is None:
                    raise CliError(f"step {step.title!r} is not in this project")
                only.add(packing.block_of(step.id))
        moved = packing.unfold(shift(placed, packing.sizes, axis, cut, by, only=only))
        if not moved:
            side = "past" if by > 0 else "before"
            raise CliError(f"no step's centre lies {side} {axis}={cut:g}")
        context.apply(divide_command(project, moved))
        keys = _keys(project)
        count = len(moved)
        headline = (
            f"Shifted {count} step{'s' if count != 1 else ''} {direction(axis, by)} by "
            f"{abs(by):g}: {' '.join(keys[step_id] for step_id in moved)}"
        )
        _report_moved(context, project, axis, cut, moved, headline, {"by": by})
        return 0

    def _contract(context: CliContext, args: Namespace) -> int:
        """The Contract gesture from the terminal: the same rule, the same command. With no
        distance the far side closes up as far as the first step ahead of it allows."""
        project = _arrangeable(context, args)
        axis, cut = _cut(args)
        by = -math.inf if args.by is None else _distance(args.by)
        packing = pack(project)
        placed = packing.blocks(positions(context.library, project))
        done = contract(placed, packing.sizes, axis, cut, by)
        moved = packing.unfold(done.moved)
        keys = _keys(project)
        pair = None if done.stopped is None else [keys[step_id] for step_id in done.stopped]
        if moved:
            context.apply(divide_command(project, moved, label=CONTRACT_LABEL))
            count = len(moved)
            headline = (
                f"Contracted {count} step{'s' if count != 1 else ''} "
                f"{direction(axis, done.by)} by {abs(done.by):g}: "
                f"{' '.join(keys[step_id] for step_id in moved)}"
                + (f"; {pair[0]} stops one gap from {pair[1]}" if pair else "")
            )
        elif pair:
            headline = f"Nothing to close: {pair[0]} already sits within one gap of {pair[1]}"
        elif math.isinf(by):
            band = "row" if axis == "x" else "column"
            raise CliError(
                f"nothing past {axis}={cut:g} has a step ahead of it in its {band} to close "
                "up to — name a distance with --by"
            )
        else:
            side = "past" if by < 0 else "before"
            raise CliError(f"no step's centre lies {side} {axis}={cut:g}")
        said = {
            "by": None if args.by is None else by,
            "moved_by": done.by,
            "stopped": None if done.stopped is None else list(done.stopped),
        }
        _report_moved(context, project, axis, cut, moved, headline, said)
        return 0

    def _report_moved(
        context: CliContext,
        project: Project,
        axis: Axis,
        cut: float,
        moved: dict[StepId, tuple[float, float]],
        headline: str,
        said: dict[str, Any],
    ) -> None:
        """What both hands report once a side has moved: what moved, and the lanes across
        the axis as they stand now."""
        after = measure(context.library, project, key_of=key_of)
        keys = _keys(project)
        report = as_json(after)
        data = {
            "project": project.id,
            "axis": axis,
            "cut": cut,
            **said,
            "moved": [
                {"id": step_id, "key": keys[step_id], "x": x, "y": y}
                for step_id, (x, y) in moved.items()
            ],
            "columns": report["columns"],
            "rows": report["rows"],
            "overlaps": report["overlaps"],
        }
        context.report(data, "\n".join([headline, *lane_lines(after, axis)]))

    def _keys(project: Project) -> dict[StepId, str]:
        return {step.id: key_of(step) or step.title for step in project.steps}

    def _stack_list(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        keys = _keys(project)
        titles = {step.id: step.title for step in project.steps}
        rows, lines = [], []
        for stack in read_stacks(project.steps):
            broken = broken_reason(stack, keys.__getitem__)
            rows.append(
                {
                    "id": stack.id,
                    "steps": [
                        {"id": member, "key": keys[member], "title": titles[member]}
                        for member in stack.members
                    ],
                    "broken": broken,
                }
            )
            named = " ".join(keys[member] for member in stack.members)
            lines.append(f"{stack.id[:8]}  {named}" + (f" — broken: {broken}" if broken else ""))
        context.report({"project": project.id, "stacks": rows}, "\n".join(lines) or "no stacks")
        return 0

    def _tidy(context: CliContext, args: Namespace) -> int:
        project = _arrangeable(context, args)
        if args.gap < 1:
            raise CliError("--gap needs at least 1 pitch")
        before = positions(context.library, project)
        placed = tidy(project, before, air=args.gap)
        moved = sum(1 for step_id, seat in placed.items() if seat != before[step_id])
        context.apply(CompositeCommand(TIDY_LABEL, position_commands(project, placed, TIDY_LABEL)))
        after = measure(context.library, project, key_of=key_of)
        widest = max(
            [
                *(pitches(lane, H_GAP, H_PITCH) or 0.0 for lane in after.columns),
                *(pitches(lane, V_GAP, V_PITCH) or 0.0 for lane in after.rows),
                1.0,
            ]
        )
        report = as_json(after)
        data = {
            "project": project.id,
            "moved": moved,
            "gap": args.gap,
            "columns": report["columns"],
            "rows": report["rows"],
            "overlaps": report["overlaps"],
        }
        overlaps = len(after.overlaps)
        context.report(
            data,
            f"Tidy: {moved} of {len(placed)} steps moved; {len(after.columns)} columns x "
            f"{len(after.rows)} rows; "
            + (
                "no overlaps"
                if not overlaps
                else f"{overlaps} overlap{'s' if overlaps != 1 else ''}"
            )
            + f"; widest gap {widest:.1f} pitch{'' if abs(widest - 1) < 0.05 else 'es'}",
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
            path=("layout", "show"),
            summary="Where every step sits and how big its card is: the bounds, the waves, "
            "every overlap, and the gaps between columns and rows in pitches; --map draws it.",
            configure=_show_args,
            run=_show,
            examples=(
                "dplanner layout show discovery",
                "dplanner layout show discovery --map",
                "dplanner layout show discovery --json",
            ),
        ),
        CliCommand(
            path=("layout", "shift"),
            summary="Push one side of the graph along an axis — the canvas's Divide: every "
            "step whose centre lies past the cut moves by the distance; negative brings "
            "the near side back.",
            configure=_shift_args,
            run=_shift,
            examples=(
                "dplanner layout shift discovery --x 640 --by 300",
                "dplanner layout shift discovery --y 400 --by -120",
                "dplanner layout shift discovery --x 0 --by 300 --steps S7 S8",
            ),
        ),
        CliCommand(
            path=("layout", "contract"),
            summary="Close up the graph along an axis — the canvas's Contract: the side "
            "behind the travel moves up to the first step ahead of it in its row or column "
            "and stops one gap short; no --by closes the far side fully.",
            configure=_contract_args,
            run=_contract,
            examples=(
                "dplanner layout contract discovery --x 640",
                "dplanner layout contract discovery --y 400 --by -120",
                "dplanner layout contract discovery --x 640 --by 300",
            ),
        ),
        CliCommand(
            path=("layout", "tidy"),
            summary="Keep every cluster and its order; resolve overlaps, even the spacing to "
            "the sort pitches, close holes wider than --gap, snap to the grid.",
            configure=_tidy_args,
            run=_tidy,
            examples=(
                "dplanner layout tidy discovery",
                "dplanner layout tidy discovery --gap 1",
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
            path=("stack", "list"),
            summary="The chains the canvas draws as one tall card: each stack's steps in "
            "chain order, and what breaks one that is no longer a single line.",
            configure=project_arg,
            run=_stack_list,
            examples=("dplanner stack list discovery", "dplanner stack list discovery --json"),
        ),
        CliCommand(
            path=("step", "duplicate"),
            summary="Copy steps — aspects, prose, attachments and the links among them — "
            "into a project, one row below the originals.",
            configure=_configure_duplicate,
            run=_step_duplicate,
            examples=(
                "dplanner step duplicate read-the-spec",
                "dplanner step duplicate read-the-spec draft-the-model --into rollout",
            ),
            edits_graph=_project_of_duplicate,
        ),
    ]


def _project_and_name(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("name", help="the layout's name")


def _show_args(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument(
        "--map",
        action="store_true",
        help="draw the graph as text: one cell per column and row pitch, keys in the cells",
    )


def _arrangeable(context: CliContext, args: Namespace) -> Project:
    project = find_project(context.library, args.project)
    if not project.steps:
        raise CliError("the project has no steps to arrange")
    return project


def _cut(args: Namespace) -> tuple[Axis, float]:
    return ("x", args.x) if args.x is not None else ("y", args.y)


def _distance(by: float) -> float:
    """A distance asked for, snapped to the grid as the drag snaps it; nought refused."""
    snapped_by = snapped(by, GRID)
    if snapped_by == 0:
        why = "" if by == 0 else f" — it snaps to the grid ({GRID:g}) as 0"
        raise CliError(f"--by {by:g} moves nothing{why}")
    return snapped_by


def _cut_args(parser: ArgumentParser, upright: str, level: str) -> None:
    project_arg(parser)
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument(
        "--x", type=float, metavar="CUT", help=f"an upright cut at this x: {upright}"
    )
    where.add_argument("--y", type=float, metavar="CUT", help=f"a level cut at this y: {level}")


def _shift_args(parser: ArgumentParser) -> None:
    _cut_args(
        parser,
        "steps whose centre lies right of it move",
        "steps whose centre lies below it move",
    )
    parser.add_argument(
        "--by",
        type=float,
        required=True,
        metavar="DISTANCE",
        help="how far, in canvas units, snapped to the grid; negative moves the near side back",
    )
    parser.add_argument(
        "--steps",
        nargs="+",
        metavar="STEP",
        help="move only these steps (the cut then only names the axis)",
    )


def _contract_args(parser: ArgumentParser) -> None:
    _cut_args(
        parser,
        "a step is on the side its centre lies, left or right",
        "a step is on the side its centre lies, above or below",
    )
    parser.add_argument(
        "--by",
        type=float,
        metavar="DISTANCE",
        help="how far at most, in canvas units, snapped to the grid; its sign is the "
        "direction — negative pulls the far side left or up, positive the near side right "
        "or down (default: close the far side up fully)",
    )


def _tidy_args(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument(
        "--gap",
        type=int,
        default=DEFAULT_AIR,
        metavar="PITCHES",
        help="the widest gap kept between neighbouring columns or rows, in pitches "
        f"(default {DEFAULT_AIR}); a wider hole closes to one",
    )


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
            {"name": name, "steps": len(snap.steps)} for name, snap in sorted(layouts.items())
        ],
    }
    if not layouts:
        context.report(data, "no saved layouts")
        return 0
    lines = [f"{name}  ({len(snap.steps)} steps)" for name, snap in sorted(layouts.items())]
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
