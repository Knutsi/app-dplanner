"""How far the plan has come, against how far it said it would be by now.

The calendar beside this says when each milestone *lands*; this says what has *landed*.
Two measures, because they answer different questions and neither lies about what it
is: **by steps** — done steps over steps — and **by days** — the estimated days of done
steps over the estimated days of all of them. Both are derived on every read from the
statuses and the estimates (``ordering.py``'s rule), never stored.

**Expected progress is the simulation's own curve.** ``domain/schedule.py``'s
``parallel_finish`` says on which working day each step lands; ``phases`` carries that
per stretch, and a :class:`Stretch` keeps it as :class:`Landing` knots — what lands on
each date. :func:`expected` turns the knots into a share landed by date: the plan's own
promise, for the stored team and focus, exact rather than a straight line drawn between
start and finish.

**The past is the one thing here that is stored, because it cannot be derived.** What the
plan looked like last Tuesday — how many steps it had, how much was done, when each of
them was expected to land — is gone once the plan changes, and a chart of the plan
against what became of it is nothing without it. So a :class:`Snapshot` — one row per
stretch of the plan: steps, done, days, done days, start, landing, and the landing knots
— is recorded per day under a module id of its own, ``progress_history``
(``modules/progress_history.json`` beside the project), **only on a day something in it
changed** and last-wins within a day. The window's recorder writes it after every
settled change; ``dplanner progress record`` writes it for a plan driven from the
terminal. A row keeps its stretches *in order*, so a later read can sum through a
milestone the way the sequence ran that day; a milestone a row never knew is simply
absent from it. Because a row carries its knots, **the plan as it stood on any recorded
day is drawn exactly**, not reconstructed.

**The baseline is the plan as recorded on the basis day, and the delta is what changed
since.** The basis is the project's start unless somebody picks another day; the
baseline is the last row on or before it (the earliest row, when none is — a project
older than its history). :func:`delta` says how the scope moved between then and now —
steps and days added, the landing shifted — and the chart draws the band between the two
curves. Qt-free by rule (``HEADLESS_FILES``); the chart renders, the CLI prints, and both
read this.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise
from typing import Any

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.ordering import cyclic
from dplanner.domain.progression import DONE
from dplanner.domain.schedule import (
    Phase,
    format_date,
    format_days,
    next_working_day,
    phases,
    share_at,
    working_days_between,
)
from dplanner.modules.time_estimates.schedule import stretched

HISTORY_ID = "progress_history"
DATA_FORMAT = ModuleDataFormat(HISTORY_ID)
ROWS_KEY = "days"

# Two shares within this of each other are "on plan" — a chart's line width, in share.
ON_PLAN = 0.005


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
class Landing:
    """What the simulation lands on one date inside a stretch: how many steps, how many
    estimated days — the knots the expected curve is drawn through."""

    day: date
    steps: int
    days: float


@dataclass(frozen=True)
class Stretch:
    """One stretch of the plan as a snapshot records it: the milestone that closes it
    (``""`` for the work after the last one), its tally, when it was expected to run, and
    what was expected to land on each date along the way."""

    key: str
    tally: Tally
    start: date
    finish: date | None
    landings: tuple[Landing, ...] = ()


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
class Delta:
    """How a scope moved between the baseline and now: what was added and how the landing
    shifted. ``shift`` is working days, positive for later; None when either side had no
    landing to compare."""

    steps: int
    days: float
    finish_then: date | None
    finish_now: date | None

    @property
    def shift(self) -> int | None:
        if self.finish_then is None or self.finish_now is None:
            return None
        return landing_shift(self.finish_then, self.finish_now)

    @property
    def unchanged(self) -> bool:
        return not self.steps and not self.days and not self.shift


def landing_shift(then: date, now: date) -> int:
    """How many working days a landing moved from ``then`` to ``now``: positive for
    later, negative for earlier, zero for the same day."""
    if now >= then:
        return working_days_between(then, now) - 1
    return -(working_days_between(now, then) - 1)


def span_of(snapshot: "Snapshot | None", key: str) -> tuple[date, date] | None:
    """Where the stretch ``key`` closes ran in a snapshot: its start and its landing, or
    None when that plan never knew it or could not date it."""
    if snapshot is None:
        return None
    for stretch in snapshot.stretches:
        if stretch.key == key:
            return (stretch.start, stretch.finish) if stretch.finish is not None else None
    return None


def standing_words(standing: float | None) -> str:
    """Ahead or behind, in one short phrase — actual against plan, as a share.

    Beside today's reading in the window and in the report; here rather than in either
    because a chart on paper and a chart on screen may not word one fact two ways.
    """
    if standing is None:
        return ""
    if abs(standing) < ON_PLAN:
        return "on plan"
    return f"{'ahead' if standing > 0 else 'behind'} {abs(standing):.0%}"


def shift_words(
    label: str, then: date | None, now: date | None, basis: date | None, today: date
) -> str:
    """A milestone's row in words: where it lands, and how that moved since the basis."""
    if now is None:
        return f"{label} — nothing estimated, so no date"
    said = f"{label} lands {format_date(now, today=today)}"
    if basis is None:
        return said
    if then is None:
        return f"{said} — not in the plan at {format_date(basis, today=today)}"
    moved = landing_shift(then, now)
    if moved == 0:
        return f"{said} — unchanged since {format_date(basis, today=today)}"
    direction = "later" if moved > 0 else "earlier"
    return (
        f"{said} — {abs(moved)} working day{'' if abs(moved) == 1 else 's'} {direction} "
        f"than planned on {format_date(basis, today=today)} ({format_date(then, today=today)})"
    )


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
            landings=landings(phase, days_for),
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


