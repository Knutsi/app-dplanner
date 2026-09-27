"""The status aspect: its vocabulary, and the one place its shape is written down.

A step's status is a claim only a person or an agent can make — the graph can say what is
*ready*, but not what is finished or stuck, which is why this is stored rather than derived.
The vocabulary is deliberately small: ``pending`` is the default and encoded as absence
(FORMAT.md: absence encodes the default), so a step that was never anything else has no
file. ``blocked`` earns its place as the one state the graph cannot see — an external
blockage is a fact from outside the plan. ``ready-for-review`` and ``ready-to-merge`` sit
between in progress and done: an agent's work is finished and somebody looks next, then
it is accepted and waits on its merge — where an agent stops, never at done.

The words are the progression walk's (``domain/progression.py``), imported rather than
copied, so the derivation and the store cannot disagree about one. Two new words cost no
format bump: an older build reads a word it does not know as pending and leaves it on
disk (:func:`read`).

**A status remembers two days** (format 2), the facts the Time tab dates work by:
``since``, the day it last changed, and ``started``, the day the step first went into any
worked status (:data:`WORKED`). Every write stamps them, so the window, the CLI and an
agent's launch all record them alike, and an undo restores them with the rest of the
entry. A step set back to pending keeps them — an entry with no ``status`` key, which reads
as pending — so a reopened step still knows when it first began.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Final

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.progression import (
    BLOCKED,
    DONE,
    IN_PROGRESS,
    READY_FOR_REVIEW,
    READY_TO_MERGE,
    REVIEW_AND_MERGE,
    phrase,
)

MODULE_ID = "step_status"

PENDING: Final = "pending"

# In the order work moves through them. "pending" first because it is the default.
STATUSES: Final = (PENDING, IN_PROGRESS, READY_FOR_REVIEW, READY_TO_MERGE, DONE, BLOCKED)
# Somebody has worked on the step: the first write of any of these stamps ``started``.
WORKED: Final = (IN_PROGRESS, *REVIEW_AND_MERGE)
# A wait (``step_wait``) has none: what it holds is released by the calendar, not by a claim.
NO_STATUS_ON_A_WAIT: Final = "a wait has no status: it is over when its day comes"

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


def read(step: Step) -> str:
    """The step's status. Absent or unreadable data reads as ``pending``, never as an error.

    An unknown word — perhaps written by a newer build — is also read as ``pending``: this
    build cannot act on a state it does not know, but it must not crash over one either.
    The unknown entry itself is left on disk untouched.
    """
    entry = step.module_data.get(MODULE_ID)
    status = entry.get("status") if entry else None
    return status if status in STATUSES else PENDING


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


def write(status: str, *, today: date, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """The entry to store, with its days: ``previous`` is the entry it replaces.

    ``since`` moves to ``today`` when the status does and stands while it is repeated;
    ``started`` is set the first time the step goes into a worked status and kept from then
    on. Pending with nothing to remember gives ``{}``, which removes the file.
    """
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r} (one of {', '.join(STATUSES)})")
    was = previous.get("status") if previous else None
    was = was if was in STATUSES else PENDING
    since = _day(previous, SINCE_KEY) if status == was else today
    started = _day(previous, STARTED_KEY) or (today if status in WORKED else None)
    entry: dict[str, Any] = {} if status == PENDING else {"status": status}
    if since is not None:
        entry[SINCE_KEY] = since.isoformat()
    if started is not None:
        entry[STARTED_KEY] = started.isoformat()
    return stamped(entry, DATA_FORMAT.version) if entry else {}


def status_command(
    step: Step, status: str, *, today: date, view_origin: object = None, label: str = ""
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
    if not library.has(step_id) or read(library.step(step_id)) == IN_PROGRESS:
        return False
    step = library.step(step_id)
    status_command(step, IN_PROGRESS, today=today, view_origin=STARTED_ORIGIN).redo(library)
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


def label(status: str) -> str:
    """A status as a menu entry: title case, with the small words kept small."""
    return " ".join(
        word if word in ("for", "to") else word.capitalize() for word in status.split("-")
    )


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when the step is simply pending."""
    status = read(step)
    return "" if status == PENDING else phrase(status)


# Last, because it names the pieces above: the one declaration everything reads.
SPEC = AspectSpec(
    id=MODULE_ID,
    label="Status",
    summary="Where a step stands: pending, in-progress, ready-for-review, ready-to-merge,"
    " done, or blocked.",
    data_format=DATA_FORMAT,
    phrase=summary,
)
