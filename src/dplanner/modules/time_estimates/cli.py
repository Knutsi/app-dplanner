"""``dplanner schedule matrix``, ``schedule focus``, ``schedule palette``, ``schedule
team``, ``schedule milestone`` — staffing the plan — and ``dplanner progress show``,
``progress record``, ``progress save``, ``progress list`` and ``progress remove`` — how
far it has come, and the snapshots that say how far it said it would.

``schedule show`` prints the brackets (serial, critical path); ``matrix`` prints what lands
between them: the makespan for every staffing in a small grid of people by coding agents,
in project working days and in calendar days once a person's divided focus is priced in —
and, for the project's team, the milestones in sequence with the dates they land. One
derivation — ``time_estimates/schedule.py``'s ``time_report`` — feeds this verb, the tab
and ``--json``, so the three can never disagree. ``focus``, ``palette``, ``team`` and
``milestone`` store the assumptions behind the calendar half — the same writes the tab's
controls push.

``progress show`` prints what has landed toward each milestone, by estimated days,
against the plan it is compared with — the plan at the project's start unless
``--basis`` names a day, a saved snapshot or ``now`` — and how the plan moved since:
steps and days added, the landing shifted, and which steps were added or re-estimated
after it; ``--as-of`` reads the now side from a saved snapshot or a day instead of the
live plan, and the volume the plan came to on each recorded day is printed with it.
``progress record`` writes today's row of the automatic history — what the window does
by itself after every settled change, for a plan driven from the terminal — and
``progress save`` keeps today's plan under a title on purpose, for ``list`` to print and
``--basis`` to name (``progress.py`` has the shape and the reasoning).

The estimate, agent-step, status, milestone and start-date readers arrive as functions
from the composition root, the same hand-over ``progression_cli.commands(status_for=…)``
uses — no ``cli.py`` imports another module's.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project, find_step, project_arg, step_arg
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Project, Step
from dplanner.domain.schedule import Phase, format_date, format_days
from dplanner.modules.time_estimates.progress import (
    AT_START,
    HISTORY_ID,
    LIVE,
    Delta,
    Pick,
    Snapshot,
    Tally,
    actual,
    changes_since,
    delta,
    delta_words,
    expected,
    find_saved,
    idle,
    pick_words,
    read_history,
    read_saved,
    recorded,
    remaining,
    resolve,
    saved_with,
    saved_without,
    take,
    volume,
    write_history,
)
from dplanner.modules.time_estimates.schedule import (
    DEFAULT_EFFICIENCY,
    DEFAULT_TEAM,
    MODULE_ID,
    Cell,
    TimeReport,
    cell_for,
    is_color,
    milestone_colors,
    phase_colors,
    read_color,
    read_efficiency,
    read_palette,
    read_start,
    read_team,
    time_report,
    write_milestone,
    write_project,
)
from dplanner.theme.palettes import PALETTES, palette, shades


@dataclass(frozen=True)
class Readers:
    """The other modules' Qt-free readers a verb here needs, handed over by the root."""

    days_for: Callable[[Step], float | None]
    is_agent: Callable[[Step], bool]
    status_for: Callable[[Step], str]
    start_of: Callable[[Project], date]
    milestone_label: Callable[[Step], str]
    # What a step's estimate was before, each with the day it changed — the change report.
    estimate_history: Callable[[Step], list[tuple[date, float]]]
    key_of: Callable[[Step], str]

    def is_milestone(self, step: Step) -> bool:
        return bool(self.milestone_label(step))


