"""How far the plan has come, against how far it said it would be by now.

The calendar beside this says when each milestone *lands*; this says what has *landed*.
Two measures, because they answer different questions and neither lies about what it
is: **by steps** — done steps over steps — and **by days** — the estimated days of done
steps over the estimated days of all of them. Both are derived on every read from the
statuses and the estimates (``ordering.py``'s rule), never stored.

**Expected progress is the simulation's own curve.** ``domain/schedule.py``'s
``parallel_finish`` now says on which working day each step lands; ``phases`` carries
that per stretch, and :func:`expected` turns it into a share landed by date — the plan's
own promise, for the stored team and focus, exact rather than a straight line drawn
between start and finish.

**The past is the one thing here that is stored, because it cannot be derived.** What the
plan looked like last Tuesday — how many steps it had, how much was done, when it said
it would land — is gone once the plan changes, and a chart of expected against actual is
nothing without it. So a :class:`Snapshot` — one row per stretch of the plan: steps,
done, days, done days, start, landing — is recorded per day under a module id of its own,
``progress_history`` (``modules/progress_history.json`` beside the project), **only on a
day something in it changed** and last-wins within a day. The window's recorder writes it
after every settled change; ``dplanner progress record`` writes it for a plan driven from
the terminal. A row keeps its stretches *in order*, so a later read can sum through a
milestone the way the sequence ran that day; a milestone a row never knew is simply
absent from it.

**Earlier plans are the rows whose promise differed.** Every row that projected a
different landing, total or size for the scope than the current plan is an
:class:`EarlierPlan` — where progress stood that day and where it was then expected to
land — which is what the chart draws faintly behind the present so a moved date is seen
rather than remembered. Qt-free by rule (``HEADLESS_FILES``); the chart renders, the CLI
prints, and both read this.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.ordering import cyclic
from dplanner.domain.progression import DONE
from dplanner.domain.schedule import Phase, phases
from dplanner.modules.time_estimates.schedule import stretched

HISTORY_ID = "progress_history"
DATA_FORMAT = ModuleDataFormat(HISTORY_ID)
ROWS_KEY = "days"


@dataclass(frozen=True)
class Tally:
    """What a scope amounts to and how much of it has landed — the two measures' inputs."""

    steps: int = 0
    done: int = 0
    days: float = 0.0  # Estimated project days, unestimated steps counting nothing.
    done_days: float = 0.0

    def __add__(self, other: "Tally") -> "Tally":
        return Tally(
            self.steps + other.steps,
            self.done + other.done,
            self.days + other.days,
            self.done_days + other.done_days,
        )

    def share(self, by_days: bool) -> float | None:
        """Done over total, 0 to 1 — None when there is nothing to be a share of."""
        whole = self.days if by_days else self.steps
        landed = self.done_days if by_days else self.done
        return landed / whole if whole else None


@dataclass(frozen=True)
class Stretch:
    """One stretch of the plan as a snapshot records it: the milestone that closes it
    (``""`` for the work after the last one), its tally, and when it was expected to run."""

    key: str
    tally: Tally
    start: date
    finish: date | None


@dataclass(frozen=True)
class Snapshot:
    """The plan on one day, stretch by stretch, in the order the sequence ran them."""

    day: date
    stretches: tuple[Stretch, ...]

    def toward(self, key: str | None) -> Tally:
        """The tally through the stretch ``key`` closes — every stretch for None."""
        total = Tally()
        for stretch in self.stretches:
            total = total + stretch.tally
            if stretch.key == key:
                return total
        return total if key is None else Tally()

    def has(self, key: str | None) -> bool:
        return key is None or any(stretch.key == key for stretch in self.stretches)

    def landing(self, key: str | None) -> date | None:
        """When the scope was expected to land: the stretch's own finish, or the last
        dated one for the whole."""
        if key is None:
            return next((s.finish for s in reversed(self.stretches) if s.finish), None)
        return next((s.finish for s in self.stretches if s.key == key), None)

    def opening(self, key: str | None) -> date | None:
        """When the scope's work was expected to begin: the first stretch's start."""
        if not self.stretches or not self.has(key):
            return None
        return self.stretches[0].start

    def same_plan(self, other: "Snapshot") -> bool:
        """Whether two days recorded the same state — everything but the day itself."""
        return self.stretches == other.stretches


