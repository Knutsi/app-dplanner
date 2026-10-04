"""The estimate: its format, the one place its shape is written down, and a project's start.

``read`` and ``write`` are what the CLI verb, the panel editor and every report call, so the
shape of an estimate exists once rather than once per caller. There is one field, so there is
no dataclass around it: ``read`` returns the days, and it is the default every derivation in
:mod:`dplanner.planning.schedule` reads — a caller passes another ``days_for`` only when it
means something else (calendar days stretched by efficiency, the simulator's world).

**Planning owns it** because the schedule, the critical path and progress all interpret it;
``modules/estimation/`` keeps the editors and the verbs. The id stays ``estimation``.

**Numbers are coerced here.** ``FORMAT.md``'s normalisation rule used to be enforced at the
model boundary, because an ``int`` writes as ``5`` where a reloaded ``float`` writes as
``5.0`` — making a file's bytes depend on whether the workspace had been reopened since it
was written. Module data is opaque to the model and ``stamped()`` writes whatever dict it is
handed, so that duty belongs to whoever owns the number. This is that owner.

**An estimate remembers what it was.** Reviewing how a plan grew needs to know that S7
was 3 days until the 12th and 5 after — so ``write`` carries a ``history`` beside the
number: the value that stood at the start of each day on which it changed, one row per
day (a second change on the same day keeps that day's first row, the same last-wins
rule the progress history keeps). Only the days a value *changed* are written, and only
when the writer hands over the entry it is replacing; nothing is derived from it, it is
read back by ``dplanner estimate show`` and the change report ``progress show`` prints.
Format 2 for the key, so an older build refuses to rewrite the entry rather than dropping
the history on its next write.

**This module used to be ``step_estimation``.** It became ``estimation`` when it grew a
project's start date and the schedule over both, so the old id is retired and its data taken
over here — the on-disk id was always the contract between the two, which is why a rename
needs no module to import another. The takeover is also what drops the ``confidence`` field
the aspect used to carry: it rebuilds an entry from ``days`` alone.
"""

from datetime import date
from typing import Any

from dplanner.core.module_data import ModuleDataFormat, Takeover, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Project, Step

MODULE_ID = "estimation"
HISTORY_KEY = "history"
START_KEY = "start"

# What ``step_estimation`` last wrote. Frozen at format 1 forever, whatever this module does
# next: it is the retired schema's history, and history does not gain entries.
RETIRED_STEP_ESTIMATION = ModuleDataFormat("step_estimation")


def _days_in(entry: dict[str, Any]) -> float | None:
    """The readable ``days`` of an entry, or None. Shared by ``read`` and the takeover.

    An opted-out entry carries no ``days`` and so reads as unestimated, which is what every
    total already knows how to skip.
    """
    days = entry.get("days")
    if isinstance(days, bool) or not isinstance(days, int | float):
        return None
    return float(days)


