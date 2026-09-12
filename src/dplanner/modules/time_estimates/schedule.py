"""The plan's assumptions, and the staffing matrix they turn the estimates into.

The derivation is the domain's (``domain/schedule.py``'s ``phases`` over ``parallel_finish``);
this is the module's half — where the stored assumptions live, and the report both surfaces
render. The tab and ``dplanner schedule matrix`` read :func:`time_report`, so the window and
the terminal cannot answer "how long with two people and three agents" two different ways.

**Qt-free**, like ``estimation/schedule.py``: the CLI reaches this file and must start on a
machine with no graphics stack. ``tests/test_architecture.py``'s ``HEADLESS_FILES`` names it.

**Five assumptions reach disk, all under this module's id, and nothing derived does.**
On the project node, ``{"efficiency": 0.5, "palette": "mako", "team": [2, 3]}`` — the
focus factor, the fraction of a working day a person actually spends on this project; the
colour map the milestones are shaded from; and the **team** the calendar is dated for,
people and coding agents (each absent for its default, FORMAT.md's absence rule — the
smallest team, the way ``schedule matrix`` always printed its milestones). The three are
one :class:`Assumptions`, read and written whole, so a control changing one carries the
others as they are stored rather than each caller juggling the rest. On a milestone step,
``{"start": "2026-10-05", "color": "#e0602c"}`` — a date the milestone's stretch of work
begins on rather than the day the previous one lands, and a colour chosen over the dealt
one; either key alone is fine and an empty entry removes the file. One module, one
namespace, two node kinds — ``estimation``'s precedent. Every matrix cell and every
landing date is recomputed from the graph and the estimates, for ``ordering.py``'s
reason: a stored answer disagrees with what it came from the moment ``dplanner estimate
set`` runs with no window open to notice.

**Calendar time is the same simulation over stretched estimates.** :func:`stretched` wraps
``days_for`` so a human step's days divide by the factor while agent steps pass through —
the domain walk never learns an efficiency exists, the same way it never learned where the
estimates live. Agents are not stretched because their human-in-the-loop cost is already
inside the quarter-day estimate convention; the factor prices the *person's* divided week.

**A milestone's colour is its place in the sequence, read off one colour map** unless
somebody picked one. The maps themselves are ``theme/palettes.py``'s — every surface that
draws a milestone needs them and modules never import each other — and what belongs here is
what is *this project's*: which map it chose, a milestone's own colour over the dealt one,
and :func:`milestone_colors`, the one deal every surface reads. Hex strings so the CLI can
print and store them; the view turns them into paint.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from math import ceil
from typing import Any, TypeGuard

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.ordering import cyclic, placed
from dplanner.domain.schedule import (
    Phase,
    critical_path,
    phases,
    working_days_between,
)
from dplanner.theme.palettes import DEFAULT_PALETTE, Palette, palette, shades

MODULE_ID = "time_estimates"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)
EFFICIENCY_KEY = "efficiency"
DEFAULT_EFFICIENCY = 0.5
PALETTE_KEY = "palette"
TEAM_KEY = "team"
START_KEY = "start"
COLOR_KEY = "color"

# The matrix's extent: enough rows to show the human ceiling, enough columns to show the
# agent one, small enough to read at a glance.
HUMANS = (1, 2, 3)
AGENTS = (1, 2, 3, 4)
# The team the calendar is dated for until somebody picks one: the smallest.
DEFAULT_TEAM = (HUMANS[0], AGENTS[0])

# How many shades the swatch menu offers of the chosen map — enough to tell apart, few
# enough to name.
SWATCH_SHADES = 8

# A project with no milestones is one stretch, in the report's own blue — the matrix's tint.
WHOLE_COLOR = "#5f87d7"
# Work after the last milestone has no milestone to be coloured for.
REMAINDER_COLOR = "#8b8f96"


def read_palette(project: Project) -> Palette:
    """The colour map the project's milestones are shaded from."""
    return palette(read_assumptions(project).palette)


@dataclass(frozen=True)
class Assumptions:
    """What the project node stores about its staffing: each None where the file is
    silent and the default answers. Read whole, changed with ``replace``, written whole."""

    efficiency: float | None = None
    palette: str | None = None
    team: tuple[int, int] | None = None  # (people, agents)


