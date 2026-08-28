"""Named layouts: an arrangement of the graph a person saved under a name.

A layout is a snapshot — where every step sat, and where every region sat — stored as one
entry on the *project* node (``projects/<p>/modules/project_editor.json``), under the same
module id as the per-step positions. One id spanning two node kinds is the ``estimation``
precedent (``FORMAT.md``), and one file per snapshot is the right diff shape here: saving a
layout is one gesture about the whole graph, where moving a node is a gesture about one step.

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
from typing import Any, TypeGuard, cast

from dplanner.domain.commands import Command, SetModuleDataCommand
from dplanner.domain.model import Product, Project, StepId
from dplanner.modules.project_editor.layout import positions
from dplanner.modules.project_editor.positions import (
    MODULE_ID,
    entry_with,
    snapped,
    write_position,
)
from dplanner.modules.project_editor.regions import (
    REGIONS_KEY,
    read_regions,
    set_regions_command,
)

LAYOUTS_KEY = "layouts"

type Point = tuple[float, float]
type Rect = tuple[float, float, float, float]


@dataclass(frozen=True)
class LayoutSnapshot:
    """Where everything sat when the layout was saved, by id."""

    steps: dict[StepId, Point] = field(default_factory=dict)
    regions: dict[str, Rect] = field(default_factory=dict)


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
        layouts[name] = LayoutSnapshot(
            steps=cast(dict[StepId, Point], _coords(body.get("steps"), 2)),
            regions=cast(dict[str, Rect], _coords(body.get(REGIONS_KEY), 4)),
        )
    return layouts


def snapshot(product: Product, project: Project) -> LayoutSnapshot:
    """The graph as it stands: every step's position and every region's rect.

    Built from :func:`~dplanner.modules.project_editor.layout.positions`, so a step nobody
    has moved still snapshots at its automatic seat — a layout restores the whole picture,
    not just the hand-placed part.
    """
    placed = positions(product, project)
    return LayoutSnapshot(
        steps={step_id: (snapped(x), snapped(y)) for step_id, (x, y) in placed.items()},
        regions=region_rects(project),
    )


def region_rects(project: Project) -> dict[str, Rect]:
    """Every region's rect by id — the half of a region a layout has opinions about."""
    return {r.id: (r.x, r.y, r.w, r.h) for r in read_regions(project)}


def write_layouts(project: Project, layouts: dict[str, LayoutSnapshot]) -> dict[str, Any]:
    """The whole project entry with these layouts, other keys carried untouched."""
    body = {name: _snapshot_body(snap) for name, snap in layouts.items()}
    return entry_with(project, LAYOUTS_KEY, body)


def is_current(product: Product, project: Project, name: str) -> bool:
    """Does the graph still sit exactly where this layout put it?

    A step or region the layout has never heard of counts as drift, deliberately — the
    picker's modified dot should light up when the graph outgrows its snapshot.
    """
    saved = read_layouts(project).get(name)
    return saved is not None and snapshot(product, project) == saved


# -- the commands both surfaces build ----------------------------------------------------------


def position_commands(
    placed: dict[StepId, Point], label: str, view_origin: object = None
) -> list[Command]:
    """One position write per step — the shared tail of apply and every auto-sort."""
    return [
        SetModuleDataCommand(
            step_id, MODULE_ID, write_position(x, y), view_origin=view_origin, label=label
        )
        for step_id, (x, y) in placed.items()
    ]


def apply_layout_commands(
    product: Product, project: Project, name: str, view_origin: object = None
) -> list[Command]:
    """Everything applying this layout means: step moves, and region rects where they still
    apply. Raises ``KeyError`` for a name the project does not have."""
    snap = read_layouts(project)[name]
    label = f'Apply Layout "{name}"'
    placed = {step.id: snap.steps[step.id] for step in project.steps if step.id in snap.steps}
    commands = position_commands(placed, label, view_origin=view_origin)
    regions = _region_update_command(project, snap, label, view_origin=view_origin)
    if regions is not None:
        commands.append(regions)
    return commands


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


def _coords(raw: object, count: int) -> dict[str, tuple[float, ...]]:
    """Id → coordinate list of exactly ``count`` numbers; anything else is skipped."""
    if not isinstance(raw, dict):
        return {}
    found: dict[str, tuple[float, ...]] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, list) or len(value) != count:
            continue
        if not all(_is_number(v) for v in value):
            continue
        found[key] = tuple(float(v) for v in value)
    return found


def _snapshot_body(snap: LayoutSnapshot) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if snap.steps:
        body["steps"] = {
            step_id: [snapped(x), snapped(y)] for step_id, (x, y) in snap.steps.items()
        }
    if snap.regions:
        body[REGIONS_KEY] = {
            region_id: [snapped(v) for v in rect] for region_id, rect in snap.regions.items()
        }
    return body


def _region_update_command(
    project: Project, snap: LayoutSnapshot, label: str, view_origin: object = None
) -> Command | None:
    """Move existing regions to their snapshotted rects. Never creates or deletes one —
    regions are content, and a layout only says where things sit."""
    current = read_regions(project)
    updated = []
    for region in current:
        rect = snap.regions.get(region.id)
        if rect is None:
            updated.append(region)
        else:
            x, y, w, h = rect
            updated.append(region.moved_to(x, y).sized(w, h))
    if updated == current:
        return None
    return set_regions_command(project, updated, label, view_origin=view_origin)
