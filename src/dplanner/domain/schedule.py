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

**A plan re-dates itself from what has happened** (:func:`phases` handed
:class:`ScheduleFacts`): its own dates stand while what is done matches them, and otherwise
the rest resumes from tomorrow, with work in flight credited — so a forecast holds still
while things go to plan and moves only when they do not.
"""

from collections.abc import Callable, Container, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from math import ceil, floor

from dplanner.domain.model import Library, Project, Step, StepId, local_day
from dplanner.domain.ordering import Placed, placed
from dplanner.domain.progression import BLOCKED, DONE, IN_PROGRESS, WAITING
from dplanner.domain.scope import cone

WORKING_DAYS_PER_WEEK = 5
SATURDAY = 5  # date.weekday(): Monday is 0.

# Past this much work, days stop being the unit a person thinks in.
WEEKS_ABOVE_DAYS = 7.0

_ONE_DAY = timedelta(days=1)

# What a fraction of a day is rounded up past: a step of 1 day at 60% focus is 1.6666…7 days,
# and float noise in a sum must never add a working day to a date.
GUARD = 1e-9


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


def working_days_after(start: date, days: float, guard: float = 0.0) -> date:
    """The date working day ``days`` falls on, counting ``start`` as working day one.

    A fraction is still a day on a calendar — half a day of work lands on a date — so the
    count rounds up, past ``guard`` (:data:`GUARD` where the days are a sum of fractions).
    A start on a weekend rolls forward to the Monday.

    Arithmetic rather than a walk: the canvas dates every milestone on each sync, and
    stepping a day at a time made that quadratic in the plan's length.
    """
    when = next_working_day(start)
    weeks, remainder = divmod(max(1, ceil(days - guard)) - 1, WORKING_DAYS_PER_WEEK)
    if when.weekday() + remainder >= SATURDAY:
        remainder += 2  # The remainder crosses a weekend.
    return when + timedelta(days=7 * weeks + remainder)


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
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


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


def short_date(when: date, today: date | None = None) -> str:
    """A date where a column has no room for the month spelled out: "23 Sep", with the
    year when it is not this one — :func:`format_date`'s rule, one size down. It is what
    the axis marks are labelled with, so a date printed inside a plot reads as the same
    kind of thing as the scale under it."""
    today = today or date.today()
    month = MONTHS[when.month - 1][:ABBREVIATION]
    if when.year == today.year:
        return f"{when.day} {month}"
    return f"{when.day} {month} '{when.year % 100:02d}"


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
        return f"{round(as_weeks(days), 1):g}w"
    return f"{days:g}d"


def format_day_count(days: float) -> str:
    """A day count as prose: "1 day", "2.5 days" — for sentences, where ``format_days``
    feeds columns. The grammar lives here so no verb prints "1 days" again."""
    return f"{days:g} day" if days == 1 else f"{days:g} days"


def volume(
    steps: Iterable[Step],
    days_for: Callable[[Step], float | None],
    counts_as_work: Callable[[Step], bool],
) -> tuple[float, int, int]:
    """What ``steps`` amount to for :func:`volume_words`: the estimated days, how many are
    work, and how many of those nobody has sized. A wait is no work, so it is no part of
    any of the three."""
    work = [step for step in steps if counts_as_work(step)]
    sized = [days for step in work if (days := days_for(step)) is not None]
    return sum(sized), len(work), len(work) - len(sized)


def volume_words(days: float, steps: int, unestimated: int) -> str:
    """How much work a set of steps comes to: "12 days over 7 steps, 1 unestimated".

    One sentence with four readers — the order table, ``dplanner order show``, ``estimate
    rollup`` and the Estimates tab's strip — for ``format_days``'s reason one function up:
    a tab that worded the same total differently from the terminal would be two answers to
    one question. What is unestimated is named rather than folded in, because a total that
    silently counted a step as nothing would read as a smaller project.
    """
    tail = f", {unestimated} unestimated" if unestimated else ""
    plural = "" if steps == 1 else "s"
    return f"{format_day_count(days)} over {steps} step{plural}{tail}"


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
class Wait:
    """What a wait step waits for: a day the steps after it may start on (``until``), or
    ``days`` working days from the moment it is reached. It takes no worker, carries no
    work and has no status of its own — handed in by ``wait_of``, like ``days_for``, so the
    domain never learns what marks one."""

    until: date | None = None
    days: float = 0.0


def no_wait(_step: Step) -> Wait | None:
    """``wait_of`` for a plan none of whose steps waits."""
    return None


def no_marker(_step: Step) -> bool:
    """``is_marker`` for a walk that knows no step carrying no work by design."""
    return False


# When a wait made ready at a moment of the walk is over, in the walk's working days.
Waits = Callable[[Step, float], float]


@dataclass(frozen=True)
class ParallelFinish:
    """Makespan under a fixed worker cap — the bracket between ``schedule`` and
    ``critical_path``.

    ``unestimated`` counts every step that ran as zero days, project-wide — broader than
    ``CriticalPath.unestimated``, which counts only the chain, because here every step
    takes a slot and every zero is in the answer. ``landings`` is the working day each
    step finished on in the simulation, from the walk's start — what an expected-progress
    curve is drawn from, and the one thing a makespan alone cannot say.
    """

    days: float  # Simulated makespan in working days.
    unestimated: int  # Steps that ran as zero days — the number's honesty.
    landings: dict[StepId, float] = field(default_factory=dict)
    starts: dict[StepId, float] = field(default_factory=dict)  # …and the day each began.


def parallel_finish(
    library: Library,
    project: Project,
    days_for: Callable[[Step], float | None],
    is_agent: Callable[[Step], bool],
    *,
    humans: int,
    agents: int,
    among: Sequence[Step] | None = None,
    running: frozenset[StepId] = frozenset(),
    wait_of: Callable[[Step], Wait | None] = no_wait,
    waits: Waits | None = None,
    is_marker: Callable[[Step], bool] = no_marker,
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

    ``running`` names work already in flight: it keeps the worker it has, so it goes first.
    It still waits for what it requires, and past the pool's size it queues like the rest.

    A wait (``wait_of``) takes no worker: the moment it is ready it waits, and ``waits`` says
    until when — by default its ``days`` from then, an ``until`` wait being over at once,
    since the walk knows no dates (:func:`phases` does, and does better). Nor does a marker
    (``is_marker``) — a milestone's own step, a feature: it lands the moment what it requires
    has, however busy the team is with other work.
    """
    if humans < 1 or agents < 1:
        raise ValueError("a pool with work in it needs at least one worker")
    steps = tuple(project.steps if among is None else among)
    if not steps:
        return None
    by_id = {step.id: step for step in steps}
    order = {step.id: index for index, step in enumerate(steps)}
    days = {step.id: _cost(step, days_for, wait_of) for step in steps}
    waiting = {step.id: _requires_among(step, order) for step in steps}
    dependents = _dependents(steps, waiting)
    tails = _tails(steps, days, dependents)
    over = waits or (lambda step, at: at + _waited_days(step, wait_of))

    free = {True: agents, False: humans}  # Keyed by is_agent's answer.
    pool = {step.id: is_agent(step) for step in steps}
    ready: dict[bool, list[StepId]] = {True: [], False: []}
    busy: list[tuple[float, StepId]] = []
    landings: dict[StepId, float] = {}
    starts: dict[StepId, float] = {}
    now = 0.0

    def idle(step: Step) -> bool:
        return wait_of(step) is not None or is_marker(step)

    def release(step_id: StepId) -> None:
        step = by_id[step_id]
        if idle(step):
            starts[step_id] = now
            busy.append((over(step, now) if wait_of(step) is not None else now, step_id))
        else:
            ready[pool[step_id]].append(step_id)

    for step in steps:
        if not waiting[step.id]:
            release(step.id)
    remaining = len(steps)
    while remaining:
        for lane, queue in ready.items():
            while queue and free[lane]:
                queue.sort(
                    key=lambda step_id: (step_id not in running, -tails[step_id], order[step_id])
                )
                step_id = queue.pop(0)
                free[lane] -= 1
                starts[step_id] = now
                busy.append((now + (days[step_id] or 0.0), step_id))
        if not busy:  # Defensive: unreachable steps under a hand-edited cycle.
            break
        now = min(finish for finish, _ in busy)
        for finish, step_id in tuple(busy):
            if finish > now:
                continue
            busy.remove((finish, step_id))
            landings[step_id] = finish
            if not idle(by_id[step_id]):
                free[pool[step_id]] += 1
            remaining -= 1
            for after in dependents[step_id]:
                waiting[after].discard(step_id)
                if not waiting[after]:
                    release(after)
    return ParallelFinish(
        days=now,
        unestimated=sum(1 for value in days.values() if value is None),
        landings=landings,
        starts=starts,
    )


