"""``dplanner estimate …`` and ``dplanner schedule …`` — sizing the work, and dating it.

Two nouns because they are two questions. ``estimate`` is about one step and what it costs;
``schedule`` is about a project and when its steps land. The second is a report over the
first plus a start date, and it renders through the same formatters the window's order table
uses, so the terminal and the window cannot show one total two ways.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from datetime import date
from typing import Any

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.authoring import StepAuthor, StepAuthored
from dplanner.cli.lint import LintCheck, LintFinding
from dplanner.cli.lookup import find_project, find_step, project_arg, step_arg
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.schedule import (
    CriticalPath,
    Scheduled,
    format_date,
    format_day_count,
    format_days,
    volume,
    volume_words,
)
from dplanner.domain.shelf import turn_off
from dplanner.domain.store import FilesFor
from dplanner.modules.estimation.aspect import MODULE_ID, enabled, read, read_history, write
from dplanner.modules.estimation.schedule import (
    critical_finish,
    finish_date,
    project_critical_path,
    project_schedule,
    read_start,
    start_of,
    write_start,
)


def step_author() -> StepAuthor:
    """`step add`'s estimate flag: the new step arrives already sized."""

    def configure(parser: ArgumentParser) -> None:
        parser.add_argument(
            "--days",
            type=float,
            metavar="N",
            help="working days the new step is thought to take",
        )

    def author(context: CliContext, step: Step, args: Namespace) -> StepAuthored | None:
        if args.days is None:
            return None
        if args.days < 0:
            raise CliError("an estimate cannot be negative")
        context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(args.days)))
        return StepAuthored({"days": args.days}, f"estimate: {format_day_count(args.days)}")

    return StepAuthor(configure, author)


