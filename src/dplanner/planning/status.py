"""A step's status: its vocabulary, how it is stored and read, and how readiness sees it.

A step's status is a claim only a person or an agent can make — the graph can say what is
*ready*, but not what is finished or stuck, which is why this is stored rather than derived.
The vocabulary is deliberately small: ``pending`` is the default and encoded as absence
(FORMAT.md: absence encodes the default), so a step that was never anything else has no
file. ``blocked`` earns its place as the one state the graph cannot see — an external
blockage is a fact from outside the plan. ``ready-for-review`` and ``ready-to-merge`` sit
between in progress and done: an agent's work is finished and somebody looks next, then
it is accepted and waits on its merge — where an agent stops, never at done.

**A status is a :class:`Status`, never a string.** It is an ``Enum`` rather than a
``StrEnum`` so that mypy's strict equality refuses ``status == "done"``: a copied word is
a type error, and the word on disk is ``.value``, said in one place. What reaches a reader
is one of three *readings*, each a type the caller must handle:

- :class:`Status` — a word this build knows.
- :class:`Unknown` — a word it does not, perhaps a newer build's. It holds the step (never
  due, listed with Blocked, refused by Run Agent) and stays on disk untouched. Two new words
  cost no format bump for exactly this reason.
- :class:`Waiting` — a wait that is not over yet: derived by ``schedule.wait_status``,
  never stored.

**Readiness accepts :class:`Status` only** (``progression.py``); :func:`held` is how a
reading becomes one — an unknown word holds the step as blocked, a wait not over is still
pending. Transitions are not policed: the graph gates *launching*, not *recording*.

The three meanings of "done" are three functions: :func:`stored` (what the step says), the
composition root's ``_card_status`` (what its card wears: nothing for a step nobody works)
and its ``_status_in`` (what it reads on a given day, waits included).

**A status remembers two days** (format 2), the facts the Time tab dates work by:
``since``, the day it last changed, and ``started``, the day the step first went into any
worked status (:data:`WORKED`). Every write stamps them, so the window, the CLI and an
agent's launch all record them alike, and an undo restores them with the rest of the
entry. A step set back to pending keeps them — an entry with no ``status`` key, which reads
as pending — so a reopened step still knows when it first began.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, Final, assert_never

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step, StepId

MODULE_ID = "step_status"


class Status(Enum):
    """A status this build knows, in the order work moves through them; ``.value`` is the
    word on disk. ``PENDING`` first because it is the default."""

    PENDING = "pending"
    IN_PROGRESS = "in-progress"
    # The agent's work is finished and a person — or a reviewing agent — looks next.
    READY_FOR_REVIEW = "ready-for-review"
    # Accepted, and waiting on its merge.
    READY_TO_MERGE = "ready-to-merge"
    DONE = "done"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class Unknown:
    """A stored word this build cannot read — perhaps a newer build's. It holds the step."""

    word: str


@dataclass(frozen=True)
class Waiting:
    """A wait that is not over yet — a derived reading, never stored."""


# What a reader may be handed: a known status, a word this build cannot read, or a wait not over.
type Reading = Status | Unknown | Waiting

# Finished work a person has yet to land — its review, then its merge: past in progress, not done.
REVIEW_AND_MERGE: Final = frozenset({Status.READY_FOR_REVIEW, Status.READY_TO_MERGE})
# Somebody has worked on the step: the first write of any of these stamps ``started``.
WORKED: Final = frozenset({Status.IN_PROGRESS, *REVIEW_AND_MERGE})


def held(reading: Reading) -> Status:
    """A reading as readiness sees it: an unknown word holds the step as :attr:`~Status.BLOCKED`
    — reading it as pending would launch it again — and a wait not over is pending."""
    match reading:
        case Status():
            return reading
        case Unknown():
            return Status.BLOCKED
        case Waiting():
            return Status.PENDING
        case _:
            assert_never(reading)


def readiness_of(status_for: Callable[[Step], Reading]) -> Callable[[Step], Status]:
    """``status_for`` as readiness reads it — :func:`held` over every answer."""
    return lambda step: held(status_for(step))


def word(reading: Reading) -> str:
    """A reading as a word on its way out — ``--json``, a CSV, a report's class name:
    a status's own word, ``unknown`` or ``waiting``."""
    match reading:
        case Status():
            return reading.value
        case Unknown():
            return "unknown"
        case Waiting():
            return "waiting"
        case _:
            assert_never(reading)


def phrase(reading: Reading) -> str:
    """A reading as running text shows it: its hyphens as spaces (*ready for review*)."""
    return word(reading).replace("-", " ")


def label(status: Status) -> str:
    """A status as a menu entry: title case, with the small words kept small."""
    return " ".join(
        part if part in ("for", "to") else part.capitalize() for part in status.value.split("-")
    )


def no_status(kind: str) -> str:
    """Why a step nobody works — a wait, a branch cut; ``kind`` is what it is called — takes
    no status: what it holds is released by the calendar or by what it waits on, never by a
    claim."""
    return f"{kind} has no status: it is over when what it waits for is"


SINCE_KEY: Final = "since"
STARTED_KEY: Final = "started"


def _to_format_2(entry: dict[str, Any]) -> dict[str, Any]:
    """Format 2 adds the two days. A format-1 entry has neither, and nothing to derive them
    from: its days are unknown, which every reader takes as "not said", never as today.
    The bump is so an older build, whose ``write`` rebuilds the entry, knows it would drop
    them."""
    return entry


DATA_FORMAT = ModuleDataFormat(MODULE_ID, 2, (_to_format_2,))

# The origin the window's own "work started here" claim carries: no view claims it, so
# every surface treats the write as foreign and repaints — the launch stamp's pattern.
STARTED_ORIGIN: Final[object] = object()
# The origin a merge's "done" carries — the same pattern, for the fact GitHub reports.
MERGED_ORIGIN: Final[object] = object()


