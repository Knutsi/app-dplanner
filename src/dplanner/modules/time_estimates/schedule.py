"""The plan's assumptions, and the staffing matrix they turn the estimates into.

The derivation is the domain's (``domain/schedule.py``'s ``phases`` over ``parallel_finish``);
this is the module's half — where the stored assumptions live, and the grid of teams
``dplanner schedule matrix`` prints (:func:`time_report`). The tab, the recorder and the
report date the plan for the stored team through the same walk (``progress.take``), so the
window and the terminal cannot answer "when does this team land it" two different ways.

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

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import date, timedelta
from math import ceil, log
from typing import Any, TypeGuard

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.ordering import cyclic, placed
from dplanner.domain.progression import DONE, IN_PROGRESS
from dplanner.domain.schedule import (
    HALF,
    SATURDAY,
    Phase,
    ScheduleFacts,
    Wait,
    critical_path,
    no_wait,
    phases,
    spent_since,
    working_days_between,
)
from dplanner.theme.palettes import DEFAULT_PALETTE, Palette, palette, shades

MODULE_ID = "time_estimates"


def _to_format_2(entry: dict[str, Any]) -> dict[str, Any]:
    """Format 2 remembers the focus before its last change (``efficiency_was``). A format-1
    entry has no such memory and none to derive; the bump is so an older build, whose
    writer rebuilds the entry, knows it would drop one."""
    return entry


DATA_FORMAT = ModuleDataFormat(MODULE_ID, 2, (_to_format_2,))
EFFICIENCY_KEY = "efficiency"
EFFICIENCY_WAS_KEY = "efficiency_was"
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

# A project with no milestones is one stretch, in the report's own blue.
WHOLE_COLOR = "#5f87d7"
# Work after the last milestone has no milestone to be coloured for.
REMAINDER_COLOR = "#8b8f96"


def read_palette(project: Project) -> Palette:
    """The colour map the project's milestones are shaded from."""
    return palette(read_assumptions(project).palette)


@dataclass(frozen=True)
class FocusChange:
    """The focus the project had before its last change, and the day the new one began.

    The one piece of past budget a forecast needs: work already under way ran at the old
    focus until ``until``, and crediting it at the new one would re-date it. Every other
    past budget is unneeded — a forecast looks forward, and each past day's is in its row.
    """

    until: date
    efficiency: float


@dataclass(frozen=True)
class Assumptions:
    """What the project node stores about its staffing: each None where the file is
    silent and the default answers. Read whole, changed with ``replace``, written whole."""

    efficiency: float | None = None
    palette: str | None = None
    team: tuple[int, int] | None = None  # (people, agents)
    efficiency_was: FocusChange | None = None


def read_assumptions(project: Project) -> Assumptions:
    """The project's stored assumptions exactly as written — None for an absent key, and
    for an unreadable one, so a rewrite drops it rather than carrying nonsense along."""
    entry = project.module_data.get(MODULE_ID) or {}
    efficiency = _factor_in(entry.get(EFFICIENCY_KEY))
    written = entry.get(PALETTE_KEY)
    palette_id = written if isinstance(written, str) and palette(written).id == written else None
    return Assumptions(
        efficiency=efficiency,
        palette=palette_id,
        team=_team_in(entry.get(TEAM_KEY)),
        efficiency_was=_change_in(entry.get(EFFICIENCY_WAS_KEY)),
    )


def _factor_in(value: object) -> float | None:
    # A bool is not a number here, and a factor outside (0, 1] would divide an estimate
    # into nonsense — either reads as the default.
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0.0 < value <= 1.0:
        return None
    return float(value)


def _change_in(value: object) -> FocusChange | None:
    if not isinstance(value, dict):
        return None
    efficiency = _factor_in(value.get(EFFICIENCY_KEY))
    try:
        until = date.fromisoformat(value["until"])
    except (KeyError, TypeError, ValueError):
        return None
    return FocusChange(until, efficiency) if efficiency is not None else None


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
    if assumptions.efficiency_was is not None:
        was = assumptions.efficiency_was
        entry[EFFICIENCY_WAS_KEY] = {
            "until": was.until.isoformat(),
            EFFICIENCY_KEY: float(was.efficiency),
        }
    return stamped(entry, DATA_FORMAT.version) if entry else {}