def _from_step_estimation(retired: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    """A ``step_estimation`` entry as an ``estimation`` one.

    Rebuilt from ``days`` alone, which is how the retired ``confidence`` field leaves without
    a migration of its own. An entry that never had a readable ``days`` had nothing to say,
    and ``{}`` leaves no file behind.

    It must return data in *this* module's current shape: the engine stamps the result with
    ``DATA_FORMAT.version`` and does not run our own migration chain over it.
    """
    days = _days_in(retired)
    kept = dict(existing)
    return kept if days is None else kept | {"days": days}


def _to_format_2(data: dict[str, Any]) -> dict[str, Any]:
    """Format 1 shapes are valid format 2 shapes: the bump exists for the ``history`` key,
    so an older build refuses to rewrite an entry rather than dropping it."""
    return dict(data)


DATA_FORMAT = ModuleDataFormat(
    MODULE_ID,
    2,
    (_to_format_2,),
    takeovers=(Takeover(retired=RETIRED_STEP_ESTIMATION, convert=_from_step_estimation),),
)


def read(step: Step) -> float | None:
    """How many days the step is estimated at, or None. Unreadable data reads as absent.

    Never as zero: "we have not estimated this" and "this is free" are different claims, and
    a planner that confuses them understates every total it prints.
    """
    entry = step.module_data.get(MODULE_ID)
    return None if not entry else _days_in(entry)


def enabled(step: Step) -> bool:
    """Whether this step is sized at all — the Type toggle's answer.

    **Absence means on**, which is the opposite of a ticket or a check and is the honest
    default: most steps are work, and work has a size. So the stored marker records the
    *exception* — a milestone, which has no work of its own — and every step written before
    this aspect became toggleable keeps its block with no data change and no migration.
    ``FORMAT.md``'s rule is that absence encodes the default; here the default is yes.
    """
    entry = step.module_data.get(MODULE_ID)
    return not (entry and entry.get("off"))



def is_marker(step: Step) -> bool:
    """A step that carries no work by design — its estimate turned off: a milestone's own
    step, a feature, a check. The schedule lands it the moment what it requires has."""
    return not enabled(step)

def read_history(step: Step) -> list[tuple[date, float]]:
    """The values the estimate had before, each with the day it was replaced on, oldest
    first. Unreadable rows read as absent."""
    entry = step.module_data.get(MODULE_ID) or {}
    return _history_in(entry)


def _history_in(entry: dict[str, Any]) -> list[tuple[date, float]]:
    raw = entry.get(HISTORY_KEY)
    if not isinstance(raw, list):
        return []
    found: list[tuple[date, float]] = []
    for row in raw:
        if not isinstance(row, dict) or not isinstance(row.get("day"), str):
            continue
        was = _days_in(row)
        try:
            when = date.fromisoformat(row["day"])
        except ValueError:
            continue
        if was is not None:
            found.append((when, was))
    return found


def write(
    days: float | None,
    *,
    on: bool = True,
    previous: dict[str, Any] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """The entry to store.

    Three cases: sized writes the number; on but unsized gives ``{}``, which removes the
    file and leaves the aspect on by absence; off writes the opt-out marker. ``previous``
    is the entry being replaced: its history rides along, and a value it held that
    differs from ``days`` joins the history under today — the first change of a day
    only, so a day's row is the value that stood when the day began.
    """
    if not on:
        return stamped({"off": True}, DATA_FORMAT.version)
    if days is None:
        return {}  # Unsized is unsized: nothing to remember it by, and no file.
    history = _history_in(previous) if previous else []
    was = _days_in(previous) if previous else None
    when = today or date.today()
    if was is not None and was != days and not any(day == when for day, _ in history):
        history.append((when, was))
    entry: dict[str, Any] = {"days": float(days)}
    if history:
        entry[HISTORY_KEY] = [{"day": day.isoformat(), "days": float(was)} for day, was in history]
    return stamped(entry, DATA_FORMAT.version)


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when there is nothing to say."""
    days = read(step)
    return "" if days is None else f"{days:g}d"


def read_start(project: Project) -> date | None:
    """When the project starts, or None. Anything unreadable reads as unset.

    **The start date lives under this aspect's id on the project node** —
    ``projects/<p>/modules/estimation.json`` = ``{"start": "2026-09-01"}``, beside each
    step's ``{"days": 3.0}``. One id, one data namespace, two node kinds, so whoever writes a
    migration for :data:`DATA_FORMAT` owes both shapes a thought. It is deliberately not part
    of :data:`SPEC`: an aspect is a fact about a step, and this is a fact about a project.
    """
    entry = project.module_data.get(MODULE_ID)
    if not entry:
        return None
    written = entry.get(START_KEY)
    if not isinstance(written, str):
        return None
    try:
        return date.fromisoformat(written)
    except ValueError:
        return None


def start_of(project: Project, today: date | None = None) -> date:
    """When this project's work begins: the date somebody set, or today.

    **Derived, never written.** Storing today would make merely opening a tab dirty the
    workspace — ``ordering.py``'s rule again — and it would be wrong by tomorrow. So a
    project nobody has dated answers "if you start now", every surface asks this rather than
    ``read_start``, and the only thing on disk is a date a person chose.

    ``today`` is the caller's clock (``core/clock.py``) — the Time tab's, which a test or
    the simulator may have pinned; a surface that holds no clock yet gets the machine's.
    """
    return read_start(project) or today or date.today()


def write_start(start: date | None) -> dict[str, Any]:
    """The project entry to store. ``None`` gives ``{}``, which removes the file — and
    puts the project back on "starts today"."""
    if start is None:
        return {}
    return stamped({START_KEY: start.isoformat()}, DATA_FORMAT.version)


# Last, because it names the pieces above: the one declaration everything reads.
SPEC = AspectSpec(
    id=MODULE_ID,
    label="Estimate",
    summary="How many working days a step is thought to take.",
    data_format=DATA_FORMAT,
    phrase=summary,
)
