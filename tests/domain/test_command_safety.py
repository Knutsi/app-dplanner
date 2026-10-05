"""Commands are all-or-nothing, and never overwrite what another writer changed since."""

import pytest

from dplanner.domain.commands import (
    CompositeCommand,
    SetEdgesCommand,
    SetFieldCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import Library, Project, Step
from dplanner.framework.undo import UndoService


@pytest.fixture
def library():
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    for title in ("Read the spec", "Draft the model", "Review"):
        library.add_child(project.id, Step(title=title))
    return library


def steps(library):
    return next(node for node in library.nodes() if isinstance(node, Project)).steps


def test_a_composite_that_fails_partway_leaves_the_model_untouched(library):
    first = steps(library)[0]
    composite = CompositeCommand(
        "Rename Two",
        [SetFieldCommand(first.id, "title", "Renamed"), SetFieldCommand("missing", "title", "x")],
    )
    with pytest.raises(KeyError):
        composite.redo(library)
    assert first.title == "Read the spec"


def test_a_composite_whose_undo_is_refused_stays_whole_and_the_stack_drops_it(library):
    first, second, _ = steps(library)
    undo = UndoService(library)
    undo.push(
        CompositeCommand(
            "Rename Two",
            [SetFieldCommand(first.id, "title", "One"), SetFieldCommand(second.id, "title", "Two")],
        )
    )
    library.set_field(first.id, "title", "Theirs")  # Undone last, so refused after the other.
    undo.undo()
    assert (first.title, second.title) == ("Theirs", "Two")
    assert not undo.can_undo()


def test_undo_keeps_a_rename_another_writer_made_since(library):
    step = steps(library)[0]
    undo = UndoService(library)
    undo.push(SetFieldCommand(step.id, "title", "Mine"))
    library.set_field(step.id, "title", "Theirs")
    undo.undo()
    assert step.title == "Theirs"
    assert not undo.can_undo() and not undo.can_redo()


def test_undo_keeps_module_data_another_writer_changed_since(library):
    step = steps(library)[0]
    undo = UndoService(library)
    undo.push(SetModuleDataCommand(step.id, "step_estimation", {"days": 1.0}))
    library.node(step.id).module_data["step_estimation"]["days"] = 4.0  # Edited in place.
    undo.undo()
    assert step.module_data["step_estimation"] == {"days": 4.0}
    assert not undo.can_undo()


def test_undo_keeps_links_another_writer_changed_since(library):
    first, second, third = steps(library)
    undo = UndoService(library)
    undo.push(SetEdgesCommand(third.id, "requires", [first.id]))
    library.set_edges(third.id, "requires", [first.id, second.id])
    undo.undo()
    assert third.edges["requires"] == [first.id, second.id]
    assert not undo.can_undo()


def test_a_redo_keeps_a_value_another_writer_changed_after_the_undo(library):
    step = steps(library)[0]
    undo = UndoService(library)
    undo.push(SetFieldCommand(step.id, "title", "Mine"))
    undo.undo()
    library.set_field(step.id, "title", "Theirs")
    undo.redo()
    assert step.title == "Theirs"
    assert not undo.can_redo()


def test_coalesced_edits_still_undo_and_redo_cleanly(library):
    step = steps(library)[0]
    undo = UndoService(library)
    undo.push(SetFieldCommand(step.id, "title", "M"))
    undo.push(SetFieldCommand(step.id, "title", "Mine"))
    undo.push(SetModuleDataCommand(step.id, "step_estimation", {"days": 1.0}))
    undo.push(SetModuleDataCommand(step.id, "step_estimation", {"days": 2.0}))
    undo.undo()
    undo.undo()
    assert step.title == "Read the spec" and "step_estimation" not in step.module_data
    undo.redo()
    undo.redo()
    assert step.title == "Mine" and step.module_data["step_estimation"] == {"days": 2.0}


def test_an_edit_after_another_writers_change_does_not_merge_across_it(library):
    step = steps(library)[0]
    undo = UndoService(library)
    undo.push(SetFieldCommand(step.id, "title", "Mine"))
    library.set_field(step.id, "title", "Theirs")
    undo.push(SetFieldCommand(step.id, "title", "Mine again"))
    undo.undo()
    assert step.title == "Theirs"
    undo.undo()
    assert step.title == "Theirs"


def test_module_data_after_another_writers_change_does_not_merge_across_it(library):
    step = steps(library)[0]
    undo = UndoService(library)
    undo.push(SetModuleDataCommand(step.id, "step_estimation", {"days": 1.0}))
    library.set_module_data(step.id, "step_estimation", {"days": 4.0})
    undo.push(SetModuleDataCommand(step.id, "step_estimation", {"days": 2.0}))
    undo.undo()
    assert step.module_data["step_estimation"] == {"days": 4.0}
    undo.undo()
    assert step.module_data["step_estimation"] == {"days": 4.0}
