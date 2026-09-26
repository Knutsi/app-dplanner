"""What the Time tab shows, as data — and what the report draws of it.

The tab and the report read one :class:`Presented`: the plan on the day shown, the plan it
is compared with, each milestone's landing then and now, and the work over the recorded
days. Nothing here is a second computation — the snapshots are ``progress.py``'s, dated by
the model — and nothing here knows a widget, so a test reads what a page would draw.

**Four numbers lead** (:class:`Scope` for the whole plan): where the work lands — or the day
it was done, once it is — how far that moved against the plan compared with, in working
days, and how much of it is done. The fourth, the steps nobody has sized, is the live plan's
and the page's to count.

**The work is read over the recorded days** (:class:`Burnup`): the scope — the estimated
days the plan held on each recorded day — and what was done by then, both step curves,
because a record holds until the next; the plan's own schedule from the day shown on
(:func:`promised_curve`, the landing knots summed); each day the scope changed
(:class:`Jump`), marked once by the day's sum (:func:`scope_marks`); and the days some step
changed status, so a day of work is told from a quiet one even when nothing finished.

**The axes hold still** (:func:`reach_of`): every plot is drawn against the reach of every
record up to the day shown and the live plan — the first day any starts, the last any
lands, the most work any holds — so moving between days moves only the lines.

The HTML prototype's ``brief.ts``, less what the model made redundant: re-dated from what
has happened, a plan is never behind itself, so there is no lag, no projection at today's
pace and no verdict.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from math import floor, log10

from dplanner.domain.model import Library, Project
from dplanner.domain.schedule import format_days, short_date
from dplanner.modules.time_estimates.cli import Readers
from dplanner.modules.time_estimates.progress import (
    Pick,
    Snapshot,
    Stretch,
    Tally,
    WaitSpan,
    landing_shift,
    pick_words,
    resolve,
    until,
)
from dplanner.modules.time_estimates.schedule import REMAINDER_COLOR, WHOLE_COLOR, milestone_colors

# Two amounts of work closer than this are the same: a scope that did not change.
SAME = 1e-9
# The work plots' scale: finer steps than 1-2-5, since two stacked plots cannot afford half
# of each left empty, and headroom to keep a line off the top edge, where its label would
# meet the other plot's key.
AXIS_STEPS = (1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 7.5, 10.0)
HEADROOM = 1.05
ALL_WORK = "All work"
REMAINDER = "Remaining work"


@dataclass(frozen=True)
class Named:
    """A stretch as the page names it: its key (the closing milestone's step id, ``""``
    for the work after the last one), its label, the milestone step's own title where the
    label is not it, the key a row prints and its shade."""

    key: str
    label: str
    title: str = ""
    badge: str = ""
    color: str = WHOLE_COLOR


@dataclass(frozen=True)
class Scope:
    """The whole plan (``key`` None) or one stretch: its own work now, where the plan now
    lands it — through everything before it, as milestones run in sequence — where the
    plan compared with landed it, and the first recorded day it read done."""

    key: str | None
    named: Named
    own: Tally
    planned: date | None
    then: date | None
    landed_by: date | None

    @property
    def moved(self) -> int | None:
        """Working days the landing moved against the plan compared with."""
        if self.then is None or self.planned is None:
            return None
        return landing_shift(self.then, self.planned)

    @property
    def end(self) -> date | None:
        """Where it ends: the day it was done, else where the plan lands it."""
        return self.landed_by if self.landed_by is not None else self.planned


@dataclass(frozen=True)
class Jump:
    """The scope changing between two records: steps and estimated days, either way."""

    day: date
    steps: int
    days: float


@dataclass(frozen=True)
class ScopeMark:
    """One day's change of scope in sum — added (``up``) or taken away."""

    day: date
    up: bool
    steps: int
    days: float


