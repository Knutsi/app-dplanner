"""A project as a build with regions left it — what "an old project still opens" is proved on.

``project_editor`` format 1 kept titled rectangles beside the project (``"regions"``), and a
named layout snapshotted their rects beside the steps' seats. Regions were retired and
format 2 drops both on read; these are the literal entries a format-1 build wrote, as plain
data, so the proof needs none of the code that wrote them.

Three steps, in project order. The second card was made larger, so a size has something to
survive. ``Plan`` puts every card somewhere else, so applying it visibly moves them; and
``Earlier`` snapshotted a region that has since been deleted, which is what a real plan
that stopped using regions still carries.
"""

from pathlib import Path
from typing import Any

from dplanner.domain.store import LibraryStore

MODULE_ID = "project_editor"

REGIONS = [
    {"id": "r1", "title": "Database setup", "x": 16.0, "y": 16.0, "w": 560.0, "h": 144.0},
    {"id": "r2", "title": "Finalize release", "x": 600.0, "y": 16.0, "w": 320.0, "h": 144.0},
]
# Where each step was left: x, y, and the size somebody dragged it to (None: the default).
SEATS: list[tuple[float, float, tuple[float, float] | None]] = [
    (40.0, 56.0, None),
    (320.0, 48.0, (264.0, 104.0)),
    (640.0, 56.0, None),
]
# Where the layout "Plan" puts them.
PLAN = [(40.0, 320.0), (320.0, 320.0), (640.0, 320.0)]


def step_entry(index: int) -> dict[str, Any]:
    x, y, size = SEATS[index]
    entry: dict[str, Any] = {"format": 1, "x": x, "y": y}
    if size is not None:
        entry |= {"w": size[0], "h": size[1]}
    return entry


def project_entry(step_ids: list[str]) -> dict[str, Any]:
    rects = {region["id"]: [region[k] for k in ("x", "y", "w", "h")] for region in REGIONS}
    return {
        "format": 1,
        "regions": REGIONS,
        "layouts": {
            "Plan": {
                "steps": {step_id: list(PLAN[i]) for i, step_id in enumerate(step_ids)},
                "regions": rects,
            },
            "Earlier": {
                "steps": {step_id: list(SEATS[i][:2]) for i, step_id in enumerate(step_ids)},
                "regions": {"deleted": [0.0, 0.0, 240.0, 240.0]},
            },
        },
    }


def plant(library_path: Path, title: str) -> list[str]:
    """Rewrite the project titled ``title`` on disk as a format-1 build left it.

    Returns its step ids in project order. The project must have exactly three steps.
    """
    store = LibraryStore(library_path)
    project = next(p for p in store.load().projects if p.title == title)
    step_ids = [step.id for step in project.steps]
    assert len(step_ids) == len(SEATS), step_ids
    store.set_module_data(project.id, MODULE_ID, project_entry(step_ids))
    for index, step_id in enumerate(step_ids):
        store.set_module_data(step_id, MODULE_ID, step_entry(index))
    store.flush({(owner, "module_data") for owner in (project.id, *step_ids)})
    store.close()
    return step_ids


def old_export(document: dict[str, Any]) -> dict[str, Any]:
    """An export of three steps as a format-1 build wrote it: ``document``, whatever build
    produced it, with this module's entries put back the way that build had them."""
    steps = document["steps"]
    return {
        **document,
        "aspects": {**document["aspects"], MODULE_ID: project_entry([s["id"] for s in steps])},
        "steps": [
            {**step, "aspects": {**step["aspects"], MODULE_ID: step_entry(index)}}
            for index, step in enumerate(steps)
        ],
    }