def commands(
    *,
    days_for: Callable[[Step], float | None],
    is_agent: Callable[[Step], bool],
    status_for: Callable[[Step], str],
    start_of: Callable[[Project], date],
    milestone_label: Callable[[Step], str],
    estimate_history: Callable[[Step], list[tuple[date, float]]],
    key_of: Callable[[Step], str],
) -> list[CliCommand]:
    readers = Readers(
        days_for, is_agent, status_for, start_of, milestone_label, estimate_history, key_of
    )

    def matrix(context: CliContext, args: Namespace) -> int:
        return _matrix(context, args, readers)

    def milestone(context: CliContext, args: Namespace) -> int:
        return _milestone(context, args, milestone_label)

    def progress_show(context: CliContext, args: Namespace) -> int:
        return _progress_show(context, args, readers)

    def progress_record(context: CliContext, args: Namespace) -> int:
        return _progress_record(context, args, readers)

    def progress_save(context: CliContext, args: Namespace) -> int:
        return _progress_save(context, args, readers)

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
            path=("schedule", "palette"),
            summary="Choose the colour map the milestones are shaded from, or see the choices.",
            configure=_configure_palette,
            run=_palette,
            examples=(
                "dplanner schedule palette discovery",
                "dplanner schedule palette discovery mako",
            ),
        ),
        CliCommand(
            path=("schedule", "team"),
            summary="Set the team the calendar is dated for — people and coding agents — "
            "or clear it back to the smallest.",
            configure=_configure_team,
            run=_team,
            examples=(
                "dplanner schedule team discovery --humans 2 --agents 3",
                "dplanner schedule team discovery --clear",
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
        CliCommand(
            path=("progress", "show"),
            summary="How far the plan has come toward each milestone, by estimated days, "
            "against the plan as it stood at the start — or at --basis, a day or a saved "
            "snapshot — what changed since, and the volume the plan came to over time.",
            configure=_configure_progress,
            run=progress_show,
            examples=(
                "dplanner progress show discovery",
                "dplanner progress show discovery --milestone v2 --basis 2026-09-15 --json",
                "dplanner progress show discovery --basis 'Kickoff review' --as-of 'Review 2'",
            ),
        ),
        CliCommand(
            path=("progress", "record"),
            summary="Record today's progress and landing dates in the project's history, "
            "when they changed — the window does this itself while it is open.",
            configure=project_arg,
            run=progress_record,
            examples=("dplanner progress record discovery",),
        ),
        CliCommand(
            path=("progress", "save"),
            summary="Keep the plan as it stands today under a title, to compare against "
            "later — the outlook at a review, the day the ground was broken.",
            configure=_configure_save,
            run=progress_save,
            examples=(
                "dplanner progress save discovery 'Kickoff review'",
                "dplanner progress save discovery 'Kickoff' --note 'What we thought on 1 Nov'",
            ),
        ),
        CliCommand(
            path=("progress", "list"),
            summary="The saved snapshots, and how many days the history has recorded.",
            configure=project_arg,
            run=_progress_list,
            examples=("dplanner progress list discovery",),
        ),
        CliCommand(
            path=("progress", "remove"),
            summary="Forget a saved snapshot by its title.",
            configure=_configure_remove,
            run=_progress_remove,
            examples=("dplanner progress remove discovery 'Kickoff review'",),
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
        help="a person's focus on this project, 1-100 — overrides the stored factor for this run",
    )


def _configure_focus(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("--percent", type=float, metavar="PERCENT", help="1-100")
    parser.add_argument(
        "--clear",
        action="store_true",
        # No "%" in argparse help text — it reads as a format specifier.
        help=f"remove the stored factor, back to the {DEFAULT_EFFICIENCY * 100:g} percent default",
    )


def _configure_palette(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument(
        "name",
        nargs="?",
        metavar="PALETTE",
        help="one of " + ", ".join(found.id for found in PALETTES) + "; omitted, prints them",
    )


def _configure_team(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("--humans", type=int, metavar="N", help="people on the project")
    parser.add_argument("--agents", type=int, metavar="N", help="coding agents in parallel")
    parser.add_argument(
        "--clear",
        action="store_true",
        help=f"back to the smallest team, {DEFAULT_TEAM[0]} person + {DEFAULT_TEAM[1]} agent",
    )


def _configure_progress(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument(
        "--milestone", metavar="STEP", help="one milestone; omitted, every milestone in turn"
    )
    parser.add_argument(
        "--basis",
        metavar="DAY|TITLE",
        help="compare against the plan as recorded on this day (YYYY-MM-DD), a saved "
        "snapshot's title, 'start' or 'now' (default: the project's start)",
    )
    parser.add_argument(
        "--as-of",
        dest="as_of",
        metavar="DAY|TITLE",
        help="read the plan now from a saved snapshot or a recorded day instead of the live plan",
    )


def _configure_save(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("title", help="what the snapshot is called — found by this later")
    parser.add_argument("--note", default="", help="what the occasion was")


def _configure_remove(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("title", help="the saved snapshot's title")


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
    parser.add_argument("--clear-color", action="store_true", help="back to the automatic colour")


def _focus(context: CliContext, args: Namespace) -> int:
    if args.clear == (args.percent is not None):
        raise CliError("give either --percent or --clear")
    if args.percent is not None and not 0 < args.percent <= 100:
        raise CliError("--percent is a percentage between 1 and 100")
    project = find_project(context.library, args.project)
    value = None if args.clear else args.percent / 100
    entry = (
        write_project(project, clear="efficiency")
        if value is None
        else write_project(project, efficiency=value)
    )
    context.apply(SetModuleDataCommand(project.id, MODULE_ID, entry))
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


def _palette(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    current = read_palette(project)
    choices = [
        {"id": found.id, "name": found.name, "shades": shades(found, 4)} for found in PALETTES
    ]
    if args.name is None:
        listed = "\n".join(
            f"  {'*' if found.id == current.id else ' '} {found.id:<8} {found.name}"
            for found in PALETTES
        )
        context.report(
            {"project": project.id, "palette": current.id, "palettes": choices},
            f"{project.title}: milestones shaded from {current.name}\n{listed}",
        )
        return 0
    chosen = palette(args.name)
    if chosen.id != args.name:
        raise CliError(
            f"no palette called {args.name!r} — one of " + ", ".join(found.id for found in PALETTES)
        )
    context.apply(
        SetModuleDataCommand(project.id, MODULE_ID, write_project(project, palette_id=chosen.id))
    )
    context.report(
        {"project": project.id, "palette": chosen.id, "palettes": choices},
        f"{project.title}: milestones shaded from {chosen.name}",
    )
    return 0


def _team(context: CliContext, args: Namespace) -> int:
    named = args.humans is not None or args.agents is not None
    if args.clear == named:
        raise CliError("give both --humans and --agents, or --clear")
    if named and (args.humans is None or args.agents is None):
        raise CliError("give both --humans and --agents")
    if named and (args.humans < 1 or args.agents < 1):
        raise CliError("a team needs at least one of each — --humans and --agents are ≥ 1")
    project = find_project(context.library, args.project)
    entry = (
        write_project(project, clear="team")
        if args.clear
        else write_project(project, team=(args.humans, args.agents))
    )
    context.apply(SetModuleDataCommand(project.id, MODULE_ID, entry))
    humans, agents = read_team(project)
    context.report(
        {"project": project.id, "team": {"humans": humans, "agents": agents}},
        f"{project.title}: the calendar is dated for {_people(humans, agents)}",
    )
    return 0


def _people(humans: int, agents: int) -> str:
    people = f"{humans} {'person' if humans == 1 else 'people'}"
    return f"{people} + {agents} {'agent' if agents == 1 else 'agents'}"


def _milestone(context: CliContext, args: Namespace, milestone_label: Callable[[Step], str]) -> int:
    if args.start and args.clear_start:
        raise CliError("give either --start or --clear-start")
    if args.color and args.clear_color:
        raise CliError("give either --color or --clear-color")
    if not (args.start or args.clear_start or args.color or args.clear_color):
        raise CliError("nothing to change: give --start, --clear-start, --color or --clear-color")
    step = find_step(context.library, args.step, context.current)
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


def _matrix(context: CliContext, args: Namespace, readers: Readers) -> int:
    if (args.humans is None) != (args.agents is None):
        raise CliError("give both --humans and --agents, or neither")
    if args.humans is not None and (args.humans < 1 or args.agents < 1):
        raise CliError("a team needs at least one of each — --humans and --agents are ≥ 1")
    if args.efficiency is not None and not 0 < args.efficiency <= 100:
        raise CliError("--efficiency is a percentage between 1 and 100")
    project = find_project(context.library, args.project)
    days_for, is_agent = readers.days_for, readers.is_agent
    milestone_label, is_milestone = readers.milestone_label, readers.is_milestone
    efficiency = args.efficiency / 100 if args.efficiency is not None else read_efficiency(project)
    start = readers.start_of(project)
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
    # The milestones are printed for one team: the one named, else the project's own.
    stored = read_team(project)
    team = next((cell for cell in calendar if (cell.humans, cell.agents) == stored), calendar[0])
    colors = phase_colors(team.phases, milestone_colors(context.library, project, is_milestone))
    data: dict[str, Any] = {
        "project": project.id,
        "start": report.start.isoformat(),
        "efficiency": efficiency,
        "palette": read_palette(project).id,
        "effort": {
            "human": report.human_days,
            "agent": report.agent_days,
            "total": report.total_days,
        },
        "unestimated": report.unestimated,
        "has_agent_steps": report.has_agent_steps,
        "floor": {"days": report.floor, "calendar_days": report.calendar_floor},
        "parallel": [
            {"humans": cell.humans, "agents": cell.agents, "days": cell.days} for cell in parallel
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
    context.report(data, _report(project.title, report, parallel, calendar, team, milestone_label))
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
        lambda cell: (
            format_days(cell.days) + (f" · {format_date(cell.finish)}" if cell.finish else "")
        ),
    )
    people = f"{team.humans} {'person' if team.humans == 1 else 'people'}"
    lines += ["", f"Milestones in sequence ({people} + {team.agents} agents)"]
    lines += [f"  {_phase_line(phase, milestone_label)}" for phase in team.phases]
    if not report.has_agent_steps:
        lines += ["", "No agent steps — agent capacity does not change these numbers."]
    return "\n".join(lines)


# -- progress -----------------------------------------------------------------------------------


def _snapshot(
    context: CliContext, project: Project, readers: Readers, today: date
) -> Snapshot | None:
    humans, agents = read_team(project)
    return take(
        context.library,
        project,
        readers.days_for,
        readers.is_agent,
        readers.status_for,
        humans=humans,
        agents=agents,
        start=readers.start_of(project),
        efficiency=read_efficiency(project),
        is_milestone=readers.is_milestone,
        start_for=read_start,
        today=today,
    )


def _progress_record(context: CliContext, args: Namespace, readers: Readers) -> int:
    project = find_project(context.library, args.project)
    now = _snapshot(context, project, readers, date.today())
    if now is None:
        raise CliError("nothing to record — the project has no steps, or cannot be dated")
    rows = recorded(read_history(project), now)
    if rows is None:
        context.report(
            {"project": project.id, "day": now.day.isoformat(), "outcome": "unchanged"},
            f"{project.title}: nothing changed since the last record",
        )
        return 0
    context.apply(
        SetModuleDataCommand(project.id, HISTORY_ID, write_history(rows, read_saved(project)))
    )
    context.report(
        {"project": project.id, "day": now.day.isoformat(), "outcome": "recorded"},
        f"{project.title}: progress recorded for {format_date(now.day)}",
    )
    return 0


def _progress_save(context: CliContext, args: Namespace, readers: Readers) -> int:
    project = find_project(context.library, args.project)
    now = _snapshot(context, project, readers, date.today())
    if now is None:
        raise CliError("nothing to save — the project has no steps, or cannot be dated")
    try:
        saved = saved_with(read_saved(project), now, args.title, args.note)
    except ValueError as error:
        raise CliError(str(error)) from error
    context.apply(
        SetModuleDataCommand(project.id, HISTORY_ID, write_history(read_history(project), saved))
    )
    kept = saved[-1]
    context.report(
        {"project": project.id, "title": kept.title, "day": kept.day.isoformat()},
        f"{project.title}: saved the plan as of {format_date(kept.day)} as {kept.title!r}",
    )
    return 0


def _progress_list(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    saved = read_saved(project)
    history = read_history(project)
    lines = [
        f"  {row.title} · {format_date(row.day)}" + (f" — {row.note}" if row.note else "")
        for row in saved
    ]
    said = (
        f"{project.title}: {len(saved)} saved snapshot{'s' if len(saved) != 1 else ''}, "
        f"{len(history)} day{'s' if len(history) != 1 else ''} recorded"
    )
    context.report(
        {
            "project": project.id,
            "saved": [_saved_row(row) for row in saved],
            "recorded_days": len(history),
        },
        "\n".join([said, *lines]),
    )
    return 0


def _progress_remove(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    saved = read_saved(project)
    kept = saved_without(saved, args.title)
    if len(kept) != len(saved):
        context.apply(
            SetModuleDataCommand(project.id, HISTORY_ID, write_history(read_history(project), kept))
        )
    context.report(
        {"project": project.id, "title": args.title, "removed": len(kept) != len(saved)},
        f"{project.title}: forgot {args.title!r}"
        if len(kept) != len(saved)
        else f"{project.title}: no snapshot called {args.title!r} — nothing to forget",
    )
    return 0


def _saved_row(row: Snapshot) -> dict[str, Any]:
    return {"title": row.title, "note": row.note, "day": row.day.isoformat()}


def _pick_arg(value: str | None, saved: list[Snapshot], default: Pick, flag: str) -> Pick:
    """A ``--basis`` or ``--as-of`` value as a pick: a day, a saved snapshot's title, or
    the two words for the sides' own defaults."""
    if value is None:
        return default
    word = value.strip()
    if word.lower() == "start":
        return AT_START
    if word.lower() == "now":
        return LIVE
    try:
        return Pick("day", day=date.fromisoformat(word))
    except ValueError:
        pass
    found = find_saved(saved, word)
    if found is not None:
        return Pick("saved", title=found.title)
    raise CliError(
        f"{flag} is a date (YYYY-MM-DD), a saved snapshot's title, 'start' or 'now': {value!r}"
    )


def _progress_show(context: CliContext, args: Namespace, readers: Readers) -> int:
    project = find_project(context.library, args.project)
    today = date.today()
    live = _snapshot(context, project, readers, today)
    if live is None:
        if not project.steps:
            context.report({"project": project.id, "steps": 0}, "No steps yet.")
            return 0
        raise CliError("these steps wait on each other, so nothing can be dated")
    history = read_history(project)
    saved = read_saved(project)
    humans, agents = read_team(project)
    start = readers.start_of(project)
    then_pick = _pick_arg(args.basis, saved, AT_START, "--basis")
    now_pick = _pick_arg(args.as_of, saved, LIVE, "--as-of")
    now = resolve(now_pick, history=history, saved=saved, live=live, start=start)
    if now is None:
        raise CliError(f"nothing recorded to read the plan as of {args.as_of!r}")
    then = resolve(then_pick, history=history, saved=saved, live=live, start=start)
    basis = pick_words(then_pick, then, now.day)
    as_of = "" if now_pick.kind == "now" else pick_words(now_pick, now, today)
    # What moved the plan, since the day the baseline was recorded — the record the
    # delta measures from.
    changes = (
        changes_since(project, then.day, readers.days_for, readers.estimate_history)
        if then is not None
        else None
    )
    scopes: list[tuple[str | None, str]] = []
    if args.milestone:
        step = _milestone_named(context, project, readers, args.milestone)
        if not readers.is_milestone(step):
            raise CliError(
                f"{step.title!r} is not a milestone — mark it with `milestone set` first"
            )
        scopes.append((step.id, readers.milestone_label(step)))
    else:
        scopes += [
            (s.key, readers.milestone_label(project.step(s.key) or Step()))
            for s in now.stretches
            if s.key
        ]
        scopes.append((None, "All work"))
    rows: list[dict[str, Any]] = []
    lines: list[str] = []
    for key, label in scopes:
        reached = now.toward(key)
        landing = now.landing(key)
        moved = delta(then, now, key) if then is not None else None
        then_landing = then.landing(key) if then is not None else None
        rows.append(
            {
                "milestone": key,
                "label": label,
                "steps": reached.steps,
                "done": reached.done,
                "days": reached.days,
                "done_days": reached.done_days,
                "by_days": reached.share(),
                "finish": landing.isoformat() if landing else "",
                "idle": [
                    {"from": since.isoformat(), "to": until.isoformat()}
                    for since, until in idle(now, key)
                ],
                "expected": _curve(expected(now, key)),
                "actual": _curve(actual(history, now, key)),
                "baseline": None
                if then is None or not then.has(key)
                else {
                    "day": then.day.isoformat(),
                    "steps": then.toward(key).steps,
                    "days": then.toward(key).days,
                    "finish": then_landing.isoformat() if then_landing else "",
                    "expected": _curve(expected(then, key)),
                },
                "delta": None
                if moved is None
                else {
                    "steps": moved.steps,
                    "days": moved.days,
                    "finish_then": moved.finish_then.isoformat() if moved.finish_then else "",
                    "finish_now": moved.finish_now.isoformat() if moved.finish_now else "",
                    "shift": moved.shift,
                },
            }
        )
        line = _progress_line(label, reached, landing, then, moved)
        gaps = idle(now, key)
        if gaps:
            line += "; no work planned " + ", ".join(
                f"{format_date(since, today=today)} to {format_date(until, today=today)}"
                for since, until in gaps
            )
        lines.append(line)
    total, left = volume(history, now), remaining(history, now)
    data = {
        "project": project.id,
        "day": now.day.isoformat(),
        "basis": {
            "pick": then_pick.kind,
            "title": then_pick.title,
            "day": then_pick.day.isoformat() if then_pick.day else "",
            "words": basis,
        },
        "baseline_day": then.day.isoformat() if then is not None else "",
        "as_of": as_of,
        "team": {"humans": humans, "agents": agents},
        "recorded_days": len(history),
        "saved": [_saved_row(row) for row in saved],
        "scopes": rows,
        # The scope over time: the total of estimated days on each recorded day, and what
        # was still ahead — the step curves the Volume page draws.
        "volume": [
            {"date": when.isoformat(), "days": days, "remaining": ahead}
            for (when, days), (_, ahead) in zip(total[::2], left[::2], strict=True)
        ],
        "changes": None
        if changes is None
        else {
            "since": changes.since.isoformat(),
            "added": [
                {"step": step.id, "key": readers.key_of(step), "title": step.title, "days": days}
                for step, days in changes.added
            ],
            "estimates": [
                {
                    "step": step.id,
                    "key": readers.key_of(step),
                    "title": step.title,
                    "day": when.isoformat(),
                    "from": was,
                    "to": days,
                }
                for step, when, was, days in changes.estimates
            ],
        },
    }
    if changes is not None:
        lines += changes.lines(readers.key_of)
    if total:
        lines.append(
            "volume: "
            + ", ".join(
                f"{format_days(days)} on {format_date(when, today=today)}"
                for when, days in total[::2]
            )
        )
    said = f"(versus {basis}" if basis else "(nothing recorded to compare with"
    said += f"; as of {as_of}" if as_of else ""
    lines.append(
        said + f"; {_people(humans, agents)}; {len(history)} day"
        f"{'s' if len(history) != 1 else ''} recorded, "
        f"{len(saved)} saved snapshot{'s' if len(saved) != 1 else ''})"
    )
    context.report(data, "\n".join(lines))
    return 0


def _milestone_named(context: CliContext, project: Project, readers: Readers, needle: str) -> Step:
    """The milestone ``needle`` names — its label (``v2``) first, since that is what a
    person calls it, else the step the way every step verb finds one."""
    wanted = needle.strip().lower()
    labelled = [step for step in project.steps if readers.milestone_label(step).lower() == wanted]
    if len(labelled) == 1:
        return labelled[0]
    return find_step(context.library, needle, project)


def _curve(points: list[tuple[date, float]]) -> list[dict[str, Any]]:
    return [{"date": when.isoformat(), "share": share} for when, share in points]


def _percent(share: float | None) -> str:
    return "—" if share is None else f"{share:.0%}"


def _progress_line(
    label: str, tally: Tally, landing: date | None, then: Snapshot | None, moved: Delta | None
) -> str:
    said = (
        f"{label}: {_percent(tally.share())} "
        f"({format_days(tally.done_days)} of {format_days(tally.days)}, "
        f"{tally.done} of {tally.steps} steps)"
    )
    said += f" — lands {format_date(landing)}" if landing else " — nothing estimated, no date"
    if moved is not None and then is not None:
        said += "; " + delta_words(moved, then.day)
    elif then is not None:
        said += "; not in the plan compared with"
    return said
