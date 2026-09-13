"""Marks: which ways of looking at the graph are on. The socket derivation they colour
is ``domain/ordering.py``'s ``ports`` — tested there, beside ``graph.orphan``'s reader."""

from dplanner.modules.project_editor.marks import Marks


def test_marks_round_trip_through_json_and_forgive_junk():
    marks = Marks().with_("ends", False).with_("orphans", False)
    assert Marks.from_json(marks.to_json()) == marks
    assert Marks.from_json(None) == Marks()
    assert Marks.from_json({"ends": 0, "nonsense": True}) == Marks(ends=False)


def test_every_mark_is_on_until_somebody_switches_one_off():
    """A socket with nothing on it and a node with nothing at all are the two things a
    graph can be wrong about; a preference that has to be found first helps nobody."""
    assert Marks() == Marks(starts=True, ends=True, orphans=True)
    # A name the stored value does not mention takes the default, so a default that changes
    # reaches somebody who never touched that switch — FORMAT.md's absence rule.
    assert Marks.from_json({"starts": False}) == Marks(starts=False)
    assert Marks.from_json({}) == Marks()