def chain_tails(
    steps: Sequence[Step],
    days_for: Callable[[Step], float | None],
    wait_of: Callable[[Step], Wait | None] = no_wait,
) -> dict[StepId, float]:
    """Each step's own days plus the longest chain among ``steps`` waiting on it — the
    priority a free worker picks by in :func:`parallel_finish`, where an edge out of
    ``steps`` counts as met. Whoever simulates a team working the plan picks the same way."""
    members = {step.id for step in steps}
    waiting = {step.id: _requires_among(step, members) for step in steps}
    costs = {step.id: _cost(step, days_for, wait_of) for step in steps}
    return _tails(steps, costs, _dependents(steps, waiting))


def _cost(
    step: Step, days_for: Callable[[Step], float | None], wait_of: Callable[[Step], Wait | None]
) -> float | None:
    """What a step weighs in the walk: its days, or a wait's own — never work."""
    return _waited_days(step, wait_of) if wait_of(step) is not None else days_for(step)


def _waited_days(step: Step, wait_of: Callable[[Step], Wait | None]) -> float:
    """A wait's own working days: a ``days`` wait's count; an ``until`` wait ends by the
    calendar, which only :func:`phases` knows."""
    wait = wait_of(step)
    return wait.days if wait is not None and wait.until is None else 0.0


