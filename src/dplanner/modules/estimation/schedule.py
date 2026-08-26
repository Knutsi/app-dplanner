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
from dplanner.domain.schedule import Scheduled, schedule
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


def write_start(start: date | None) -> dict[str, Any]:
    """The project entry to store. ``None`` gives ``{}``, which removes the file."""
    if start is None:
        return {}
    return stamped({START_KEY: start.isoformat()}, DATA_FORMAT.version)


def project_schedule(product: Product, project: Project) -> list[Scheduled]:
    """The project's steps in order, each with its running total and its date."""
    return schedule(placed(product, project), read, read_start(project))


def finish_date(rows: list[Scheduled]) -> date | None:
    """When the last step that has a date lands, or None if none of them do."""
    return next((row.finish for row in reversed(rows) if row.finish is not None), None)
