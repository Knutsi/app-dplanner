"""Which work is taken by which squad: a lease in git, a file per claim (FORMAT.md's *The
`claims` directory*).

```
<project dir>/
└── claims/                      beside ledger/ and questions/, not one of the plan entries
    └── 2026-10/                 the month it was taken
        └── 20261007T100212Z-5a0b7c3d.json        shown as C-5a0b
```

**One claim per squad**, written by its coordinator: the squad word, the machine it works
on, the steps it holds, and a heartbeat. Which member works which step is on the run. A
claim must be seen from other machines, so it is in git and its clock is slow — renewed only
when ten minutes old (:func:`beaten`) — and it is judged by the reader's clock: past its
lease it reads as **abandoned**, unless every step it holds is parked on a question, and
nothing is ever deleted (:func:`standing`). It is not the at-work claim of
``domain/at_work.py``, which says a process here is editing the plan right now.

Acquiring is a push, not a write — ``domain/claim_sync.py`` does the git half — and when a
merge brings two claims onto one step, the one pushed first holds it (:func:`holdings`'s
``order``). A person's override is the one deliberate second writer: it releases one step
(:func:`released`), or ends the whole claim (:func:`ended`). Each change is a
read-modify-write under an OS lock (:func:`update`).
"""

import json
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from dplanner.core.config_dir import config_dir
from dplanner.core.fsio import os_lock, write_atomic
from dplanner.domain import questions
from dplanner.domain.ledger import new_run_id
from dplanner.domain.model import now_stamp
from dplanner.domain.questions import Question

CLAIMS_DIR = "claims"
FORMAT = 1

LEASE_MINUTES = 90
MAX_PARK_HOURS = 24
# A heartbeat is written only when it is this old, and a commit carrying nothing else is
# pushed at most this often: git stays quiet, and the lease is three pushes long.
BEAT_MINUTES = 10
PUSH_MINUTES = 30

LIVE = "live"
PARKED = "parked"
ABANDONED = "abandoned"
ENDED = "ended"
# Still owned: another squad may not take its steps.
HOLDING = (LIVE, PARKED)


@dataclass(frozen=True)
class Claim:
    id: str
    project: str
    callsign: str  # The squad word: "kettle".
    started: str  # ISO stamp, UTC.
    heartbeat: str
    worker: Mapping[str, str] = field(default_factory=dict)  # {machine, host}
    steps: tuple[str, ...] = ()
    released: tuple[Mapping[str, Any], ...] = ()  # {step, at, by: {kind, name}, why}
    lease_minutes: int = LEASE_MINUTES
    max_park_hours: int = MAX_PARK_HOURS
    supersedes: tuple[str, ...] = ()  # Abandoned claims whose steps this one took.
    ended: Mapping[str, Any] = field(default_factory=dict)  # {at, by: {kind, name}, why}

    @property
    def short(self) -> str:
        return short(self.id)

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "format": FORMAT,
            "id": self.id,
            "project": self.project,
            "callsign": self.callsign,
            "started": self.started,
            "heartbeat": self.heartbeat,
            "steps": list(self.steps),
        }
        # Absence encodes the default, FORMAT.md's rule.
        optional: dict[str, Any] = {
            "worker": dict(self.worker),
            "released": [dict(entry) for entry in self.released],
            "lease_minutes": self.lease_minutes if self.lease_minutes != LEASE_MINUTES else 0,
            "max_park_hours": self.max_park_hours if self.max_park_hours != MAX_PARK_HOURS else 0,
            "supersedes": list(self.supersedes),
            "ended": dict(self.ended),
        }
        data.update({key: value for key, value in optional.items() if value})
        return data

    @classmethod
    def from_json(cls, raw: object) -> "Claim | None":
        """A stored claim, or None for one this build cannot read."""
        if not isinstance(raw, dict) or not isinstance(raw.get("format"), int):
            return None
        if raw["format"] > FORMAT:
            return None
        id_, project, callsign = _text(raw, "id"), _text(raw, "project"), _text(raw, "callsign")
        if not (id_ and project and callsign):
            return None
        worker = raw.get("worker")
        return cls(
            id=id_,
            project=project,
            callsign=callsign,
            started=_text(raw, "started"),
            heartbeat=_text(raw, "heartbeat"),
            worker={str(k): str(v) for k, v in worker.items()} if isinstance(worker, dict) else {},
            steps=_texts(raw, "steps"),
            released=tuple(e for e in _list(raw, "released") if isinstance(e, dict)),
            lease_minutes=_count(raw, "lease_minutes") or LEASE_MINUTES,
            max_park_hours=_count(raw, "max_park_hours") or MAX_PARK_HOURS,
            supersedes=_texts(raw, "supersedes"),
            ended=_mapping(raw, "ended"),
        )