def _requires_among(step: Step, members: Container[StepId]) -> set[StepId]:
    return {target for target in step.edges.get("requires", []) if target in members}


def _dependents(
    steps: Sequence[Step], waiting: Mapping[StepId, set[StepId]]
) -> dict[StepId, list[StepId]]:
    dependents: dict[StepId, list[StepId]] = {step.id: [] for step in steps}
    for step in steps:
        for target in waiting[step.id]:
            dependents[target].append(step.id)
    return dependents


def _tails(
    steps: Sequence[Step],
    days: Mapping[StepId, float | None],
    dependents: Mapping[StepId, list[StepId]],
) -> dict[StepId, float]:
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
    return tails


@dataclass(frozen=True)
class Phase:
    """One stretch of the plan: a milestone and the work leading up to it — or, with no
    milestone, the work nothing gathers, which runs after the last one.

    ``finish`` is None when nothing in the stretch is estimated, for ``Scheduled``'s
    reason. ``asked`` is the milestone's own start date when it has one; ``start`` is
    where the stretch actually begins, which differs only when the date asked for fell
    before the previous milestone landed — the sequence holds and the ask is reported.

    Re-dated from what has happened, ``start`` is tomorrow for a stretch with work left and
    ``began`` is when its work really began — the first day any of it was done or started;
    ``facts`` holds the day each of its done steps was done, which dates it.
    """

    milestone: Step | None
    steps: tuple[Step, ...]  # Project order, the milestone last among its own.
    days: float  # Makespan of this stretch alone, in working days.
    start: date
    finish: date | None
    asked: date | None
    unestimated: int
    began: date
    # The working day each step lands on inside the stretch, from ``start``: the
    # simulation's own answer, which is what an expected-progress curve is made of.
    landings: dict[StepId, float] = field(default_factory=dict)
    starts: dict[StepId, float] = field(default_factory=dict)
    lead: float = 0.0  # Part of the start day the stretch before used up.
    facts: dict[StepId, date] = field(default_factory=dict)

    def landing_of(self, step_id: StepId) -> date:
        """The date a step of this stretch lands — the day it was done, where it is, else
        the simulation's; its own start for a step that cost nothing, as ``finish`` has."""
        fact = self.facts.get(step_id)
        return fact if fact is not None else self._day_at(self.landings.get(step_id, 0.0))

    def start_day_of(self, step_id: StepId) -> date:
        """The day a step starts on. Work that starts the moment a day ends starts on that
        day, as a team picks up the next step when it finishes one — a landing's rule."""
        fact = self.facts.get(step_id)
        return fact if fact is not None else self._day_at(self.starts.get(step_id, 0.0))

    def _day_at(self, offset: float) -> date:
        at = self.lead + offset
        return working_days_after(self.start, at, GUARD) if at > 0 else self.start

    @property
    def pushed(self) -> bool:
        """Whether the date asked for could not be kept — a weekend rolling to its Monday
        is keeping it."""
        return self.asked is not None and self.start > next_working_day(self.asked)

    @property
    def calendar_days(self) -> int:
        """The stretch as a calendar reads it: whole working days from the day its work
        began to its landing, both counted — what a list prints, where ``days`` is the
        simulation's fraction. Zero when nothing landed."""
        return working_days_between(self.began, self.finish) if self.finish else 0


