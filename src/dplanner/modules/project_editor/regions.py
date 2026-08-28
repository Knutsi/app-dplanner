"""Regions: named rectangles painted behind the graph — "Database setup", "Finalize release".

A region is annotation, not structure. It has no edges, no aspects and no place in the
ordering; the model never learns it exists. The list lives on the *project* node in the same
``projects/<p>/modules/project_editor.json`` entry the named layouts use, in creation order
so the diff of adding one is one appended line.

Reads are tolerant the way ``read_position`` is: an entry this build cannot understand reads
as absent rather than taking the canvas down.

**Qt-free** — the composition root reaches this file when the CLI builds a layout snapshot.
"""

import uuid
from dataclasses import dataclass
from typing import Any, TypeGuard

from dplanner.domain.commands import Command, SetModuleDataCommand
from dplanner.domain.model import Project
from dplanner.modules.project_editor.positions import MODULE_ID, entry_with, snapped

REGIONS_KEY = "regions"

# The title strip across a region's top: dragging it moves the frame alone, and
# double-clicking it renames. Deep enough for a line of text with DESIGN.md's breathing room.
TITLE_STRIP_H = 24.0
# No region smaller than this on either side — below it there is nothing to put inside.
MIN_REGION = 48.0


@dataclass(frozen=True)
class Region:
    """One rectangle and its name. ``x, y`` is the top-left corner."""

    id: str
    title: str
    x: float
    y: float
    w: float
    h: float

    def moved_to(self, x: float, y: float) -> "Region":
        return Region(self.id, self.title, snapped(x), snapped(y), self.w, self.h)

    def sized(self, w: float, h: float) -> "Region":
        return Region(
            self.id,
            self.title,
            self.x,
            self.y,
            max(MIN_REGION, snapped(w)),
            max(MIN_REGION, snapped(h)),
        )

    def named(self, title: str) -> "Region":
        return Region(self.id, title, self.x, self.y, self.w, self.h)

    def contains_centre(self, x: float, y: float, w: float, h: float) -> bool:
        """Does a node's centre lie inside? The rule body-dragging carries steps by."""
        cx, cy = x + w / 2, y + h / 2
        return self.x <= cx <= self.x + self.w and self.y <= cy <= self.y + self.h


def new_region(title: str, x: float, y: float, w: float, h: float) -> Region:
    return Region(uuid.uuid4().hex, title, snapped(x), snapped(y), snapped(w), snapped(h))


def read_regions(project: Project) -> list[Region]:
    """Every region in creation order. Unreadable entries read as absent."""
    entry = project.module_data.get(MODULE_ID)
    raw = entry.get(REGIONS_KEY) if entry else None
    if not isinstance(raw, list):
        return []
    regions = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        region_id, title = item.get("id"), item.get("title")
        values = [item.get(key) for key in ("x", "y", "w", "h")]
        floats = [float(v) for v in values if _is_number(v)]
        if not isinstance(region_id, str) or not region_id or len(floats) != 4:
            continue
        x, y, w, h = floats
        regions.append(Region(region_id, title if isinstance(title, str) else "", x, y, w, h))
    return regions


def write_regions(project: Project, regions: list[Region]) -> dict[str, Any]:
    """The whole project entry with these regions, the layouts carried untouched."""
    body = [
        {
            "id": region.id,
            "title": region.title,
            "x": snapped(region.x),
            "y": snapped(region.y),
            "w": snapped(region.w),
            "h": snapped(region.h),
        }
        for region in regions
    ]
    return entry_with(project, REGIONS_KEY, body)


def set_regions_command(
    project: Project, regions: list[Region], label: str, view_origin: object = None
) -> Command:
    """The one shape every region gesture ends in: the full list, written at once."""
    return SetModuleDataCommand(
        project.id,
        MODULE_ID,
        write_regions(project, regions),
        view_origin=view_origin,
        label=label,
    )


def _is_number(value: object) -> TypeGuard[int | float]:
    return not isinstance(value, bool) and isinstance(value, int | float)