def landings(phase: Phase, days_for: Callable[[Step], float | None]) -> tuple[Landing, ...]:
    """What the stretch lands on each date, in date order — the simulation's per-step
    landings gathered per day."""
    by_day: dict[date, Landing] = {}
    for step in phase.steps:
        when = phase.landing_of(step.id)
        found = by_day.get(when, Landing(when, 0, 0.0))
        by_day[when] = Landing(when, found.steps + 1, found.days + (days_for(step) or 0.0))
    return tuple(by_day[when] for when in sorted(by_day))


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


def _through(snapshot: Snapshot, key: str | None) -> list[Stretch]:
    """The stretches through the one ``key`` closes — every stretch for None."""
    chosen: list[Stretch] = []
    for stretch in snapshot.stretches:
        chosen.append(stretch)
        if stretch.key == key:
            break
    return chosen


def marks(snapshot: Snapshot, key: str | None) -> list[tuple[date, str]]:
    """Where each milestone through ``key`` was expected to land, with its key. The
    remainder after the last milestone is no milestone and has no mark."""
    return [
        (stretch.finish, stretch.key)
        for stretch in _through(snapshot, key)
        if stretch.key and stretch.finish is not None
    ]


def idle(snapshot: Snapshot, key: str | None) -> list[tuple[date, date]]:
    """The spans the plan leaves empty through the stretch ``key`` closes: from one
    stretch's landing to the next stretch's start, when a milestone's own start date
    holds its work back past the working day after the previous one lands. A weekend
    between two stretches is not a gap."""
    spans: list[tuple[date, date]] = []
    for previous, following in pairwise(_through(snapshot, key)):
        if previous.finish is None:
            continue
        if following.start > next_working_day(previous.finish + timedelta(days=1)):
            spans.append((previous.finish, following.start))
    return spans