# Half a working day: what is taken as spent on the day work started, and the least left of
# work that has run past its estimate.
HALF = 0.5


@dataclass(frozen=True)
class ScheduleFacts:
    """What has happened by ``today``, for a plan re-dated from it — handed in like
    ``days_for``, so the domain never learns what a status is stored as or what a focus is.

    ``status_of`` is the stored status (``DONE``, ``IN_PROGRESS``, ``BLOCKED``, anything else
    pending) and ``since_of`` the day it last changed. ``is_marker`` is a step that carries
    no work by design — a milestone's own step, a feature, a check — whose status is no fact
    about the schedule: people rarely mark one done on the day its work lands. ``worked`` is
    how many working days of a running step's work are behind it (``spent_since`` from its
    ``since``, weighed by whoever knows the focus it ran at), and ``resume_days``, where
    given, what the rest costs from tomorrow in place of ``days_for``.

    ``day_over`` is when in ``today`` the reading is taken. A window reads a day still
    going, where a step due today has until tonight: were it late the moment the day
    began, every plan made this morning would start tomorrow and every landing would slip
    until somebody marked it. A simulation reads each day at its end, when it is late.
    """

    today: date
    status_of: Callable[[Step], str]
    since_of: Callable[[Step], date | None]
    is_marker: Callable[[Step], bool]
    worked: Callable[[Step], float]
    resume_days: Callable[[Step], float | None] | None = None
    day_over: bool = False


def spent_since(day: date | None, today: date) -> float:
    """Working days behind work started on ``day``, today's included, from the middle of the
    day it started — what a running step is credited with."""
    if day is None or day > today:
        return 0.0
    return working_days_between(day, today) - HALF


