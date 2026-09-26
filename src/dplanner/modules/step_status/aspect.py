"""The status aspect: its vocabulary, and the one place its shape is written down.

A step's status is a claim only a person or an agent can make — the graph can say what is
*ready*, but not what is finished or stuck, which is why this is stored rather than derived.
The vocabulary is deliberately small: ``pending`` is the default and encoded as absence
(FORMAT.md: absence encodes the default), so a step that was never anything else has no
file. ``blocked`` earns its place as the one state the graph cannot see — an external
blockage is a fact from outside the plan.

**A status remembers two days** (format 2), the facts the Time tab dates work by:
``since``, the day it last changed, and ``started``, the day the step first went in
progress. Every write stamps them, so the window, the CLI and an agent's launch all record
them alike, and an undo restores them with the rest of the entry. A step set back to
pending keeps them — an entry with no ``status`` key, which reads as pending — so a
reopened step still knows when it first began.
"""

from collections.abc import Sequence
from datetime import date
from typing import Any, Final

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step, StepId

MODULE_ID = "step_status"

IN_PROGRESS: Final = "in-progress"

# In the order work moves through them. "pending" first because it is the default.
STATUSES: Final = ("pending", IN_PROGRESS, "done", "blocked")

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
    return status if status in STATUSES else "pending"


def _day(entry: dict[str, Any] | None, key: str) -> date | None:
    try:
        return date.fromisoformat(entry[key]) if entry and entry.get(key) else None
    except (TypeError, ValueError):
        return None


def read_since(step: Step) -> date | None:
    """The day the step's status last changed; None where no write has said."""
    return _day(step.module_data.get(MODULE_ID), SINCE_KEY)


def read_started(step: Step) -> date | None:
    """The day the step first went in progress; None where it never did, or no write said."""
    return _day(step.module_data.get(MODULE_ID), STARTED_KEY)


def write(status: str, *, today: date, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """The entry to store, with its days: ``previous`` is the entry it replaces.

    ``since`` moves to ``today`` when the status does and stands while it is repeated;
    ``started`` is set the first time the step goes in progress and kept from then on.
    Pending with nothing to remember gives ``{}``, which removes the file.
    """
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r} (one of {', '.join(STATUSES)})")
    was = previous.get("status") if previous else None
    was = was if was in STATUSES else "pending"
    since = _day(previous, SINCE_KEY) if status == was else today
    started = _day(previous, STARTED_KEY) or (today if status == IN_PROGRESS else None)
    entry: dict[str, Any] = {} if status == "pending" else {"status": status}
    if since is not None:
        entry[SINCE_KEY] = since.isoformat()
    if started is not None:
        entry[STARTED_KEY] = started.isoformat()
    return stamped(entry, DATA_FORMAT.version) if entry else {}


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
    previous = library.step(step_id).module_data.get(MODULE_ID)
    entry = write(IN_PROGRESS, today=today, previous=previous)
    SetModuleDataCommand(step_id, MODULE_ID, entry, view_origin=STARTED_ORIGIN).redo(library)
    return True


def forget_days_for_paste(_project: Project, steps: Sequence[Step]) -> None:
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
    status = read(step)
    return "" if status == "pending" else status.replace("-", " ")


# Last, because it names the pieces above: the one declaration everything reads.
SPEC = AspectSpec(
    id=MODULE_ID,
    label="Status",
    summary="Where a step stands: pending, in-progress, done, or blocked.",
    data_format=DATA_FORMAT,
    phrase=summary,
)