@dataclass(frozen=True)
class Burnup:
    """The work over the recorded days, then the day shown — step curves in estimated
    days."""

    scope: tuple[tuple[date, float], ...]
    done: tuple[tuple[date, float], ...]
    baseline: float | None  # The work the plan compared with held.
    promised: tuple[tuple[date, float], ...]  # The plan's schedule, cumulative by landing day.
    jumps: tuple[Jump, ...]
    active: tuple[date, ...]  # The days some step changed status.

    @property
    def marks(self) -> tuple["ScopeMark", ...]:
        return scope_marks(self.jumps)


@dataclass(frozen=True)
class Reach:
    """How far the plots reach: the first day and the last on the date axis, and the most
    work either scale must hold."""

    first: date
    last: date
    days: float


@dataclass(frozen=True)
class Presented:
    """The plan on the day shown and what the page draws of it."""

    now: Snapshot
    then: Snapshot | None
    basis: str  # The plan compared with, in words; "" when nothing was found.
    whole: Scope
    stretches: tuple[Scope, ...]  # In sequence, the work after the last milestone included.
    burnup: Burnup
    reach: Reach
    saved: tuple[tuple[date, str], ...]  # Each saved snapshot's day and title.

    @property
    def day(self) -> date:
        return self.now.day

    @property
    def compared(self) -> bool:
        """Whether there is another plan to compare with at all: never the plan now, which
        ``resolve`` hands back only when asked for it — but a snapshot saved earlier today
        is one."""
        return self.then is not None and self.then is not self.now

    @property
    def milestones(self) -> tuple[Scope, ...]:
        """The stretches a milestone closes — the shift view's rows."""
        return tuple(scope for scope in self.stretches if scope.key)

    @property
    def marked(self) -> tuple[Scope, ...]:
        """What the done plot marks: the milestones — the whole plan where there are none."""
        return self.milestones or (self.whole,)

    @property
    def schedule(self) -> tuple[tuple[date, float], ...]:
        """The plan's schedule from the day shown on: re-dated from what has happened, the
        schedule before it holds only finished work's old dates."""
        return steps_from(self.burnup.promised, self.day)

    @property
    def scale(self) -> float:
        """What the top of both work plots stands for, in days: one scale, so a height in
        one is the same work in the other, holding the reach so it stays still."""
        data = self.burnup
        values = [1.0, self.reach.days, data.baseline or 0.0]
        values += [value for _day, value in (*data.scope, *data.promised)]
        return nice_ceiling(HEADROOM * max(values))


def present(
    now: Snapshot,
    *,
    history: Sequence[Snapshot],
    saved: Sequence[Snapshot],
    pick: Pick,
    start: date,
    named: Sequence[Named],
    reach_of_rows: Sequence[Snapshot] = (),
) -> Presented:
    """The page for ``now`` compared with the plan ``pick`` names. ``named`` says what each
    stretch is called and wears, by key; ``reach_of_rows`` are more snapshots the axes must
    hold beside the records up to ``now`` — the live plan, when ``now`` is an earlier day."""
    then = resolve(pick, history=history, saved=saved, live=now, start=start)
    basis = pick_words(pick, then, now.day)
    compared = then is not None and then is not now
    by_key = {one.key: one for one in named}

    def scope(key: str | None, names: Named) -> Scope:
        return Scope(
            key=key,
            named=names,
            own=own_tally(now, key) or Tally(),
            planned=now.landing(key),
            then=then.landing(key) if compared and then is not None else None,
            landed_by=landed_by(history, now, key),
        )

    rows = until(history, now)
    return Presented(
        now=now,
        then=then,
        basis=basis,
        whole=scope(None, Named("", ALL_WORK)),
        stretches=tuple(
            scope(stretch.key, by_key.get(stretch.key, Named(stretch.key, stretch.key)))
            for stretch in now.stretches
        ),
        burnup=burnup(now, history, then if compared else None, None),
        reach=reach_of([*rows, *reach_of_rows]),
        saved=tuple((row.day, row.title) for row in saved),
    )