def lint_checks(*, counts_as_work: Callable[[Step], bool]) -> list[LintCheck]:
    def missing_estimates(
        _product: Library, project: Project, _files: FilesFor
    ) -> list[LintFinding]:
        findings = [
            LintFinding(
                check="estimate.missing",
                subject_id=step.id,
                subject=step.title,
                message=f"no estimate — `dplanner estimate set '{step.title}' --days N`",
            )
            for step in project.steps
            # A step that has turned the aspect off is not missing an estimate; it has
            # said it has no work of its own, and a wait has none. Lint reports gaps, not
            # decisions.
            if enabled(step) and read(step) is None and counts_as_work(step)
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


def commands(*, counts_as_work: Callable[[Step], bool]) -> list[CliCommand]:
    """``counts_as_work`` says a wait is no work — no part of a total, never unestimated."""

    def rollup(context: CliContext, args: Namespace) -> int:
        return _rollup(context, args, counts_as_work)

    def show(context: CliContext, args: Namespace) -> int:
        return _show(context, args, counts_as_work)

    return [
        CliCommand(
            path=("estimate", "set"),
            summary="Say how many working days a step is thought to take.",
            configure=_configure_set,
            run=_set,
            examples=("dplanner estimate set 'Read the spec' --days 3",),
        ),
        CliCommand(
            path=("estimate", "show"),
            summary="A step's estimate, and every value it had before with the day it changed.",
            configure=step_arg,
            run=_estimate_show,
            examples=("dplanner estimate show S7",),
        ),
        CliCommand(
            path=("estimate", "clear"),
            summary="This step has no size of its own — a milestone, say. Stops lint asking.",
            configure=step_arg,
            run=_clear,
            examples=("dplanner estimate clear 'Read the spec'",),
        ),
        CliCommand(
            path=("estimate", "rollup"),
            summary="Total a project's estimates, and count what is still unestimated.",
            configure=project_arg,
            run=rollup,
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
            configure=project_arg,
            run=show,
            examples=(
                "dplanner schedule show discovery",
                "dplanner schedule show discovery --json",
            ),
        ),
    ]


def _configure_set(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument("--days", type=float, required=True, help="working days")


def _configure_start(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("--date", help="ISO-8601, e.g. 2026-09-01")
    parser.add_argument(
        "--clear", action="store_true", help="remove the start date, so it starts today"
    )


def _set(context: CliContext, args: Namespace) -> int:
    if args.days < 0:
        raise CliError("an estimate cannot be negative")
    step = find_step(context.library, args.step, context.current)
    entry = write(args.days, previous=step.module_data.get(MODULE_ID), today=context.clock.today())
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, entry))
    context.report({"step": step.id} | entry, f"{step.title}: {format_day_count(args.days)}")
    return 0


def _estimate_show(context: CliContext, args: Namespace) -> int:
    """The estimate as it stands, and what it was before — one line per day it changed."""
    step = find_step(context.library, args.step, context.current)
    days = read(step)
    history = read_history(step)
    data = {
        "step": step.id,
        "days": days,
        "on": enabled(step),
        "history": [{"day": when.isoformat(), "days": was} for when, was in history],
    }
    said = (
        f"{step.title}: {format_day_count(days)}"
        if days is not None
        else f"{step.title}: " + ("unestimated" if enabled(step) else "no estimate — no work")
    )
    lines = [said] + [
        f"  was {format_day_count(was)} until {format_date(when)}" for when, was in history
    ]
    context.report(data, "\n".join(lines))
    return 0


def _clear(context: CliContext, args: Namespace) -> int:
    """The opt-out, and the CLI half of the GUI's Type ▸ Estimate toggle.

    An estimate defaults to *on*, so removing the entry would only mean "not sized yet" and
    lint would keep asking. What a person means by clearing it on a milestone is that the
    step has no work of its own, and that is what gets written.
    """
    step = find_step(context.library, args.step, context.current)
    message = f"{step.title}: no estimate — this step has no work"
    if not enabled(step):
        # Already clear is success, and writes nothing: a state-clearing verb must survive
        # a batch without dirtying a project it had no change to make to.
        context.report({"step": step.id}, message)
        return 0
    context.apply(
        turn_off(step.id, MODULE_ID, leaving=write(None, on=False), label="Remove Estimate")
    )
    context.report({"step": step.id}, message)
    return 0


def _rollup(context: CliContext, args: Namespace, counts_as_work: Callable[[Step], bool]) -> int:
    """A total, plus how much of it is a guess.

    The count of unestimated steps is not decoration: a total that silently treats them as
    zero understates the plan, and the person reading it has no way to tell.
    """
    project = find_project(context.library, args.project)
    total, steps, missing = volume(project.steps, read, counts_as_work)
    data = {"project": project.id, "days": total, "steps": steps, "unestimated": missing}
    context.report(data, f"{project.title}: {volume_words(total, steps, missing)}")
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
    project = find_project(context.library, args.project)
    context.apply(SetModuleDataCommand(project.id, MODULE_ID, write_start(start)))
    today = context.clock.today()
    said = (
        f"starts today, {format_date(today, today)}"
        if start is None
        else f"starts {format_date(start, today)}"
    )
    written = "" if start is None else start.isoformat()
    context.report({"project": project.id, "start": written}, f"{project.title}: {said}")
    return 0


def _show(context: CliContext, args: Namespace, counts_as_work: Callable[[Step], bool]) -> int:
    """The schedule: the order walk carrying estimates, under both honest assumptions.

    The serial total and the critical path bracket every real staffing, so both are
    always printed, each labelled with the assumption it makes — a single number here
    would be a guess wearing a date.
    """
    project = find_project(context.library, args.project)
    rows = project_schedule(context.library, project)
    start = start_of(project)
    unestimated = sum(1 for row in rows if row.days is None and counts_as_work(row.place.step))
    landing = finish_date(rows)
    path = project_critical_path(context.library, project)
    path_landing = critical_finish(project, path) if path is not None else None
    data: dict[str, Any] = {
        "project": project.id,
        "start": start.isoformat(),
        "finish": landing.isoformat() if landing else "",
        "days": rows[-1].accumulated if rows else 0.0,
        "assumption": "serial",  # What the finish/days/accumulated keys mean.
        "unestimated": unestimated,
        "critical_path": None
        if path is None
        else {
            "days": path.days,
            "finish": path_landing.isoformat() if path_landing else "",
            "steps": [{"id": step.id, "title": step.title} for step in path.steps],
            "unestimated": path.unestimated,
        },
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
    context.report(data, _report(project.title, rows, landing, unestimated, path, path_landing))
    return 0


def _report(
    title: str,
    rows: list[Scheduled],
    landing: date | None,
    unestimated: int,
    path: CriticalPath | None,
    path_landing: date | None,
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
    tail += " (serial: one worker, steps end to end)"
    if unestimated:
        tail += f", {unestimated} unestimated"
    summary = [f"{title}: {tail}"]
    if path is not None:
        chain = " → ".join(step.title or "Untitled step" for step in path.steps)
        second = f"critical path: {format_days(path.days)}"
        if path_landing is not None:
            second += f", landing {format_date(path_landing)}"
        second += f" (dependency-aware: unlimited workers) — {chain}"
        if path.unestimated:
            second += f", {path.unestimated} unestimated on the path"
        summary.append(second)
    return "\n".join([*lines, "", *summary])
