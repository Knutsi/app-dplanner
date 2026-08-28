"""The project's start date, and the schedule it turns the estimates into.

The derivation is the domain's (``domain/schedule.py``); this is the module's half of it —
where the start date is stored, and how a number becomes something a person reads. Both the
order table and ``dplanner schedule show`` render through the formatters here, so the window
and the terminal cannot show the same day count two different ways.

**Qt-free**, like ``aspect.py`` beside it: the CLI reaches this file and must start on a
machine with no graphics stack. ``tests/test_architecture.py``'s ``HEADLESS_FILES`` names it.

**The start date lives under the module's own id on the project node** —
``projects/<p>/modules/estimation.json`` = ``{"start": "2026-09-01"}``, beside each step's
``{"days": 3.0}``. One module, one data namespace, two node kinds; ``module_data`` is on
``Node`` and ``set_module_data`` is flat over ids, so the model needs to know nothing about
it. Whoever writes a migration for :data:`~dplanner.modules.estimation.aspect.DATA_FORMAT`
owes both shapes a thought — it is one format covering both.

It is deliberately *not* an ``AspectSpec``: an aspect is a fact about a step, and this is a
fact about a project. ``FORMAT.md``'s note on the graph's node positions is the precedent.
"""

from datetime import date
from typing import Any

from dplanner.core.module_data import stamped
from dplanner.domain.model import Product, Project
from dplanner.domain.ordering import placed
from dplanner.domain.schedule import (
    CriticalPath,
    Scheduled,
    critical_path,
    schedule,
    working_days_after,
)
from dplanner.modules.estimation.aspect import DATA_FORMAT, MODULE_ID, read

START_KEY = "start"


def read_start(project: Project) -> date | None:
    """When the project starts, or None. Anything unreadable reads as unset."""
    entry = project.module_data.get(MODULE_ID)
    if not entry:
        return None
    written = entry.get(START_KEY)
    if not isinstance(written, str):
        return None
    try:
        return date.fromisoformat(written)
    except ValueError:
        return None


def start_of(project: Project) -> date:
    """When this project's work begins: the date somebody set, or today.

    **Derived, never written.** Storing today would make merely opening a tab dirty the
    workspace — ``ordering.py``'s rule again — and it would be wrong by tomorrow. So a
    project nobody has dated answers "if you start now", every surface asks this rather than
    ``read_start``, and the only thing on disk is a date a person chose.
    """
    return read_start(project) or date.today()


def write_start(start: date | None) -> dict[str, Any]:
    """The project entry to store. ``None`` gives ``{}``, which removes the file — and
    puts the project back on "starts today"."""
    if start is None:
        return {}
    return stamped({START_KEY: start.isoformat()}, DATA_FORMAT.version)


def project_schedule(product: Product, project: Project) -> list[Scheduled]:
    """The project's steps in order, each with its running total and its date."""
    return schedule(placed(product, project), read, start_of(project))


def finish_date(rows: list[Scheduled]) -> date | None:
    """When the last step that has a date lands, or None if none of them do."""
    return next((row.finish for row in reversed(rows) if row.finish is not None), None)


def project_critical_path(product: Product, project: Project) -> CriticalPath | None:
    """The longest days-weighted chain, over this module's estimates."""
    return critical_path(product, project, read)


def critical_finish(project: Project, path: CriticalPath) -> date | None:
    """When the critical path lands from the project's start — None when nothing on any
    chain is estimated, because a date on a weightless path would read as a promise."""
    return working_days_after(start_of(project), path.days) if path.days > 0 else None