def short(id_: str) -> str:
    """``C-5a0b``: the first four of an id's random half, for a person to type."""
    return "C-" + id_.rpartition("-")[2][:4]


def squad_of(callsign: str) -> str:
    """The squad word of a member's callsign: ``kettle-three`` → ``kettle``."""
    return callsign.strip().lower().partition("-")[0]


def claimed(
    project: str,
    callsign: str,
    steps: Sequence[str],
    at: str,
    *,
    worker: Mapping[str, str],
    supersedes: Sequence[str] = (),
    lease_minutes: int = LEASE_MINUTES,
    max_park_hours: int = MAX_PARK_HOURS,
) -> Claim:
    """A new claim, its id minted as a run's is."""
    return Claim(
        id=new_run_id(),
        project=project,
        callsign=squad_of(callsign),
        started=at,
        heartbeat=at,
        worker=dict(worker),
        steps=tuple(dict.fromkeys(steps)),
        lease_minutes=lease_minutes,
        max_park_hours=max_park_hours,
        supersedes=tuple(supersedes),
    )


# -- what may happen to one ---------------------------------------------------------------------


def beaten(claim: Claim, at: str) -> Claim:
    """The claim with its heartbeat renewed — unchanged while the last one is under
    ``BEAT_MINUTES`` old, or once it has ended, so most renewals write nothing."""
    if claim.ended or minutes_between(claim.heartbeat, at) < BEAT_MINUTES:
        return claim
    return replace(claim, heartbeat=at)


def released(claim: Claim, step: str, by: Mapping[str, str], why: str, at: str) -> Claim:
    """``step`` handed back, the squad keeping the rest; the last one out ends the claim."""
    if step not in claim.steps:
        raise ValueError(f"{claim.short} does not hold that step")
    entry = {"step": step, "at": at, "by": dict(by), "why": why}
    rest = tuple(s for s in claim.steps if s != step)
    changed = replace(claim, steps=rest, released=(*claim.released, entry))
    return changed if rest else replace(changed, ended={"at": at, "by": dict(by), "why": why})


def ended(claim: Claim, by: Mapping[str, str], why: str, at: str) -> Claim:
    """The whole claim over. Written once."""
    if claim.ended:
        raise ValueError(f"{claim.short} has already ended")
    return replace(claim, ended={"at": at, "by": dict(by), "why": why})


# -- reading what it means now ------------------------------------------------------------------


def parks(asked: Iterable[Question]) -> dict[str, str]:
    """Each step waiting on a question, to when its oldest unsettled one was asked."""
    waiting: dict[str, str] = {}
    for question in asked:
        if not question.settled and (
            question.step not in waiting or question.asked < waiting[question.step]
        ):
            waiting[question.step] = question.asked
    return waiting


def standing(claim: Claim, now: str, parked: Mapping[str, str]) -> str:
    """``live``, ``parked``, ``abandoned`` or ``ended``, by the reader's clock. Past its lease
    a claim is still owned while every step it holds waits on a question — nothing live is
    there to renew it — until the oldest of those waits is ``max_park_hours`` old."""
    if claim.ended:
        return ENDED
    if minutes_between(claim.heartbeat, now) <= claim.lease_minutes:
        return LIVE
    waits = [parked.get(step, "") for step in claim.steps]
    if waits and all(waits) and minutes_between(min(waits), now) < claim.max_park_hours * 60:
        return PARKED
    return ABANDONED


@dataclass(frozen=True)
class Holding:
    claim: Claim
    state: str


def holdings(
    claims: Iterable[Claim], now: str, parked: Mapping[str, str], order: Sequence[str] = ()
) -> dict[str, Holding]:
    """Who holds each claimed step: the live or parked claim pushed first — ``order`` is
    claim ids in the order their files reached the remote, and one not in it yet comes after
    — else, so a reader can say so, the most recent abandoned one."""
    rank = {id_: index for index, id_ in enumerate(order)}

    def first(claim: Claim) -> tuple[int, str, str]:
        return (rank.get(claim.id, len(rank)), claim.started, claim.id)

    held: dict[str, Holding] = {}
    for claim in sorted(claims, key=first):
        state = standing(claim, now, parked)
        if state == ENDED:
            continue
        for step in claim.steps:
            current = held.get(step)
            if current is None or (
                current.state == ABANDONED
                and (state in HOLDING or claim.started > current.claim.started)
            ):
                held[step] = Holding(claim, state)
    return held


def read_holdings(project_dir: Path, now: str, order: Sequence[str] = ()) -> dict[str, Holding]:
    """:func:`holdings` over the project's claims as they are on disk, parked judged by its
    questions."""
    return holdings(records(project_dir), now, parks(questions.records(project_dir)), order)


