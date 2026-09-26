"""How far the plan has come, against how far it said it would be by now — and the
snapshots that remember what it said.

The calendar beside this says when each milestone *lands*; this says what has *landed*.
**The measure is estimated days**: the days of done steps over the days of all of them.
A count of steps was offered beside it once and dropped, because a share of steps calls a
two-hour step and a two-week one the same thing — the one comparison a plan priced in
days must not make. The count is still tallied and printed in words, never as the share.
Everything here is derived on every read from the statuses and the estimates
(``ordering.py``'s rule), never stored — except the past.

**Expected progress is the simulation's own curve.** ``domain/schedule.py``'s
``parallel_finish`` says on which working day each step lands; ``phases`` carries that
per stretch, and a :class:`Stretch` keeps it as :class:`Landing` knots — what lands on
each date. :func:`expected` turns the knots into a share landed by date: the plan's own
promise, for the stored team and focus, exact rather than a straight line drawn between
start and finish.

**A snapshot is the plan on one day, and the past is a list of them.** What the plan
looked like last Tuesday — how many steps it had, how much was done, when each of them
was expected to land — is gone once the plan changes, and a chart of the plan against
what became of it is nothing without it. So a :class:`Snapshot` — one row per stretch of
the plan: steps, done, days, done days, start, landing, and the landing knots — is
recorded under a module id of its own, ``progress_history``
(``modules/progress_history.json`` beside the project). Two lists live there:

- **Automatic** snapshots, one per day, written **only on a day something in the plan
  changed** — a step or an estimate added or taken away, a link that reorders the graph,
  a status that lands work, a milestone dated — and last-wins within the day. The
  window's recorder writes them after every settled change; ``dplanner progress record``
  writes them for a plan driven from the terminal.
- **Saved** snapshots, taken on purpose and named — *"What we thought on 1 November"* —
  with a note saying what the occasion was. They are never replaced by a later change
  and never expire: a saved snapshot is a record of a decision, kept whole.

A row keeps its stretches *in order*, so a later read can sum through a milestone the way
the sequence ran that day; a milestone a row never knew is simply absent from it. Because
a row carries its knots, **the plan as it stood on any recorded day is drawn exactly**,
not reconstructed.

**A comparison is two snapshots, and both are picked.** The plots compare a *then* with
a *now*; a :class:`Pick` says which recorded plan each side reads — the plan at the
project's start, a saved snapshot by name, any recorded day, or the live plan — and
:func:`resolve` finds the record that stands for it. The then side defaults to the
project's start (the last record on or before it, else the earliest one, but never
today's own: the plan over itself is no comparison) and the now side to the live plan,
which is the question almost everybody asks; a saved snapshot on either side is how a
review meeting's outlook is measured against a later one. :func:`pick_words` names the
record that answered, so a heading never hides which plan it is comparing.

**Volume is the scope over time.** :func:`volume` reads every snapshot's total of
estimated days into a step curve — the sum the plan came to on each recorded day — and
:func:`remaining` the same less what had landed; together they say how the scope grew as
the work went on and how much of it was still ahead. Qt-free by rule
(``HEADLESS_FILES``); the chart renders, the CLI prints, and both read this.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from itertools import pairwise
from typing import Any, Literal

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.model import Library, Project, Step, local_day
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
ROWS_KEY = "days"
SAVED_KEY = "saved"


def _to_format_2(data: dict[str, Any]) -> dict[str, Any]:
    """Format 1 shapes are valid format 2 shapes: the bump exists for the ``saved`` key,
    so an older build refuses to rewrite the entry rather than dropping what somebody
    saved on purpose."""
    return dict(data)


def _to_format_3(data: dict[str, Any]) -> dict[str, Any]:
    """Format 3 counts, per stretch, the steps whose status changed on the row's day
    (``changed``, absent when none did). Older rows say nothing about it, and a reader takes
    their silence as a day nobody can vouch for; the bump is so an older build, whose
    writer rebuilds every row, knows it would drop the counts."""
    return dict(data)


DATA_FORMAT = ModuleDataFormat(HISTORY_ID, 3, (_to_format_2, _to_format_3))

# Two shares within this of each other are "on plan" — a chart's line width, in share.
ON_PLAN = 0.005


@dataclass(frozen=True)
class Tally:
    """What a scope amounts to and how much of it has landed — the two measures' inputs."""

    steps: int = 0
    done: int = 0
    days: float = 0.0  # Estimated project days, unestimated steps counting nothing.
    done_days: float = 0.0
    # How many of the steps' statuses changed on the day recorded: a day of work, told
    # from a day nothing moved even when nothing finished.
    changed: int = 0

    def __add__(self, other: "Tally") -> "Tally":
        return Tally(
            self.steps + other.steps,
            self.done + other.done,
            self.days + other.days,
            self.done_days + other.done_days,
            self.changed + other.changed,
        )

    def share(self) -> float | None:
        """Done days over all days, 0 to 1 — None when there is nothing to be a share of."""
        return self.done_days / self.days if self.days else None

    @property
    def remaining(self) -> float:
        """The estimated days not yet landed."""
        return self.days - self.done_days


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
    """The plan on one day, stretch by stretch, in the order the sequence ran them.

    ``title`` and ``note`` are a saved snapshot's — what the occasion was called and what
    it was about; an automatic day carries neither.
    """

    day: date
    stretches: tuple[Stretch, ...]
    title: str = ""
    note: str = ""

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
        """Whether two days recorded the same plan — everything but the day, and how many
        statuses changed on it."""
        return _plan(self) == _plan(other)

    @property
    def changed(self) -> int:
        """How many statuses changed on the day recorded, across every stretch."""
        return sum(stretch.tally.changed for stretch in self.stretches)