@dataclass(frozen=True)
class EarlierPlan:
    """Where progress stood one day, and where the plan then said it would land."""

    day: date
    share: float
    finish: date
    tally: Tally


# -- taking a snapshot ------------------------------------------------------------------------


def take(
    library: Library,
    project: Project,
    days_for: Callable[[Step], float | None],
    is_agent: Callable[[Step], bool],
    status_for: Callable[[Step], str],
    *,
    humans: int,
    agents: int,
    start: date,
    efficiency: float,
    is_milestone: Callable[[Step], bool],
    start_for: Callable[[Step], date | None],
    today: date,
) -> Snapshot | None:
    """The plan today: the calendar's own stretches, each with what has landed in it.
    None for a project with no steps, or one a hand-edited loop keeps from being dated —
    there is nothing honest to record about either."""
    if not project.steps or cyclic(library, project):
        return None
    stretches = tuple(
        Stretch(
            key=phase.milestone.id if phase.milestone else "",
            tally=tally(phase.steps, days_for, status_for),
            start=phase.start,
            finish=phase.finish,
        )
        for phase in calendar_phases(
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
    )
    return Snapshot(day=today, stretches=stretches)


def calendar_phases(
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
) -> list[Phase]:
    """The plan's stretches dated on the calendar — the simulation over stretched
    estimates, the one the landing list prints."""
    return phases(
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


def tally(
    steps: Sequence[Step],
    days_for: Callable[[Step], float | None],
    status_for: Callable[[Step], str],
) -> Tally:
    """What these steps amount to, and how much of it reads done."""
    total = Tally()
    for step in steps:
        days = days_for(step) or 0.0
        landed = status_for(step) == DONE
        total = total + Tally(1, int(landed), days, days if landed else 0.0)
    return total


# -- the curves ---------------------------------------------------------------------------------


def expected(
    stretches: Sequence[Phase],
    days_for: Callable[[Step], float | None],
    key: str | None,
    *,
    by_days: bool,
) -> list[tuple[date, float]]:
    """The plan's own promise for the scope: the share landed by each date, from the
    simulation's per-step landings, 0 at the first start and 1 at the scope's landing.

    Cumulative through the stretch ``key`` closes — every stretch for None. Steps that
    land on one date collapse into one point, so the curve is a step function's corners.
    """
    chosen: list[Phase] = []
    for phase in stretches:
        chosen.append(phase)
        if key is not None and phase.milestone is not None and phase.milestone.id == key:
            break
    else:
        if key is not None:
            return []
    if not chosen:
        return []
    whole = sum(
        (days_for(step) or 0.0) if by_days else 1.0 for phase in chosen for step in phase.steps
    )
    if not whole:
        return []
    landed: dict[date, float] = {}
    for phase in chosen:
        for step in phase.steps:
            when = phase.landing_of(step.id)
            landed[when] = landed.get(when, 0.0) + ((days_for(step) or 0.0) if by_days else 1.0)
    points = [(chosen[0].start, 0.0)]
    running = 0.0
    for when in sorted(landed):
        running += landed[when]
        points.append((when, min(running / whole, 1.0)))
    return points


def actual(
    history: Sequence[Snapshot],
    now: Snapshot | None,
    key: str | None,
    *,
    by_days: bool,
) -> list[tuple[date, float]]:
    """Where progress actually stood, day by day: every recorded day that knew the scope,
    then today. A day the scope had nothing to be a share of contributes no point."""
    points: list[tuple[date, float]] = []
    rows = [*history, *([now] if now is not None else [])]
    for row in rows:
        if not row.has(key):
            continue
        share = row.toward(key).share(by_days)
        if share is None:
            continue
        if points and points[-1][0] == row.day:
            points[-1] = (row.day, share)  # Today's live reading replaces its record.
        else:
            points.append((row.day, share))
    return points


def earlier_plans(
    history: Sequence[Snapshot],
    now: Snapshot | None,
    key: str | None,
    *,
    by_days: bool,
) -> list[EarlierPlan]:
    """The recorded days whose promise for the scope differs from the plan as it stands
    now — one entry per distinct promise, at the first day it was made."""
    found: list[EarlierPlan] = []
    current = (now.landing(key), now.toward(key)) if now is not None and now.has(key) else None
    last: tuple[date | None, Tally] | None = None
    for row in history:
        if not row.has(key):
            continue
        finish = row.landing(key)
        promise = (finish, row.toward(key))
        share = promise[1].share(by_days)
        if finish is None or share is None:
            last = promise
            continue
        if last is not None and _same_promise(promise, last):
            continue
        last = promise
        if current is not None and _same_promise(promise, current):
            continue
        found.append(EarlierPlan(day=row.day, share=share, finish=finish, tally=promise[1]))
    return found


def _same_promise(one: tuple[date | None, Tally], other: tuple[date | None, Tally]) -> bool:
    """Two promises are the same when they land the same day for the same total; how
    much was done then is progress, not the plan."""
    return one[0] == other[0] and (one[1].steps, one[1].days) == (other[1].steps, other[1].days)


# -- the history on disk ------------------------------------------------------------------------


def read_history(project: Project) -> list[Snapshot]:
    """Every recorded day, oldest first. An unreadable row reads as absent."""
    entry = project.module_data.get(HISTORY_ID, {})
    raw = entry.get(ROWS_KEY)
    if not isinstance(raw, list):
        return []
    rows: list[Snapshot] = []
    for row in raw:
        if not isinstance(row, dict) or not isinstance(row.get("day"), str):
            continue
        day = _day(row["day"])
        stretches = row.get("stretches")
        if day is None or not isinstance(stretches, list):
            continue
        parsed = [_stretch(item) for item in stretches if isinstance(item, dict)]
        if any(item is None for item in parsed):
            continue
        rows.append(Snapshot(day, tuple(s for s in parsed if s is not None)))
    return rows


def _stretch(row: dict[str, Any]) -> Stretch | None:
    begins, lands = row.get("start"), row.get("finish")
    start = _day(begins) if isinstance(begins, str) else None
    if start is None:
        return None
    finish = _day(lands) if isinstance(lands, str) else None
    return Stretch(
        key=str(row.get("milestone", "") or ""),
        tally=Tally(
            steps=_count(row.get("steps")),
            done=_count(row.get("done")),
            days=_amount(row.get("days")),
            done_days=_amount(row.get("done_days")),
        ),
        start=start,
        finish=finish,
    )


def _day(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _amount(value: object) -> float:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def write_history(rows: Sequence[Snapshot]) -> dict[str, Any]:
    """The entry for these days — ``{}`` (remove the file) when there are none. Absence
    is the default throughout: no milestone key for the remainder, no ``finish`` for a
    stretch nothing dated, and a zero is written because it is a count, not a default."""
    if not rows:
        return {}
    return stamped(
        {
            ROWS_KEY: [
                {
                    "day": row.day.isoformat(),
                    "stretches": [
                        {
                            **({"milestone": s.key} if s.key else {}),
                            "steps": s.tally.steps,
                            "done": s.tally.done,
                            "days": float(s.tally.days),
                            "done_days": float(s.tally.done_days),
                            "start": s.start.isoformat(),
                            **({"finish": s.finish.isoformat()} if s.finish else {}),
                        }
                        for s in row.stretches
                    ],
                }
                for row in rows
            ]
        },
        DATA_FORMAT.version,
    )


def recorded(history: Sequence[Snapshot], now: Snapshot) -> list[Snapshot] | None:
    """The history with today recorded — None when the last row already says exactly
    this, so nothing is written. Today's own earlier row is replaced: one row per day,
    the last state of the day wins."""
    rows = list(history)
    if rows and rows[-1].day == now.day:
        if rows[-1].same_plan(now):
            return None
        rows[-1] = now
        return rows
    if rows and rows[-1].same_plan(now):
        return None
    rows.append(now)
    return rows
