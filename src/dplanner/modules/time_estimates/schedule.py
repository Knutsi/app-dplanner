"""The plan's assumptions, and the staffing matrix they turn the estimates into.

The derivation is the domain's (``domain/schedule.py``'s ``phases`` over ``parallel_finish``);
this is the module's half — where the stored assumptions live, and the report both surfaces
render. The tab and ``dplanner schedule matrix`` read :func:`time_report`, so the window and
the terminal cannot answer "how long with two people and three agents" two different ways.

**Qt-free**, like ``estimation/schedule.py``: the CLI reaches this file and must start on a
machine with no graphics stack. ``tests/test_architecture.py``'s ``HEADLESS_FILES`` names it.

**Four assumptions reach disk, all under this module's id, and nothing derived does.**
On the project node, ``{"efficiency": 0.5, "palette": "mako"}`` — the focus factor, the
fraction of a working day a person actually spends on this project, and the colour map
the milestones are shaded from (absent for the default, FORMAT.md's absence rule). On a
milestone step, ``{"start": "2026-10-05", "color": "#e0602c"}`` — a date the milestone's
stretch of work begins on rather than the day the previous one lands, and a colour chosen
over the dealt one; either key alone is fine and an empty entry removes the file. One
module, one namespace, two node kinds — ``estimation``'s precedent. Every matrix cell and
every landing date is recomputed from the graph and the estimates, for ``ordering.py``'s
reason: a stored answer disagrees with what it came from the moment ``dplanner estimate
set`` runs with no window open to notice.

**Calendar time is the same simulation over stretched estimates.** :func:`stretched` wraps
``days_for`` so a human step's days divide by the factor while agent steps pass through —
the domain walk never learns an efficiency exists, the same way it never learned where the
estimates live. Agents are not stretched because their human-in-the-loop cost is already
inside the quarter-day estimate convention; the factor prices the *person's* divided week.

**A milestone's colour is its place in the sequence, read off one colour map** unless
somebody picked one. The project chooses a :class:`Palette` — a perceptually ordered map
from data visualisation (viridis, mako, rocket, …), the interior of it so every shade
reads on a light and a dark surface — and :func:`shades` deals the milestones evenly along
it: two milestones sit a quarter and three quarters of the way in, eight fill it, and the
order of the shades is the order of the roadmap. Shades of one map rather than eight
competing hues, because a calendar of milestones is a sequence and should look like one.
Hex strings here so the CLI can print and store them; the view turns them into paint.
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
PALETTE_KEY = "palette"
START_KEY = "start"
COLOR_KEY = "color"

# The matrix's extent: enough rows to show the human ceiling, enough columns to show the
# agent one, small enough to read at a glance.
HUMANS = (1, 2, 3)
AGENTS = (1, 2, 3, 4)


@dataclass(frozen=True)
class Palette:
    """One colour map, as the stops the milestones are shaded between.

    Each is the legible interior of a published map — the darkest and lightest ends are
    left off, because a fill that vanishes into a light theme or a dark one is no colour
    at all. ``stops`` run dark to light, so the first milestone wears the deepest shade.
    """

    id: str
    name: str
    stops: tuple[str, ...]


PALETTES: tuple[Palette, ...] = (
    Palette(
        "viridis",
        "Viridis",
        ("#482878", "#3e4989", "#31688e", "#26828e", "#1f9e89", "#35b779", "#6ece58"),
    ),
    Palette(
        "mako",
        "Mako",
        ("#2f1c4f", "#3b3f7c", "#3b5f92", "#3c7da0", "#47a1ad", "#6dc1ae"),
    ),
    Palette(
        "crest",
        "Crest",
        ("#2a4e7d", "#2d5f8c", "#37739c", "#3f87a3", "#4b9ba2", "#5fae9d", "#7fbf98"),
    ),
    Palette(
        "plasma",
        "Plasma",
        ("#46039f", "#7201a8", "#9c179e", "#bd3786", "#d8576b", "#ed7953", "#fb9f3a"),
    ),
    Palette(
        "magma",
        "Magma",
        ("#3b0f70", "#641a80", "#8c2981", "#b73779", "#de4968", "#f7705c", "#fe9f6d"),
    ),
    Palette(
        "inferno",
        "Inferno",
        ("#420a68", "#781c6d", "#a52c60", "#cf4446", "#ed6925", "#fb9b06"),
    ),
    Palette(
        "rocket",
        "Rocket",
        ("#2c1439", "#5b1a4c", "#8a1f55", "#b7284e", "#dc4b3b", "#f07a3a", "#f8a952"),
    ),
    Palette(
        "flare",
        "Flare",
        ("#5d3444", "#77384f", "#913c56", "#a94057", "#be4a54", "#cf5b4f", "#da6f52", "#e79a6d"),
    ),
    Palette(
        "cividis",
        "Cividis",
        ("#123570", "#3b496c", "#575d6d", "#707173", "#8a8678", "#a59c74", "#c3b369"),
    ),
)
DEFAULT_PALETTE = PALETTES[0].id

# How many shades the swatch menu offers of the chosen map — enough to tell apart, few
# enough to name.
SWATCH_SHADES = 8

# A project with no milestones is one stretch, in the report's own blue — the matrix's tint.
WHOLE_COLOR = "#5f87d7"
# Work after the last milestone has no milestone to be coloured for.
REMAINDER_COLOR = "#8b8f96"


def palette(palette_id: str | None) -> Palette:
    """The palette by id; anything unknown — or None — reads as the default."""
    return next((found for found in PALETTES if found.id == palette_id), PALETTES[0])


def read_palette(project: Project) -> Palette:
    """The colour map the project's milestones are shaded from."""
    entry = project.module_data.get(MODULE_ID)
    written = entry.get(PALETTE_KEY) if entry else None
    return palette(written if isinstance(written, str) else None)