def names_of(
    library: Library, project: Project, snapshot: Snapshot, readers: Readers
) -> tuple[Named, ...]:
    """Every stretch of ``snapshot`` as the page names it: a milestone by its label (its
    step's title where it has none) and its shade of the project's map; the work after the
    last milestone neutral, unless it is all there is."""
    colors = milestone_colors(library, project, readers.is_milestone)
    found = []
    for index, stretch in enumerate(snapshot.stretches):
        step = project.step(stretch.key) if stretch.key else None
        if step is None:
            alone = len(snapshot.stretches) == 1
            label = ALL_WORK if alone else REMAINDER
            found.append(
                Named(stretch.key, label, color=WHOLE_COLOR if not index else REMAINDER_COLOR)
            )
            continue
        label = readers.milestone_label(step) or step.title or "Milestone"
        found.append(
            Named(
                key=step.id,
                label=label,
                title=step.title if step.title != label else "",
                badge=readers.key_of(step),
                color=colors.get(step.id, WHOLE_COLOR),
            )
        )
    return tuple(found)


def own_tally(snapshot: Snapshot, key: str | None) -> Tally | None:
    """A stretch's own work — everything for None; None for a stretch the snapshot never
    knew."""
    if key is None:
        return snapshot.toward(None)
    return next((stretch.tally for stretch in snapshot.stretches if stretch.key == key), None)


def landed_by(history: Sequence[Snapshot], now: Snapshot, key: str | None) -> date | None:
    """The first recorded day everything through ``key`` read done — ``now``'s own day
    when no record before it did; None while any of it is undone."""

    def landed(row: Snapshot) -> bool:
        reached = row.toward(key)
        return row.has(key) and reached.steps > 0 and reached.done == reached.steps

    if not landed(now):
        return None
    return next((row.day for row in until(history, now) if landed(row)), now.day)


def promised_curve(stretches: Sequence[Stretch]) -> list[tuple[date, float]]:
    """The estimated days the stretches promise done by each landing day, cumulative."""
    by_day: dict[date, float] = {}
    for stretch in stretches:
        for knot in stretch.landings:
            by_day[knot.day] = by_day.get(knot.day, 0.0) + knot.days
    running = 0.0
    found = []
    for day in sorted(by_day):
        running += by_day[day]
        found.append((day, running))
    return found


def burnup(
    now: Snapshot, history: Sequence[Snapshot], then: Snapshot | None, key: str | None
) -> Burnup:
    """``key``'s own work (everything for None) over the recorded days through ``now``."""
    scope: list[tuple[date, float]] = []
    done: list[tuple[date, float]] = []
    jumps: list[Jump] = []
    active: set[date] = set()
    before: Tally | None = None
    for row in until(history, now):
        own = own_tally(row, key)
        if own is None:
            continue
        if scope and scope[-1][0] == row.day:  # The day shown replaces its own record.
            scope.pop()
            done.pop()
        if before is not None and (own.steps != before.steps or abs(own.days - before.days) > SAME):
            jumps.append(Jump(row.day, own.steps - before.steps, own.days - before.days))
        # A row DPlanner wrote before it counted status changes says only what was done.
        if own.changed > 0 or (before is not None and own.done != before.done):
            active.add(row.day)
        scope.append((row.day, own.days))
        done.append((row.day, own.done_days))
        before = own
    chosen = now.stretches if key is None else [one for one in now.stretches if one.key == key]
    promised = promised_curve(chosen)
    if chosen:
        promised = [(chosen[0].start, 0.0), *promised]
    baseline = own_tally(then, key) if then is not None else None
    return Burnup(
        scope=tuple(scope),
        done=tuple(done),
        baseline=baseline.days if baseline is not None else None,
        promised=tuple(promised),
        jumps=tuple(jumps),
        active=tuple(sorted(active)),
    )


def scope_marks(jumps: Sequence[Jump]) -> tuple[ScopeMark, ...]:
    """One mark per day the scope changed, by the day's sum; a day that netted nothing has
    none. Days decide the way it went, and steps where the days did not move."""
    by_day: dict[date, Jump] = {}
    for jump in jumps:
        summed = by_day.get(jump.day)
        by_day[jump.day] = (
            Jump(jump.day, summed.steps + jump.steps, summed.days + jump.days) if summed else jump
        )
    found = []
    for jump in by_day.values():
        way = jump.days if abs(jump.days) > SAME else jump.steps
        if way:
            found.append(ScopeMark(jump.day, way > 0, jump.steps, jump.days))
    return tuple(found)


