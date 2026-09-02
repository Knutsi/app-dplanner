"""The plan's assumptions, and the staffing matrix they turn the estimates into.

The derivation is the domain's (``domain/schedule.py``'s ``phases`` over ``parallel_finish``);
this is the module's half — where the stored assumptions live, and the report both surfaces
render. The tab and ``dplanner schedule matrix`` read :func:`time_report`, so the window and
the terminal cannot answer "how long with two people and three agents" two different ways.

**Qt-free**, like ``estimation/schedule.py``: the CLI reaches this file and must start on a
machine with no graphics stack. ``tests/test_architecture.py``'s ``HEADLESS_FILES`` names it.

**Three assumptions reach disk, all under this module's id, and nothing derived does.**
On the project node, ``{"efficiency": 0.5}`` — the focus factor, the fraction of a working
day a person actually spends on this project. On a milestone step, ``{"start": "2026-10-05",
"color": "#e0602c"}`` — a date the milestone's stretch of work begins on rather than the day
the previous one lands, and a colour chosen over the automatic one; either key alone is
fine and an empty entry removes the file. One module, one namespace, two node kinds —
``estimation``'s precedent. Every matrix cell and every landing date is recomputed from the
graph and the estimates, for ``ordering.py``'s reason: a stored answer disagrees with what
it came from the moment ``dplanner estimate set`` runs with no window open to notice.

**Calendar time is the same simulation over stretched estimates.** :func:`stretched` wraps
``days_for`` so a human step's days divide by the factor while agent steps pass through —
the domain walk never learns an efficiency exists, the same way it never learned where the
estimates live. Agents are not stretched because their human-in-the-loop cost is already
inside the quarter-day estimate convention; the factor prices the *person's* divided week.

**A milestone's colour follows its place in the sequence** unless somebody picked one:
:data:`PALETTE` is eight hues validated to stay apart under every common colour-vision
deficiency on both themes, assigned in order and never cycled past — the ninth milestone
wears the first hue again, and its label beside it is what tells them apart, as it always
was. Hex strings here so the CLI can print and store them; the view turns them into paint.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from math import ceil
from typing import Any, TypeGuard

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.ordering import cyclic
from dplanner.domain.schedule import (
    Phase,
    critical_path,
    phases,
    working_days_between,
)

MODULE_ID = "time_estimates"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)
EFFICIENCY_KEY = "efficiency"
DEFAULT_EFFICIENCY = 0.5
START_KEY = "start"
COLOR_KEY = "color"

# The matrix's extent: enough rows to show the human ceiling, enough columns to show the
# agent one, small enough to read at a glance.
HUMANS = (1, 2, 3)
AGENTS = (1, 2, 3, 4)

# Milestone hues in the order they are handed out. The first is the report's own blue, so a
# project with no milestones keeps the tint it always had; the rest were stepped to pass
# the adjacent-pair colour-deficiency and contrast checks on a light and a dark surface.
PALETTE = (
    "#5f87d7",
    "#e0602c",
    "#1aa675",
    "#c98500",
    "#d55181",
    "#2c8f2c",
    "#9682dc",
    "#e45a5a",
)
# Work after the last milestone has no milestone to be coloured for.
REMAINDER_COLOR = "#8b8f96"


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


def read_start(step: Step) -> date | None:
    """The date a milestone's stretch begins on, or None: it begins when the last lands."""
    entry = step.module_data.get(MODULE_ID)
    written = entry.get(START_KEY) if entry else None
    if not isinstance(written, str):
        return None
    try:
        return date.fromisoformat(written)
    except ValueError:
        return None


def is_color(value: object) -> TypeGuard[str]:
    """``#rrggbb``, lower or upper case — the one spelling stored and accepted."""
    return (
        isinstance(value, str)
        and len(value) == 7
        and value[0] == "#"
        and all(char in "0123456789abcdefABCDEF" for char in value[1:])
    )


def read_color(step: Step) -> str | None:
    """The colour somebody chose for a milestone, or None for the automatic one."""
    entry = step.module_data.get(MODULE_ID)
    written = entry.get(COLOR_KEY) if entry else None
    return written.lower() if is_color(written) else None


def write_milestone(start: date | None, color: str | None) -> dict[str, Any]:
    """A milestone's entry: whichever of the two is set. Neither gives ``{}``, which
    removes the file — the stretch begins when the previous lands, coloured in turn."""
    entry: dict[str, Any] = {}
    if start is not None:
        entry[START_KEY] = start.isoformat()
    if color is not None:
        if not is_color(color):
            raise ValueError(f"a colour is #rrggbb, not {color!r}")
        entry[COLOR_KEY] = color.lower()
    return stamped(entry, DATA_FORMAT.version) if entry else {}


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
    date — where it lands, stretch by stretch. ``finish`` is None on parallel-adjusted
    cells, and on a calendar cell with no estimated work: a date on weightless work would
    read as a promise (``estimation/schedule.py``'s ``critical_finish`` makes the same
    call). ``phases`` are the milestones in sequence; a parallel cell's carry days only."""

    humans: int
    agents: int
    days: float
    finish: date | None = None
    phases: tuple[Phase, ...] = ()