def write_project(
    project: Project,
    *,
    today: date,
    efficiency: float | None = None,
    palette_id: str | None = None,
    team: tuple[int, int] | None = None,
    clear: str = "",
) -> dict[str, Any]:
    """The project's entry with one assumption changed and the rest as stored — what
    every control and verb pushes. ``clear`` names a field going back to its default.

    A change of focus remembers the one it replaced (``efficiency_was``), the new one
    beginning tomorrow — today's work was done at the old. A second change the same day
    keeps the focus the day began with, as an estimate's history keeps the day's first.
    """
    current = read_assumptions(project)
    changed = Assumptions(
        efficiency=efficiency if efficiency is not None else current.efficiency,
        palette=palette_id if palette_id is not None else current.palette,
        team=team if team is not None else current.team,
        efficiency_was=current.efficiency_was,
    )
    if clear:
        changed = replace(changed, **{clear: None})
    was, now = _effective(current.efficiency), _effective(changed.efficiency)
    if now != was:
        began = today + timedelta(days=1)
        earlier = current.efficiency_was
        kept = earlier.efficiency if earlier is not None and earlier.until == began else was
        changed = replace(changed, efficiency_was=FocusChange(began, kept))
    return write_assumptions(changed)


def _effective(efficiency: float | None) -> float:
    return efficiency if efficiency is not None else DEFAULT_EFFICIENCY


def read_efficiency_was(project: Project) -> FocusChange | None:
    """The focus before the last change, and the day the new one began — or None."""
    return read_assumptions(project).efficiency_was


def read_efficiency(project: Project) -> float:
    """The stored focus factor, or the default."""
    return _effective(read_assumptions(project).efficiency)


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


# The evidence a pace needs: working days of work behind the plan, and people's steps
# finished. Before both it is a guess, and a date moved by a guess is worse than none.
PACE_AFTER = 5
PACE_STEPS = 3
# A pace this close to the planned one is the plan's: step-sized noise, not a trend.
PACE_BAND = 0.1
# How far either way a pace is believed.
PACE_LEAST, PACE_MOST = 0.25, 4.0


def pace_so_far(
    steps: Iterable[Step],
    days_for: Callable[[Step], float | None],
    *,
    is_agent: Callable[[Step], bool],
    status_for: Callable[[Step], str],
    started_for: Callable[[Step], date | None],
    since_for: Callable[[Step], date | None],
    start: date,
    today: date,
    people: int,
) -> float | None:
    """How fast people's finished steps ran against the plan: the days they were given —
    ``days_for``, stretched at the planned focus — over the working days they took, each from
    the middle of the day it started to the middle of the day it was done. 1 is as planned,
    0.5 half the speed. It is the focus measured, so like the focus it is people's alone: an
    agent's step runs at its estimate. None before :data:`PACE_AFTER` working days of work
    and :data:`PACE_STEPS` finished steps.

    **A day is shared by the steps open on it.** Where more of people's steps were in
    progress than there are ``people``, each is taken to have had its share of the day — two
    steps kept going by one person half each — so juggling reads as juggling, not as working
    at half the speed; and a step blocked on the way counts its stall as slowness only while
    nothing else was being worked."""
    if today < start or working_days_between(start, today) <= PACE_AFTER:
        return None
    theirs = [step for step in steps if not is_agent(step)]
    spans: dict[StepId, list[_HalfDay]] = {}
    for step in theirs:
        status, started = status_for(step), started_for(step)
        until = since_for(step) if status == DONE else today if status == IN_PROGRESS else None
        if started is not None and until is not None:
            spans[step.id] = _half_days(started, until)
    open_in: dict[_HalfDay, int] = {}
    for span in spans.values():
        for half in span:
            open_in[half] = open_in.get(half, 0) + 1
    given = took = 0.0
    count = 0
    for step in theirs:
        days = days_for(step)
        if days is None or status_for(step) != DONE or step.id not in spans:
            continue
        given += days
        took += sum(HALF * min(1.0, people / open_in[half]) for half in spans[step.id])
        count += 1
    if count < PACE_STEPS or took <= 0:
        return None
    return min(PACE_MOST, max(PACE_LEAST, given / took))


