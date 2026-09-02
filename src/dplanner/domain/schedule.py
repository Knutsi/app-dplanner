"""When does the work land — the order walk, carrying estimates instead of counting hops.

``ordering.py`` answers "in what order can this be done"; this answers "and when". It is the
same walk: take the placed order, ask how many days each step is thought to take, and lay
them end to end from a start date.

**The domain never learns what an estimate is stored as.** ``days_for`` is a function the
caller supplies, so the module that owns the estimate aspect owns its schema, and this file
works for any other source of days somebody wires in later. That is the same seam
``ordering.py`` uses for the graph — plain functions over the model, no Qt — and it is what
lets the order table, ``dplanner schedule show``, ``--json`` and every report after them read
one implementation.

**Named assumptions, no pretend precision.** ``schedule`` is serial — one worker, steps
end to end down the topological order, weekends skipped, a week is five working days.
``critical_path`` is the other bracket: unlimited workers, bounded only by the ``requires``
chains. Real staffing lands between the two — ``parallel_finish`` simulates it for a stated
worker cap — and a report that prints its assumption labelled is honest where a single
number would be a guess wearing a date.

**Every plan has a start.** A project nobody has dated starts today — the caller resolves
that (see ``estimation/schedule.py``'s ``start_of``) and this file is simply handed a date.
"If you start now" is the useful answer to a plan with no date on it, and it means there is
one code path here rather than two.

**Nothing here is written to disk**, for ``ordering.py``'s reason: a stored date disagrees
with the estimate it came from the moment ``dplanner estimate set`` runs with no window open
to notice.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil

from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.ordering import Placed, placed
from dplanner.domain.scope import cone

WORKING_DAYS_PER_WEEK = 5
SATURDAY = 5  # date.weekday(): Monday is 0.

# Past this much work, days stop being the unit a person thinks in.
WEEKS_ABOVE_DAYS = 7.0

_ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class Scheduled:
    """One step's place in the plan: what it costs, what it has cost by then, and when.

    ``days`` is ``None`` for an unestimated step, and so is ``finish``. "We have not
    estimated this" and "this is free" are different claims — a date printed against a step
    nobody has sized would read as a promise, so the column stays empty and the gap shows.
    ``accumulated`` still carries the known work through that point.
    """

    place: Placed
    days: float | None
    accumulated: float
    finish: date | None


def next_working_day(when: date) -> date:
    """``when``, or the Monday after it if it lands on a weekend."""
    while when.weekday() >= SATURDAY:
        when += _ONE_DAY
    return when


def working_days_after(start: date, days: float) -> date:
    """The date working day ``days`` falls on, counting ``start`` as working day one.

    A fraction is still a day on a calendar — half a day of work lands on a date — so the
    count rounds up. A start on a weekend rolls forward to the Monday.
    """
    when = next_working_day(start)
    for _ in range(max(1, ceil(days)) - 1):
        when = next_working_day(when + _ONE_DAY)
    return when


def working_days_between(start: date, finish: date) -> int:
    """How many working days ``start`` through ``finish`` span, both ends counted — the
    inverse of :func:`working_days_after`, so a landing date reads back as a length."""
    count = 0
    when = start
    while when <= finish:
        if when.weekday() < SATURDAY:
            count += 1
        when += _ONE_DAY
    return count


MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
ABBREVIATION = 3  # "September" → "Sep". True of every month in English.


def format_date(when: date, today: date | None = None) -> str:
    """A date as a person reads it: "23 September", or "14 Feb '27" in another year.

    A schedule is read for *when*, and an ISO date makes the reader do the month arithmetic.
    The year is the part that is usually obvious, so it appears only when it is not — and
    when it does, the month abbreviates to keep the column from doubling in width.

    The month names are spelled out here rather than taken from ``strftime``, which is
    locale-dependent: the interface is English, and a date that read "23 september" on one
    machine and "23 September" on another would be a test that passes where it was written.

    ``today`` is a parameter so the rule can be tested without waiting for a year to pass;
    the default is the clock, because every caller means "now".
    """
    today = today or date.today()
    if when.year == today.year:
        return f"{when.day} {MONTHS[when.month - 1]}"
    return f"{when.day} {MONTHS[when.month - 1][:ABBREVIATION]} '{when.year % 100:02d}"


def as_weeks(days: float) -> float:
    """``days`` of work as working weeks. A week is five days, because a day is a working one."""
    return days / WORKING_DAYS_PER_WEEK


def format_days(days: float | None) -> str:
    """A day count as a person reads it: "3d", or "2.4w" once there are too many days.

    Here rather than in a view because the order table and ``dplanner schedule show`` render
    the same numbers, and a table that said "2.4w" where the terminal said "12d" would be two
    answers to one question — the argument ``ordering.placed()`` already makes for the index.
    """
    if days is None:
        return ""
    if days > WEEKS_ABOVE_DAYS:
        return f"{as_weeks(days):g}w"
    return f"{days:g}d"


def format_day_count(days: float) -> str:
    """A day count as prose: "1 day", "2.5 days" — for sentences, where ``format_days``
    feeds columns. The grammar lives here so no verb prints "1 days" again."""
    return f"{days:g} day" if days == 1 else f"{days:g} days"


def schedule(
    order: Sequence[Placed],
    days_for: Callable[[Step], float | None],
    start: date,
) -> list[Scheduled]:
    """The order with a running total and a date against each step."""
    scheduled: list[Scheduled] = []
    accumulated = 0.0
    for place in order:
        days = days_for(place.step)
        if days is not None:
            accumulated += days
        finish = working_days_after(start, accumulated) if days is not None else None
        scheduled.append(Scheduled(place=place, days=days, accumulated=accumulated, finish=finish))
    return scheduled


@dataclass(frozen=True)
class ParallelFinish:
    """Makespan under a fixed worker cap — the bracket between ``schedule`` and
    ``critical_path``.

    ``unestimated`` counts every step that ran as zero days, project-wide — broader than
    ``CriticalPath.unestimated``, which counts only the chain, because here every step
    takes a slot and every zero is in the answer.
    """

    days: float  # Simulated makespan in working days.
    unestimated: int  # Steps that ran as zero days — the number's honesty.


def parallel_finish(
    library: Library,
    project: Project,
    days_for: Callable[[Step], float | None],
    is_agent: Callable[[Step], bool],
    *,
    humans: int,
    agents: int,
    among: Sequence[Step] | None = None,
) -> ParallelFinish | None:
    """The makespan with ``humans`` people and ``agents`` coding agents. None only when
    there are no steps to run.

    ``among`` narrows the walk to those steps — one stretch of a plan — and an edge to a
    step outside it counts as already met: whoever hands over a subset is saying the rest
    has happened, or belongs to another stretch of time (:func:`phases`). The default is
    the whole project.

    Two pools, handed as a predicate the way ``days_for`` is handed as a function: an
    agent step waits for an agent slot, every other step for a human one, and neither
    pool ever takes the other's work. Anything else about staffing — an efficiency
    factor, say — belongs to the caller, who can wrap ``days_for`` before handing it in;
    this walk never learns such a thing exists.

    The simulation is greedy list scheduling: whenever a slot frees, it takes the ready
    step with the longest remaining ``requires`` chain, ties broken by project step
    order. That is a deterministic model of "the team picks the longest pole first", not
    an optimum — but with ample slots it meets ``critical_path`` exactly, and with one
    human on all-human work it meets ``schedule``'s serial total, so the brackets pin it.
    """
    if humans < 1 or agents < 1:
        raise ValueError("a pool with work in it needs at least one worker")
    steps = tuple(project.steps if among is None else among)
    if not steps:
        return None
    order = {step.id: index for index, step in enumerate(steps)}
    days = {step.id: days_for(step) for step in steps}
    waiting: dict[StepId, set[StepId]] = {}
    dependents: dict[StepId, list[StepId]] = {step.id: [] for step in steps}
    for step in steps:
        requires = {target for target in step.edges.get("requires", []) if target in order}
        waiting[step.id] = requires
        for target in requires:
            dependents[target].append(step.id)

    tails: dict[StepId, float] = {}

    def tail_of(step_id: StepId, seen: frozenset[StepId]) -> float:
        if step_id in tails:
            return tails[step_id]
        if step_id in seen:  # Defensive: a hand-edited file could still contain a cycle.
            return 0.0
        ahead = max(
            (tail_of(after, seen | {step_id}) for after in dependents[step_id]),
            default=0.0,
        )
        tails[step_id] = (days[step_id] or 0.0) + ahead
        return tails[step_id]

    for step in steps:
        tail_of(step.id, frozenset())

    free = {True: agents, False: humans}  # Keyed by is_agent's answer.
    pool = {step.id: is_agent(step) for step in steps}
    ready: dict[bool, list[StepId]] = {True: [], False: []}
    for step in steps:
        if not waiting[step.id]:
            ready[pool[step.id]].append(step.id)
    running: list[tuple[float, StepId]] = []
    now = 0.0
    remaining = len(steps)
    while remaining:
        for lane, queue in ready.items():
            while queue and free[lane]:
                queue.sort(key=lambda step_id: (-tails[step_id], order[step_id]))
                step_id = queue.pop(0)
                free[lane] -= 1
                running.append((now + (days[step_id] or 0.0), step_id))
        if not running:  # Defensive: unreachable steps under a hand-edited cycle.
            break
        now = min(finish for finish, _ in running)
        for finish, step_id in tuple(running):
            if finish > now:
                continue
            running.remove((finish, step_id))
            free[pool[step_id]] += 1
            remaining -= 1
            for after in dependents[step_id]:
                waiting[after].discard(step_id)
                if not waiting[after]:
                    ready[pool[after]].append(after)
    return ParallelFinish(
        days=now,
        unestimated=sum(1 for value in days.values() if value is None),
    )


@dataclass(frozen=True)
class Phase:
    """One stretch of the plan: a milestone and the work leading up to it — or, with no
    milestone, the work nothing gathers, which runs after the last one.

    ``finish`` is None when nothing in the stretch is estimated, for ``Scheduled``'s
    reason. ``asked`` is the milestone's own start date when it has one; ``start`` is
    where the stretch actually begins, which differs only when the date asked for fell
    before the previous milestone landed — the sequence holds and the ask is reported.
    """

    milestone: Step | None
    steps: tuple[Step, ...]  # Project order, the milestone last among its own.
    days: float  # Makespan of this stretch alone, in working days.
    start: date
    finish: date | None
    asked: date | None
    unestimated: int

    @property
    def pushed(self) -> bool:
        """Whether the date asked for could not be kept — a weekend rolling to its Monday
        is keeping it."""
        return self.asked is not None and self.start > next_working_day(self.asked)

    @property
    def calendar_days(self) -> int:
        """The stretch as a calendar reads it: whole working days from its start to its
        landing, both counted — what a list prints, where ``days`` is the simulation's
        fraction. Zero when nothing landed."""
        return working_days_between(self.start, self.finish) if self.finish else 0


def phases(
    library: Library,
    project: Project,
    days_for: Callable[[Step], float | None],
    is_agent: Callable[[Step], bool],
    *,
    humans: int,
    agents: int,
    start: date,
    is_milestone: Callable[[Step], bool],
    start_for: Callable[[Step], date | None],
) -> list[Phase]:
    """The plan as milestones run one after another, each dated from the last.

    A milestone's stretch is its ``requires`` cone truncated at the milestones before it
    (``scope.cone``) — what is new since the last one — plus itself; a step two milestones
    both reach belongs to the earlier. Stretches run **in sequence**: the first begins at
    ``start``, every later one the working day after the previous lands, and a milestone
    with a date of its own (``start_for``) begins there instead when that is later. Each
    stretch is :func:`parallel_finish` over its own steps, so the team is the same
    throughout and the whole is that one simulation asked once per milestone.

    What no milestone gathers runs last, as a stretch with no milestone. A project with no
    milestones is that one stretch, which is the plain simulation from ``start``. Both
    ``is_milestone`` and ``start_for`` are handed in like ``days_for``: the domain learns
    that some steps close a stretch, never what marks them.
    """
    milestones = [place.step for place in placed(library, project) if is_milestone(place.step)]
    taken: set[StepId] = set()
    groups: list[tuple[Step | None, tuple[Step, ...]]] = []
    for closing in milestones:
        found = cone(library, project, closing.id, stops_at=is_milestone)
        own = ({step.id for step in found.steps} - taken) | {closing.id}
        taken |= own
        groups.append((closing, tuple(step for step in project.steps if step.id in own)))
    rest = tuple(step for step in project.steps if step.id not in taken)
    if rest:
        groups.append((None, rest))

    result: list[Phase] = []
    when = start  # The earliest the next stretch may begin.
    for index, (milestone, steps) in enumerate(groups):
        asked = start_for(milestone) if milestone is not None else None
        begins = asked if asked is not None and (index == 0 or asked >= when) else when
        begins = next_working_day(begins)
        run = parallel_finish(
            library, project, days_for, is_agent, humans=humans, agents=agents, among=steps
        )
        assert run is not None  # A group is never empty: a milestone is at least itself.
        finish = working_days_after(begins, run.days) if run.days > 0 else None
        result.append(
            Phase(
                milestone=milestone,
                steps=steps,
                days=run.days,
                start=begins,
                finish=finish,
                asked=asked,
                unestimated=run.unestimated,
            )
        )
        when = next_working_day(finish + _ONE_DAY) if finish is not None else begins
    return result


@dataclass(frozen=True)
class CriticalPath:
    """The longest days-weighted chain through a project's ``requires`` graph.

    The serial schedule answers "one worker, steps end to end"; this answers the other
    honest assumption — unlimited workers, dependency-bound — and the two bracket every
    real staffing in between.
    """

    days: float  # The chain's total; a floor no amount of staffing gets under.
    steps: tuple[Step, ...]  # The chain itself, first thing first.
    unestimated: int  # Steps on the chain counted as zero days — the floor's honesty.


def critical_path(
    library: Library,
    project: Project,
    days_for: Callable[[Step], float | None],
) -> CriticalPath | None:
    """None only when the project has no steps.

    ``ordering.depths()``'s walk, weighted by ``days_for`` instead of one per hop — and
    handed the function rather than a schema, so whoever owns the estimate keeps its
    shape. Ties break by project step order, the same rule every derivation here uses,
    so the answer changes when the graph or the estimates change and not otherwise.
    """
    if not project.steps:
        return None
    order = {step.id: index for index, step in enumerate(project.steps)}
    finishes: dict[StepId, float] = {}
    towards: dict[StepId, StepId | None] = {}

    def finish_of(step_id: StepId, seen: frozenset[StepId]) -> float:
        if step_id in finishes:
            return finishes[step_id]
        if step_id in seen:  # Defensive: a hand-edited file could still contain a cycle.
            return 0.0
        step = library.step(step_id)
        own = days_for(step) or 0.0
        waiting = step.edges.get("requires", [])
        resolved = sorted(
            (target for target in waiting if project.step(target) is not None),
            key=lambda target: order[target],
        )
        best: StepId | None = None
        upstream = 0.0
        for target in resolved:
            candidate = finish_of(target, seen | {step_id})
            if candidate > upstream:  # Strict: the earliest of equals keeps the tie.
                upstream, best = candidate, target
        finishes[step_id] = own + upstream
        towards[step_id] = best
        return finishes[step_id]

    for step in project.steps:
        finish_of(step.id, frozenset())
    last = max(project.steps, key=lambda step: (finishes[step.id], -order[step.id]))
    chain: list[Step] = []
    at: StepId | None = last.id
    while at is not None:
        chain.append(library.step(at))
        at = towards.get(at)
    chain.reverse()
    return CriticalPath(
        days=finishes[last.id],
        steps=tuple(chain),
        unestimated=sum(1 for step in chain if days_for(step) is None),
    )