def _plan(snapshot: Snapshot) -> tuple[Stretch, ...]:
    return tuple(replace(s, tally=replace(s.tally, changed=0)) for s in snapshot.stretches)


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


def shift_words(label: str, then: date | None, now: date | None, basis: str, today: date) -> str:
    """A milestone's row in words: where it lands, and how that moved against the plan
    it is compared with — ``basis`` is that plan named (:func:`pick_words`), empty when
    there is none to compare with."""
    if now is None:
        return f"{label} — nothing estimated, so no date"
    said = f"{label} lands {format_date(now, today=today)}"
    if not basis:
        return said
    if then is None:
        return f"{said} — not in {basis}"
    moved = landing_shift(then, now)
    if moved == 0:
        return f"{said} — unchanged since {basis}"
    direction = "later" if moved > 0 else "earlier"
    return (
        f"{said} — {abs(moved)} working day{'' if abs(moved) == 1 else 's'} {direction} "
        f"than {basis} said ({format_date(then, today=today)})"
    )


# -- taking a snapshot ------------------------------------------------------------------------


def take(
    library: Library,
    project: Project,
    days_for: Callable[[Step], float | None],
    is_agent: Callable[[Step], bool],
    status_for: Callable[[Step], str],
    since_for: Callable[[Step], date | None],
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
    phases = calendar_phases(
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
    return snapshot_of(phases, today, days_for, status_for, since_for)


def snapshot_of(
    phases: Sequence[Phase],
    day: date,
    days_for: Callable[[Step], float | None],
    status_for: Callable[[Step], str],
    since_for: Callable[[Step], date | None],
) -> Snapshot:
    """The plan on ``day`` from its dated stretches: each with what has landed in it and
    how many of its steps' statuses changed that day."""
    return Snapshot(
        day=day,
        stretches=tuple(
            Stretch(
                key=phase.milestone.id if phase.milestone else "",
                tally=replace(
                    tally(phase.steps, days_for, status_for),
                    changed=sum(1 for step in phase.steps if since_for(step) == day),
                ),
                start=phase.start,
                finish=phase.finish,
                landings=landings(phase, days_for),
            )
            for phase in phases
        ),
    )


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


def expected(snapshot: Snapshot, key: str | None) -> list[tuple[date, float]]:
    """The plan's promise for the scope as the snapshot recorded it: the share of
    estimated days landed by each date, from the stretches' landing knots, 0 at the first
    start and 1 at the scope's landing. Cumulative through the stretch ``key`` closes —
    every stretch for None; empty for a scope the snapshot never knew or one with nothing
    to be a share of. Across a gap the plan leaves empty (:func:`idle`) the line holds
    flat to the day work resumes, so a chart can draw the gap as what it is rather than
    a slope."""
    if not snapshot.has(key):
        return []
    chosen = _through(snapshot, key)
    whole = sum(landing.days for stretch in chosen for landing in stretch.landings)
    if not whole:
        return []
    landed: dict[date, float] = {}
    for stretch in chosen:
        for landing in stretch.landings:
            landed[landing.day] = landed.get(landing.day, 0.0) + landing.days
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


def until(history: Sequence[Snapshot], now: Snapshot | None) -> list[Snapshot]:
    """The recorded days through ``now``'s own, then ``now`` — the rows a curve ending
    at ``now`` is drawn from. A day after it is the future of a plan read as of an
    earlier snapshot, and says nothing about it."""
    rows = [row for row in history if now is None or row.day <= now.day]
    return [*rows, *([now] if now is not None else [])]


def actual(
    history: Sequence[Snapshot], now: Snapshot | None, key: str | None
) -> list[tuple[date, float]]:
    """Where progress actually stood, day by day: every recorded day that knew the scope,
    then ``now``. A day the scope had nothing to be a share of contributes no point."""
    points: list[tuple[date, float]] = []
    for row in until(history, now):
        if not row.has(key):
            continue
        share = row.toward(key).share()
        if share is None:
            continue
        if points and points[-1][0] == row.day:
            points[-1] = (row.day, share)  # Today's live reading replaces its record.
        else:
            points.append((row.day, share))
    return points


def baseline(
    history: Sequence[Snapshot], basis: date, *, today: date | None = None
) -> Snapshot | None:
    """The plan as it stood on the basis day: the last row on or before it, else the
    earliest row there is — a project older than its history compares against the first
    day anybody recorded. None with no history at all.

    That fallback stops at ``today``'s own record. A project whose history begins today
    has no earlier plan, and standing today's record in for one draws the plan now over
    itself and calls the pair a comparison — two lines in one place saying "nothing has
    changed since the outset", which is a claim nobody recorded. Callers that show a
    comparison pass ``today``; a caller that only reports the day it found need not.
    """
    before = [row for row in history if row.day <= basis]
    if before:
        return before[-1]
    first = history[0] if history else None
    if first is None or (today is not None and first.day >= today):
        return None
    return first


def scope_words(basis: str) -> str:
    """The scope plot's heading: what the plan now is measured against, named by
    :func:`pick_words` — empty when the pick found no record. Worded here rather than
    in either surface because the window and the report may not word one fact two
    ways."""
    return f"Scope change — versus {basis}" if basis else "Scope change — nothing to compare with"


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


def delta_words(moved: Delta, since: date, today: date) -> str:
    """The delta in one clause: what was added and how the landing moved since the
    baseline's recorded day."""
    when = format_date(since, today)
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
            + (f" (was {format_date(moved.finish_then, today)})" if moved.finish_then else "")
        )
    elif moved.finish_then is None and moved.finish_now is not None:
        parts.append(f"now lands {format_date(moved.finish_now, today)}")
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

    def lines(self, key_of: Callable[[Step], str], today: date) -> list[str]:
        when = format_date(self.since, today)
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
                f"on {format_date(day, today)}"
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
        born = local_day(step.created)
        if born is not None and born > since:
            added.append((step, days_for(step)))
            continue
        later = [(when, was) for when, was in estimate_history(step) if when > since]
        if later:
            # One line per step: what it was on the day it first changed, what it is now.
            first_when, was = later[0]
            estimates.append((step, first_when, was, days_for(step)))
    return Changes(added, estimates, since)


# -- the history on disk ------------------------------------------------------------------------


def read_history(project: Project) -> list[Snapshot]:
    """Every automatically recorded day, oldest first. An unreadable row reads as absent."""
    return _rows(project, ROWS_KEY)


def read_saved(project: Project) -> list[Snapshot]:
    """Every snapshot somebody saved on purpose, in the order they were saved — each
    with its title; one without a title is not a saved snapshot and reads as absent."""
    return [row for row in _rows(project, SAVED_KEY) if row.title]


def _rows(project: Project, key: str) -> list[Snapshot]:
    entry = project.module_data.get(HISTORY_ID, {})
    raw = entry.get(key)
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
        rows.append(
            Snapshot(
                day,
                tuple(s for s in parsed if s is not None),
                title=_text(row.get("title")),
                note=_text(row.get("note")),
            )
        )
    return rows


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


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
            changed=_count(row.get("changed")),
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


def write_history(rows: Sequence[Snapshot], saved: Sequence[Snapshot] = ()) -> dict[str, Any]:
    """The entry for these days and these saved snapshots — ``{}`` (remove the file)
    when there are none of either. Absence is the default throughout: no milestone key
    for the remainder, no ``finish`` for a stretch nothing dated, no ``landings`` for one
    with nothing to land, no ``saved`` list without a saved snapshot and no ``note`` on
    one without; a zero is written because it is a count, not a default."""
    if not rows and not saved:
        return {}
    entry: dict[str, Any] = {}
    if rows:
        entry[ROWS_KEY] = [_row(row) for row in rows]
    if saved:
        entry[SAVED_KEY] = [
            {"title": row.title, **({"note": row.note} if row.note else {}), **_row(row)}
            for row in saved
        ]
    return stamped(entry, DATA_FORMAT.version)


def _row(row: Snapshot) -> dict[str, Any]:
    return {
        "day": row.day.isoformat(),
        "stretches": [
            {
                **({"milestone": s.key} if s.key else {}),
                "steps": s.tally.steps,
                "done": s.tally.done,
                "days": float(s.tally.days),
                "done_days": float(s.tally.done_days),
                **({"changed": s.tally.changed} if s.tally.changed else {}),
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


def recorded(history: Sequence[Snapshot], now: Snapshot) -> list[Snapshot] | None:
    """The history with today recorded — None when the last row already says exactly
    this, so nothing is written. Today's own earlier row is replaced: one row per day,
    the last state of the day wins. A title on ``now`` is not recorded here: the
    automatic days carry none."""
    now = replace(now, title="", note="")
    rows = list(history)
    if rows and rows[-1].day == now.day:
        if rows[-1].stretches == now.stretches:
            return None
        rows[-1] = now
        return rows
    # A new day is written when the plan moved or a status changed on it — never merely
    # because yesterday's row counted changes today does not.
    if rows and rows[-1].same_plan(now) and not now.changed:
        return None
    rows.append(now)
    return rows


def find_saved(saved: Sequence[Snapshot], title: str) -> Snapshot | None:
    """The saved snapshot called ``title``, case and surrounding space aside."""
    wanted = title.strip().lower()
    return next((row for row in saved if row.title.lower() == wanted), None)


def saved_with(
    saved: Sequence[Snapshot], now: Snapshot, title: str, note: str = ""
) -> list[Snapshot]:
    """The saved snapshots with ``now`` kept under ``title`` — refused when the title is
    empty or already taken, because a saved snapshot is found by its name."""
    title = title.strip()
    if not title:
        raise ValueError("a saved snapshot needs a title")
    if find_saved(saved, title) is not None:
        raise ValueError(f"a snapshot called {title!r} is already saved")
    return [*saved, replace(now, title=title, note=note.strip())]


def saved_without(saved: Sequence[Snapshot], title: str) -> list[Snapshot]:
    """The saved snapshots less the one called ``title`` — unchanged when there is none."""
    wanted = title.strip().lower()
    return [row for row in saved if row.title.lower() != wanted]


# -- which plan a comparison reads ---------------------------------------------------------------

PickKind = Literal["start", "now", "saved", "day"]


@dataclass(frozen=True)
class Pick:
    """Which recorded plan one side of the comparison reads: the plan at the project's
    start, the live plan now, a saved snapshot by ``title``, or the plan as recorded on
    ``day``. View state, never stored — a way of looking, like the picked milestone."""

    kind: PickKind
    title: str = ""
    day: date | None = None


AT_START = Pick("start")
LIVE = Pick("now")


def resolve(
    pick: Pick,
    *,
    history: Sequence[Snapshot],
    saved: Sequence[Snapshot],
    live: Snapshot | None,
    start: date,
) -> Snapshot | None:
    """The record ``pick`` names — None when nothing recorded answers it.

    The start and a day resolve through :func:`baseline`: the last record on or before
    the day, else the earliest there is, but never the live plan's own day standing in
    for an earlier one — that is the plan now and no comparison at all.
    """
    if pick.kind == "now":
        return live
    if pick.kind == "saved":
        return find_saved(saved, pick.title)
    when = start if pick.kind == "start" else pick.day
    if when is None:
        return None
    return baseline(history, when, today=live.day if live is not None else None)


def pick_words(pick: Pick, found: Snapshot | None, today: date) -> str:
    """The pick named for a heading or a row's sentence — and, when a record stood in
    for the day asked for, which one: *the plan at start (7 Sep), recorded 9 Sep*. Empty
    when the pick found nothing, so a caller can say so in its own words."""
    if pick.kind == "now":
        return "now"
    if pick.kind == "saved":
        return f"{pick.title} ({format_date(found.day, today=today)})" if found else ""
    when = pick.day if pick.kind == "day" else None
    asked = f"the plan at {format_date(when, today=today)}" if when else "the plan at start"
    if found is None:
        return ""
    if when is not None and found.day == when:
        return asked
    return f"{asked}, recorded {format_date(found.day, today=today)}"


# -- volume: the scope over time -----------------------------------------------------------------


def volume(history: Sequence[Snapshot], now: Snapshot | None) -> list[tuple[date, float]]:
    """The total of estimated days the plan came to on each recorded day through
    ``now``, as a step curve: a value holds until the day it changed, because a record
    is what the plan was until the next one."""
    return _steps(until(history, now), lambda reached: reached.days)


def remaining(history: Sequence[Snapshot], now: Snapshot | None) -> list[tuple[date, float]]:
    """The estimated days still ahead on each recorded day through ``now`` — the volume
    less what had landed — as the same step curve."""
    return _steps(until(history, now), lambda reached: reached.remaining)


def nice_ceiling(value: float) -> float:
    """The least of 1, 2 or 5 times a power of ten at or above ``value`` — at least one
    day, so an empty scale still has a top. What the volume plots' scale is set to, in
    the window and in the report alike."""
    if value <= 1.0:
        return 1.0
    magnitude = 10 ** int(f"{value:e}".split("e")[1])
    for step in (1, 2, 5, 10):
        if step * magnitude >= value:
            return float(step * magnitude)
    return float(10 * magnitude)


def volume_scale(total: Sequence[tuple[date, float]], left: Sequence[tuple[date, float]]) -> float:
    """One scale for both volume plots — the largest value either reaches, rounded up
    (:func:`nice_ceiling`) — so the gap between them is read by eye."""
    return nice_ceiling(max((value for _, value in (*total, *left)), default=0.0))


def _steps(
    rows: Sequence[Snapshot], value_of: Callable[[Tally], float]
) -> list[tuple[date, float]]:
    points: list[tuple[date, float]] = []
    for row in rows:
        value = value_of(row.toward(None))
        if points and points[-1][0] == row.day:
            points[-1] = (row.day, value)  # The live reading replaces its own day's record.
            continue
        if points:
            points.append((row.day, points[-1][1]))  # Held flat until the day it changed.
        points.append((row.day, value))
    return points


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
    now: Snapshot, history: Sequence[Snapshot], then: Snapshot | None, key: str | None
) -> ScopeView:
    promised = tuple(expected(now, key))
    landed = tuple(actual(history, now, key))
    return ScopeView(
        key=key,
        reached=now.toward(key),
        finish=now.landing(key),
        expected=promised,
        actual=landed,
        baseline=tuple(expected(then, key)) if then is not None else (),
        baseline_day=then.day if then is not None else None,
        baseline_finish=then.landing(key) if then is not None else None,
        moved=delta(then, now, key) if then is not None else None,
        marks=tuple(marks(now, key)),
        idle=tuple(idle(now, key)),
        standing=_standing(promised, landed, now.day),
    )


def _standing(
    plan: tuple[tuple[date, float], ...], landed: tuple[tuple[date, float], ...], today: date
) -> float | None:
    promised, reached = share_at(plan, today), share_at(landed, today)
    return None if promised is None or reached is None else reached - promised
