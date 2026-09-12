"""What the time estimates say in a report: when it lands, how the plan moved, the
progress and volume plots, the milestones in sequence and the staffing what-ifs.

The same derivations the Time tab renders and ``dplanner schedule matrix`` /
``progress show`` print — ``time_report``, ``take``, ``view_scope`` — read once for the
project's stored team, focus and palette, and handed over as plain parts. Nothing here is
a second computation of anything the tab shows.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from dplanner.cli.report.parts import (
    NOTHING,
    Chart,
    Column,
    Contribution,
    Figure,
    Placed,
    Plot,
    ReportSource,
    Row,
    Series,
    Span,
    Stretch,
    Table,
    Timeline,
    Tone,
)
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.schedule import Phase, format_date, format_days
from dplanner.domain.store import FilesFor
from dplanner.modules.time_estimates.cli import Readers
from dplanner.modules.time_estimates.progress import (
    AT_START,
    Delta,
    ScopeView,
    Snapshot,
    delta_words,
    pick_words,
    read_history,
    read_saved,
    remaining,
    resolve,
    scope_words,
    shift_words,
    span_of,
    standing_words,
    take,
    tally,
    view_scope,
    volume,
    volume_scale,
)
from dplanner.modules.time_estimates.schedule import (
    Cell,
    TimeReport,
    milestone_colors,
    phase_colors,
    read_efficiency,
    read_start,
    read_team,
    time_report,
)

CHART_ID = "progress"
TIMELINE_ID = "milestones"
MILESTONES_TABLE_ID = "milestones"
MATRIX_TABLE_ID = "staffing"
WHOLE_LABEL = "All work"
REMAINDER_LABEL = "Remaining work"


def report_source(
    *,
    days_for: Callable[[Step], float | None],
    is_agent: Callable[[Step], bool],
    status_for: Callable[[Step], str],
    start_of: Callable[[Project], date],
    milestone_label: Callable[[Step], str],
    estimate_history: Callable[[Step], list[tuple[date, float]]],
    key_of: Callable[[Step], str],
) -> ReportSource:
    readers = Readers(
        days_for, is_agent, status_for, start_of, milestone_label, estimate_history, key_of
    )

    def source(library: Library, project: Project, _files: FilesFor) -> Contribution:
        if not project.steps:
            return NOTHING
        dated = _dated(library, project, readers)
        if dated is None:
            return NOTHING
        if dated.cycle:
            names = ", ".join(step.title or "Untitled step" for step in dated.cycle)
            figure = Figure("Lands", "—", note=f"steps wait on each other: {names}", tone="bad")
            return Contribution(placed=(Placed("overview", 12, figure),))
        team, today = dated.team, dated.today
        now = take(
            library,
            project,
            readers.days_for,
            readers.is_agent,
            readers.status_for,
            humans=team.humans,
            agents=team.agents,
            start=dated.start,
            efficiency=dated.efficiency,
            is_milestone=readers.is_milestone,
            start_for=read_start,
            today=today,
        )
        if now is None:
            return NOTHING
        history = read_history(project)
        saved = read_saved(project)
        then = resolve(AT_START, history=history, saved=saved, live=now, start=dated.start)
        basis = pick_words(AT_START, then, today)
        view = view_scope(now, history, then, None)
        colors = phase_colors(team.phases, milestone_colors(library, project, readers.is_milestone))
        labels = dated.labels
        placed = [
            Placed(
                "overview",
                12,
                Figure(
                    "Lands",
                    format_date(team.finish, today=today) if team.finish else "—",
                    note=f"{_people(team)} · {dated.efficiency:.0%} focus",
                ),
            ),
            Placed("overview", 14, _change_figure(view.moved, then, today)),
            Placed(
                "overview",
                30,
                Chart(
                    CHART_ID,
                    "Progress against the plan",
                    today,
                    plots=_plots(view, then, basis, history, now),
                    stretches=_stretches(team, colors, labels, now, then, basis, today),
                    idle=view.idle,
                    marks=tuple((row.day, row.title) for row in saved),
                    note="Plots on one time axis, by estimated days: where the work "
                    "stands against the plan, how the plan itself has moved since it was "
                    "recorded, where each milestone has slid, and how much work the plan "
                    "came to on each recorded day.",
                ),
            ),
            Placed(
                "timeline",
                10,
                Timeline(
                    TIMELINE_ID,
                    "Milestones in sequence",
                    today,
                    tuple(
                        Span(
                            labels[id(phase)],
                            phase.start,
                            phase.finish,
                            color,
                            step_id=phase.milestone.id if phase.milestone else "",
                            asked=phase.asked,
                            share=tally(phase.steps, readers.days_for, readers.status_for).share(),
                        )
                        for phase, color in zip(team.phases, colors, strict=True)
                    ),
                ),
            ),
            Placed("timeline", 20, _milestones_table(dated, readers)),
        ]
        matrix = _matrix_table(dated.report, today)
        if matrix is not None:
            placed.append(Placed("timeline", 30, matrix))
        return Contribution(placed=tuple(placed))

    return source


def milestones_table(library: Library, project: Project, readers: Readers) -> Table | None:
    """The milestones as the report tabulates them — what *Milestones (CSV)…* writes.
    None when the project has no steps or cannot be dated."""
    dated = _dated(library, project, readers)
    if dated is None or dated.cycle:
        return None
    return _milestones_table(dated, readers)


@dataclass(frozen=True)
class _Dated:
    """The plan dated for its stored team and focus, read once for every part here."""

    report: TimeReport
    team: Cell
    start: date
    efficiency: float
    today: date
    labels: dict[int, str]  # A phase (by identity) and what it is called.

    @property
    def cycle(self) -> tuple[Step, ...]:
        return self.report.cycle


def _dated(library: Library, project: Project, readers: Readers) -> _Dated | None:
    start = readers.start_of(project)
    efficiency = read_efficiency(project)
    report = time_report(
        library,
        project,
        readers.days_for,
        readers.is_agent,
        start=start,
        efficiency=efficiency,
        is_milestone=readers.is_milestone,
        start_for=read_start,
    )
    if report is None or (not report.cycle and not report.calendar):
        return None
    humans, agents = read_team(project)
    team = next(
        (cell for cell in report.calendar if (cell.humans, cell.agents) == (humans, agents)),
        report.calendar[0] if report.calendar else Cell(humans, agents, 0.0),
    )
    labels = {id(phase): _label(phase, team.phases, readers) for phase in team.phases}
    return _Dated(report, team, start, efficiency, date.today(), labels)


def _label(phase: Phase, phases: tuple[Phase, ...], readers: Readers) -> str:
    if phase.milestone is None:
        alone = all(other.milestone is None for other in phases)
        return WHOLE_LABEL if alone else REMAINDER_LABEL
    return readers.milestone_label(phase.milestone) or phase.milestone.title or "Milestone"


def _people(team: Cell) -> str:
    people = "person" if team.humans == 1 else "people"
    agents = "agent" if team.agents == 1 else "agents"
    return f"{team.humans} {people} + {team.agents} {agents}"


def _change_figure(moved: Delta | None, then: Snapshot | None, today: date) -> Figure:
    if then is None:
        return Figure("Change since the plan", "—", note="no earlier plan recorded yet")
    label = f"Since the plan of {format_date(then.day, today=today)}"
    if moved is None:
        return Figure(label, "—", note="not in the plan then")
    words = delta_words(moved, then.day)
    tone: Tone = "" if moved.unchanged else "busy"
    shift = moved.shift
    if shift is not None and shift > 0:
        tone = "bad"
    return Figure(label, words, tone=tone)


def _plots(
    view: ScopeView,
    then: Snapshot | None,
    basis: str,
    history: list[Snapshot],
    now: Snapshot,
) -> tuple[Plot, ...]:
    """The plots the chart stacks — the window's every page, said as data.

    The scope plot is left out when there is no earlier plan to compare against: an empty
    box saying "nothing recorded yet" is the placeholder the card rule forbids. The
    volume plots share one scale in days, the window's rule, so the gap between them is
    read by eye.
    """
    plan = Series("Plan now" if then is not None else "Plan", view.expected, "plan")
    found = [
        Plot(
            "status",
            "Progress",
            (plan, Series("Landed", view.actual, "actual")),
            standing=standing_words(view.standing),
        )
    ]
    if then is not None and view.baseline:
        found.append(
            Plot(
                "scope",
                scope_words(basis),
                (plan, Series("Plan then", view.baseline, "baseline")),
                note="Amber where the plan now promises more by a date than it did then, "
                "red where it promises less, green where the two agree.",
            )
        )
    found.append(Plot("shift", "Milestones"))
    total, left = tuple(volume(history, now)), tuple(remaining(history, now))
    scale = volume_scale(total, left)
    found.append(
        Plot(
            "volume",
            "Scope volume",
            (Series("Estimated days", total, "plan"),),
            ceiling=scale,
            note="The total of estimated days the plan came to on each recorded day.",
        )
    )
    found.append(
        Plot(
            "remaining",
            "Remaining work",
            (Series("Total", total, "baseline"), Series("Remaining", left, "plan")),
            ceiling=scale,
            note="The same less what had landed: the gap between the two is what is done.",
        )
    )
    return tuple(found)


def _stretches(
    team: Cell,
    colors: list[str],
    labels: dict[int, str],
    now: Snapshot,
    then: Snapshot | None,
    basis: str,
    today: date,
) -> tuple[Stretch, ...]:
    """Every stretch of the plan: its shade, where it runs now and where it ran in the
    plan compared with. One shape for every plot, as in the window."""
    found = []
    for phase, color in zip(team.phases, colors, strict=True):
        key = phase.milestone.id if phase.milestone else ""
        span, was = span_of(now, key), span_of(then, key)
        found.append(
            Stretch(
                label=labels[id(phase)],
                color=color,
                start=span[0] if span else None,
                finish=span[1] if span else None,
                was_start=was[0] if was else None,
                was_finish=was[1] if was else None,
                step_id=key,
                note=shift_words(
                    labels[id(phase)],
                    was[1] if was else None,
                    span[1] if span else None,
                    basis if then is not None else "",
                    today,
                ),
            )
        )
    return tuple(found)


def _milestones_table(dated: _Dated, readers: Readers) -> Table:
    team, labels, efficiency, today = dated.team, dated.labels, dated.efficiency, dated.today
    rows = []
    for phase in team.phases:
        key = phase.milestone.id if phase.milestone else None
        reached = tally(phase.steps, readers.days_for, readers.status_for)
        share = reached.share()
        rows.append(
            Row(
                (
                    labels[id(phase)],
                    format_date(phase.asked, today=today) if phase.asked else "",
                    format_date(phase.finish, today=today) if phase.finish else "",
                    format_days(phase.days),
                    str(reached.steps),
                    f"{share:.0%}" if share is not None else "",
                    "pushed" if phase.pushed else "",
                ),
                step_id=key or "",
                strong=phase.milestone is not None,
            )
        )
    return Table(
        MILESTONES_TABLE_ID,
        "Milestones",
        (
            Column("Milestone"),
            Column("Set date", "date"),
            Column("Lands", "date"),
            Column("Days", "days"),
            Column("Steps", "number"),
            Column("Done", "number"),
            Column(""),
        ),
        tuple(rows),
        note=f"Dated for {_people(team)} at {efficiency:.0%} focus; *Done* is the share of "
        "the stretch's estimated days that has landed. A milestone whose set date the work "
        "cannot meet is pushed, never overlapped.",
    )


def _matrix_table(report: TimeReport, today: date) -> Table | None:
    cells = report.calendar
    if not cells:
        return None
    humans = sorted({cell.humans for cell in cells})
    agents = (
        sorted({cell.agents for cell in cells}) if report.has_agent_steps else [cells[0].agents]
    )
    at = {(cell.humans, cell.agents): cell for cell in cells}

    def said(cell: Cell | None) -> str:
        if cell is None:
            return ""
        if cell.finish is not None:
            return format_date(cell.finish, today=today)
        return format_days(cell.days)

    columns = [Column("Team")]
    columns += [
        Column(
            f"{count} agent{'s' if count != 1 else ''}" if report.has_agent_steps else "Lands",
            "date",
        )
        for count in agents
    ]
    rows = tuple(
        Row(
            (
                f"{count} {'person' if count == 1 else 'people'}",
                *(said(at.get((count, agent))) for agent in agents),
            )
        )
        for count in humans
    )
    return Table(
        MATRIX_TABLE_ID,
        "Staffing",
        tuple(columns),
        rows,
        note=f"When the work lands with that many people and coding agents, at "
        f"{report.efficiency:.0%} focus. The rest of this page is dated for the stored team.",
    )
