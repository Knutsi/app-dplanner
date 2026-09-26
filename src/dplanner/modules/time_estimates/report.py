"""What the time estimates say in a report: where the plan lands, how far that moved and
how much of the work is done; each milestone against the plan at start, the scope and the
work done over the recorded days; and the milestones in sequence.

The Time tab's own reading — ``Readers.snapshot`` for the stored team, focus and start,
then ``present.py``'s :func:`present` against the plan at start — handed over as plain
parts, so the page draws what the tab draws. Nothing here is a second computation of
anything the tab shows.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from datetime import date

from dplanner.cli.report.parts import (
    NOTHING,
    Change,
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
from dplanner.domain.model import Library, Project
from dplanner.domain.ordering import cyclic
from dplanner.domain.schedule import format_date, format_days, short_date
from dplanner.domain.store import FilesFor
from dplanner.modules.time_estimates.cli import Readers
from dplanner.modules.time_estimates.present import (
    Presented,
    change_words,
    milestone_words,
    moved_words,
    names_of,
    present,
)
from dplanner.modules.time_estimates.progress import AT_START, read_history, read_saved
from dplanner.modules.time_estimates.schedule import read_efficiency, read_start, read_team

CHART_ID = "progress"
TIMELINE_ID = "milestones"
MILESTONES_TABLE_ID = "milestones"


def report_source(readers: Readers) -> ReportSource:
    def source(library: Library, project: Project, _files: FilesFor, day: date) -> Contribution:
        if not project.steps:
            return NOTHING
        cycle = cyclic(library, project)
        if cycle:
            names = ", ".join(step.title or "Untitled step" for step in cycle)
            figure = Figure("Lands", "—", note=f"steps wait on each other: {names}", tone="bad")
            return Contribution(placed=(Placed("overview", 12, figure),))
        shown = _presented(library, project, readers, day)
        if shown is None:
            return NOTHING
        placed = [
            Placed("overview", 12, _landing_figure(shown, project)),
            Placed("overview", 13, _moved_figure(shown)),
            Placed("overview", 14, _done_figure(shown)),
        ]
        unsized = sum(
            1
            for step in project.steps
            if readers.days_for(step) is None and not readers.is_marker(step)
        )
        if unsized:
            placed.append(
                Placed("overview", 15, Figure("Unsized", str(unsized), note="counted as 0 days"))
            )
        placed += [
            Placed("overview", 30, _chart(shown)),
            Placed("timeline", 10, _timeline(shown, project)),
            Placed("timeline", 20, _milestones_table(shown, project)),
        ]
        return Contribution(placed=tuple(placed))

    return source


def milestones_table(
    library: Library, project: Project, readers: Readers, today: date
) -> Table | None:
    """The milestones as the report tabulates them — what *Milestones (CSV)…* writes.
    None when the project has no steps or cannot be dated."""
    shown = _presented(library, project, readers, today)
    return _milestones_table(shown, project) if shown is not None else None


def _presented(library: Library, project: Project, readers: Readers, day: date) -> Presented | None:
    """The plan today against the plan at start, as the tab first opens on it."""
    now = readers.snapshot(library, project, day)
    if now is None:
        return None
    return present(
        now,
        history=read_history(project),
        saved=read_saved(project),
        pick=AT_START,
        start=readers.start_of(project, day),
        named=names_of(library, project, now, readers),
    )


def _people(project: Project) -> str:
    humans, agents = read_team(project)
    people = "person" if humans == 1 else "people"
    bots = "agent" if agents == 1 else "agents"
    return f"{humans} {people} + {agents} {bots} at {read_efficiency(project):.0%} focus"


def _landing_figure(shown: Presented, project: Project) -> Figure:
    whole = shown.whole
    if whole.landed_by is not None:
        return Figure("Landed", f"✓ {format_date(whole.landed_by, shown.day)}", tone="good")
    if whole.planned is None:
        return Figure("Lands", "—", note="nothing estimated, so nothing to date")
    return Figure("Lands", format_date(whole.planned, shown.day), note=_people(project))


def _moved_figure(shown: Presented) -> Figure:
    moved = shown.whole.moved
    if moved is None:
        return Figure("Moved", "—", note="no earlier plan recorded yet")
    tone: Tone = "bad" if moved > 0 else "good" if moved < 0 else ""
    return Figure(
        "Moved", moved_words(moved), note=f"working days, against {shown.basis}", tone=tone
    )


def _done_figure(shown: Presented) -> Figure:
    own = shown.whole.own
    share = own.share()
    return Figure(
        "Work done",
        f"{share:.0%}" if share is not None else "—",
        note=f"{format_days(own.done_days) or '0d'} of {format_days(own.days) or '0d'} estimated",
    )


def _chart(shown: Presented) -> Chart:
    """The tab's Milestones and Work pages on one time axis, said as data — under one
    heading naming the plan they are compared with, as the tab's *Compared with* does."""
    data, today = shown.burnup, shown.day
    scope = [Series("Scope", data.scope, "plan")]
    if shown.compared and shown.then is not None and data.baseline is not None:
        scope.append(Series("Plan then", ((shown.then.day, data.baseline),), "baseline"))
    saved = "; ".join(f"{title} ({short_date(when, today)})" for when, title in shown.saved)
    return Chart(
        CHART_ID,
        f"Progress — versus {shown.basis}" if shown.compared and shown.basis else "Progress",
        today,
        plots=(
            Plot("shift", "Milestones"),
            Plot(
                "scope",
                "Scope",
                tuple(scope),
                ceiling=shown.scale,
                changes=tuple(
                    Change(mark.day, mark.up, change_words(mark, today)) for mark in data.marks
                ),
            ),
            Plot(
                "done",
                "Work done",
                (
                    Series("Done", data.done, "actual"),
                    Series("The plan's schedule", shown.schedule, "plan"),
                ),
                ceiling=shown.scale,
                active=data.active,
            ),
        ),
        stretches=tuple(
            Stretch(
                label=scope.named.label,
                color=scope.named.color,
                finish=scope.end,
                was_finish=scope.then,
                done=scope.landed_by is not None,
                step_id=scope.key or "",
                note=milestone_words(scope, today),
            )
            for scope in shown.stretches
        ),
        marks=shown.saved,
        note="On one time axis, in estimated days: where each milestone lands against the "
        "plan compared with — a check where its work is done — the work the plan held on "
        "each recorded day, ▲ where some was added and ▼ where some was taken away, and "
        "what was done by then, dotted across a day no step changed status, beside the "
        "plan's schedule from today on."
        + (f" Dashed lines are the saved snapshots: {saved}." if saved else ""),
    )


