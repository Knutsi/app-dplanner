"""``dplanner schedule matrix``, ``schedule focus`` and ``schedule milestone`` — staffing
the plan.

``schedule show`` prints the brackets (serial, critical path); ``matrix`` prints what lands
between them: the makespan for every staffing in a small grid of people by coding agents,
in project working days and in calendar days once a person's divided focus is priced in —
and, for one team, the milestones in sequence with the dates they land. One derivation —
``time_estimates/schedule.py``'s ``time_report`` — feeds this verb, the tab and ``--json``,
so the three can never disagree. ``focus`` and ``milestone`` store the assumptions behind
the calendar half — the same writes the tab's controls push.

The estimate, agent-step, milestone and start-date readers arrive as functions from the
composition root, the same hand-over ``progression_cli.commands(status_for=…)`` uses — no
``cli.py`` imports another module's.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from datetime import date
from typing import Any

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project, find_step, project_arg, step_arg
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Project, Step
from dplanner.domain.schedule import Phase, format_date, format_days
from dplanner.modules.time_estimates.schedule import (
    DEFAULT_EFFICIENCY,
    MODULE_ID,
    Cell,
    TimeReport,
    cell_for,
    is_color,
    phase_colors,
    read_color,
    read_efficiency,
    read_start,
    time_report,
    write_efficiency,
    write_milestone,
)


def commands(
    *,
    days_for: Callable[[Step], float | None],
    is_agent: Callable[[Step], bool],
    start_of: Callable[[Project], date],
    milestone_label: Callable[[Step], str],
) -> list[CliCommand]:
    def matrix(context: CliContext, args: Namespace) -> int:
        return _matrix(context, args, days_for, is_agent, start_of, milestone_label)

    def milestone(context: CliContext, args: Namespace) -> int:
        return _milestone(context, args, milestone_label)

    return [
        CliCommand(
            path=("schedule", "matrix"),
            summary="How long the project takes with 1-3 people and 1-4 coding agents "
            "in parallel, and when each milestone lands.",
            configure=_configure,
            run=matrix,
            examples=(
                "dplanner schedule matrix discovery",
                "dplanner schedule matrix discovery --humans 2 --agents 3",
                "dplanner schedule matrix discovery --efficiency 80 --json",
            ),
        ),
        CliCommand(
            path=("schedule", "focus"),
            summary="Set how much of a person's working day this project gets, or clear it.",
            configure=_configure_focus,
            run=_focus,
            examples=(
                "dplanner schedule focus discovery --percent 60",
                "dplanner schedule focus discovery --clear",
            ),
        ),
        CliCommand(
            path=("schedule", "milestone"),
            summary="Date a milestone's stretch of work, or colour it, instead of the "
            "sequence's own answer.",
            configure=_configure_milestone,
            run=milestone,
            examples=(
                "dplanner schedule milestone 'Ship the beta' --start 2026-10-05",
                "dplanner schedule milestone 'Ship the beta' --color '#e0602c'",
                "dplanner schedule milestone 'Ship the beta' --clear-start --clear-color",
            ),
        ),
    ]


def _configure(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("--humans", type=int, metavar="N", help="people on the project")
    parser.add_argument("--agents", type=int, metavar="N", help="coding agents in parallel")
    parser.add_argument(
        "--efficiency",
        type=float,
        metavar="PERCENT",
        help="a person's focus on this project, 1-100 — overrides the stored factor "
        "for this run",
    )


def _configure_focus(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("--percent", type=float, metavar="PERCENT", help="1-100")
    parser.add_argument(
        "--clear",
        action="store_true",
        # No "%" in argparse help text — it reads as a format specifier.
        help=f"remove the stored factor, back to the {DEFAULT_EFFICIENCY * 100:g} percent "
        "default",
    )


def _configure_milestone(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument(
        "--start", metavar="YYYY-MM-DD", help="begin this milestone's work on a date"
    )
    parser.add_argument(
        "--clear-start",
        action="store_true",
        help="begin it when the previous milestone lands again",
    )
    parser.add_argument("--color", metavar="#RRGGBB", help="the colour it wears in the calendar")
    parser.add_argument(
        "--clear-color", action="store_true", help="back to the automatic colour"
    )


def _focus(context: CliContext, args: Namespace) -> int:
    if args.clear == (args.percent is not None):
        raise CliError("give either --percent or --clear")
    if args.percent is not None and not 0 < args.percent <= 100:
        raise CliError("--percent is a percentage between 1 and 100")
    project = find_project(context.library, args.project)
    value = None if args.clear else args.percent / 100
    context.apply(SetModuleDataCommand(project.id, MODULE_ID, write_efficiency(value)))
    said = (
        f"focus back to the default, {DEFAULT_EFFICIENCY:.0%}"
        if value is None
        else f"focus {value:.0%} of a person's working days"
    )
    context.report(
        {"project": project.id, "efficiency": value if value is not None else ""},
        f"{project.title}: {said}",
    )
    return 0


def _milestone(
    context: CliContext, args: Namespace, milestone_label: Callable[[Step], str]
) -> int:
    if args.start and args.clear_start:
        raise CliError("give either --start or --clear-start")
    if args.color and args.clear_color:
        raise CliError("give either --color or --clear-color")
    if not (args.start or args.clear_start or args.color or args.clear_color):
        raise CliError("nothing to change: give --start, --clear-start, --color or --clear-color")
    step = find_step(context.library, args.step)
    if not milestone_label(step):
        raise CliError(f"{step.title!r} is not a milestone — mark it with `milestone set` first")
    start = read_start(step)
    color = read_color(step)
    if args.start:
        try:
            start = date.fromisoformat(args.start)
        except ValueError as error:
            raise CliError(f"--start is a date, YYYY-MM-DD: {args.start!r}") from error
    elif args.clear_start:
        start = None
    if args.color:
        if not is_color(args.color):
            raise CliError(f"--color is #rrggbb, not {args.color!r}")
        color = args.color.lower()
    elif args.clear_color:
        color = None
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, write_milestone(start, color)))
    said = [
        f"starts {format_date(start)}" if start else "starts when the previous lands",
        f"colour {color}" if color else "automatic colour",
    ]
    context.report(
        {
            "step": step.id,
            "start": start.isoformat() if start else "",
            "color": color or "",
        },
        f"{milestone_label(step)} ({step.title}): {', '.join(said)}",
    )
    return 0


def _matrix(
    context: CliContext,
    args: Namespace,
    days_for: Callable[[Step], float | None],
    is_agent: Callable[[Step], bool],
    start_of: Callable[[Project], date],
    milestone_label: Callable[[Step], str],
) -> int:
    if (args.humans is None) != (args.agents is None):
        raise CliError("give both --humans and --agents, or neither")
    if args.humans is not None and (args.humans < 1 or args.agents < 1):
        raise CliError("a team needs at least one of each — --humans and --agents are ≥ 1")
    if args.efficiency is not None and not 0 < args.efficiency <= 100:
        raise CliError("--efficiency is a percentage between 1 and 100")
    project = find_project(context.library, args.project)
    efficiency = (
        args.efficiency / 100 if args.efficiency is not None else read_efficiency(project)
    )
    start = start_of(project)

    def is_milestone(step: Step) -> bool:
        return bool(milestone_label(step))

    report = time_report(
        context.library,
        project,
        days_for,
        is_agent,
        start=start,
        efficiency=efficiency,
        is_milestone=is_milestone,
        start_for=read_start,
    )
    if report is None:
        context.report({"project": project.id, "steps": 0}, "No steps yet.")
        return 0
    if report.cycle:
        names = ", ".join(repr(step.title) for step in report.cycle)
        raise CliError(f"these steps wait on each other, so nothing can be dated: {names}")
    parallel, calendar = report.parallel, report.calendar
    if args.humans is not None:
        parallel, calendar = (
            (cell,)
            for cell in cell_for(
                context.library,
                project,
                days_for,
                is_agent,
                humans=args.humans,
                agents=args.agents,
                start=start,
                efficiency=efficiency,
                is_milestone=is_milestone,
                start_for=read_start,
            )
        )
    # The milestones are printed for one team: the one named, else the smallest.
    team = calendar[0]
    colors = phase_colors(team.phases, read_color)
    data: dict[str, Any] = {
        "project": project.id,
        "start": report.start.isoformat(),
        "efficiency": efficiency,
        "effort": {
            "human": report.human_days,
            "agent": report.agent_days,
            "total": report.total_days,
        },
        "unestimated": report.unestimated,
        "has_agent_steps": report.has_agent_steps,
        "floor": {"days": report.floor, "calendar_days": report.calendar_floor},
        "parallel": [
            {"humans": cell.humans, "agents": cell.agents, "days": cell.days}
            for cell in parallel
        ],
        "calendar": [
            {
                "humans": cell.humans,
                "agents": cell.agents,
                "days": cell.days,
                "finish": cell.finish.isoformat() if cell.finish else "",
            }
            for cell in calendar
        ],
        "team": {"humans": team.humans, "agents": team.agents},
        "milestones": [
            {
                "step": phase.milestone.id if phase.milestone else "",
                "label": milestone_label(phase.milestone) if phase.milestone else "",
                "steps": [step.id for step in phase.steps],
                "days": phase.days,
                "calendar_days": phase.calendar_days,
                "start": phase.start.isoformat(),
                "finish": phase.finish.isoformat() if phase.finish else "",
                "asked": phase.asked.isoformat() if phase.asked else "",
                "pushed": phase.pushed,
                "color": color,
            }
            for phase, color in zip(team.phases, colors, strict=True)
        ],
    }
    context.report(
        data, _report(project.title, report, parallel, calendar, team, milestone_label)
    )
    return 0


def _grid(cells: tuple[Cell, ...], text: Callable[[Cell], str]) -> list[str]:
    """The cells as rows of people by columns of agents, widths computed per column."""
    humans = sorted({cell.humans for cell in cells})
    agents = sorted({cell.agents for cell in cells})
    at = {(cell.humans, cell.agents): text(cell) for cell in cells}
    labels = [f"{count} {'human' if count == 1 else 'humans'}" for count in humans]
    head = [f"{count} {'agent' if count == 1 else 'agents'}" for count in agents]
    widths = [
        max(len(head[column]), *(len(at[(row, agents[column])]) for row in humans))
        for column in range(len(agents))
    ]
    label_width = max(len(label) for label in labels)
    titles = zip(head, widths, strict=True)
    lines = ["  ".join([" " * label_width, *(title.rjust(width) for title, width in titles)])]
    for row, label in zip(humans, labels, strict=True):
        lines.append(
            "  ".join(
                [
                    label.ljust(label_width),
                    *(
                        at[(row, column)].rjust(width)
                        for column, width in zip(agents, widths, strict=True)
                    ),
                ]
            )
        )
    return lines


def _phase_line(phase: Phase, milestone_label: Callable[[Step], str]) -> str:
    name = milestone_label(phase.milestone) if phase.milestone else "remaining work"
    when = (
        f"{format_date(phase.start)} → {format_date(phase.finish)}"
        if phase.finish
        else f"from {format_date(phase.start)}, nothing estimated"
    )
    said = f"{name}: {when} ({format_days(phase.calendar_days)}, {len(phase.steps)} steps)"
    if phase.pushed and phase.asked is not None:
        said += f" — asked for {format_date(phase.asked)}, but the previous lands later"
    return said


def _report(
    title: str,
    report: TimeReport,
    parallel: tuple[Cell, ...],
    calendar: tuple[Cell, ...],
    team: Cell,
    milestone_label: Callable[[Step], str],
) -> str:
    head = (
        f"{title}: {format_days(report.total_days)} of work — "
        f"{format_days(report.human_days)} human, {format_days(report.agent_days)} agent; "
        f"dependency floor {format_days(report.floor)}"
    )
    if report.unestimated:
        head += f"; {report.unestimated} unestimated (they run as zero days here)"
    lines = [head, "", "Parallel-adjusted (working days of project time)"]
    lines += _grid(parallel, lambda cell: format_days(cell.days))
    lines += [
        "",
        f"Calendar (at {report.efficiency:.0%} focus, from {format_date(report.start)}; "
        "cells are days and landing dates)",
    ]
    lines += _grid(
        calendar,
        lambda cell: format_days(cell.days)
        + (f" · {format_date(cell.finish)}" if cell.finish else ""),
    )
    people = f"{team.humans} {'person' if team.humans == 1 else 'people'}"
    lines += ["", f"Milestones in sequence ({people} + {team.agents} agents)"]
    lines += [f"  {_phase_line(phase, milestone_label)}" for phase in team.phases]
    if not report.has_agent_steps:
        lines += ["", "No agent steps — agent capacity does not change these numbers."]
    return "\n".join(lines)