def _mix(low: str, high: str, share: float) -> str:
    """The colour ``share`` of the way from ``low`` to ``high``, channel by channel."""

    def channel(offset: int) -> int:
        start, end = int(low[offset : offset + 2], 16), int(high[offset : offset + 2], 16)
        return round(start + (end - start) * share)

    return "#" + "".join(f"{channel(offset):02x}" for offset in (1, 3, 5))


def shade(found: Palette, position: float) -> str:
    """The colour ``position`` of the way along the map, 0 to 1, blended between stops."""
    stops = found.stops
    place = min(max(position, 0.0), 1.0) * (len(stops) - 1)
    index = min(int(place), len(stops) - 2)
    return _mix(stops[index], stops[index + 1], place - index)


def shades(found: Palette, count: int) -> list[str]:
    """``count`` shades dealt evenly along the map, centred — one milestone sits in the
    middle, two at a quarter and three quarters, so no shade ever lands on an end."""
    return [shade(found, (index + 0.5) / count) for index in range(count)]


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


def write_project(efficiency: float | None, palette_id: str | None) -> dict[str, Any]:
    """The project entry to store: the focus factor, and the palette when it is not the
    default. Neither gives ``{}``, which removes the file — the project is back on both
    defaults. A caller changing one passes the other as it reads it."""
    entry: dict[str, Any] = {}
    if efficiency is not None:
        entry[EFFICIENCY_KEY] = float(efficiency)
    if palette_id is not None and palette_id != DEFAULT_PALETTE:
        if palette(palette_id).id != palette_id:
            raise ValueError(f"no palette called {palette_id!r}")
        entry[PALETTE_KEY] = palette_id
    return stamped(entry, DATA_FORMAT.version) if entry else {}


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


def phase_colors(
    stretches: tuple[Phase, ...], color_of: Callable[[Step], str | None], found: Palette
) -> list[str]:
    """One hex colour per stretch: the milestone's chosen colour, else its shade of the
    map by place in the sequence; the work after the last milestone is neutral — unless
    it is all there is."""
    dealt = shades(found, sum(1 for phase in stretches if phase.milestone is not None))
    colors: list[str] = []
    index = 0
    for phase in stretches:
        if phase.milestone is None:
            colors.append(REMAINDER_COLOR if index else WHOLE_COLOR)
            continue
        colors.append(color_of(phase.milestone) or dealt[index])
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
