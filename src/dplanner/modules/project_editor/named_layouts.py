"""Named layouts: an arrangement of the graph a person saved under a name.

A layout is a snapshot — where every step sat — stored as one entry on the *project* node
(``projects/<p>/modules/project_editor.json``), under the same module id as the per-step
positions. One id spanning two node kinds is the ``estimation`` precedent (``FORMAT.md``),
and one file per snapshot is the right diff shape here: saving a layout is one gesture about
the whole graph, where moving a node is a gesture about one step.

Unlike the automatic layout next door, a snapshot is authored — somebody arranged the graph
and named the result — so storing it does not violate "derived facts are computed, never
stored". Applying one is a command like any drag, which is what keeps a CLI ``layout apply``
undoable in an open window.

Reads are tolerant the way ``read_position`` is: an entry this build cannot understand reads
as absent, and applying a layout skips ids the project no longer has — a deleted step's seat
is kept, because undoing the deletion has to find it again.

**Qt-free** — the CLI's ``layout`` verbs are built from these same functions.
"""

from dataclasses import dataclass, field
from typing import Any, TypeGuard

from dplanner.domain.commands import Command, SetModuleDataCommand
from dplanner.domain.model import Library, Project, StepId
from dplanner.modules.project_editor.placement import positions
from dplanner.modules.project_editor.positions import (
    MODULE_ID,
    Size,
    entry_with,
    node_size,
    read_size,
    read_stack,
    snapped,
    write_member,
    write_position,
)
from dplanner.modules.project_editor.stacks import member_seats, read_stacks

LAYOUTS_KEY = "layouts"

type Point = tuple[float, float]


@dataclass(frozen=True)
class LayoutSnapshot:
    """Where every step sat when the layout was saved, by id."""

    steps: dict[StepId, Point] = field(default_factory=dict)


def read_layouts(project: Project) -> dict[str, LayoutSnapshot]:
    """Every saved layout by name. Unreadable entries read as absent."""
    entry = project.module_data.get(MODULE_ID)
    raw = entry.get(LAYOUTS_KEY) if entry else None
    if not isinstance(raw, dict):
        return {}
    layouts: dict[str, LayoutSnapshot] = {}
    for name, body in raw.items():
        if not isinstance(name, str) or not isinstance(body, dict):
            continue
        layouts[name] = LayoutSnapshot(steps=_points(body.get("steps")))
    return layouts


def snapshot(library: Library, project: Project) -> LayoutSnapshot:
    """The graph as it stands: every step's position.

    Built from :func:`~dplanner.modules.project_editor.layout.positions`, so a step nobody
    has moved still snapshots at its automatic seat — a layout restores the whole picture,
    not just the hand-placed part.
    """
    placed = positions(library, project)
    return LayoutSnapshot(
        steps={step_id: (snapped(x), snapped(y)) for step_id, (x, y) in placed.items()}
    )


def write_layouts(project: Project, layouts: dict[str, LayoutSnapshot]) -> dict[str, Any]:
    """The whole project entry with these layouts, other keys carried untouched."""
    body = {name: _snapshot_body(snap) for name, snap in layouts.items()}
    return entry_with(project, LAYOUTS_KEY, body)


def is_current(library: Library, project: Project, name: str) -> bool:
    """Does the graph still sit exactly where this layout put it?

    A step the layout has never heard of counts as drift, deliberately — the picker's
    modified dot should light up when the graph outgrows its snapshot.
    """
    saved = read_layouts(project).get(name)
    return saved is not None and snapshot(library, project) == saved


# -- the commands both surfaces build ----------------------------------------------------------


