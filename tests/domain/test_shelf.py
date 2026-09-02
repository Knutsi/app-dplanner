"""The shelf: an aspect turned off keeps its data, and turned on gets it back."""

import pytest

from dplanner.core.module_data import ModuleDataFormat
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.shelf import (
    SHELF_ID,
    ShelveCommand,
    UnshelveCommand,
    migrate_shelved,
    shelved,
    shelved_text,
    turn_off,
    turn_on,
)


@pytest.fixture
def library():
    library = Library()
    project = Project(title="Build")
    library.add_child(library.id, project)
    library.add_child(project.id, Step(title="Wire the panel"))
    return library


def step(library):
    return next(node for node in library.nodes() if node.kind == "step")


def test_turning_off_shelves_data_and_prose_and_leaves_the_marker(library):
    s = step(library)
    library.set_module_data(s.id, "step_description", {"format": 1, "note": "x"})
    library.set_text(s.id, "step_description", "What it is")

    turn_off(s.id, "step_description", leaving={"off": True}).redo(library)

    assert s.module_data["step_description"] == {"off": True}
    assert "step_description" not in s.module_text
    assert shelved(s, "step_description") == ({"format": 1, "note": "x"}, "What it is")
    assert shelved_text(s, "step_description") == "What it is"


def test_turning_on_restores_from_the_shelf_and_forgets_it(library):
    s = step(library)
    library.set_module_data(s.id, "step_milestone", {"label": "v2"})
    turn_off(s.id, "step_milestone").redo(library)
    assert "step_milestone" not in s.module_data

    command = turn_on(s, "step_milestone", fresh={"label": "v9"})
    assert isinstance(command, UnshelveCommand)
    command.redo(library)

    assert s.module_data["step_milestone"] == {"label": "v2"}
    assert SHELF_ID not in s.module_data  # An emptied shelf leaves no file behind.


def test_turning_on_with_nothing_shelved_writes_the_fresh_entry(library):
    s = step(library)
    command = turn_on(s, "step_milestone", fresh={"label": "v9"})
    assert isinstance(command, SetModuleDataCommand)
    command.redo(library)
    assert s.module_data["step_milestone"] == {"label": "v9"}


def test_an_aspect_that_held_nothing_shelves_nothing(library):
    """A bare marker toggled off must not grow a shelf: the file would say nothing."""
    s = step(library)
    library.set_module_data(s.id, "step_feature", {"on": True})
    # The marker is the whole entry, so it is data — but a description that is on with no
    # prose and no entry is not, and that is the case that must stay silent.
    turn_off(s.id, "step_description", leaving={"off": True}).redo(library)
    assert SHELF_ID not in s.module_data
    assert s.module_data["step_description"] == {"off": True}


def test_undo_of_both_commands_puts_all_three_stores_back(library):
    s = step(library)
    library.set_module_data(s.id, "docs", {"on": True})
    library.set_text(s.id, "docs", "Fragment")

    off = ShelveCommand(s.id, "docs", {})
    off.redo(library)
    assert s.module_text.get("docs") is None
    off.undo(library)
    assert s.module_data["docs"] == {"on": True}
    assert s.module_text["docs"] == "Fragment"
    assert SHELF_ID not in s.module_data

    off.redo(library)
    on = UnshelveCommand(s.id, "docs")
    on.redo(library)
    assert s.module_text["docs"] == "Fragment"
    on.undo(library)
    assert "docs" not in s.module_data
    assert "docs" not in s.module_text
    assert shelved_text(s, "docs") == "Fragment"


def test_the_shelf_keeps_several_aspects_apart(library):
    s = step(library)
    library.set_module_data(s.id, "a", {"x": 1})
    library.set_module_data(s.id, "b", {"y": 2})
    turn_off(s.id, "a").redo(library)
    turn_off(s.id, "b").redo(library)
    turn_on(s, "a", fresh={}).redo(library)
    assert s.module_data["a"] == {"x": 1}
    assert shelved(s, "b") == ({"y": 2}, "")
    assert shelved(s, "a") is None


class FakeRepo:
    def __init__(self, library):
        self.library = library

    def owners(self):
        return list(self.library.nodes())

    def set_module_data(self, owner_id, module_id, data):
        self.library.set_module_data(owner_id, module_id, data)


def fake_repo(library):
    """Unannotated on purpose: the narrow face the migration needs, typed as the test's."""
    return FakeRepo(library)


def test_shelved_data_is_migrated_with_its_module(library):
    """Data shelved at format 1 comes back readable by a build that moved to format 2."""
    s = step(library)
    library.set_module_data(s.id, "estimation", {"days": 2.0})
    turn_off(s.id, "estimation", leaving={"off": True}).redo(library)

    bumped = ModuleDataFormat(
        "estimation", version=2, migrations=(lambda d: {"working_days": d["days"]},)
    )
    changed = migrate_shelved(fake_repo(library), [bumped])

    assert changed == [s.id]
    assert shelved(s, "estimation") == ({"working_days": 2.0, "format": 2}, "")
    assert migrate_shelved(fake_repo(library), [bumped]) == []  # Already current.
