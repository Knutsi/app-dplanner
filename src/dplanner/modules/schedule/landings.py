"""The schedule a project's estimates imply, read whole: its rows, its finish and its
critical path, for the order table, ``dplanner schedule show`` and the report.

The derivation is the planning tier's (``planning/schedule.py``), and so are the estimate
and the project's start date (``planning/estimate.py``); this is the module's shorthand
over both. **Qt-free**: the CLI reaches it, and ``tests/test_architecture.py``'s
``HEADLESS_FILES`` names it.
"""

from datetime import date

from dplanner.domain.model import Library, Project
from dplanner.domain.ordering import placed
from dplanner.planning.dates import format_date
from dplanner.planning.estimate import read as estimated_days
from dplanner.planning.estimate import start_of
from dplanner.planning.milestone import is_milestone
from dplanner.planning.schedule import (
    CriticalPath,
    Scheduled,
    critical_path,
    format_days,
    schedule,
    working_days_after,
)
from dplanner.planning.wait import read as wait_read
from dplanner.planning.wait import stat as wait_stat


def project_schedule(library: Library, project: Project) -> list[Scheduled]:
    """The project's steps in order, each with its running total and its date."""
    return schedule(placed(library, project), start_of(project))


def milestone_stats(library: Library, project: Project) -> dict[str, str]:
    """What each milestone answers with: the schedule's accumulated days and landing date
    at its row — the same pair the order table's milestone row highlights.

    A milestone closes the block of work above it, so its number is the walk's total at
    that row. One walk per project rather than one per milestone, because a canvas sync
    asks for every milestone at once and the order is the same for all of them. A
    milestone the project cannot date is absent; so is every step when nothing is a
    milestone, which costs the sync no walk at all.
    """
    if not any(is_milestone(step) for step in project.steps):
        return {}
    stats: dict[str, str] = {}
    for scheduled in project_schedule(library, project):
        step = scheduled.place.step
        if not is_milestone(step):
            continue
        if scheduled.finish is not None:
            stats[step.id] = (
                f"{format_days(scheduled.accumulated)} · {format_date(scheduled.finish)}"
            )
        elif scheduled.accumulated:
            stats[step.id] = format_days(scheduled.accumulated)
    return stats


def card_stats(library: Library, project: Project, today: date | None = None) -> dict[str, str]:
    """The figure at each card's bottom right — a milestone's total and landing, how long a
    wait holds, any other step's estimate — read once for every card the canvas and the
    report's graph paint. A wait is said as of ``today``, or as of its own date where none
    is given: a printed card names no year."""
    stats = milestone_stats(library, project)
    for step in project.steps:
        if is_milestone(step):
            continue
        wait = wait_read(step)
        if wait is not None:
            stats[step.id] = wait_stat(wait, today or wait.until)
            continue
        days = estimated_days(step)
        if days is not None:
            stats[step.id] = format_days(days)
    return stats


def finish_date(rows: list[Scheduled]) -> date | None:
    """When the last step that has a date lands, or None if none of them do."""
    return next((row.finish for row in reversed(rows) if row.finish is not None), None)


def project_critical_path(library: Library, project: Project) -> CriticalPath | None:
    """The longest days-weighted chain, over the estimates."""
    return critical_path(library, project)


def critical_finish(project: Project, path: CriticalPath) -> date | None:
    """When the critical path lands from the project's start — None when nothing on any
    chain is estimated, because a date on a weightless path would read as a promise."""
    return working_days_after(start_of(project), path.days) if path.days > 0 else None