def waited(
    step: Step,
    before: Sequence[Step],
    status_of: Callable[[Step], str],
    since_of: Callable[[Step], date | None],
    today: date,
) -> float:
    """Working days a wait has held by ``today``, ``before`` being what it waits on. A wait
    made after all that was done has waited since the start of the day it was made;
    otherwise since the day the last of it was done, part-way through it. Nothing while any
    of it is not done."""
    if any(status_of(one) != DONE for one in before):
        return 0.0
    done = [day for one in before if (day := since_of(one)) is not None]
    last = max(done, default=None)
    made = local_day(step.created)
    if made is not None and (last is None or made > last):
        return 0.0 if made > today else float(working_days_between(made, today))
    return spent_since(last, today)


def wait_status(
    library: Library,
    status_of: Callable[[Step], str],
    since_of: Callable[[Step], date | None],
    wait_of: Callable[[Step], Wait | None],
    today: date,
) -> Callable[[Step], str]:
    """``status_of`` with every wait read as done once it is over and :data:`WAITING` until
    then — what the board and the Run Agent gate read, so what follows a wait is ready on the
    day it may start. A wait is over when what it waits on is done and its day has come, or
    its days have been waited; a wait on a wait asks the one before."""

    def status(step: Step, seen: frozenset[StepId] = frozenset()) -> str:
        wait = wait_of(step)
        if wait is None:
            return status_of(step)
        if step.id in seen:  # Defensive: a loop a hand-edited file carries.
            return WAITING
        before = library.requires(step.id)
        derived = [status(one, seen | {step.id}) for one in before]
        if any(found != DONE for found in derived):
            return WAITING
        if wait.until is not None:
            return DONE if today >= wait.until else WAITING
        held = waited(step, before, lambda _one: DONE, since_of, today)
        return DONE if held >= wait.days else WAITING

    return lambda step: status(step)


