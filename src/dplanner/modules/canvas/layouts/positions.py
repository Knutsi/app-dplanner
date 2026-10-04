"""Where a step's node sits on the canvas, how big it is, and which stack it stands in.

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

**A stack member says which stack it stands in, and only the first stores a seat.** A step
in a stack keeps ``"stack": "<id>"`` in the same entry; the first member's ``x`` and ``y``
are the stack's, and the others keep no seat of their own — the column derives theirs
(``stacks/stack.py``, and ``ARCHITECTURE.md``'s *A stack is presentation over a chain*). Every
writer here carries the key, since a write rebuilds the whole entry.

**Snapping is the gesture's, never the write's.** What reaches disk is rounded to a whole
unit — short JSON, and a float — and lands on :data:`GRID` only because the canvas snapped
the drag, the resize or the click while *Snap to Grid* was on. A CLI verb has no gesture
and stores what it was given; a sort's output is what the algorithm computed — ``tidy``
computes on the grid — and ``layout shift``, a drag by a distance, snaps that distance
the way the drag would.

**Qt-free**, because the composition root reaches this file when it builds the CLI's
migration list — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from collections.abc import Callable, Container
from typing import Any, TypeGuard

from dplanner.core.module_data import ModuleDataFormat, migrated, stamped
from dplanner.domain.model import Project, Step, StepId

MODULE_ID = "project_editor"


def _drop_regions(data: dict[str, Any]) -> dict[str, Any]:
    """Format 1 → 2: regions are retired.

    Format 1 kept titled rectangles beside the project, ``"regions": [...]``, and every
    named layout snapshotted their rects beside the steps' seats. A rectangle the graph
    knew nothing about went stale with every sort, tidy and move, so both go — and a
    project saved with them opens exactly as it was, minus the rectangles. A step's entry
    never carried either key and passes through.
    """
    kept = {key: value for key, value in data.items() if key != "regions"}
    layouts = kept.get("layouts")
    if isinstance(layouts, dict):
        kept["layouts"] = {
            name: {k: v for k, v in body.items() if k != "regions"}
            if isinstance(body, dict)
            else body
            for name, body in layouts.items()
        }
    return kept


def _stack_key(data: dict[str, Any]) -> dict[str, Any]:
    """Format 2 → 3: nothing changes. Format 3 is a stack member's ``"stack"`` key, which a
    format-2 writer drops from any card it moves, because it rebuilds the entry from the
    seat and the size — so the number changes to say so (``FORMAT.md``'s rule)."""
    return data


DATA_FORMAT = ModuleDataFormat(MODULE_ID, version=3, migrations=(_drop_regions, _stack_key))
# The key a stack member's entry names its stack under.
STACK_KEY = "stack"

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
# to its minimum still sits on it. The width also leaves the narrowest title its room past
# the key block (``KEY_BLOCK_W``), rounded up to the grid.
MIN_NODE_W = 176.0
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
    """The card's body: what was stored, else the default. The sorts space by this, through
    :func:`footprint` when a card may wear a strip under it."""
    return read_size(step) or (NODE_W, NODE_H)


def default_size(_step: Step) -> Size:
    """Every card at the default footprint, whatever was stored — Wave view's measure, where
    a stored size applies only in Free view."""
    return (NODE_W, NODE_H)


# A card whose work is on a feature branch wears the branch's name in a strip under its
# body, this tall. The strip is part of the card — its shadow, its ring, what a click and a
# lasso hit, the room a sort leaves — while arrows still meet the body's middle.
STRIP_H = 16.0


def footprint(step: Step, strip: bool, body: Callable[[Step], Size] = node_size) -> Size:
    """What a card takes on the plane: its ``body`` — the stored size, else the default; a
    view that draws every card at the default hands its own — and the strip under it when
    it wears one. The one rule every arranger and the canvas measure a card by."""
    w, h = body(step)
    return (w, h + STRIP_H) if strip else (w, h)


def footprints(
    strips: Container[StepId], body: Callable[[Step], Size] = node_size
) -> Callable[[Step], Size]:
    """:func:`footprint` for a project whose cards in ``strips`` wear one — the ``size_for``
    a sort, a stack's column and the canvas are handed."""
    return lambda step: footprint(step, step.id in strips, body)


def read_stack(step: Step) -> str:
    """The id of the stack this step stands in, or "" for none."""
    entry = step.module_data.get(MODULE_ID)
    stack = entry.get(STACK_KEY) if entry else None
    return stack if isinstance(stack, str) else ""


def write_position(
    x: float, y: float, size: Size | None = None, *, stack: str = ""
) -> dict[str, Any]:
    """The entry to store: the position, the size when it is not the default, and the stack
    the card stands first in, if any.

    Coerced to ``float`` like every number that reaches disk: an int would write as ``8``
    where a reloaded float writes as ``8.0``, making the file's bytes depend on whether the
    workspace had been reopened. ``FORMAT.md`` states the rule; ``estimation`` is the
    other place that owes it. A caller moving a card hands its current size and stack back
    in, so a move never shrinks a card somebody made larger or takes it out of its stack.
    """
    return _entry({"x": snapped(x), "y": snapped(y)}, size, stack)


def write_member(stack: str, size: Size | None = None) -> dict[str, Any]:
    """The entry of a stack member below the first: its stack and its size, and no seat —
    the column derives it from the first member's."""
    return _entry({}, size, stack)


def _entry(entry: dict[str, Any], size: Size | None, stack: str) -> dict[str, Any]:
    if size is not None and size != (NODE_W, NODE_H):
        entry["w"] = max(MIN_NODE_W, snapped(size[0]))
        entry["h"] = max(MIN_NODE_H, snapped(size[1]))
    if stack:
        entry[STACK_KEY] = stack
    return stamped(entry, DATA_FORMAT.version)


def entry_with(project: Project, key: str, value: Any) -> dict[str, Any]:
    """The project-level entry with one key replaced, the other keys carried untouched.

    Every key on ``projects/<p>/modules/project_editor.json`` is written through here, so
    each can be written without knowing another's shape. What it carries is brought to the
    current format first: an entry adopted from another writer since the open — a CLI
    import, a pull — has not been through the migration pass, and stamping it current as
    it stood would keep whatever that pass drops forever. An empty value drops its key, and
    ``stamped`` turns a bare entry into ``{}``, which deletes the file.
    """
    current = project.module_data.get(MODULE_ID) or {}
    if (brought := migrated(current, DATA_FORMAT)) is not None:
        current = brought
    entry = {k: v for k, v in current.items() if k not in (key, "format")}
    if value:
        entry[key] = value
    return stamped(entry, DATA_FORMAT.version)


def _is_number(value: object) -> TypeGuard[int | float]:
    return not isinstance(value, bool) and isinstance(value, int | float)
