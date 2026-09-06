"""What the time estimates say in a report: when it lands, how the plan moved, the
progress chart, the milestones in sequence and the staffing what-ifs.

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
    Mark,
    Placed,
    ReportSource,
    Row,
    Series,
    Span,
    Table,
    Timeline,
    Tone,
)
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.schedule import Phase, format_date, format_days
from dplanner.domain.store import FilesFor
from dplanner.modules.time_estimates.cli import Readers
from dplanner.modules.time_estimates.progress import (
    Delta,
    ScopeView,
    Snapshot,
    baseline,
    delta_words,
    read_history,
    take,
    tally,
    view_scope,
)
from dplanner.modules.time_estimates.schedule import (
    Cell,
    TimeReport,
    phase_colors,
    read_color,
    read_efficiency,
    read_palette,
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
        then = baseline(history, dated.start)
        view = view_scope(now, history, then, None, by_days=False)
        colors = phase_colors(team.phases, read_color, read_palette(project))
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
                    _series(view, then, today),
                    marks=tuple(
                        Mark(when, labels[id(phase)], phase.milestone.id)
                        for when, milestone_id in view.marks
                        for phase in team.phases
                        if phase.milestone is not None and phase.milestone.id == milestone_id
                    ),
                    idle=view.idle,
                    note="The share of steps done, over time: the plan as it stands, the plan "
                    "as it was recorded on the basis day, and what has landed.",
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
                            share=tally(phase.steps, readers.days_for, readers.status_for).share(
                                by_days=False
                            ),
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


def _series(view: ScopeView, then: Snapshot | None, today: date) -> tuple[Series, ...]:
    found = [Series("Plan now", view.expected, "plan")]
    if then is not None and view.baseline:
        found.append(
            Series(f"Plan at {format_date(then.day, today=today)}", view.baseline, "baseline")
        )
    found.append(Series("Landed", view.actual, "actual"))
    return tuple(found)


def _milestones_table(dated: _Dated, readers: Readers) -> Table:
    team, labels, efficiency, today = dated.team, dated.labels, dated.efficiency, dated.today
    rows = []
    for phase in team.phases:
        key = phase.milestone.id if phase.milestone else None
        reached = tally(phase.steps, readers.days_for, readers.status_for)
        share = reached.share(by_days=False)
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
        note=f"Dated for {_people(team)} at {efficiency:.0%} focus; a milestone whose set "
        "date the work cannot meet is pushed, never overlapped.",
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
