"""What a copied step is, and how a paste clones it — ``clipboard.py`` alone, with no Qt.

The window's Paste and ``dplanner step duplicate`` both end here, so the rules are pinned
once: fresh ids, links between copies remapped, links outside kept only where they resolve,
a block that keeps its arrangement, and policies that see the whole batch. The two paste
policies the composition root wires are tested beside them for the same reason.
"""

import pytest

from dplanner.domain.model import Library, Project, Step
from dplanner.modules.project_editor.clipboard import (
    StepClip,
    clip,
    from_json,
    paste,
    titles,
    to_json,
)
from dplanner.modules.project_editor.placement import below
from dplanner.modules.project_editor.positions import read_position, write_position


def no_files(node_id, _module_id):
    raise KeyError(node_id)  # A store with no directory for anything: the never-flushed case.


@pytest.fixture
def library():
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    for title in ("Read the spec", "Draft the model", "Ship it"):
        library.add_child(project.id, Step(title=title))
    first, second, third = project.steps
    library.set_edges(second.id, "requires", [first.id])
    library.set_edges(third.id, "requires", [second.id])
    return library


def steps_of(library):
    return library.projects[0].steps


# -- a clip ---------------------------------------------------------------------------------


def test_a_clip_carries_everything_but_the_identity(library):
    first = steps_of(library)[0]
    first.module_data["estimation"] = {"days": 2.0}
    first.module_text["step_description"] = "Read all of it."

    [held] = clip(library, no_files, (), [first.id])

    assert held.id == first.id and held.title == "Read the spec"
    assert held.module_data["estimation"] == {"days": 2.0}
    assert held.module_text == {"step_description": "Read all of it."}
    assert held.files == {}
    held.module_data["estimation"]["days"] = 9.0
    assert first.module_data["estimation"] == {"days": 2.0}  # A copy, not a view.


def test_the_payload_round_trips_bytes():
    held = StepClip(
        id="s1",
        title="One",
        edges={"requires": ["s0"]},
        module_data={"m": {"k": 1}},
        module_text={"m": "prose"},
        files={"m": {"assets/a.png": b"\x89PNG\x00\xff"}},
        x=8.0,
        y=16.0,
    )
    assert from_json(to_json([held])) == [held]
    assert titles([held]) == "One"


def test_anything_else_is_nothing_to_paste():
    assert from_json(b"garbage") == []
    assert from_json(b'{"steps": "no"}') == []
    assert from_json(b'{"steps": [{"title": "no id"}, 4]}') == []
    assert from_json(b"\xff\xfe") == []


# -- a paste --------------------------------------------------------------------------------


def test_a_paste_clones_with_fresh_ids_and_remaps_the_links_between_copies(library):
    project = library.projects[0]
    first, second, third = project.steps
    clips = clip(library, no_files, (), [second.id, third.id])

    command, clones = paste(library, project.id, clips, anchor=None)
    assert all(not s.folder_name for s in clones)  # The store mints a directory of its own.
    command.redo(library)

    copy_second, copy_third = clones
    assert {s.id for s in clones}.isdisjoint({first.id, second.id, third.id})
    assert copy_second.folder_name != second.folder_name
    assert library.step(copy_third.id).edges["requires"] == [copy_second.id]  # Remapped.
    assert library.step(copy_second.id).edges["requires"] == [first.id]  # Kept: it resolves.
    assert command.text() == "Paste 2 Steps"
    command.undo(library)
    assert [s.id for s in project.steps] == [first.id, second.id, third.id]


def test_a_paste_into_another_project_drops_links_it_cannot_resolve(library):
    other = Project(title="Rollout")
    library.add_child(library.id, other)
    second = steps_of(library)[1]

    command, [copy] = paste(
        library, other.id, clip(library, no_files, (), [second.id]), anchor=None
    )
    command.redo(library)

    assert library.project_of(copy.id) is other
    assert "requires" not in library.step(copy.id).edges
    assert command.text() == "Paste Step"