def release_step(
    project_dir: Path,
    step: str,
    by: Mapping[str, str],
    why: str,
    claim_id: str = "",
    config: Path | None = None,
) -> Claim | None:
    """Release ``step`` from ``claim_id`` — by default, from whichever claim holds it — and
    return that claim as it now stands, or None when nothing held the step."""
    if not claim_id:
        holding = read_holdings(project_dir, now_stamp()).get(step)
        if holding is None:
            return None
        claim_id = holding.claim.id

    def releasing(claim: Claim) -> Claim:
        return released(claim, step, by, why, now_stamp()) if step in claim.steps else claim

    return update(project_dir, claim_id, releasing, config)


# -- the files ----------------------------------------------------------------------------------


def path_for(project_dir: Path, claim: Claim) -> Path:
    month = claim.started[:7] if len(claim.started) >= 7 else "unknown"
    return project_dir / CLAIMS_DIR / month / f"{claim.id}.json"


def write(project_dir: Path, claim: Claim) -> None:
    path = path_for(project_dir, claim)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, json.dumps(claim.to_json(), indent=2, sort_keys=True) + "\n")


def records(project_dir: Path) -> list[Claim]:
    """Every claim of the project this build can read, oldest first."""
    found = [c for path in _files(project_dir) if (c := _load(path)) is not None]
    return sorted(found, key=lambda c: (c.started, c.id))


def find(project_dir: Path, id_: str) -> Claim | None:
    for path in (project_dir / CLAIMS_DIR).glob(f"*/{id_}.json"):
        claim = _load(path)
        if claim is not None and claim.id == id_:
            return claim
    return None


def resolve(project_dir: Path, ref: str) -> Claim:
    """A claim by its id, its ``C-5a0b`` or a unique start of either half of its id."""
    ref = ref.strip()
    key = ref[2:] if ref.upper().startswith("C-") else ref
    found = [
        c
        for c in records(project_dir)
        if c.id == ref or c.id.startswith(key) or c.id.rpartition("-")[2].startswith(key.lower())
    ]
    if not key or not found:
        raise LookupError(f"no claim {ref!r} in this project")
    if len(found) > 1:
        raise LookupError(f"{ref!r} names several claims: {', '.join(c.id for c in found)}")
    return found[0]


def update(
    project_dir: Path, id_: str, change: Callable[[Claim], Claim], config: Path | None = None
) -> Claim:
    """Read the claim, change it and write it back, under its OS lock — the coordinator and a
    person's release re-read inside it. ``change`` raises to refuse."""
    with os_lock((config or config_dir()) / CLAIMS_DIR / f"{id_}.lock", wait=True):
        claim = find(project_dir, id_)
        if claim is None:
            raise LookupError(f"no claim {id_} in {project_dir}")
        changed = change(claim)
        if changed != claim:
            write(project_dir, changed)
        return changed


@contextmanager
def acquiring(project: str, config: Path | None = None) -> Iterator[None]:
    """The project's taking lock on this machine: two coordinators here check and claim one
    after the other. Another machine is met at the push."""
    with os_lock((config or config_dir()) / CLAIMS_DIR / f"take-{project}.lock", wait=True):
        yield


def fingerprint(project_dir: Path) -> tuple[tuple[str, int], ...]:
    """What the claims look like on disk, cheaply: a view polls this."""
    stamps: list[tuple[str, int]] = []
    for path in _files(project_dir):
        try:
            stamps.append((path.name, path.stat().st_mtime_ns))
        except OSError:
            continue
    return tuple(stamps)


def _files(project_dir: Path) -> Iterator[Path]:
    root = project_dir / CLAIMS_DIR
    if not root.is_dir():
        return iter(())
    # The dot excludes write_atomic's temporaries, which sit beside the file they become.
    return iter(sorted(p for p in root.glob("*/*.json") if not p.name.startswith(".")))


def _load(path: Path) -> Claim | None:
    try:
        return Claim.from_json(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None  # A half-written file, or one a newer build wrote.


def minutes_between(since: str, until: str) -> float:
    """Minutes from one stamp to another; an unreadable stamp is infinitely old."""
    start, end = _moment(since), _moment(until)
    if start is None or end is None:
        return float("inf")
    return (end - start) / timedelta(minutes=1)


def _moment(stamp: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    return value if isinstance(value, str) else ""


def _list(raw: Mapping[str, Any], key: str) -> list[Any]:
    value = raw.get(key)
    return value if isinstance(value, list) else []


def _texts(raw: Mapping[str, Any], key: str) -> tuple[str, ...]:
    return tuple(v for v in _list(raw, key) if isinstance(v, str) and v)


def _count(raw: Mapping[str, Any], key: str) -> int:
    value = raw.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _mapping(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key)
    return value if isinstance(value, dict) else {}