def read_assumptions(project: Project) -> Assumptions:
    """The project's stored assumptions exactly as written — None for an absent key, and
    for an unreadable one, so a rewrite drops it rather than carrying nonsense along."""
    entry = project.module_data.get(MODULE_ID) or {}
    efficiency = entry.get(EFFICIENCY_KEY)
    # A bool is not a number here, and a factor outside (0, 1] would divide an estimate
    # into nonsense — either reads as the default.
    if (
        isinstance(efficiency, bool)
        or not isinstance(efficiency, int | float)
        or not 0.0 < efficiency <= 1.0
    ):
        efficiency = None
    written = entry.get(PALETTE_KEY)
    palette_id = written if isinstance(written, str) and palette(written).id == written else None
    return Assumptions(
        efficiency=float(efficiency) if efficiency is not None else None,
        palette=palette_id,
        team=_team_in(entry.get(TEAM_KEY)),
    )


def _team_in(value: object) -> tuple[int, int] | None:
    if not isinstance(value, list) or len(value) != 2:
        return None
    humans, agents = value
    if any(isinstance(count, bool) or not isinstance(count, int) for count in (humans, agents)):
        return None
    return (humans, agents) if humans >= 1 and agents >= 1 else None


def write_assumptions(assumptions: Assumptions) -> dict[str, Any]:
    """The project entry to store. Every field on its default gives ``{}``, which removes
    the file — the project is back on every default."""
    entry: dict[str, Any] = {}
    if assumptions.efficiency is not None:
        entry[EFFICIENCY_KEY] = float(assumptions.efficiency)
    if assumptions.palette is not None and assumptions.palette != DEFAULT_PALETTE:
        if palette(assumptions.palette).id != assumptions.palette:
            raise ValueError(f"no palette called {assumptions.palette!r}")
        entry[PALETTE_KEY] = assumptions.palette
    if assumptions.team is not None and assumptions.team != DEFAULT_TEAM:
        humans, agents = assumptions.team
        if humans < 1 or agents < 1:
            raise ValueError("a team needs at least one person and one agent")
        entry[TEAM_KEY] = [int(humans), int(agents)]
    return stamped(entry, DATA_FORMAT.version) if entry else {}


def write_project(
    project: Project,
    *,
    efficiency: float | None = None,
    palette_id: str | None = None,
    team: tuple[int, int] | None = None,
    clear: str = "",
) -> dict[str, Any]:
    """The project's entry with one assumption changed and the rest as stored — what
    every control and verb pushes. ``clear`` names a field going back to its default."""
    current = read_assumptions(project)
    changed = Assumptions(
        efficiency=efficiency if efficiency is not None else current.efficiency,
        palette=palette_id if palette_id is not None else current.palette,
        team=team if team is not None else current.team,
    )
    if clear:
        changed = replace(changed, **{clear: None})
    return write_assumptions(changed)


def read_efficiency(project: Project) -> float:
    """The stored focus factor, or the default."""
    efficiency = read_assumptions(project).efficiency
    return DEFAULT_EFFICIENCY if efficiency is None else efficiency


def read_team(project: Project) -> tuple[int, int]:
    """The team the calendar is dated for: (people, agents), the smallest by default."""
    return read_assumptions(project).team or DEFAULT_TEAM


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


def milestone_colors(
    library: Library, project: Project, is_milestone: Callable[[Step], bool]
) -> dict[StepId, str]:
    """Every milestone's hex, by step id: the colour somebody chose for it, else its shade
    of the project's map dealt by place in the sequence.

    **The one deal.** The canvas, the order table, the progression board, the Tests tab, the
    coverage lane, the step panel, the calendar and the report all read this, so a milestone
    cannot wear two colours in one window. The sequence is ``ordering.placed``'s — the order
    ``dplanner milestone list`` prints and the order the stretches run in, which
    :func:`phase_colors` relies on and a test pins.

    One walk per project rather than one per milestone, the shape ``_milestone_stats`` has
    in the composition root; a project with no milestones costs no walk at all. An override
    does not consume a slot differently — the dealt list is indexed by ordinal either way,
    so pinning one milestone leaves the others where they were.
    """
    if not any(is_milestone(step) for step in project.steps):
        return {}
    ordered = [place.step for place in placed(library, project) if is_milestone(place.step)]
    dealt = shades(read_palette(project), len(ordered))
    return {step.id: read_color(step) or dealt[index] for index, step in enumerate(ordered)}


def phase_colors(stretches: tuple[Phase, ...], colors: dict[StepId, str]) -> list[str]:
    """One hex colour per stretch, from :func:`milestone_colors`: the work after the last
    milestone is neutral — unless it is all there is."""
    return [
        colors[phase.milestone.id]
        if phase.milestone is not None
        else (REMAINDER_COLOR if index else WHOLE_COLOR)
        for index, phase in enumerate(stretches)
    ]


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