def test_an_edge_kind_this_build_does_not_know_is_not_carried(library):
    project = library.projects[0]
    first = project.steps[0]
    held = StepClip(
        id="elsewhere",
        title="From a newer build",
        edges={"blocks": [first.id], "requires": [first.id]},
        module_data={},
        module_text={},
        files={},
        x=0.0,
        y=0.0,
    )
    command, [copy] = paste(library, project.id, [held], anchor=None)
    command.redo(library)
    assert library.step(copy.id).edges == {"requires": [first.id]}


def test_a_block_keeps_its_arrangement_and_lands_on_the_anchor(library):
    first, second, _third = steps_of(library)
    first.module_data["project_editor"] = write_position(0.0, 0.0)
    second.module_data["project_editor"] = write_position(240.0, 80.0)

    command, clones = paste(
        library,
        library.projects[0].id,
        clip(library, no_files, (), [second.id, first.id]),
        anchor=(1000.0, 496.0),  # On the grid every stored position snaps to.
    )
    command.redo(library)

    copy_second, copy_first = clones
    assert read_position(copy_first) == (1000.0, 496.0)
    assert read_position(copy_second) == (1240.0, 576.0)


def test_without_an_anchor_each_copy_lands_one_row_below_its_original(library):
    first = steps_of(library)[0]
    first.module_data["project_editor"] = write_position(160.0, 240.0)
    command, [copy] = paste(
        library, library.projects[0].id, clip(library, no_files, (), [first.id]), anchor=None
    )
    command.redo(library)
    expected = write_position(*below(160.0, 240.0))
    assert read_position(copy) == (expected["x"], expected["y"])


def test_a_policy_sees_the_clones_and_the_target_project_before_anything_exists(library):
    project = library.projects[0]
    first = project.steps[0]
    first.module_data["secret"] = {"x": 1}
    seen = []

    def policy(target, clones):
        seen.append((target.id, [s.title for s in clones], len(target.steps)))
        clones[0].module_data.pop("secret")

    clips = clip(library, no_files, (), [first.id])
    command, [copy] = paste(library, project.id, clips, anchor=None, policies=(policy,))
    assert seen == [(project.id, ["Read the spec"], 3)]
    command.redo(library)
    assert "secret" not in copy.module_data and first.module_data["secret"] == {"x": 1}


def test_pasting_nothing_is_refused(library):
    with pytest.raises(ValueError):
        paste(library, library.projects[0].id, [], anchor=None)


# -- the two policies the composition root wires ----------------------------------------------


def test_a_copied_test_gets_a_fresh_id_minted_across_the_batch(library):
    from dplanner.modules.testing.aspect import Test, read, remint_for_paste, write

    project = library.projects[0]
    first, second, _third = project.steps
    first.module_data["testing"] = write([Test("T100", "parses"), Test("T101", "renders")])
    second.module_data["testing"] = write([Test("T102", "ships")])
    clones = [Step(title="a"), Step(title="b"), Step(title="c")]
    clones[0].module_data["testing"] = dict(first.module_data["testing"])
    clones[1].module_data["testing"] = dict(second.module_data["testing"])

    remint_for_paste(project, clones)

    assert [t.id for t in read(clones[0])] == ["T103", "T104"]
    assert [t.id for t in read(clones[1])] == ["T105"]
    assert [t.title for t in read(clones[0])] == ["parses", "renders"]
    assert "testing" not in clones[2].module_data


def test_a_copied_agent_run_is_forgotten(library):
    from dplanner.modules.step_agent_run.aspect import MODULE_ID, forget_for_paste, read, write

    clone = Step(title="a")
    clone.module_data[MODULE_ID] = write("working")
    clone.module_data["step_status"] = {"status": "done"}
    forget_for_paste(library.projects[0], [clone])
    assert read(clone) == "" and MODULE_ID not in clone.module_data
    assert clone.module_data["step_status"] == {"status": "done"}
