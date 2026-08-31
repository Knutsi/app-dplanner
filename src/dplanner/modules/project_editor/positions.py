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
from dplanner.domain.model import Project, Step

MODULE_ID = "project_editor"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)

# Positions snap to this, which keeps a hand-arranged graph tidy and the JSON short.
GRID = 8.0

# A node's footprint. It lives here rather than in items.py so the Qt-free sort algorithms
# can default to it; the canvas imports it back. Sized for a two-line title over one line
# of detail; pairs with sorts' gaps to keep round pitches — a change here owes one there.
NODE_W = 220.0
NODE_H = 76.0


def snapped(value: float) -> float:
    """A coordinate on the grid, as the float every number that reaches disk owes."""
    return float(round(value / GRID) * GRID)


def centred_on(x: float, y: float) -> tuple[float, float]:
    """A node's top-left, given the point it should sit centred on.

    One implementation because two gestures place a node by pointing at a spot — a
    double-click on empty canvas, and New from a menu opened there — and a node that
    appeared half a width off in one of them would read as a bug.
    """
    return x - NODE_W / 2, y - NODE_H / 2


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
    return stamped({"x": snapped(x), "y": snapped(y)}, DATA_FORMAT.version)


def entry_with(project: Project, key: str, value: Any) -> dict[str, Any]:
    """The project-level entry with one key replaced, the other keys carried untouched.

    The named layouts and the regions share ``projects/<p>/modules/project_editor.json``,
    and this is what lets each be written without knowing the other's shape. An empty value
    drops its key, and ``stamped`` turns a bare entry into ``{}``, which deletes the file.
    """
    entry = {
        k: v
        for k, v in (project.module_data.get(MODULE_ID) or {}).items()
        if k not in (key, "format")
    }
    if value:
        entry[key] = value
    return stamped(entry, DATA_FORMAT.version)
