"""The estimate aspect: its format, and the one place its shape is written down.

``read`` and ``write`` are what the CLI verb, the panel editor and every report call, so the
shape of an estimate exists once rather than once per caller. There is one field, so there is
no dataclass around it: ``read`` returns the days, which makes it exactly the ``days_for``
function :mod:`dplanner.domain.schedule` asks for, with no adapter in between.

**Numbers are coerced here.** ``FORMAT.md``'s normalisation rule used to be enforced at the
model boundary, because an ``int`` writes as ``5`` where a reloaded ``float`` writes as
``5.0`` — making a file's bytes depend on whether the workspace had been reopened since it
was written. Module data is opaque to the model and ``stamped()`` writes whatever dict it is
handed, so that duty belongs to whoever owns the number. This is that owner.

**This module used to be ``step_estimation``.** It became ``estimation`` when it grew a
project's start date and the schedule over both, so the old id is retired and its data taken
over here — the on-disk id was always the contract between the two, which is why a rename
needs no module to import another. The takeover is also what drops the ``confidence`` field
the aspect used to carry: it rebuilds an entry from ``days`` alone.
"""

from typing import Any

from dplanner.core.module_data import ModuleDataFormat, Takeover, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Step

MODULE_ID = "estimation"

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


DATA_FORMAT = ModuleDataFormat(
    MODULE_ID,
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


def write(days: float | None, *, on: bool = True) -> dict[str, Any]:
    """The entry to store.

    Three cases: sized writes the number; on but unsized gives ``{}``, which removes the
    file and leaves the aspect on by absence; off writes the opt-out marker.
    """
    if not on:
        return stamped({"off": True}, DATA_FORMAT.version)
    if days is None:
        return {}
    return stamped({"days": float(days)}, DATA_FORMAT.version)


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when there is nothing to say."""
    days = read(step)
    return "" if days is None else f"{days:g}d"


# Last, because it names the pieces above: the one declaration everything reads.
SPEC = AspectSpec(
    id=MODULE_ID,
    label="Estimate",
    summary="How many working days a step is thought to take.",
    data_format=DATA_FORMAT,
    phrase=summary,
)
