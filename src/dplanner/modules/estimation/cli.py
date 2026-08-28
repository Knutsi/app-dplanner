"""``dplanner estimate …`` and ``dplanner schedule …`` — sizing the work, and dating it.

Two nouns because they are two questions. ``estimate`` is about one step and what it costs;
``schedule`` is about a project and when its steps land. The second is a report over the
first plus a start date, and it renders through the same formatters the window's order table
uses, so the terminal and the window cannot show one total two ways.
"""

from argparse import ArgumentParser, Namespace
from datetime import date
from typing import Any

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lint import LintCheck, LintFinding
from dplanner.cli.lookup import find_project, find_step
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Product, Project
from dplanner.domain.schedule import Scheduled, format_date, format_days
from dplanner.modules.estimation.aspect import MODULE_ID, read, write
from dplanner.modules.estimation.schedule import (
    finish_date,
    project_schedule,
    read_start,
    start_of,
    write_start,
)


def lint_checks() -> list[LintCheck]:
    def missing_estimates(_product: Product, project: Project) -> list[LintFinding]:
        findings = [
            LintFinding(
                check="estimate.missing",
                subject_id=step.id,
                subject=step.title,
                message=f"no estimate — `dplanner estimate set '{step.title}' --days N`",
            )
            for step in project.steps
            if read(step) is None
        ]
        # A start date only matters once somebody has started sizing the work; flagging it
        # on every unestimated project would be noise.
        if read_start(project) is None and any(read(step) is not None for step in project.steps):
            findings.append(
                LintFinding(
                    check="schedule.start-missing",
                    subject_id=project.id,
                    subject=project.title,
                    message="estimates but no start date — "
                    f"`dplanner schedule start '{project.title}' --date YYYY-MM-DD`",
                )
            )
        return findings

    return [missing_estimates]


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("estimate", "set"),
            summary="Say how many working days a step is thought to take.",
            configure=_configure_set,
            run=_set,
            examples=("dplanner estimate set 'Read the spec' --days 3",),
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
        CliCommand(
            path=("schedule", "start"),
            summary="Set the date a project's work begins, or clear it.",
            configure=_configure_start,
            run=_start,
            examples=(
                "dplanner schedule start discovery --date 2026-09-01",
                "dplanner schedule start discovery --clear",
            ),
        ),
        CliCommand(
            path=("schedule", "show"),
            summary="When each step lands, in the order the work can be done.",
            configure=_one_project,
            run=_show,
            examples=(
                "dplanner schedule show discovery",
                "dplanner schedule show discovery --json",
            ),
        ),
    ]


def _one_step(parser: ArgumentParser) -> None:
    parser.add_argument("step", help="step id, folder name, or part of its title")


def _one_project(parser: ArgumentParser) -> None:
    parser.add_argument("project", help="project id, folder name, or part of its title")


def _configure_set(parser: ArgumentParser) -> None:
    _one_step(parser)
    parser.add_argument("--days", type=float, required=True, help="working days")


def _configure_start(parser: ArgumentParser) -> None:
    _one_project(parser)
    parser.add_argument("--date", help="ISO-8601, e.g. 2026-09-01")
    parser.add_argument(
        "--clear", action="store_true", help="remove the start date, so it starts today"
    )


def _set(context: CliContext, args: Namespace) -> int:
    if args.days < 0:
        raise CliError("an estimate cannot be negative")
    step = find_step(context.product, args.step)
    entry = write(args.days)
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
    total = sum(days for days in estimates if days is not None)
    missing = sum(1 for days in estimates if days is None)
    data = {
        "project": project.id,
        "days": total,
        "steps": len(project.steps),
        "unestimated": missing,
    }
    tail = f", {missing} unestimated" if missing else ""
    context.report(data, f"{project.title}: {total:g} days over {len(project.steps)} steps{tail}")
    return 0


def _start(context: CliContext, args: Namespace) -> int:
    if args.clear == bool(args.date):
        raise CliError("give either --date or --clear")
    start = None
    if args.date:
        try:
            start = date.fromisoformat(args.date)
        except ValueError as error:
            raise CliError(f"{args.date!r} is not an ISO-8601 date, e.g. 2026-09-01") from error
    project = find_project(context.product, args.project)
    context.apply(SetModuleDataCommand(project.id, MODULE_ID, write_start(start)))
    said = (
        f"starts today, {format_date(date.today())}"
        if start is None
        else f"starts {format_date(start)}"
    )
    written = "" if start is None else start.isoformat()
    context.report({"project": project.id, "start": written}, f"{project.title}: {said}")
    return 0


def _show(context: CliContext, args: Namespace) -> int:
    """The schedule: the order walk, carrying estimates instead of counting hops."""
    project = find_project(context.product, args.project)
    rows = project_schedule(context.product, project)
    start = start_of(project)
    unestimated = sum(1 for row in rows if row.days is None)
    landing = finish_date(rows)
    data: dict[str, Any] = {
        "project": project.id,
        "start": start.isoformat(),
        "finish": landing.isoformat() if landing else "",
        "days": rows[-1].accumulated if rows else 0.0,
        "unestimated": unestimated,
        "steps": [
            {
                "index": row.place.index,
                "id": row.place.step.id,
                "title": row.place.step.title,
                "days": row.days,
                "accumulated": row.accumulated,
                "date": row.finish.isoformat() if row.finish else "",
            }
            for row in rows
        ],
    }
    context.report(data, _report(project.title, rows, landing, unestimated))
    return 0


def _report(
    title: str,
    rows: list[Scheduled],
    landing: date | None,
    unestimated: int,
) -> str:
    """The same columns the order table shows, through the same formatter."""
    if not rows:
        return "No steps yet."
    width = max(len(row.place.step.title or "Untitled step") for row in rows)
    lines = [
        f"{row.place.index:>3}  {(row.place.step.title or 'Untitled step'):<{width}}  "
        f"{format_days(row.days):>6}  {format_days(row.accumulated):>6}  "
        f"{format_date(row.finish) if row.finish else ''}"
        for row in rows
    ]
    tail = f"{format_days(rows[-1].accumulated)} of work"
    if landing is not None:
        tail += f", landing {format_date(landing)}"
    if unestimated:
        tail += f", {unestimated} unestimated"
    return "\n".join([*lines, "", f"{title}: {tail}"])