def stored(step: Step) -> Status | Unknown:
    """The status the step says it has — never an error.

    Three cases, kept apart: a known word reads as its :class:`Status`; no entry, or one
    with no ``status`` key, reads as pending (absence encodes the default); any other word
    — perhaps written by a newer build — reads as :class:`Unknown`. Reading that as pending
    would make the step due again, so it holds the step instead (:func:`held`), and the
    entry itself is left on disk untouched.
    """
    entry = step.module_data.get(MODULE_ID)
    found = entry.get("status") if entry else None
    if found is None:
        return Status.PENDING
    try:
        return Status(found)
    except ValueError:
        return Unknown(str(found))


def _known(entry: dict[str, Any] | None) -> Status:
    """The known status an entry carries, pending for none or a word this build cannot read."""
    try:
        return Status(entry.get("status") if entry else None)
    except ValueError:
        return Status.PENDING


def _day(entry: dict[str, Any] | None, key: str) -> date | None:
    try:
        return date.fromisoformat(entry[key]) if entry and entry.get(key) else None
    except (TypeError, ValueError):
        return None


def read_since(step: Step) -> date | None:
    """The day the step's status last changed; None where no write has said."""
    return _day(step.module_data.get(MODULE_ID), SINCE_KEY)


def read_started(step: Step) -> date | None:
    """The day the step first went into a worked status; None where it never did, or no
    write said."""
    return _day(step.module_data.get(MODULE_ID), STARTED_KEY)


def write(status: Status, *, today: date, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """The entry to store, with its days: ``previous`` is the entry it replaces.

    ``since`` moves to ``today`` when the status does and stands while it is repeated;
    ``started`` is set the first time the step goes into a worked status and kept from then
    on. Pending with nothing to remember gives ``{}``, which removes the file.
    """
    was = _known(previous)
    since = _day(previous, SINCE_KEY) if status == was else today
    started = _day(previous, STARTED_KEY) or (today if status in WORKED else None)
    entry: dict[str, Any] = {} if status is Status.PENDING else {"status": status.value}
    if since is not None:
        entry[SINCE_KEY] = since.isoformat()
    if started is not None:
        entry[STARTED_KEY] = started.isoformat()
    return stamped(entry, DATA_FORMAT.version) if entry else {}


def status_command(
    step: Step, status: Status, *, today: date, view_origin: object = None, label: str = ""
) -> SetModuleDataCommand:
    """The command that sets ``step``'s status, its days stamped from the entry it replaces
    — what the Status verbs, ``status set``, the launch's claim and the review verbs all
    write through."""
    entry = write(status, today=today, previous=step.module_data.get(MODULE_ID))
    return SetModuleDataCommand(step.id, MODULE_ID, entry, view_origin=view_origin, label=label)


def record_started(library: Library, step_id: StepId, today: date) -> bool:
    """Work on the step just began: claim ``in-progress`` — directly, off the undo stack.

    The claim rides on something nobody can undo — a detached agent shell now exists — so
    it is applied the way that launch is stamped (``step_agent_run``'s ``record_launch``
    has the reasoning): an undo entry here would let Ctrl+Z file the step as pending while
    an agent is still working in it. False, and no write, when the step is gone or already
    claims to be in progress.
    """
    if not library.has(step_id) or stored(library.step(step_id)) is Status.IN_PROGRESS:
        return False
    step = library.step(step_id)
    status_command(step, Status.IN_PROGRESS, today=today, view_origin=STARTED_ORIGIN).redo(library)
    return True


def record_merged(
    library: Library, step_id: StepId, today: date, *, accepted_by_merge: bool = False
) -> bool:
    """The step's PR reads merged: a step waiting on its merge is ``done`` — directly, off
    the undo stack, like the PR state it follows (``ARCHITECTURE.md``'s *Syncing an
    external fact*): Ctrl+Z must not file a merged step as still waiting on its merge. False,
    and no write, when the step is gone or is not waiting on its merge — a merged PR says
    nothing about a step nobody has accepted — unless ``accepted_by_merge``: a PR merged
    into the feature branch a step is on is the acceptance, and the branch's review comes
    when it lands, so a step still under review is done by that merge too.
    """
    accepting = REVIEW_AND_MERGE if accepted_by_merge else {Status.READY_TO_MERGE}
    if not library.has(step_id) or stored(library.step(step_id)) not in accepting:
        return False
    step = library.step(step_id)
    status_command(step, Status.DONE, today=today, view_origin=MERGED_ORIGIN).redo(library)
    return True


def forget_days_for_paste(
    _project: Project, steps: Sequence[Step], _remapped: Mapping[StepId, StepId]
) -> None:
    """A copied step keeps its status but not the days it was said on — the paste policy
    this module hands in. The copy did not start or change on the original's days; its days
    are unknown until somebody writes one, and an entry left with nothing goes."""
    for step in steps:
        entry = step.module_data.get(MODULE_ID)
        if not entry:
            continue
        kept = {key: value for key, value in entry.items() if key not in (SINCE_KEY, STARTED_KEY)}
        if kept.get("status"):
            step.module_data[MODULE_ID] = kept
        else:
            step.module_data.pop(MODULE_ID, None)


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when the step is simply pending."""
    status = stored(step)
    return "" if status is Status.PENDING else phrase(status)


# Last, because it names the pieces above: the one declaration everything reads.
SPEC = AspectSpec(
    id=MODULE_ID,
    label="Status",
    summary="Where a step stands: pending, in-progress, ready-for-review, ready-to-merge,"
    " done, or blocked.",
    data_format=DATA_FORMAT,
    phrase=summary,
)