def reach_of(snapshots: Sequence[Snapshot]) -> Reach:
    """The reach that holds every one of ``snapshots``: from the first day any starts to
    the last any lands, and the most work any holds. Drawn to it, moving between them moves
    only the lines. ``snapshots`` is never empty."""
    starts: list[date] = []
    ends: list[date] = []
    work: list[float] = [0.0]
    for one in snapshots:
        starts += [one.day, *(stretch.start for stretch in one.stretches)]
        ends.append(one.landing(None) or one.day)
        ends.append(one.day)
        work.append(one.toward(None).days)
        work += [days for _day, days in promised_curve(one.stretches)]
    return Reach(min(starts), max(ends), max(work))


def nice_ceiling(value: float) -> float:
    """The least of :data:`AXIS_STEPS` times a power of ten at or above ``value`` — at
    least one day, so an empty scale still has a top."""
    if value <= 1.0:
        return 1.0
    magnitude = 10.0 ** floor(log10(value))
    return next(
        (step * magnitude for step in AXIS_STEPS if step * magnitude >= value), 10 * magnitude
    )


def step_at(points: Sequence[tuple[date, float]], day: date) -> float | None:
    """A step curve's value on ``day``: what the last point at or before it said."""
    found = None
    for when, value in points:
        if when > day:
            break
        found = value
    return found


def steps_from(points: Sequence[tuple[date, float]], day: date) -> tuple[tuple[date, float], ...]:
    """A step curve from ``day`` on: its value that day, then every later point — the
    plan's schedule re-planned from the day shown, which before it holds only finished
    work's old dates."""
    at = step_at(points, day)
    return (*(((day, at),) if at is not None else ()), *(p for p in points if p[0] > day))


def moved_words(moved: int | None) -> str:
    """How far a landing moved, as the figure says it: ``▶ +3d`` later, the arrow the other
    way and a true minus earlier, ``± 0d`` where it held."""
    if moved is None:
        return ""
    if moved == 0:
        return "± 0d"
    return f"▶ +{moved}d" if moved > 0 else f"◀ \N{MINUS SIGN}{-moved}d"


def change_words(mark: ScopeMark, today: date) -> str:
    """A day's change of scope, as its mark's tooltip says it: ``+2 steps, +3d on 4 Oct``."""
    minus = "\N{MINUS SIGN}"
    count = abs(mark.steps)
    steps = f"{'+' if mark.steps >= 0 else minus}{count} step{'' if count == 1 else 's'}"
    days = f"{'+' if mark.days >= 0 else minus}{format_days(abs(mark.days)) or '0d'}"
    return f"{steps}, {days} on {short_date(mark.day, today)}"


def milestone_words(scope: Scope, today: date, waits: Sequence[WaitSpan] = ()) -> str:
    """A milestone as its row and its mark say it: its key and name, where the plan
    compared with landed it, where it ends now, and each wait in its stretch."""
    named = scope.named
    lines = [f"{named.badge} {named.label}".strip() + (f" — {named.title}" if named.title else "")]
    if scope.then is not None:
        lines.append(f"then: {short_date(scope.then, today)}")
    if scope.landed_by is not None:
        lines.append(f"done by {short_date(scope.landed_by, today)}")
    elif scope.planned is not None:
        lines.append(f"plan now: {short_date(scope.planned, today)}")
    lines += [
        f"waits: {wait.title} ({wait_days(wait, today)})" for wait in waits if wait.key == scope.key
    ]
    return "\n".join(lines)


def wait_days(wait: WaitSpan, today: date) -> str:
    """The days a wait holds, as words: ``9 Oct``, ``9 Oct to 14 Oct``."""
    if wait.start == wait.end:
        return short_date(wait.end, today)
    return f"{short_date(wait.start, today)} to {short_date(wait.end, today)}"