def position_commands(
    project: Project, placed: dict[StepId, Point], label: str, view_origin: object = None
) -> list[Command]:
    """One seat write per card that moves — the shared tail of a drag, apply, every sort, a
    divide and a contract.

    Each write carries the card's own size and its stack: a layout says where a card sits,
    never how big it is or what it stands in, so applying one — or sorting — leaves a card
    somebody enlarged as it was and a stack whole. **A stack's seat is its first member's**,
    so any member's seat moves the stack: the first member's own wins when both are given,
    and a member below it never gains a seat of its own.
    """
    steps = {step.id: step for step in project.steps}
    stacks = read_stacks(project.steps)
    stack_of = {member: stack for stack in stacks for member in stack.members}
    seats: dict[StepId, Point] = {}
    for step_id, (x, y) in placed.items():
        stack = stack_of.get(step_id)
        if stack is None or step_id == stack.head:
            seats[step_id] = (x, y)
        elif stack.head not in seats:
            _x, dy = member_seats(stack, (0.0, 0.0), lambda m: node_size(steps[m]))[step_id]
            seats[stack.head] = (x, y - dy)
    return [
        SetModuleDataCommand(
            step_id,
            MODULE_ID,
            write_position(x, y, read_size(steps[step_id]), stack=read_stack(steps[step_id])),
            view_origin=view_origin,
            label=label,
        )
        for step_id, (x, y) in seats.items()
    ]


def resize_command(
    project: Project, step_id: StepId, seat: Point, size: Size, view_origin: object = None
) -> Command:
    """A card made bigger or smaller, as one write. A member below a stack's first keeps no
    seat — the column derives it — so only its size changes, and its column never shifts
    under the resize."""
    step = next(step for step in project.steps if step.id == step_id)
    stack = read_stack(step)
    below_first = any(step_id in found.members[1:] for found in read_stacks(project.steps))
    entry = write_member(stack, size) if below_first else write_position(*seat, size, stack=stack)
    return SetModuleDataCommand(
        step_id, MODULE_ID, entry, view_origin=view_origin, label="Resize Step"
    )


def apply_layout_commands(
    library: Library, project: Project, name: str, view_origin: object = None
) -> list[Command]:
    """Everything applying this layout means: a move for every step it still has a seat
    for. Raises ``KeyError`` for a name the project does not have."""
    snap = read_layouts(project)[name]
    placed = {step.id: snap.steps[step.id] for step in project.steps if step.id in snap.steps}
    return position_commands(project, placed, f'Apply Layout "{name}"', view_origin=view_origin)


def save_layout_command(
    project: Project,
    name: str,
    snap: LayoutSnapshot,
    label: str = "",
    view_origin: object = None,
) -> Command:
    """Store (or replace) one named layout."""
    layouts = read_layouts(project)
    layouts[name] = snap
    return SetModuleDataCommand(
        project.id,
        MODULE_ID,
        write_layouts(project, layouts),
        view_origin=view_origin,
        label=label or f'Save Layout "{name}"',
    )


def rename_layout_command(project: Project, old: str, new: str) -> Command:
    """Move a layout to a new name. Raises ``KeyError`` when the old name is absent."""
    layouts = read_layouts(project)
    layouts[new] = layouts.pop(old)
    return SetModuleDataCommand(
        project.id, MODULE_ID, write_layouts(project, layouts), label="Rename Layout"
    )


def delete_layout_command(project: Project, name: str) -> Command:
    """Forget a named layout. Raises ``KeyError`` when there is nothing to forget."""
    layouts = read_layouts(project)
    del layouts[name]
    return SetModuleDataCommand(
        project.id,
        MODULE_ID,
        write_layouts(project, layouts),
        label=f'Delete Layout "{name}"',
    )


# -- helpers -----------------------------------------------------------------------------------


def _is_number(value: object) -> TypeGuard[int | float]:
    return not isinstance(value, bool) and isinstance(value, int | float)


def _points(raw: object) -> dict[StepId, Point]:
    """Step id → ``[x, y]``; anything else is skipped."""
    if not isinstance(raw, dict):
        return {}
    found: dict[StepId, Point] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, list) or len(value) != 2:
            continue
        x, y = value
        if _is_number(x) and _is_number(y):
            found[key] = (float(x), float(y))
    return found


def _snapshot_body(snap: LayoutSnapshot) -> dict[str, Any]:
    if not snap.steps:
        return {}
    return {"steps": {step_id: [snapped(x), snapped(y)] for step_id, (x, y) in snap.steps.items()}}
