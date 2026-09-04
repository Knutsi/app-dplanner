"""Regions on disk: titled rectangles stored on the project node.

No ``qapp`` fixture: ``regions.py`` is Qt-free by rule — the CLI reaches it when a layout
snapshot records region rects — and exercising it without one is part of the proof.
"""

from dplanner.domain.model import Library, Project
from dplanner.modules.project_editor.named_layouts import LayoutSnapshot, write_layouts
from dplanner.modules.project_editor.positions import MODULE_ID
from dplanner.modules.project_editor.regions import (
    Region,
    new_region,
    read_regions,
    set_regions_command,
    write_regions,
)


def build():
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    return library, project


def test_write_and_read_round_trip_in_creation_order():
    library, project = build()
    first = new_region("Database setup", 8.0, 8.0, 320.0, 240.0)
    second = new_region("Finalize release", 400.0, 8.0, 320.0, 240.0)
    set_regions_command(project, [first, second], "Add Region").redo(library)
    assert read_regions(project) == [first, second]


def test_rects_are_stored_as_whole_unit_floats():
    """Snapping to the grid is the canvas gesture's; what reaches disk is rounded to the
    unit, as a float — a ``region add --rect`` stores the rect it was given."""
    _library, project = build()
    entry = write_regions(project, [Region("r1", "DB", 11.4, 3.0, 101.0, 55.6)])
    stored = entry["regions"][0]
    assert (stored["x"], stored["y"]) == (11.0, 3.0)
    assert (stored["w"], stored["h"]) == (101.0, 56.0)
    assert all(isinstance(stored[key], float) for key in ("x", "y", "w", "h"))


def test_unreadable_regions_read_as_absent():
    library, project = build()
    library.set_module_data(
        project.id,
        MODULE_ID,
        {
            "regions": [
                {"id": "ok", "title": "DB", "x": 8.0, "y": 8.0, "w": 100.0, "h": 100.0},
                {"id": "", "title": "no id", "x": 1, "y": 2, "w": 3, "h": 4},
                {"id": "bad", "title": "words", "x": "left", "y": 2, "w": 3, "h": 4},
                "not a region",
            ]
        },
    )
    found = read_regions(project)
    assert [region.id for region in found] == ["ok"]


def test_contains_centre_is_the_carry_rule():
    region = Region("r", "DB", 0.0, 0.0, 300.0, 120.0)
    assert region.contains_centre(40.0, 40.0, 180.0, 56.0)  # centre (130, 68)
    assert not region.contains_centre(40.0, 150.0, 180.0, 56.0)  # centre (130, 178)


def test_writing_regions_carries_the_layouts_untouched():
    library, project = build()
    library.set_module_data(
        project.id, MODULE_ID, write_layouts(project, {"Plan": LayoutSnapshot()})
    )
    set_regions_command(project, [new_region("DB", 0.0, 0.0, 100.0, 100.0)], "Add").redo(library)
    entry = project.module_data[MODULE_ID]
    assert "layouts" in entry and "regions" in entry


def test_deleting_the_last_region_leaves_no_file_behind():
    library, project = build()
    set_regions_command(project, [new_region("DB", 0.0, 0.0, 100.0, 100.0)], "Add").redo(library)
    set_regions_command(project, [], "Delete Region").redo(library)
    assert MODULE_ID not in project.module_data