def expected(snapshot: Snapshot, key: str | None, *, by_days: bool) -> list[tuple[date, float]]:
    """The plan's promise for the scope as the snapshot recorded it: the share landed by
    each date, from the stretches' landing knots, 0 at the first start and 1 at the
    scope's landing. Cumulative through the stretch ``key`` closes — every stretch for
    None; empty for a scope the snapshot never knew or one with nothing to be a share of.
    Across a gap the plan leaves empty (:func:`idle`) the line holds flat to the day
    work resumes, so a chart can draw the gap as what it is rather than a slope."""
    if not snapshot.has(key):
        return []
    chosen = _through(snapshot, key)
    whole = sum(
        landing.days if by_days else landing.steps
        for stretch in chosen
        for landing in stretch.landings
    )
    if not whole:
        return []
    landed: dict[date, float] = {}
    for stretch in chosen:
        for landing in stretch.landings:
            amount = landing.days if by_days else landing.steps
            landed[landing.day] = landed.get(landing.day, 0.0) + amount
    resumes = {start for _finish, start in idle(snapshot, key)}
    points = [(chosen[0].start, 0.0)]
    running = 0.0
    for when in sorted(landed.keys() | resumes):
        if when in resumes:
            points.append((when, points[-1][1]))
        if when in landed:
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


def baseline(history: Sequence[Snapshot], basis: date) -> Snapshot | None:
    """The plan as it stood on the basis day: the last row on or before it, else the
    earliest row there is — a project older than its history compares against the
    first day anybody recorded. None with no history at all."""
    before = [row for row in history if row.day <= basis]
    if before:
        return before[-1]
    return history[0] if history else None


def delta(then: Snapshot, now: Snapshot, key: str | None) -> Delta | None:
    """How the scope moved from the baseline to now — None when either never knew it."""
    if not then.has(key) or not now.has(key):
        return None
    was, is_now = then.toward(key), now.toward(key)
    return Delta(
        steps=is_now.steps - was.steps,
        days=is_now.days - was.days,
        finish_then=then.landing(key),
        finish_now=now.landing(key),
    )


def delta_words(moved: Delta, since: date) -> str:
    """The delta in one clause: what was added and how the landing moved since the
    baseline's day."""
    when = format_date(since)
    if moved.unchanged:
        return f"unchanged since {when}"
    parts = []
    if moved.steps:
        parts.append(f"{moved.steps:+d} step{'s' if abs(moved.steps) != 1 else ''}")
    if moved.days:
        parts.append(f"{moved.days:+g}d")
    shift = moved.shift
    if shift:
        direction = "later" if shift > 0 else "earlier"
        parts.append(
            f"lands {abs(shift)} working day{'s' if abs(shift) != 1 else ''} {direction}"
            + (f" (was {format_date(moved.finish_then)})" if moved.finish_then else "")
        )
    elif moved.finish_then is None and moved.finish_now is not None:
        parts.append(f"now lands {format_date(moved.finish_now)}")
    elif moved.finish_now is None and moved.finish_then is not None:
        parts.append("no longer dated")
    return f"since {when}: " + ", ".join(parts)


@dataclass(frozen=True)
class Changes:
    """What moved the plan since the basis: steps born after it, and estimates that
    changed after it — the reasons behind a delta, read off the steps themselves."""

    added: list[tuple[Step, float | None]]
    estimates: list[tuple[Step, date, float, float | None]]  # step, day, from, to

    since: date

    def lines(self, key_of: Callable[[Step], str]) -> list[str]:
        when = format_date(self.since)
        found = []
        if self.added:
            named = ", ".join(
                f"{key_of(step) or step.title}"
                + (f" ({format_days(days)})" if days is not None else "")
                for step, days in self.added
            )
            found.append(f"added since {when}: {named}")
        if self.estimates:
            named = ", ".join(
                f"{key_of(step) or step.title} {format_days(was)} → {format_days(days)} "
                f"on {format_date(day)}"
                for step, day, was, days in self.estimates
            )
            found.append(f"re-estimated since {when}: {named}")
        return found


