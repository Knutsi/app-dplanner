"""The estimation aspect: its format, and the one place its shape is written down.

``read`` and ``write`` are what the CLI verb, the future GUI card and the exporter all call,
so the shape of an estimate exists once rather than once per caller.

**Numbers are coerced here.** ``FORMAT.md``'s normalisation rule used to be enforced at the
model boundary, because an ``int`` writes as ``5`` where a reloaded ``float`` writes as
``5.0`` — making a file's bytes depend on whether the workspace had been reopened since it
was written. Module data is opaque to the model and ``stamped()`` writes whatever dict it is
handed, so that duty belongs to whoever owns the number. This is that owner.
"""

from dataclasses import dataclass
from typing import Any

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Step

MODULE_ID = "step_estimation"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)

CONFIDENCES = ("low", "medium", "high")

SPEC = AspectSpec(
    id=MODULE_ID,
    label="Estimate",
    summary="How many days a step is thought to take, and how sure that is.",
    data_format=DATA_FORMAT,
)


@dataclass(frozen=True)
class Estimate:
    days: float
    confidence: str = ""


def read(step: Step) -> Estimate | None:
    """The step's estimate, or None. Unreadable data reads as absent, never as zero.

    "We have not estimated this" and "this is free" are different claims, and a planner that
    confuses them understates every total it prints.
    """
    entry = step.module_data.get(MODULE_ID)
    if not entry:
        return None
    days = entry.get("days")
    if isinstance(days, bool) or not isinstance(days, int | float):
        return None
    confidence = entry.get("confidence")
    return Estimate(days=float(days), confidence=confidence if confidence in CONFIDENCES else "")


def write(estimate: Estimate | None) -> dict[str, Any]:
    """The entry to store. ``None`` gives ``{}``, which removes the file."""
    if estimate is None:
        return {}
    entry: dict[str, Any] = {"days": float(estimate.days)}
    if estimate.confidence in CONFIDENCES:
        entry["confidence"] = estimate.confidence
    return stamped(entry, DATA_FORMAT.version)


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when there is nothing to say."""
    estimate = read(step)
    if estimate is None:
        return ""
    days = f"{estimate.days:g}d"
    return f"{days} ({estimate.confidence})" if estimate.confidence else days
