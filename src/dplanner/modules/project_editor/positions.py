"""Where a step's node sits on the canvas, and how big it is.

This is the first module data in DPlanner that is **not an aspect**, and the distinction is
worth keeping sharp. An aspect is a fact about the work — an estimate, a ticket — and it
appears in ``dplanner aspect list`` because an agent may want to write one. A position is
presentation: it says nothing about the plan and nothing should reason about it.

It is stored per step rather than as one map on the project so that moving a node is a
one-file diff, which is the same reason ordering lives in the parent's list rather than in
filename prefixes (``FORMAT.md``).

**A size lives in the same entry, and absence is the default footprint.** A card somebody
dragged wider or taller keeps ``w`` and ``h`` beside its ``x`` and ``y``; every other card
is :data:`NODE_W` by :data:`NODE_H`, and nothing is written to say so. A size that comes
back to the default drops its keys again, so a project of untouched cards never learns the
keys exist (``FORMAT.md``'s absence rule).

**Snapping is the gesture's, never the write's.** What reaches disk is rounded to a whole
unit — short JSON, and a float — and lands on :data:`GRID` only because the canvas snapped
the drag, the resize or the click while *Snap to Grid* was on. A CLI verb has no gesture
and stores what it was given; a sort's output is what the algorithm computed — ``tidy``
computes on the grid — and ``layout shift``, a drag by a distance, snaps that distance
the way the drag would.

**Qt-free**, because the composition root reaches this file when it builds the CLI's
migration list — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from typing import Any, TypeGuard

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.model import Project, Step

MODULE_ID = "project_editor"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)

# The canvas's snap pitch: a drag, a resize or a placement lands on it while Snap to Grid is
# on, which keeps a hand-arranged graph tidy. The ground's dots and lines are drawn on a
# multiple of it (grid.py), so what snaps and what is seen agree.
GRID = 8.0

# A node's footprint. It lives here rather than in items.py so the Qt-free sort algorithms
# can default to it; the canvas imports it back. Sized for a two-line title over one line
# of detail; pairs with sorts' gaps to keep round pitches — a change here owes one there.
NODE_W = 220.0
NODE_H = 76.0
# No card smaller than this on either side: room for a row of medallions across the top
# and for one line of title over the detail line. Both on the grid, so a card resized down
# to its minimum still sits on it.
MIN_NODE_W = 144.0
MIN_NODE_H = 64.0

type Size = tuple[float, float]


def snapped(value: float, grid: float = 1.0) -> float:
    """``value`` on a pitch, as the float every number that reaches disk owes.

    A whole unit by default — what every coordinate is rounded to on its way to disk. The
    canvas passes :data:`GRID` for the gestures it snaps.
    """
    return float(round(value / grid) * grid)


def centred_on(x: float, y: float) -> tuple[float, float]:
    """A node's top-left, given the point it should sit centred on.

    One implementation because two gestures place a node by pointing at a spot — a
    double-click on empty canvas, and New from a menu opened there — and a node that
    appeared half a width off in one of them would read as a bug. A placed node is born at
    the default footprint, so that is what it is centred by.
    """
    return x - NODE_W / 2, y - NODE_H / 2


def read_position(step: Step) -> tuple[float, float] | None:
    """Where this step was left, or None if nobody has moved it."""
    entry = step.module_data.get(MODULE_ID)
    if not entry:
        return None
    x, y = entry.get("x"), entry.get("y")
    if not _is_number(x) or not _is_number(y):
        return None
    return float(x), float(y)


def read_size(step: Step) -> Size | None:
    """How big this step's card was made, or None for the default footprint."""
    entry = step.module_data.get(MODULE_ID)
    if not entry:
        return None
    w, h = entry.get("w"), entry.get("h")
    if not _is_number(w) or not _is_number(h):
        return None
    return max(MIN_NODE_W, float(w)), max(MIN_NODE_H, float(h))


def node_size(step: Step) -> Size:
    """The card's footprint: what was stored, else the default. The sorts space by this."""
    return read_size(step) or (NODE_W, NODE_H)


def write_position(x: float, y: float, size: Size | None = None) -> dict[str, Any]:
    """The entry to store: the position, and the size when it is not the default.

    Coerced to ``float`` like every number that reaches disk: an int would write as ``8``
    where a reloaded float writes as ``8.0``, making the file's bytes depend on whether the
    workspace had been reopened. ``FORMAT.md`` states the rule; ``estimation`` is the
    other place that owes it. A caller moving a card hands its current size back in, so
    a move never shrinks a card somebody made larger.
    """
    entry = {"x": snapped(x), "y": snapped(y)}
    if size is not None and size != (NODE_W, NODE_H):
        entry["w"] = max(MIN_NODE_W, snapped(size[0]))
        entry["h"] = max(MIN_NODE_H, snapped(size[1]))
    return stamped(entry, DATA_FORMAT.version)


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


def _is_number(value: object) -> TypeGuard[int | float]:
    return not isinstance(value, bool) and isinstance(value, int | float)
