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
from dplanner.planning.estimate import start_of
from dplanner.planning.schedule import (
    CriticalPath,
    Scheduled,
    critical_path,
    schedule,
    working_days_after,
)


def project_schedule(library: Library, project: Project) -> list[Scheduled]:
    """The project's steps in order, each with its running total and its date."""
    return schedule(placed(library, project), start_of(project))


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