@dataclass(frozen=True)
class TimeReport:
    """Everything the tab and the CLI print: the effort split, the floors, both grids.

    ``floor`` and ``calendar_floor`` are the critical path priced with raw and stretched
    estimates — the number no staffing in that grid gets under, which is what marks the
    cells where more capacity has stopped helping.

    ``cycle`` names the steps that wait on themselves when a file edited by hand carries a
    loop; then nothing can be dated, both grids are empty, and the surfaces say so.
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
    cycle: tuple[Step, ...] = ()

    @property
    def total_days(self) -> float:
        """All estimated work — also the serial answer, one worker end to end."""
        return self.human_days + self.agent_days


def phase_colors(stretches: tuple[Phase, ...], color_of: Callable[[Step], str | None]) -> list[str]:
    """One hex colour per stretch: the milestone's chosen colour, else its place in the
    palette; the work after the last milestone is neutral — unless it is all there is."""
    colors: list[str] = []
    index = 0
    for phase in stretches:
        if phase.milestone is None:
            colors.append(REMAINDER_COLOR if index else PALETTE[0])
            continue
        colors.append(color_of(phase.milestone) or PALETTE[index % len(PALETTE)])
        index += 1
    return colors


def cell_for(
    library: Library,
    project: Project,
    days_for: Callable[[Step], float | None],
    is_agent: Callable[[Step], bool],
    *,
    humans: int,
    agents: int,
    start: date,
    efficiency: float,
    is_milestone: Callable[[Step], bool],
    start_for: Callable[[Step], date | None],
) -> tuple[Cell, Cell]:
    """One staffing, both lenses: the parallel-adjusted cell and the calendar one."""
    raw = phases(
        library,
        project,
        days_for,
        is_agent,
        humans=humans,
        agents=agents,
        start=start,
        is_milestone=is_milestone,
        start_for=start_for,
    )
    slow = phases(
        library,
        project,
        stretched(days_for, is_agent, efficiency),
        is_agent,
        humans=humans,
        agents=agents,
        start=start,
        is_milestone=is_milestone,
        start_for=start_for,
    )
    landing = next((phase.finish for phase in reversed(slow) if phase.finish), None)
    return (
        Cell(humans=humans, agents=agents, days=sum(phase.days for phase in raw)),
        Cell(
            humans=humans,
            agents=agents,
            # Whole days on a calendar, first stretch's start to the last landing — gaps
            # a dated milestone opens included, because they are calendar time too.
            days=float(working_days_between(slow[0].start, landing)) if landing else 0.0,
            finish=landing,
            phases=tuple(slow),
        ),
    )


def time_report(
    library: Library,
    project: Project,
    days_for: Callable[[Step], float | None],
    is_agent: Callable[[Step], bool],
    *,
    start: date,
    efficiency: float,
    is_milestone: Callable[[Step], bool],
    start_for: Callable[[Step], date | None],
) -> TimeReport | None:
    """The full matrix over ``HUMANS`` by ``AGENTS``. None only when the project has no
    steps. ``start`` and ``efficiency`` arrive resolved — the caller owns where a start
    date and a stored factor live, the same seam ``days_for`` and ``is_agent`` use."""
    if not project.steps:
        return None
    human_days = sum(days_for(step) or 0.0 for step in project.steps if not is_agent(step))
    agent_days = sum(days_for(step) or 0.0 for step in project.steps if is_agent(step))
    has_agent_steps = any(is_agent(step) for step in project.steps)
    loop = tuple(cyclic(library, project))
    if loop:
        return TimeReport(
            start=start,
            efficiency=efficiency,
            human_days=human_days,
            agent_days=agent_days,
            unestimated=sum(1 for step in project.steps if days_for(step) is None),
            has_agent_steps=has_agent_steps,
            floor=0.0,
            calendar_floor=0.0,
            parallel=(),
            calendar=(),
            cycle=loop,
        )
    calendar_days = stretched(days_for, is_agent, efficiency)
    path = critical_path(library, project, days_for)
    calendar_path = critical_path(library, project, calendar_days)
    parallel: list[Cell] = []
    calendar: list[Cell] = []
    for humans in HUMANS:
        for agents in AGENTS:
            raw, slow = cell_for(
                library,
                project,
                days_for,
                is_agent,
                humans=humans,
                agents=agents,
                start=start,
                efficiency=efficiency,
                is_milestone=is_milestone,
                start_for=start_for,
            )
            parallel.append(raw)
            calendar.append(slow)
    return TimeReport(
        # The first stretch may begin on its milestone's own date rather than the project's.
        start=calendar[0].phases[0].start,
        efficiency=efficiency,
        human_days=human_days,
        agent_days=agent_days,
        unestimated=sum(phase.unestimated for phase in calendar[0].phases),
        has_agent_steps=has_agent_steps,
        floor=path.days if path else 0.0,
        # Whole days like the cells, so a cell on the floor still matches it exactly.
        calendar_floor=float(ceil(calendar_path.days - 1e-9)) if calendar_path else 0.0,
        parallel=tuple(parallel),
        calendar=tuple(calendar),
    )