@dataclass(frozen=True)
class _Clock:
    """When the next stretch may begin, and how much of that day is already used."""

    when: date
    lead: float


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
    facts: ScheduleFacts | None = None,
    wait_of: Callable[[Step], Wait | None] = no_wait,
) -> list[Phase]:
    """The plan as milestones run one after another, each dated from the last.

    A milestone's stretch is its ``requires`` cone truncated at the milestones before it
    (``scope.cone``) — what is new since the last one — plus itself; a step two milestones
    both reach belongs to the earlier. Stretches run **in sequence**: the first begins at
    ``start``, every later one where the previous lands — on the same day, when it ended
    part-way through one — and a milestone with a date of its own (``start_for``) begins
    there instead when that is later. Each stretch is :func:`parallel_finish` over its own
    steps, so the team is the same throughout.

    What no milestone gathers runs last, as a stretch with no milestone. A project with no
    milestones is that one stretch, which is the plain simulation from ``start``. Both
    ``is_milestone`` and ``start_for`` are handed in like ``days_for``: the domain learns
    that some steps close a stretch, never what marks them.

    **Handed ``facts``, the plan re-dates itself from what has happened.** Its own dates
    stand while reality matches them (:func:`_holds`); otherwise the rest resumes from
    tomorrow (:func:`_resumed`). A plan followed exactly therefore reads the same date every
    day, and a forecast moves only when the work does.

    A wait (``wait_of``) holds what requires it: an ``until`` wait lets it start on its day's
    first moment and not before, a ``days`` wait for that many working days from when it is
    reached — re-dated, less the days it has already waited.
    """
    groups = stretches(library, project, is_milestone)

    def dated(
        milestone: Step | None,
        steps: tuple[Step, ...],
        members: Sequence[Step],
        costs: Callable[[Step], float | None],
        clock: _Clock,
        first: bool,
        running: frozenset[StepId] = frozenset(),
        known: dict[StepId, date] | None = None,
        began_by: date | None = None,
        waited: Callable[[Step], float] | None = None,
        borrowed: frozenset[StepId] = frozenset(),
    ) -> tuple[Phase, _Clock]:
        """One stretch dated from ``clock``, and the clock it leaves for the next. ``borrowed``
        are ``members`` of later stretches, run beside this one's own: they hold workers, and
        the stretch lands when its own work does."""
        asked = start_for(milestone) if milestone is not None else None
        begins = asked if asked is not None and (first or asked >= clock.when) else clock.when
        used = clock.lead if begins == clock.when else 0.0
        if next_working_day(begins) != begins:
            used = 0.0
        begins = next_working_day(begins)

        def waits(step: Step, at: float) -> float:
            wait = wait_of(step)
            assert wait is not None  # The walk asks only of a wait.
            if wait.until is None:
                return at + max(0.0, wait.days - (waited(step) if waited is not None else 0.0))
            # What waits on it may start on its day: that day's first moment, from where
            # this stretch began.
            opens = next_working_day(wait.until)
            offset = 0.0 if opens <= begins else working_days_between(begins, opens) - 1 - used
            return max(at, offset)

        run = parallel_finish(
            library,
            project,
            costs,
            is_agent,
            humans=humans,
            agents=agents,
            among=members,
            running=running,
            wait_of=wait_of,
            waits=waits,
            is_marker=facts.is_marker if facts is not None else no_marker,
        )
        assert run is not None  # A stretch dated here always has something to run.
        days = max(
            (offset for step_id, offset in run.landings.items() if step_id not in borrowed),
            default=0.0,
        )
        finish = working_days_after(begins, used + days, GUARD) if days > 0 else None
        phase = Phase(
            milestone=milestone,
            steps=steps,
            days=days,
            start=begins,
            finish=finish,
            asked=asked,
            unestimated=run.unestimated,
            began=min(begins, began_by) if began_by is not None else begins,
            landings=run.landings,
            starts=run.starts,
            lead=used,
            facts=known or {},
        )
        if finish is None:
            return phase, _Clock(begins, used)
        # Ending exactly as a day ends still ends on that day: what follows starts then, as a
        # team picks up the next step the moment it finishes one.
        total = used + days
        part = total - floor(total + GUARD)
        return phase, _Clock(finish, part if part > GUARD else 1.0)

    planned: list[Phase] = []
    clock = _Clock(start, 0.0)
    for index, (milestone, steps) in enumerate(groups):
        phase, clock = dated(milestone, steps, steps, days_for, clock, index == 0)
        planned.append(phase)
    if facts is None or _holds(planned, facts, wait_of):
        return planned
    return _resumed(
        groups, planned, facts, facts.resume_days or days_for, dated, start_for, wait_of
    )


def stretches(
    library: Library, project: Project, is_milestone: Callable[[Step], bool]
) -> list[tuple[Step | None, tuple[Step, ...]]]:
    """The stretches' membership, before any dating — each milestone's cone truncated at
    the ones before it, then whatever no milestone gathers: what :func:`phases` dates, and
    what a simulated team works through in turn."""
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
    return groups


def _holds(
    planned: Sequence[Phase], facts: ScheduleFacts, wait_of: Callable[[Step], Wait | None]
) -> bool:
    """Does reality still match the plan? Each step is done exactly when the plan has it
    landed — none early, on the very day where that is known (or a plan finished late would
    hold again once everything is done), and none still open once its day is over — nothing
    in flight started after the day the plan started it, and nothing was planned to start
    before it existed. A step nobody marked in progress says nothing about when it started,
    and a marker step or a wait says nothing at all but when it was made. A step stamped
    later than today — a clock running ahead elsewhere — was made today."""
    today = facts.today
    for phase in planned:
        for step in phase.steps:
            created = local_day(step.created)
            if created is not None and phase.start_day_of(step.id) < min(created, today):
                return False
            if facts.is_marker(step) or wait_of(step) is not None:
                continue
            status, since = facts.status_of(step), facts.since_of(step)
            lands = phase.landing_of(step.id)
            if status == DONE:
                if lands > today or (since is not None and since != lands):
                    return False
            elif lands < today or (lands == today and facts.day_over):
                return False
            begun = status in (IN_PROGRESS, BLOCKED)
            if begun and since is not None and since > phase.start_day_of(step.id):
                return False
    return True


