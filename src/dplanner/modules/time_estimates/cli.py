"""``dplanner schedule matrix`` and ``schedule focus`` — staffing the plan.

``schedule show`` prints the brackets (serial, critical path); this prints what lands
between them: the makespan for every staffing in a small grid of people by coding agents,
in project working days and in calendar days once a person's divided focus is priced in.
One derivation — ``time_estimates/schedule.py``'s ``time_report`` — feeds this verb, the
tab and ``--json``, so the three can never disagree. ``schedule focus`` stores the one
assumption behind the calendar half — the same write the tab's spinbox pushes.

The estimate, agent-step and start-date readers arrive as functions from the composition
root, the same hand-over ``progression_cli.commands(status_for=…)`` uses — no ``cli.py``
imports another module's.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from datetime import date
from typing import Any

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project, project_arg
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Project, Step
from dplanner.domain.schedule import (
    format_date,
    format_days,
    parallel_finish,
    working_days_after,
)
from dplanner.modules.time_estimates.schedule import (
    DEFAULT_EFFICIENCY,
    MODULE_ID,
    Cell,
    TimeReport,
    read_efficiency,
    stretched,
    time_report,
    write_efficiency,
)


def commands(
    *,
    days_for: Callable[[Step], float | None],
    is_agent: Callable[[Step], bool],
    start_of: Callable[[Project], date],
) -> list[CliCommand]:
    def matrix(context: CliContext, args: Namespace) -> int:
        return _matrix(context, args, days_for, is_agent, start_of)

    return [
        CliCommand(
            path=("schedule", "matrix"),
            summary="How long the project takes with 1-3 people and 1-4 coding agents "
            "in parallel.",
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


def _matrix(
    context: CliContext,
    args: Namespace,
    days_for: Callable[[Step], float | None],
    is_agent: Callable[[Step], bool],
    start_of: Callable[[Project], date],
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
    report = time_report(
        context.library, project, days_for, is_agent, start=start, efficiency=efficiency
    )
    if report is None:
        context.report({"project": project.id, "steps": 0}, "No steps yet.")
        return 0
    parallel, calendar = report.parallel, report.calendar
    if args.humans is not None:
        parallel, calendar = _one_scenario(
            context, project, args, days_for, is_agent, start, efficiency
        )
    data: dict[str, Any] = {
        "project": project.id,
        "start": start.isoformat(),
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
    }
    context.report(data, _report(project.title, report, parallel, calendar))
    return 0


def _one_scenario(
    context: CliContext,
    project: Project,
    args: Namespace,
    days_for: Callable[[Step], float | None],
    is_agent: Callable[[Step], bool],
    start: date,
    efficiency: float,
) -> tuple[tuple[Cell, ...], tuple[Cell, ...]]:
    """The asked-for staffing alone — the flags may name a team outside the grid."""
    raw = parallel_finish(
        context.library, project, days_for, is_agent, humans=args.humans, agents=args.agents
    )
    slow = parallel_finish(
        context.library,
        project,
        stretched(days_for, is_agent, efficiency),
        is_agent,
        humans=args.humans,
        agents=args.agents,
    )
    assert raw is not None and slow is not None  # the caller checked project.steps
    landing = working_days_after(start, slow.days) if slow.days > 0 else None
    return (
        (Cell(humans=args.humans, agents=args.agents, days=raw.days),),
        (Cell(humans=args.humans, agents=args.agents, days=slow.days, finish=landing),),
    )


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


def _report(
    title: str,
    report: TimeReport,
    parallel: tuple[Cell, ...],
    calendar: tuple[Cell, ...],
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
    if not report.has_agent_steps:
        lines += ["", "No agent steps — agent capacity does not change these numbers."]
    return "\n".join(lines)
