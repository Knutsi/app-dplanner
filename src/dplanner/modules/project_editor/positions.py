"""Where a step's node sits on the canvas.

This is the first module data in DPlanner that is **not an aspect**, and the distinction is
worth keeping sharp. An aspect is a fact about the work — an estimate, a ticket — and it
appears in ``dplanner aspect list`` because an agent may want to write one. A position is
presentation: it says nothing about the plan and nothing should reason about it.

It is stored per step rather than as one map on the project so that moving a node is a
one-file diff, which is the same reason ordering lives in the parent's list rather than in
filename prefixes (``FORMAT.md``).

**Qt-free**, because the composition root reaches this file when it builds the CLI's
migration list — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from typing import Any

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.model import Step

MODULE_ID = "project_editor"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)

# Positions snap to this, which keeps a hand-arranged graph tidy and the JSON short.
GRID = 8.0


def read_position(step: Step) -> tuple[float, float] | None:
    """Where this step was left, or None if nobody has moved it."""
    entry = step.module_data.get(MODULE_ID)
    if not entry:
        return None
    x, y = entry.get("x"), entry.get("y")
    if isinstance(x, bool) or isinstance(y, bool):
        return None
    if not isinstance(x, int | float) or not isinstance(y, int | float):
        return None
    return float(x), float(y)


def write_position(x: float, y: float) -> dict[str, Any]:
    """The entry to store, snapped to the grid.

    Coerced to ``float`` like every number that reaches disk: an int would write as ``8``
    where a reloaded float writes as ``8.0``, making the file's bytes depend on whether the
    workspace had been reopened. ``FORMAT.md`` states the rule; ``estimation`` is the
    other place that owes it.
    """
    return stamped(
        {"x": float(round(x / GRID) * GRID), "y": float(round(y / GRID) * GRID)},
        DATA_FORMAT.version,
    )