def _resumed(
    groups: Sequence[tuple[Step | None, tuple[Step, ...]]],
    planned: Sequence[Phase],
    facts: ScheduleFacts,
    days_for: Callable[[Step], float | None],
    dated: Callable[..., tuple[Phase, _Clock]],
    start_for: Callable[[Step], date | None],
    wait_of: Callable[[Step], Wait | None],
) -> list[Phase]:
    """The rest of the work from tomorrow. A stretch whose work is all done is dated by when
    it was done and holds nothing back — its marker steps need not be marked. From the first
    with work left, stretches follow one another from the next working day: done steps are
    facts, work in flight keeps its worker and is credited with ``facts.worked`` (at least
    half a day is left) — work in flight in a later stretch too, which runs now rather than
    in its turn — a ``days`` wait with the days it has already waited, and everything
    else costs its estimate. A done step nobody dated — a status older than its days — is
    taken as done by its planned landing, or today if that is earlier: never later than it
    could have been."""
    today = facts.today
    planned_day = {step.id: phase.landing_of(step.id) for phase in planned for step in phase.steps}
    by_id = {step.id: step for _milestone, steps in groups for step in steps}

    def done_on(step: Step) -> date:
        since = facts.since_of(step)
        return since if since is not None else min(planned_day.get(step.id, today), today)

    def held(step: Step) -> float:
        before = [by_id[target] for target in step.edges.get("requires", []) if target in by_id]
        return waited(step, before, facts.status_of, facts.since_of, today)

    def credited(step: Step) -> float | None:
        days = days_for(step)
        return days if days is None else max(HALF, days - facts.worked(step))

    result: list[Phase] = []
    clock: _Clock | None = None
    # Work in flight in a stretch not reached yet — somebody started it early — keeps its
    # worker from tomorrow, beside the stretch being worked, and what is left of it when
    # that one lands carries on into the next. A step that lands on the way is done, where
    # it belongs, on the day it landed. None until the first stretch with work left.
    carried: dict[StepId, float] | None = None
    settled: dict[StepId, date] = {}
    for index, (milestone, steps) in enumerate(groups):
        known = {step.id: done_on(step) for step in steps if facts.status_of(step) == DONE}
        known |= {step.id: settled[step.id] for step in steps if step.id in settled}
        left = [step for step in steps if step.id not in known]
        if all(facts.is_marker(step) or wait_of(step) is not None for step in left):
            result.append(_finished(milestone, steps, known, today, start_for))
            continue
        if clock is None:
            clock = _Clock(next_working_day(today + _ONE_DAY), 0.0)
        if carried is None:
            carried = {
                step.id: days
                for _later, ahead in groups[index + 1 :]
                for step in ahead
                if facts.status_of(step) == IN_PROGRESS and (days := credited(step)) is not None
            }
        own = {step.id for step in left}
        extra = [by_id[step_id] for step_id in carried if step_id not in own]
        running = frozenset(
            {step.id for step in left if facts.status_of(step) == IN_PROGRESS} | set(carried)
        )

        def costs(
            step: Step,
            running: frozenset[StepId] = running,
            carried: Mapping[StepId, float] = dict(carried),
        ) -> float | None:
            if step.id in carried:
                return carried[step.id]
            return credited(step) if step.id in running else days_for(step)

        started = [
            since
            for step in steps
            if facts.status_of(step) == IN_PROGRESS and (since := facts.since_of(step)) is not None
        ]
        began_by = min([*known.values(), *started], default=None)
        phase, clock = dated(
            milestone,
            steps,
            [*left, *extra],
            costs,
            clock,
            False,
            running,
            known,
            began_by,
            held,
            frozenset(step.id for step in extra),
        )
        for step in extra:
            if phase.landings[step.id] <= phase.days + GUARD:
                settled[step.id] = phase.landing_of(step.id)
                del carried[step.id]
            else:
                carried[step.id] -= max(0.0, phase.days - phase.starts[step.id])
        for step_id in own:
            carried.pop(step_id, None)
        result.append(phase)
    return result


