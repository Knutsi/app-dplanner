"""The undo stack: applying, merging, sealing, and the redo tail."""

import pytest

from dplanner.framework.undo import UndoService


class Append:
    """A command over a plain list, so the stack is tested without a model."""

    def __init__(self, value, mergeable=True):
        self.values = [value]
        self.mergeable = mergeable

    def text(self):
        return "Append"

    def redo(self, document):
        document.extend(self.values)

    def undo(self, document):
        del document[-len(self.values) :]

    def merge_with(self, other):
        if not (self.mergeable and isinstance(other, Append) and other.mergeable):
            return False
        self.values.extend(other.values)
        return True


@pytest.fixture
def document():
    return []


def test_pushing_applies_immediately(document):
    undo = UndoService(document)
    undo.push(Append(1))
    assert document == [1]


def test_undo_and_redo_walk_the_stack(document):
    undo = UndoService(document)
    undo.push(Append(1, mergeable=False))
    undo.push(Append(2, mergeable=False))
    undo.undo()
    assert document == [1]
    undo.redo()
    assert document == [1, 2]


def test_consecutive_commands_merge_into_one_step(document):
    undo = UndoService(document)
    undo.push(Append(1))
    undo.push(Append(2))
    undo.undo()
    assert document == []


def test_sealing_starts_a_new_step(document):
    undo = UndoService(document)
    undo.push(Append(1))
    undo.break_coalescing()
    undo.push(Append(2))
    undo.undo()
    assert document == [1]


def test_a_new_edit_discards_the_redo_tail(document):
    undo = UndoService(document)
    undo.push(Append(1, mergeable=False))
    undo.push(Append(2, mergeable=False))
    undo.undo()
    undo.push(Append(3, mergeable=False))
    assert not undo.can_redo()
    assert document == [1, 3]


def test_typing_after_an_undo_never_merges_into_old_history(document):
    undo = UndoService(document)
    undo.push(Append(1))
    undo.undo()
    undo.push(Append(2))
    undo.undo()
    assert document == []


def test_labels_follow_the_stack(document):
    undo = UndoService(document)
    assert undo.undo_text() == ""
    undo.push(Append(1))
    assert undo.undo_text() == "Append"
    undo.undo()
    assert undo.redo_text() == "Append"


def test_every_change_announces_itself(document):
    undo = UndoService(document)
    seen = []
    undo.changed.connect(lambda: seen.append(1))
    undo.push(Append(1))
    undo.undo()
    undo.redo()
    assert len(seen) == 3


def test_a_gesture_lands_as_one_step_and_undoes_as_one(document):
    """Several pushes inside a gesture are applied as they come — later ones see earlier
    ones' effects — and reach the stack as one named step."""
    undo = UndoService(document)
    with undo.gesture("Make Three"):
        undo.push(Append(1, mergeable=False))
        assert document == [1]
        undo.push(Append(2, mergeable=False))
        undo.push(Append(3, mergeable=False))
    assert document == [1, 2, 3]
    assert undo.undo_text() == "Make Three"
    undo.undo()
    assert document == []
    undo.redo()
    assert document == [1, 2, 3]


def test_a_gesture_of_one_push_is_that_push_and_of_none_is_nothing(document):
    undo = UndoService(document)
    with undo.gesture("Nothing"):
        pass
    assert not undo.can_undo()
    with undo.gesture("One"):
        undo.push(Append(1))
    assert undo.undo_text() == "Append"


def test_a_gesture_inside_a_gesture_belongs_to_the_outer_one(document):
    undo = UndoService(document)
    with undo.gesture("Outer"):
        undo.push(Append(1, mergeable=False))
        with undo.gesture("Inner"):
            undo.push(Append(2, mergeable=False))
    assert undo.undo_text() == "Outer"
    undo.undo()
    assert document == []