# A working day's morning (0) or afternoon (1).
_HalfDay = tuple[date, int]


def _half_days(first: date, last: date) -> list[_HalfDay]:
    """The half days from the middle of ``first`` to the middle of ``last``: its afternoon,
    both halves of every working day between, and the morning of ``last``."""
    days = (first + timedelta(days=offset) for offset in range((last - first).days + 1))
    working = [day for day in days if day.weekday() < SATURDAY]
    if len(working) < 2:
        return []
    between = [(day, half) for day in working[1:-1] for half in (0, 1)]
    return [(working[0], 1), *between, (working[-1], 0)]


def as_planned(pace: float) -> bool:
    """Whether ``pace`` is the plan's own, within :data:`PACE_BAND` either way."""
    return abs(log(pace)) < log(1 + PACE_BAND)


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


def schedule_facts(
    project: Project,
    today: date,
    *,
    is_agent: Callable[[Step], bool],
    status_for: Callable[[Step], str],
    since_for: Callable[[Step], date | None],
    is_marker: Callable[[Step], bool],
    day_over: bool = False,
    resume_days: Callable[[Step], float | None] | None = None,
) -> ScheduleFacts:
    """What has happened in ``project`` by ``today``, for the calendar to re-date it from:
    the stored statuses with their days, and work in flight credited at the focus it ran at
    — and, where given, what the rest costs once the plan no longer holds (``resume_days``).

    A person's step started before the focus last changed ran at the old focus until the new
    one began (``efficiency_was``), so those days count at the old one's pace — crediting
    them at the new one re-dates work already done. An agent's step has no focus.
    ``day_over`` reads ``today`` at its end, as a simulation's day is (``ScheduleFacts``).
    """
    efficiency = read_efficiency(project)
    was = read_efficiency_was(project)

    def worked(step: Step) -> float:
        since = since_for(step)
        whole = spent_since(since, today)
        if was is None or is_agent(step) or since is None or was.until <= since:
            return whole
        after = 0.0 if was.until > today else float(working_days_between(was.until, today))
        return (whole - after) * (was.efficiency / efficiency) + after

    return ScheduleFacts(
        today=today,
        status_of=status_for,
        since_of=since_for,
        is_marker=is_marker,
        worked=worked,
        resume_days=resume_days,
        day_over=day_over,
    )


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
    facts: ScheduleFacts | None = None,
    wait_of: Callable[[Step], Wait | None] = no_wait,
) -> tuple[Cell, Cell]:
    """One staffing, both lenses: the parallel-adjusted cell and the calendar one. Project
    days count work, not dates, so only the calendar is re-dated from ``facts``."""
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
        wait_of=wait_of,
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
        facts=facts,
        wait_of=wait_of,
    )
    # The whole lands when its latest stretch does — which work done out of sequence makes
    # other than the last.
    landing = max((phase.finish for phase in slow if phase.finish), default=None)
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
    facts: ScheduleFacts | None = None,
    wait_of: Callable[[Step], Wait | None] = no_wait,
) -> TimeReport | None:
    """The full matrix over ``HUMANS`` by ``AGENTS``. None only when the project has no
    steps. ``start`` and ``efficiency`` arrive resolved — the caller owns where a start
    date and a stored factor live, the same seam ``days_for`` and ``is_agent`` use — and
    ``facts``, where given, re-date every calendar cell from what has happened."""
    if not project.steps:
        return None
    work = [step for step in project.steps if wait_of(step) is None]  # A wait is no work.
    human_days = sum(days_for(step) or 0.0 for step in work if not is_agent(step))
    agent_days = sum(days_for(step) or 0.0 for step in work if is_agent(step))
    has_agent_steps = any(is_agent(step) for step in work)
    loop = tuple(cyclic(library, project))
    if loop:
        return TimeReport(
            start=start,
            efficiency=efficiency,
            human_days=human_days,
            agent_days=agent_days,
            unestimated=sum(1 for step in work if days_for(step) is None),
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
                facts=facts,
                wait_of=wait_of,
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
