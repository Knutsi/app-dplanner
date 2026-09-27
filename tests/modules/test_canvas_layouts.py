"""Named layouts: snapshots of the graph, stored on the project node.

No ``qapp`` fixture: ``layouts.py`` is Qt-free by rule — the CLI's ``layout`` verbs are
built from the same functions — and exercising it without one is part of the proof.
"""

from tests.old_canvas import PLAN, SEATS, project_entry, step_entry

from dplanner.core.module_data import migrated
from dplanner.domain.model import Library, Project, Step
from dplanner.modules.project_editor.named_layouts import (
    LayoutSnapshot,
    apply_layout_commands,
    delete_layout_command,
    is_current,
    read_layouts,
    rename_layout_command,
    save_layout_command,
    snapshot,
    write_layouts,
)
from dplanner.modules.project_editor.positions import (
    DATA_FORMAT,
    MODULE_ID,
    read_position,
    write_position,
)


def build():
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    for title in ("A", "B", "C"):
        library.add_child(project.id, Step(title=title))
    return library, project


def save(library, project, name):
    snap = snapshot(library, project)
    save_layout_command(project, name, snap).redo(library)
    return snap


def test_save_and_read_round_trip():
    library, project = build()
    snap = save(library, project, "Plan")
    assert read_layouts(project)["Plan"] == snap
    assert set(snap.steps) == {step.id for step in project.steps}


def test_layout_coordinates_are_whole_unit_floats():
    """FORMAT.md's numeric rule, one level up: the snapshot stores what a move would."""
    _library, project = build()
    entry = write_layouts(project, {"P": LayoutSnapshot(steps={"s": (11.4, 3.0)})})
    stored = entry["layouts"]["P"]["steps"]["s"]
    assert stored == [11.0, 3.0]
    assert all(isinstance(value, float) for value in stored)


def test_unreadable_layouts_read_as_absent():
    """A hand-edited or newer file must not take the picker down with it."""
    library, project = build()
    library.set_module_data(
        project.id,
        MODULE_ID,
        {
            "layouts": {
                "ok": {"steps": {"a": [1.0, 2.0]}},
                "bad": "not a snapshot",
                "partial": {"steps": {"a": [1, 2, 3], "b": ["x", 2], "c": [3, 4]}},
            }
        },
    )
    found = read_layouts(project)
    assert set(found) == {"ok", "partial"}
    assert found["ok"].steps == {"a": (1.0, 2.0)}
    # The two unreadable coordinate entries vanish; the readable one survives.
    assert found["partial"].steps == {"c": (3.0, 4.0)}


def test_apply_restores_positions_and_skips_unknown_ids():
    library, project = build()
    a, b, _c = project.steps
    library.set_module_data(b.id, MODULE_ID, write_position(504.0, 304.0))
    snap = snapshot(library, project)
    ghost = LayoutSnapshot(steps={**snap.steps, "ghost": (0.0, 0.0)})
    save_layout_command(project, "Plan", ghost).redo(library)

    library.set_module_data(a.id, MODULE_ID, write_position(800.0, 800.0))
    library.set_module_data(b.id, MODULE_ID, write_position(900.0, 900.0))
    for command in apply_layout_commands(library, project, "Plan"):
        command.redo(library)

    assert read_position(b) == (504.0, 304.0)
    assert read_position(a) == snap.steps[a.id]


def test_apply_leaves_steps_the_layout_never_saw_untouched():
    library, project = build()
    a, b, _c = project.steps
    partial = LayoutSnapshot(steps={a.id: (8.0, 8.0)})
    save_layout_command(project, "Partial", partial).redo(library)
    library.set_module_data(b.id, MODULE_ID, write_position(504.0, 304.0))

    for command in apply_layout_commands(library, project, "Partial"):
        command.redo(library)

    assert read_position(a) == (8.0, 8.0)
    assert read_position(b) == (504.0, 304.0)


def test_rename_moves_the_snapshot():
    library, project = build()
    snap = save(library, project, "Old")
    rename_layout_command(project, "Old", "New").redo(library)
    found = read_layouts(project)
    assert "Old" not in found
    assert found["New"] == snap


def test_deleting_the_last_layout_leaves_no_file_behind():
    """Absence encodes the default: an empty entry deletes ``modules/project_editor.json``."""
    library, project = build()
    save(library, project, "Plan")
    delete_layout_command(project, "Plan").redo(library)
    assert MODULE_ID not in project.module_data


def test_is_current_tracks_drift():
    library, project = build()
    save(library, project, "Plan")
    assert is_current(library, project, "Plan")

    moved = project.steps[0]
    library.set_module_data(moved.id, MODULE_ID, write_position(800.0, 800.0))
    assert not is_current(library, project, "Plan")

    # A step the snapshot has never heard of counts as drift too.
    for command in apply_layout_commands(library, project, "Plan"):
        command.redo(library)
    assert is_current(library, project, "Plan")
    library.add_child(project.id, Step(title="D"))
    assert not is_current(library, project, "Plan")


def test_format_2_drops_the_regions_and_every_layouts_region_rects():
    """Regions were retired: a project entry keeps its layouts' step seats and nothing else
    it had about them — including a layout's rects for a region deleted long before."""
    ids = ["a", "b", "c"]
    assert migrated(project_entry(ids), DATA_FORMAT) == {
        "format": 2,
        "layouts": {
            "Plan": {"steps": {i: list(seat) for i, seat in zip(ids, PLAN, strict=True)}},
            "Earlier": {"steps": {i: list(seat[:2]) for i, seat in zip(ids, SEATS, strict=True)}},
        },
    }


def test_a_steps_entry_passes_through_format_2_as_it_was():
    for index in range(len(SEATS)):
        assert migrated(step_entry(index), DATA_FORMAT) == {**step_entry(index), "format": 2}


def test_a_layout_saved_over_an_entry_nobody_migrated_drops_its_regions():
    """An entry adopted from another writer since the open — a CLI import, a pull — has not
    met the migration pass; stamping it current as it stood would keep its regions forever."""
    library, project = build()
    library.set_module_data(project.id, MODULE_ID, project_entry([s.id for s in project.steps]))
    save(library, project, "New")
    entry = project.module_data[MODULE_ID]
    assert entry["format"] == 2 and "regions" not in entry
    assert set(entry["layouts"]) == {"Plan", "Earlier", "New"}
    assert all("regions" not in body for body in entry["layouts"].values())