def _finished(
    milestone: Step | None,
    steps: tuple[Step, ...],
    known: dict[StepId, date],
    today: date,
    start_for: Callable[[Step], date | None],
) -> Phase:
    """A stretch whose work is all done: from the first day any of it was done to the last.
    A marker step nobody marked is dated by what it requires — a milestone lands with its
    work."""
    dates = dict(known)
    work = max(dates.values(), default=today)
    pending = [step for step in steps if step.id not in dates]
    while pending:
        waiting_ids = {step.id for step in pending}
        waiting = [
            step
            for step in pending
            if any(target in waiting_ids for target in step.edges.get("requires", []))
        ]
        for step in pending:
            if step in waiting:
                continue
            needs = [dates[target] for target in step.edges.get("requires", []) if target in dates]
            dates[step.id] = max(needs, default=work)
        if len(waiting) == len(pending):  # Defensive: a loop a hand-edited file carries.
            for step in waiting:
                dates[step.id] = work
            break
        pending = waiting
    days = list(dates.values()) or [today]
    return Phase(
        milestone=milestone,
        steps=steps,
        days=0.0,
        start=min(days),
        finish=max(days),
        asked=start_for(milestone) if milestone is not None else None,
        unestimated=0,
        began=min(days),
        facts=dates,
    )


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
            (target for target in waiting if target in order),
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


# -- the axis of a chart over dates -------------------------------------------------------------

Tick = tuple[date, str]  # A date on the axis and the label it wears.


def _day_label(when: date) -> str:
    return f"{when.day} {MONTHS[when.month - 1][:ABBREVIATION]}"


def _month_label(when: date) -> str:
    return MONTHS[when.month - 1][:ABBREVIATION]


def _with_years(ticks: list[Tick]) -> tuple[Tick, ...]:
    """The first mark of each new year carries the year, whatever the unit — thinned
    months may skip January, and a week may cross the boundary."""
    labelled: list[Tick] = []
    for index, (when, label) in enumerate(ticks):
        if index and when.year != ticks[index - 1][0].year:
            label = f"{label} '{when.year % 100:02d}"
        labelled.append((when, label))
    return tuple(labelled)


def _days(first: date, last: date) -> Iterator[date]:
    when = first
    while when <= last:
        yield when
        when += timedelta(days=1)


def _mondays(first: date, last: date) -> Iterator[date]:
    when = first + timedelta(days=(7 - first.weekday()) % 7)
    while when <= last:
        yield when
        when += timedelta(days=7)


def _month_starts(first: date, last: date) -> Iterator[date]:
    year, month = first.year, first.month
    if first.day != 1:
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    while date(year, month, 1) <= last:
        yield date(year, month, 1)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def axis_ticks(first: date, last: date, room: int) -> tuple[Tick, ...]:
    """The dates marked along the axis and their labels: every day, else every Monday,
    else every month's first — the finest unit whose marks fit ``room`` (how many labels
    the plot has width for) — and months thinned to every second, third… when even those
    do not. Calendar boundaries, never an even division of the span, because a reader
    places a point by the nearest mark. At least one mark, whatever the room."""
    days = list(_days(first, last))
    if len(days) <= room:
        return _with_years([(when, _day_label(when)) for when in days])
    mondays = list(_mondays(first, last))
    if mondays and len(mondays) <= room:
        return _with_years([(when, _day_label(when)) for when in mondays])
    months = list(_month_starts(first, last))
    every = max(1, ceil(len(months) / max(1, room)))
    ticks = _with_years([(when, _month_label(when)) for when in months[::every]])
    return ticks or ((first, _day_label(first)),)
