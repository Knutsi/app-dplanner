"""``dplanner layout …`` end to end, over a real library. No ``qapp`` fixture."""

import json

import pytest

from dplanner.domain.store import LibraryStore
from dplanner.modules.project_editor.positions import read_position


@pytest.fixture
def cli(cli):
    """The shared CLI, with a two-step project already in place."""
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Read the spec")
    cli("step", "add", "Discovery", "Draft the model")
    return cli


def reload(library_path):
    return LibraryStore(library_path).load()


def test_save_list_apply_round_trip(cli, cli_library):
    assert "created" in cli("layout", "save", "Discovery", "plan")
    assert "updated" in cli("layout", "save", "Discovery", "plan")

    listed = json.loads(cli("layout", "list", "Discovery", "--json"))
    assert listed["layouts"] == [{"name": "plan", "steps": 2, "regions": 0}]

    cli("layout", "apply", "Discovery", "plan")
    library = reload(cli_library)
    for step in library.projects[0].steps:
        assert read_position(step) is not None


def test_apply_leaves_a_later_step_unplaced(cli, cli_library):
    cli("layout", "save", "Discovery", "plan")
    cli("step", "add", "Discovery", "Ship it")
    cli("layout", "apply", "Discovery", "plan")
    library = reload(cli_library)
    placed = [read_position(step) for step in library.projects[0].steps]
    assert placed[0] is not None and placed[1] is not None
    assert placed[2] is None  # the layout never saw it, so it keeps its automatic seat


def test_apply_refuses_an_unknown_name(cli):
    said = cli("layout", "apply", "Discovery", "ghost", expect=1)
    assert "no layout named" in said


def test_rename_refuses_a_collision(cli):
    cli("layout", "save", "Discovery", "one")
    cli("layout", "save", "Discovery", "two")
    said = cli("layout", "rename", "Discovery", "one", "two", expect=1)
    assert "already exists" in said
    cli("layout", "rename", "Discovery", "one", "three")
    listed = json.loads(cli("layout", "list", "Discovery", "--json"))
    assert {row["name"] for row in listed["layouts"]} == {"three", "two"}


def test_delete_forgets_the_layout(cli):
    cli("layout", "save", "Discovery", "plan")
    cli("layout", "delete", "Discovery", "plan")
    assert "no saved layouts" in cli("layout", "list", "Discovery")
    assert "no layout named" in cli("layout", "delete", "Discovery", "plan", expect=1)


# -- the agent's eyes and hands: show, shift, tidy ----------------------------------------------


def test_show_measures_the_graph(cli):
    said = cli("layout", "show", "Discovery")
    assert "2 steps in 1 columns x 2 rows" in said
    assert "overlaps: none" in said
    assert "gap 44 (1.0 pitch)" in said
    assert "regions: none" in said

    data = json.loads(cli("layout", "show", "Discovery", "--json"))
    assert [row["key"] for row in data["steps"]] == ["S1", "S2"]
    assert data["bounds"] == {"x": 40.0, "y": 40.0, "w": 220.0, "h": 196.0}
    assert data["rows"]["lanes"][1]["pitches"] == 1.0
    assert data["overlaps"] == [] and data["regions"] == []


def test_show_draws_a_map(cli):
    said = cli("layout", "show", "Discovery", "--map")
    assert said.splitlines()[:2] == ["S1", "S2"]
    assert "one cell = one column pitch" in said
    data = json.loads(cli("layout", "show", "Discovery", "--map", "--json"))
    assert data["map"] == "S1\nS2"


def test_shift_pushes_the_side_past_the_cut(cli, cli_library):
    said = cli("layout", "shift", "Discovery", "--y", "100", "--by", "120")
    assert "Shifted 1 step down by 120: S2" in said
    assert "gap 164 (2.0 pitches)" in said
    first, second = reload(cli_library).projects[0].steps
    assert read_position(second) == (40.0, 280.0)
    assert read_position(first) is None  # the near side is untouched, as the canvas leaves it

    said = cli("layout", "shift", "Discovery", "--y", "100", "--by", "-40")
    assert "Shifted 1 step up by 40: S1" in said
    assert read_position(reload(cli_library).projects[0].steps[0]) == (40.0, 0.0)


def test_shift_moves_only_the_named_steps_and_snaps_the_distance(cli, cli_library):
    said = cli("layout", "shift", "Discovery", "--x", "9999", "--by", "300", "--steps", "S1")
    assert "Shifted 1 step right by 304: S1" in said  # 300 is not on the 8-point grid
    data = json.loads(cli("layout", "show", "Discovery", "--json"))
    assert [(row["x"], row["y"]) for row in data["steps"]] == [(344.0, 40.0), (40.0, 160.0)]


def test_shift_refuses_what_moves_nothing(cli):
    assert "moves nothing" in cli("layout", "shift", "Discovery", "--x", "0", "--by", "0", expect=1)
    said = cli("layout", "shift", "Discovery", "--x", "0", "--by", "3", expect=1)
    assert "snaps to the grid" in said
    said = cli("layout", "shift", "Discovery", "--x", "9999", "--by", "80", expect=1)
    assert "no step's centre lies past x=9999" in said
    said = cli(
        "layout", "shift", "Discovery", "--x", "0", "--by", "80", "--steps", "ghost", expect=1
    )
    assert "ghost" in said


def test_tidy_resolves_an_overlap_and_is_idempotent(cli, cli_library):
    cli("layout", "shift", "Discovery", "--y", "0", "--by", "-120", "--steps", "S2")  # onto S1
    assert "overlaps: S1 x S2" in cli("layout", "show", "Discovery")

    said = cli("layout", "tidy", "Discovery")
    assert "Tidy: 1 of 2 steps moved; 1 columns x 2 rows; no overlaps; widest gap 1.0 pitch" in said
    first, second = reload(cli_library).projects[0].steps
    assert read_position(first) == (40.0, 40.0) and read_position(second) == (40.0, 160.0)

    data = json.loads(cli("layout", "tidy", "Discovery", "--json"))
    assert data["moved"] == 0 and data["gap"] == 2 and data["overlaps"] == []
    assert "--gap needs at least 1 pitch" in cli(
        "layout", "tidy", "Discovery", "--gap", "0", expect=1
    )