def _timeline(shown: Presented, project: Project) -> Timeline:
    began = {stretch.key: stretch.start for stretch in shown.now.stretches}
    return Timeline(
        TIMELINE_ID,
        "Milestones in sequence",
        shown.day,
        tuple(
            Span(
                scope.named.label,
                began[scope.key or ""],
                scope.planned,
                scope.named.color,
                step_id=scope.key or "",
                asked=_asked(project, scope.key),
                share=scope.own.share(),
            )
            for scope in shown.stretches
        ),
    )


def _asked(project: Project, key: str | None) -> date | None:
    """The start date a milestone was given, when it was given one."""
    step = project.step(key) if key else None
    return read_start(step) if step is not None else None


def _milestones_table(shown: Presented, project: Project) -> Table:
    began = {stretch.key: stretch.start for stretch in shown.now.stretches}
    today = shown.day
    rows = []
    for scope in shown.stretches:
        asked = _asked(project, scope.key)
        share = scope.own.share()
        rows.append(
            Row(
                (
                    scope.named.label,
                    format_date(asked, today=today) if asked else "",
                    format_date(scope.planned, today=today) if scope.planned else "",
                    format_days(scope.own.days),
                    str(scope.own.steps),
                    f"{share:.0%}" if share is not None else "",
                    "pushed" if asked is not None and began[scope.key or ""] > asked else "",
                ),
                step_id=scope.key or "",
                strong=bool(scope.key),
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
        note=f"Dated for {_people(project)}; *Done* is the share of the stretch's estimated "
        "days that has landed. A milestone whose set date the work cannot meet is pushed, "
        "never overlapped.",
    )
