"""Marks: the socket facts a canvas colours, derived from the edges it draws — no Qt."""

from dplanner.domain.model import Step
from dplanner.modules.project_editor.marks import Marks, ports


def test_ports_count_every_kind_of_edge_between_the_steps_given():
    first, second, third = Step(title="a"), Step(title="b"), Step(title="c")
    second.edges["requires"] = [first.id]
    third.edges["relates"] = [second.id]
    assert ports([first, second, third]) == {
        first.id: (False, True),
        second.id: (True, True),
        third.id: (True, False),
    }


def test_an_edge_to_a_step_that_is_not_there_connects_nothing():
    """The canvas draws no arrow for it, so no socket should claim one."""
    first, second = Step(title="a"), Step(title="b")
    second.edges["requires"] = [first.id]
    assert ports([second]) == {second.id: (False, False)}


def test_marks_round_trip_through_json_and_forgive_junk():
    marks = Marks().with_("ends", True).with_("orphans", True)
    assert Marks.from_json(marks.to_json()) == marks
    assert Marks.from_json(None) == Marks()
    assert Marks.from_json({"ends": 1, "nonsense": True}) == Marks(ends=True)
