"""An agent's own claim that it is at work on a plan — per user, per machine.

An agent drives ``dplanner`` against a project a window has open, and the window takes
every change in as it lands (``domain/store.py``'s *Two writers, one folder*). That works
perfectly until the developer edits the same entry at the same moment, and then the window
has to interrupt them with a question nobody wanted. The fix is not a lock: it is for the
agent to **say it is working**, loudly enough that the developer does not start editing in
the first place.

So this is one small record, written by the CLI and read by whoever wants to know:

    who       the project, and the step when the agent is on one
    what      one line the agent wrote about what it is doing
    how far   ``done`` of ``of``, when the agent counts something
    when      ``started``, and ``seen`` — the last sign of life

**Liveness is reported, never guessed.** An agent may think for twenty minutes without
touching the CLI, and a crashed agent leaves its claim behind; no timeout can tell those
apart, so nothing here tries. The record carries when the agent was last heard from and
every reader says so out loud — :func:`is_fresh` only decides whether the words read as
*is at work* or *was at work*, and a claim goes away when the agent ends it, when a person
clears it, or when a later claim sweeps it as ancient. That is three ways out and no
guessing, which is what makes it robust against an agent that stops without a word.

**Every ``dplanner`` run is a sign of life.** :meth:`AtWorkBoard.touch` runs from
``cli/main.py`` on every invocation, so an agent that is working — writing statuses, adding
notes, reading the graph — renews its claim without doing anything about it. The
``agent-work`` verbs exist to say *what* it is doing, not to prove it is alive.

**One file per claim.** Several agents may work one plan at once, each in its own process,
and a shared file would need a lock that two of them could lose an update over. A file per
claim means every writer touches only its own, and a reader is a directory listing.

It lives beside the telemetry journal under ``core/config_dir.py``, never in the project:
"an agent is running on this machine right now" is this machine's fact, and a plan that
carried it would commit a heartbeat into everybody's history. See FORMAT.md.
"""

import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dplanner.core.fsio import write_atomic
from dplanner.domain.model import ProjectId, StepId, now_stamp

FORMAT = 1
DIRECTORY = "at-work"  # Under config_dir(); the composition root names the path.
PLAN = "plan"  # The file-name half of a claim on no particular step.

# Silence past which the words read "was at work … last heard 20 minutes ago" rather than
# "is at work". Generous on purpose: an agent can spend a long time on one tool call, and
# reading a working agent as gone is the more expensive mistake. It changes nothing about
# what is stored — a claim is a claim until it is ended.
FRESH_MINUTES = 15

# A claim nobody ended and nobody has renewed since yesterday is swept by the next writer:
# the machine rebooted, or an agent died in a way it could not report. Long enough that it
# can never take a claim from an agent that is merely quiet.
SWEEP_HOURS = 24

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


@dataclass(frozen=True)
class AtWork:
    """One agent's claim on one project — and on one step, when it is working a step.

    What identifies one is its project and its step: two agents on two steps of one plan are
        two claims, and two on the same step are one.

        ``done``/``of`` are the agent's own count of whatever it decided to count; ``of`` zero
        means it offered none. There is deliberately no field for *which* agent CLI it is: the
        step it names says which run this is, and a name nothing reads is a field that drifts.
    """

    project: ProjectId
    step: StepId = ""
    doing: str = ""
    done: int = 0
    of: int = 0
    started: str = ""
    seen: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "project": self.project,
            "step": self.step,
            "doing": self.doing,
            "done": self.done,
            "of": self.of,
            "started": self.started,
            "seen": self.seen,
        }

    @classmethod
    def from_json(cls, raw: Any) -> "AtWork | None":
        """A stored claim, or None for a file this build cannot read — never a crash over
        one: the directory is the user's, and a newer build may have written it."""
        if not isinstance(raw, dict) or not isinstance(raw.get("project"), str):
            return None
        return cls(
            project=raw["project"],
            step=_text(raw.get("step")),
            doing=_text(raw.get("doing")),
            done=_count(raw.get("done")),
            of=_count(raw.get("of")),
            started=_text(raw.get("started")),
            seen=_text(raw.get("seen")),
        )


def _text(raw: object) -> str:
    return raw if isinstance(raw, str) else ""


def _count(raw: object) -> int:
    return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else 0


# -- reading a claim ----------------------------------------------------------------------------


def quiet_seconds(claim: AtWork, now: datetime | None = None) -> int:
    """How long since the agent was last heard from. A claim with no stamp reads as 0 —
    something wrote it and we have no reason to call it old."""
    heard = _moment(claim.seen)
    if heard is None:
        return 0
    return max(0, int(((now or datetime.now(UTC)) - heard).total_seconds()))


def is_fresh(claim: AtWork, now: datetime | None = None) -> bool:
    """Whether this reads as an agent that is at work, rather than one that was."""
    return quiet_seconds(claim, now) < FRESH_MINUTES * 60


def fraction(claim: AtWork) -> float:
    """How far along the agent says it is, or -1 when it offered no count."""
    if claim.of <= 0:
        return -1.0
    return min(1.0, claim.done / claim.of)


