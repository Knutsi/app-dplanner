"""The focus factor, and the staffing matrix it turns the estimates into.

The derivation is the domain's (``domain/schedule.py``'s ``parallel_finish``); this is the
module's half — where the one stored assumption lives, and the report both surfaces render.
The tab and ``dplanner schedule matrix`` read :func:`time_report`, so the window and the
terminal cannot answer "how long with two people and three agents" two different ways.

**Qt-free**, like ``estimation/schedule.py``: the CLI reaches this file and must start on a
machine with no graphics stack. ``tests/test_architecture.py``'s ``HEADLESS_FILES`` names it.

**The focus factor lives under the module's own id on the project node** —
``projects/<p>/modules/time_estimates.json`` = ``{"efficiency": 0.5}``. It is the fraction
of a working day a person actually spends on this project, and it is the *only* thing here
that reaches disk: every matrix cell is recomputed from the graph and the estimates, for
``ordering.py``'s reason — a stored answer disagrees with what it came from the moment
``dplanner estimate set`` runs with no window open to notice.

**Calendar time is the same simulation over stretched estimates.** :func:`stretched` wraps
``days_for`` so a human step's days divide by the factor while agent steps pass through —
the domain walk never learns an efficiency exists, the same way it never learned where the
estimates live. Agents are not stretched because their human-in-the-loop cost is already
inside the quarter-day estimate convention; the factor prices the *person's* divided week.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.schedule import (
    critical_path,
    parallel_finish,
    working_days_after,
)

MODULE_ID = "time_estimates"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)
EFFICIENCY_KEY = "efficiency"
DEFAULT_EFFICIENCY = 0.5

# The matrix's extent: enough rows to show the human ceiling, enough columns to show the
# agent one, small enough to read at a glance.
HUMANS = (1, 2, 3)
AGENTS = (1, 2, 3, 4)


def read_efficiency(project: Project) -> float:
    """The stored focus factor, or the default. Anything unreadable reads as the default —
    a factor outside (0, 1] would divide an estimate into nonsense, so it does too."""
    entry = project.module_data.get(MODULE_ID)
    if not entry:
        return DEFAULT_EFFICIENCY
    value = entry.get(EFFICIENCY_KEY)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return DEFAULT_EFFICIENCY
    if not 0.0 < value <= 1.0:
        return DEFAULT_EFFICIENCY
    return float(value)


def write_efficiency(value: float | None) -> dict[str, Any]:
    """The project entry to store. ``None`` gives ``{}``, which removes the file — and
    puts the project back on the default."""
    if value is None:
        return {}
    return stamped({EFFICIENCY_KEY: float(value)}, DATA_FORMAT.version)


def stretched(
    days_for: Callable[[Step], float | None],
    is_agent: Callable[[Step], bool],
    efficiency: float,
) -> Callable[[Step], float | None]:
    """``days_for`` with human steps stretched to calendar days; agent steps untouched."""

    def calendar_days(step: Step) -> float | None:
        days = days_for(step)
        if days is None or is_agent(step):
            return days
        return days / efficiency

    return calendar_days


@dataclass(frozen=True)
class Cell:
    """One staffing scenario: the cap, the makespan, and — when measured from a start
    date — where it lands. ``finish`` is None on parallel-adjusted cells, and on a
    calendar cell whose makespan is zero: a date on weightless work would read as a
    promise (``estimation/schedule.py``'s ``critical_finish`` makes the same call)."""

    humans: int
    agents: int
    days: float
    finish: date | None = None


@dataclass(frozen=True)
class TimeReport:
    """Everything the tab and the CLI print: the effort split, the floors, both grids.

    ``floor`` and ``calendar_floor`` are the critical path priced with raw and stretched
    estimates — the number no staffing in that grid gets under, which is what marks the
    cells where more capacity has stopped helping.
    """

    start: date
    efficiency: float
    human_days: float
    agent_days: float
    unestimated: int
    has_agent_steps: bool
    floor: float
    calendar_floor: float
    parallel: tuple[Cell, ...]
    calendar: tuple[Cell, ...]

    @property
    def total_days(self) -> float:
        """All estimated work — also the serial answer, one worker end to end."""
        return self.human_days + self.agent_days


def time_report(
    library: Library,
    project: Project,
    days_for: Callable[[Step], float | None],
    is_agent: Callable[[Step], bool],
    *,
    start: date,
    efficiency: float,
) -> TimeReport | None:
    """The full matrix over ``HUMANS`` by ``AGENTS``. None only when the project has no
    steps. ``start`` and ``efficiency`` arrive resolved — the caller owns where a start
    date and a stored factor live, the same seam ``days_for`` and ``is_agent`` use."""
    if not project.steps:
        return None
    calendar_days = stretched(days_for, is_agent, efficiency)
    path = critical_path(library, project, days_for)
    calendar_path = critical_path(library, project, calendar_days)
    parallel: list[Cell] = []
    calendar: list[Cell] = []
    unestimated = 0
    for humans in HUMANS:
        for agents in AGENTS:
            raw = parallel_finish(
                library, project, days_for, is_agent, humans=humans, agents=agents
            )
            slow = parallel_finish(
                library, project, calendar_days, is_agent, humans=humans, agents=agents
            )
            assert raw is not None and slow is not None  # project.steps checked above
            unestimated = raw.unestimated
            parallel.append(Cell(humans=humans, agents=agents, days=raw.days))
            calendar.append(
                Cell(
                    humans=humans,
                    agents=agents,
                    days=slow.days,
                    finish=working_days_after(start, slow.days) if slow.days > 0 else None,
                )
            )
    human_days = sum(
        days_for(step) or 0.0 for step in project.steps if not is_agent(step)
    )
    agent_days = sum(days_for(step) or 0.0 for step in project.steps if is_agent(step))
    return TimeReport(
        start=start,
        efficiency=efficiency,
        human_days=human_days,
        agent_days=agent_days,
        unestimated=unestimated,
        has_agent_steps=any(is_agent(step) for step in project.steps),
        floor=path.days if path else 0.0,
        calendar_floor=calendar_path.days if calendar_path else 0.0,
        parallel=tuple(parallel),
        calendar=tuple(calendar),
    )
