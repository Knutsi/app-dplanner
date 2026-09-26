"""The wait aspect: a step that holds what requires it — until a day, or for working days.

A wait is a step like any other in the graph: it requires what must come before it, and what
comes after requires it. What it carries is how long it holds them — ``{"until":
"2026-11-04"}``, the first day they may start, or ``{"days": 3}``, that many working days from
the moment it is reached. It is no work: it takes no worker, has no status of its own and is
no part of any tally, so the schedule reads it as a wait (``domain/schedule.py``'s ``Wait``)
and the tallies leave it out. A step, not a kind of node, so it works unchanged in cones,
ordering, cycles, copy and paste, and numbering.
"""

from datetime import date
from typing import Any

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Step
from dplanner.domain.schedule import Wait, short_date

MODULE_ID = "step_wait"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)
UNTIL_KEY = "until"
DAYS_KEY = "days"


def read(step: Step) -> Wait | None:
    """What the step waits for, or None when it is no wait — or its entry says nothing
    readable, which is the same answer."""
    entry = step.module_data.get(MODULE_ID) or {}
    until = entry.get(UNTIL_KEY)
    if isinstance(until, str):
        try:
            return Wait(until=date.fromisoformat(until))
        except ValueError:
            return None
    days = entry.get(DAYS_KEY)
    if isinstance(days, int | float) and not isinstance(days, bool) and days >= 0:
        return Wait(days=float(days))
    return None


def is_wait(step: Step) -> bool:
    return read(step) is not None


def write(wait: Wait | None) -> dict[str, Any]:
    """The entry to store — ``{}`` for no wait, which removes the file. Days are written as
    a float, whatever was handed in (``FORMAT.md``'s rule)."""
    if wait is None:
        return {}
    if wait.until is not None:
        return stamped({UNTIL_KEY: wait.until.isoformat()}, DATA_FORMAT.version)
    return stamped({DAYS_KEY: float(wait.days)}, DATA_FORMAT.version)


def words(wait: Wait, today: date | None = None) -> str:
    """How long it holds, as a stat says it: ``until 21 Oct``, ``3 working days``."""
    if wait.until is not None:
        return f"until {short_date(wait.until, today)}"
    return f"{wait.days:g} working day{'' if wait.days == 1 else 's'}"


def stat(wait: Wait, today: date | None = None) -> str:
    """What a wait's card says at its bottom right, where a step's estimate would be:
    ``until 21 Oct``, ``3 wd``."""
    if wait.until is not None:
        return f"until {short_date(wait.until, today)}"
    return f"{wait.days:g} wd"


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when it is no wait."""
    wait = read(step)
    return f"waits {words(wait)}" if wait is not None else ""


SPEC = AspectSpec(
    id=MODULE_ID,
    label="Wait",
    summary="Holds what requires it until a day, or for working days; no work, no worker.",
    data_format=DATA_FORMAT,
    phrase=summary,
)