def _moment(stamp: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def heard_words(claim: AtWork, now: datetime | None = None) -> str:
    """When the agent was last heard from, coarsely — so the phrase changes rarely rather
    than every second, which is the difference between a fact and a ticking clock."""
    seconds = quiet_seconds(claim, now)
    if not claim.seen:
        return "not heard from yet"
    lead = "heard" if is_fresh(claim, now) else "last heard"
    if seconds < 90:
        return f"{lead} just now"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{lead} {minutes} minutes ago"
    hours = round(minutes / 60)
    return f"{lead} {hours} hour{'s' if hours != 1 else ''} ago"


def progress_words(claim: AtWork) -> str:
    """The agent's own count, or "" when it offered none."""
    return f"{claim.done} of {claim.of}" if claim.of > 0 else ""


def claim_words(claim: AtWork, where: str = "", step: str = "", now: datetime | None = None) -> str:
    """One line about a claim, for a banner, a status line or the terminal.

    ``where`` is the project as the reader knows it and ``step`` the step's key — neither
    is on the record, because a claim names ids and only the caller has the titles. Worded
    here so the window and ``dplanner agent-work show`` cannot say it differently.
    """
    named = " · ".join(part for part in (where, step) if part)
    lead = f"An agent {'is' if is_fresh(claim, now) else 'was'} at work"
    if named:
        lead = f"{lead} on {named}"
    rest = [part for part in (claim.doing, progress_words(claim), heard_words(claim, now)) if part]
    return f"{lead} — " + " · ".join(rest) if rest else lead


# -- the directory of claims --------------------------------------------------------------------


class AtWorkBoard:
    """Every claim on this machine: one small JSON file each, in one directory.

    ``directory=None`` is a board that holds nothing — it reads empty and writes nothing,
    the shape ``cli/gate.py``'s record-less gate uses, so a test never writes into the
    user's own configuration directory.
    """

    def __init__(self, directory: Path | None) -> None:
        self.directory = directory

    # -- reading -------------------------------------------------------------------------

    def claims(self, project: ProjectId = "") -> list[AtWork]:
        """Every claim, or every claim on one project — in the order they began, so a new
        one joins the end of a list rather than pushing what is there down."""
        found = [claim for _path, claim in self._files() if not project or claim.project == project]
        return sorted(found, key=lambda claim: (claim.started, claim.step))

    def at_work(self, project: ProjectId, now: datetime | None = None) -> list[AtWork]:
        """The claims on ``project`` that still read as an agent at work."""
        return [claim for claim in self.claims(project) if is_fresh(claim, now)]

    # -- writing -------------------------------------------------------------------------

    def start(
        self,
        project: ProjectId,
        step: StepId = "",
        doing: str = "",
        of: int = 0,
    ) -> AtWork:
        """Begin a claim, replacing whatever stood for this project and step."""
        self._sweep()
        stamp = now_stamp()
        return self._write(
            AtWork(
                project=project, step=step, doing=doing, of=max(0, of), started=stamp, seen=stamp
            )
        )

    def set(
        self,
        project: ProjectId,
        step: StepId = "",
        doing: str | None = None,
        done: int | None = None,
        of: int | None = None,
    ) -> AtWork:
        """Update a claim, keeping what is not given — and begin one when none stands.

        An agent that reports progress without having said it started is telling us the
        same thing; refusing it would cost the developer the warning it came with.
        """
        standing = self._read(project, step) or self.start(project, step)
        changed = replace(
            standing,
            doing=standing.doing if doing is None else doing,
            done=standing.done if done is None else max(0, done),
            of=standing.of if of is None else max(0, of),
            seen=now_stamp(),
        )
        return self._write(changed)

    def touch(self, project: ProjectId) -> None:
        """A sign of life: every ``dplanner`` run renews the project's standing claims.

        It never creates one — running a verb is not a claim to be working, it is only
        evidence for a claim somebody made.
        """
        stamp = now_stamp()
        for path, claim in self._files():
            if claim.project == project:
                self._put(path, replace(claim, seen=stamp))

    def end(self, project: ProjectId, step: StepId = "") -> bool:
        """The agent is done, or a person cleared it. False when nothing stood."""
        path = self._path(project, step)
        if path is None or not path.exists():
            return False
        path.unlink(missing_ok=True)
        return True

    # -- the files -----------------------------------------------------------------------

    def _files(self) -> list[tuple[Path, AtWork]]:
        if self.directory is None or not self.directory.is_dir():
            return []
        found: list[tuple[Path, AtWork]] = []
        for path in sorted(self.directory.glob("*.json")):
            claim = self._load(path)
            if claim is not None:
                found.append((path, claim))
        return found

    def _load(self, path: Path) -> AtWork | None:
        try:
            return AtWork.from_json(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return None  # A half-written file, or one a newer build wrote. Try again later.

    def _read(self, project: ProjectId, step: StepId) -> AtWork | None:
        path = self._path(project, step)
        return None if path is None else self._load(path)

    def _write(self, claim: AtWork) -> AtWork:
        path = self._path(claim.project, claim.step)
        if path is not None:
            self._put(path, claim)
        return claim

    def _put(self, path: Path, claim: AtWork) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(path, json.dumps(claim.to_json(), indent=2, sort_keys=True) + "\n")

    def _path(self, project: ProjectId, step: StepId) -> Path | None:
        if self.directory is None:
            return None
        return self.directory / f"{_safe(project)}-{_safe(step) or PLAN}.json"

    def _sweep(self) -> None:
        """Drop claims nobody has renewed since yesterday — a reboot, or an agent that
        died without a word. Done when a claim is made, which is the moment somebody is
        already writing here."""
        cutoff = SWEEP_HOURS * 3600
        for path, claim in self._files():
            if quiet_seconds(claim) > cutoff:
                path.unlink(missing_ok=True)


def _safe(name: str) -> str:
    """A file-name-safe form of an id. Ids are uuid hex, so this normally changes nothing;
    what is inside the file is the truth, and every reader reads the record, not the name."""
    return _UNSAFE.sub("_", name)[:48]