def changes_since(
    project: Project,
    since: date,
    days_for: Callable[[Step], float | None],
    estimate_history: Callable[[Step], list[tuple[date, float]]],
) -> Changes:
    """The steps born after ``since`` and the estimates changed after it — the reasons
    behind a delta, read off the steps themselves. ``since`` is the baseline's recorded
    day, not the basis: the delta measures from that record, so what this names is what
    moved it. A step's birth is its ``created`` stamp; an estimate's history says the day
    each value was replaced, so a row after ``since`` is a change after it (a change on
    the day itself is inside that day's record — last-wins). Both readers are handed in:
    this module never learns how an estimate remembers, and the stamp is the model's."""
    added = []
    estimates = []
    for step in project.steps:
        born = _created_on(step)
        if born is not None and born > since:
            added.append((step, days_for(step)))
            continue
        later = [(when, was) for when, was in estimate_history(step) if when > since]
        if later:
            # One line per step: what it was on the day it first changed, what it is now.
            first_when, was = later[0]
            estimates.append((step, first_when, was, days_for(step)))
    return Changes(added, estimates, since)


def _created_on(step: Step) -> date | None:
    try:
        return date.fromisoformat(step.created[:10])
    except ValueError:
        return None


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
    knots = row.get("landings")
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
        landings=tuple(
            Landing(when, _count(knot.get("steps")), _amount(knot.get("days")))
            for knot in (knots if isinstance(knots, list) else [])
            if isinstance(knot, dict)
            and isinstance(knot.get("date"), str)
            and (when := _day(knot["date"])) is not None
        ),
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
    stretch nothing dated, no ``landings`` for one with nothing to land, and a zero is
    written because it is a count, not a default."""
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
                            **(
                                {
                                    "landings": [
                                        {
                                            "date": knot.day.isoformat(),
                                            "steps": knot.steps,
                                            "days": float(knot.days),
                                        }
                                        for knot in s.landings
                                    ]
                                }
                                if s.landings
                                else {}
                            ),
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


@dataclass(frozen=True)
class ScopeView:
    """One scope of the plan as the chart draws it: the plan now, the plan as recorded on
    the basis day, what landed, and where the milestones through it stand.

    The Time tab, ``dplanner progress show`` and the report each read this once per scope
    rather than assembling the same eight calls three ways.
    """

    key: str | None
    reached: Tally
    finish: date | None
    expected: tuple[tuple[date, float], ...]
    actual: tuple[tuple[date, float], ...]
    baseline: tuple[tuple[date, float], ...]
    baseline_day: date | None
    baseline_finish: date | None
    moved: Delta | None
    marks: tuple[tuple[date, str], ...]  # (the day it lands, the milestone's step id)
    idle: tuple[tuple[date, date], ...]
    # Actual against plan today, as a share: positive ahead, negative behind, None when
    # either line has nothing to say for today.
    standing: float | None = None


def view_scope(
    now: Snapshot,
    history: Sequence[Snapshot],
    then: Snapshot | None,
    key: str | None,
    *,
    by_days: bool,
) -> ScopeView:
    return ScopeView(
        key=key,
        reached=now.toward(key),
        finish=now.landing(key),
        expected=tuple(expected(now, key, by_days=by_days)),
        actual=tuple(actual(history, now, key, by_days=by_days)),
        baseline=tuple(expected(then, key, by_days=by_days)) if then is not None else (),
        baseline_day=then.day if then is not None else None,
        baseline_finish=then.landing(key) if then is not None else None,
        moved=delta(then, now, key) if then is not None else None,
        marks=tuple(marks(now, key)),
        idle=tuple(idle(now, key)),
        standing=_standing(
            tuple(expected(now, key, by_days=by_days)),
            tuple(actual(history, now, key, by_days=by_days)),
            now.day,
        ),
    )


def _standing(
    plan: tuple[tuple[date, float], ...], landed: tuple[tuple[date, float], ...], today: date
) -> float | None:
    promised, reached = share_at(plan, today), share_at(landed, today)
    return None if promised is None or reached is None else reached - promised
