"""``dplanner layout …`` end to end, over a real library. No ``qapp`` fixture."""

import json

import pytest
from tests.old_canvas import PLAN, SEATS, old_export, plant

from dplanner.domain.store import LibraryStore
from dplanner.modules.canvas.layouts.positions import (
    DATA_FORMAT,
    MODULE_ID,
    NODE_H,
    NODE_W,
    node_size,
    read_position,
    write_member,
    write_position,
)


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
    assert listed["layouts"] == [{"name": "plan", "steps": 2}]

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


# -- the agent's eyes and hands: show, shift, contract, tidy ------------------------------------


def test_show_measures_the_graph(cli):
    said = cli("layout", "show", "Discovery")
    assert "2 steps in 1 columns x 2 rows" in said
    assert "overlaps: none" in said
    assert "gap 44 (1.0 pitch)" in said

    data = json.loads(cli("layout", "show", "Discovery", "--json"))
    assert [row["key"] for row in data["steps"]] == ["S1", "S2"]
    assert data["bounds"] == {"x": 40.0, "y": 40.0, "w": 220.0, "h": 196.0}
    assert data["rows"]["lanes"][1]["pitches"] == 1.0
    assert data["overlaps"] == []


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


def test_contract_closes_a_hole_to_one_gap_and_names_what_stopped_it(cli, cli_library):
    cli("layout", "shift", "Discovery", "--y", "100", "--by", "240")  # S2 three pitches down
    said = cli("layout", "contract", "Discovery", "--y", "300")
    assert "Contracted 1 step up by 240: S2; S2 stops one gap from S1" in said
    assert "gap 44 (1.0 pitch)" in said
    first, second = reload(cli_library).projects[0].steps
    assert read_position(second) == (40.0, 160.0)
    assert read_position(first) is None  # the side it closed up to is untouched

    said = cli("layout", "contract", "Discovery", "--y", "190")  # S2 still lies past it
    assert "Nothing to close: S2 already sits within one gap of S1" in said
    assert read_position(reload(cli_library).projects[0].steps[1]) == (40.0, 160.0)


def test_contract_goes_only_as_far_as_asked(cli, cli_library):
    cli("layout", "shift", "Discovery", "--y", "100", "--by", "240")
    data = json.loads(
        cli("layout", "contract", "Discovery", "--y", "300", "--by", "-120", "--json")
    )
    assert data["by"] == -120.0 and data["moved_by"] == -120.0 and data["stopped"] is None
    assert [(row["key"], row["y"]) for row in data["moved"]] == [("S2", 280.0)]

    data = json.loads(cli("layout", "contract", "Discovery", "--y", "300", "--json"))
    first, second = reload(cli_library).projects[0].steps
    assert data["by"] is None and data["moved_by"] == -120.0
    assert data["stopped"] == [second.id, first.id]


def test_contract_refuses_what_closes_nothing(cli):
    said = cli("layout", "contract", "Discovery", "--y", "9999", expect=1)
    assert "nothing past y=9999 has a step ahead of it in its column" in said
    said = cli("layout", "contract", "Discovery", "--y", "9999", "--by", "-80", expect=1)
    assert "no step's centre lies past y=9999" in said
    said = cli("layout", "contract", "Discovery", "--x", "0", "--by", "3", expect=1)
    assert "snaps to the grid" in said


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


# -- a stack --------------------------------------------------------------------------------------


def stack_on_disk(library_path, project_title, titles, stack_id="s1", seat=None):
    """Membership written the way S17's verbs will: the key on each member, the seat (if
    any) on the first."""
    store = LibraryStore(library_path)
    project = next(p for p in store.load().projects if p.title == project_title)
    ids = [next(step.id for step in project.steps if step.title == t) for t in titles]
    first = write_position(*seat, stack=stack_id) if seat else write_member(stack_id)
    store.set_module_data(ids[0], MODULE_ID, first)
    for step_id in ids[1:]:
        store.set_module_data(step_id, MODULE_ID, write_member(stack_id))
    store.flush({(step_id, "module_data") for step_id in ids})
    store.close()
    return ids


@pytest.fixture
def stacked(cli, cli_library):
    """Kick-off → One → Two → Three → Wrap-up (S1…S5) in a project of their own, with One,
    Two and Three stacked and nothing placed by hand."""
    cli("project", "create", "Stacks")
    for title in ("Kick-off", "One", "Two", "Three", "Wrap-up"):
        cli("step", "add", "Stacks", title)
    for waiter, on in (("One", "Kick-off"), ("Two", "One"), ("Three", "Two"), ("Wrap-up", "Three")):
        cli("step", "link", waiter, on)
    return stack_on_disk(cli_library, "Stacks", ["One", "Two", "Three"])


def column_of(picture, *keys):
    """The line and column each key starts at on the map."""
    lines = picture.splitlines()
    return [
        next((row, line.index(key)) for row, line in enumerate(lines) if key in line.split())
        for key in keys
    ]


def test_show_names_a_stack_and_counts_it_as_one_card(cli, stacked):
    said = cli("layout", "show", "Stacks")
    assert "5 steps in 3 columns x 2 rows" in said
    assert "  2  x 340..592  [S2 S3 S4]" in said
    assert said.rstrip().endswith("stacks:\n  s1  frame 340,40 to 592,356  S2 S3 S4")

    data = json.loads(cli("layout", "show", "Stacks", "--json"))
    assert data["stacks"][0]["id"] == "s1" and data["stacks"][0]["steps"] == stacked
    assert [row["stack"] for row in data["steps"]] == [None, "s1", "s1", "s1", None]
    assert [row["wave"] for row in data["steps"]] == [1, 2, 2, 2, 3]
    assert data["columns"]["lanes"][1]["steps"] == stacked
    assert data["overlaps"] == []


def test_the_map_draws_a_stack_as_a_column_a_row_per_member(cli, cli_library, stacked):
    picture = cli("layout", "show", "Stacks", "--map")
    (row, at), *rest = column_of(picture, "S2", "S3", "S4")
    assert rest == [(row + 1, at), (row + 2, at)]
    # The flow centres Kick-off and Wrap-up on the stack: drawn beside its middle, not under it.
    assert [line for line, _at in column_of(picture, "S1", "S5")] == [row + 1, row + 1]

    stack_on_disk(cli_library, "Stacks", ["Kick-off", "One", "Two", "Three", "Wrap-up"], "s2")
    picture = cli("layout", "show", "Stacks", "--map")
    assert [line.split() for line in picture.splitlines()[:5]] == [
        ["S1"],
        ["S2"],
        ["S3"],
        ["S4"],
        ["S5"],
    ]


def test_shift_carries_a_stack_whole_by_its_frame(cli, cli_library, stacked):
    # A cut through the stack's column, left of its frame's centre: the stack goes with the
    # far side, first member and all.
    said = cli("layout", "shift", "Stacks", "--x", "400", "--by", "120")
    assert "Shifted 4 steps right by 120: S2 S3 S4 S5" in said
    steps = {step.title: step for step in reload(cli_library).projects[-1].steps}
    assert read_position(steps["One"]) == (476.0, 56.0)
    assert read_position(steps["Two"]) is None and read_position(steps["Three"]) is None

    said = cli("layout", "shift", "Stacks", "--x", "0", "--by", "80", "--steps", "S3")
    assert "Shifted 3 steps right by 80: S2 S3 S4" in said


def test_stack_list_names_each_stack_and_what_breaks_one(cli, stacked):
    assert cli("stack", "list", "Stacks").strip() == "s1  S2 S3 S4"
    data = json.loads(cli("stack", "list", "Stacks", "--json"))
    assert data["stacks"] == [
        {
            "id": "s1",
            "steps": [
                {"id": step_id, "key": key, "title": title}
                for step_id, key, title in zip(
                    stacked, ("S2", "S3", "S4"), ("One", "Two", "Three"), strict=True
                )
            ],
            "broken": None,
        }
    ]
    cli("step", "unlink", "Two", "One")
    said = cli("stack", "list", "Stacks").strip()
    assert said == "s1  S2 S3 S4 — broken: S3 does not wait on S2"
    assert cli("stack", "list", "Discovery").strip() == "no stacks"


# -- a project saved with regions ----------------------------------------------------------------


@pytest.fixture
def old(cli, cli_library):
    """Discovery, three steps, as a build with regions left it (``tests/old_canvas.py``)."""
    cli("step", "add", "Discovery", "Ship it")
    return plant(cli_library, "Discovery")


def assert_seated(steps, seats):
    """Every card where ``seats`` puts it, at the size ``SEATS`` gave it."""
    for step, (x, y), (_x, _y, size) in zip(steps, seats, SEATS, strict=True):
        assert read_position(step) == (x, y), step.title
        assert node_size(step) == (size or (NODE_W, NODE_H)), step.title


def assert_regionless(project, directory):
    entry = project.module_data[MODULE_ID]
    assert entry["format"] == DATA_FORMAT.version
    assert set(entry["layouts"]) == {"Plan", "Earlier"}
    assert all(
        step.module_data[MODULE_ID]["format"] == DATA_FORMAT.version for step in project.steps
    )
    for written in directory.rglob(f"{MODULE_ID}.json"):
        assert "regions" not in written.read_text(), written


def test_a_project_saved_with_regions_opens_without_them(cli, cli_library, workspace, old):
    assert "Plan  (3 steps)" in cli("layout", "list", "Discovery")
    project = reload(cli_library).projects[0]
    assert_regionless(project, workspace / "discovery")
    assert_seated(project.steps, [seat[:2] for seat in SEATS])


def test_an_old_project_is_measured_and_mapped(cli, old):
    data = json.loads(cli("layout", "show", "Discovery", "--json"))
    assert [(row["x"], row["y"], row["w"]) for row in data["steps"]] == [
        (40.0, 56.0, NODE_W),
        (320.0, 48.0, 264.0),
        (640.0, 56.0, NODE_W),
    ]
    assert set(data) == {
        "project",
        "steps",
        "bounds",
        "waves",
        "overlaps",
        "columns",
        "rows",
        "stacks",
    }
    assert cli("layout", "show", "Discovery", "--map").splitlines()[0].split() == [
        "S1",
        "S2",
        "S3",
    ]


def test_an_old_layout_applies_without_its_regions(cli, cli_library, old):
    assert json.loads(cli("layout", "apply", "Discovery", "Plan", "--json"))["moved"] == 3
    assert_seated(reload(cli_library).projects[0].steps, PLAN)
    cli("layout", "apply", "Discovery", "Earlier")
    assert_seated(reload(cli_library).projects[0].steps, [seat[:2] for seat in SEATS])


def test_an_old_project_reports_without_its_regions(cli, old):
    page = cli("report", "html", "Discovery")
    assert '<svg class="graph"' in page
    assert "Database setup" not in page and 'class="region"' not in page


def test_an_old_export_imports_without_its_regions(cli, cli_stdin, cli_library, workspace, old):
    document = old_export(json.loads(cli("project", "export", "Discovery")))
    cli_stdin("project", "import", "--title", "Imported", stdin=json.dumps(document))
    cli("layout", "list", "Imported")  # The next open migrates what the import wrote.
    imported = next(p for p in reload(cli_library).projects if p.title == "Imported")
    assert_regionless(imported, workspace / "imported")
    assert_seated(imported.steps, [seat[:2] for seat in SEATS])


# -- Wave view, headless ----------------------------------------------------------------------


def estimated(cli, days):
    for title, count in days.items():
        cli("estimate", "set", title, "--days", str(count))


def test_sorting_into_waves_writes_what_keep_this_arrangement_writes(cli, cli_library, stacked):
    """The headless form of *Keep This Arrangement* (N41): the same function, the same
    days, so the window and the terminal keep one arrangement."""
    from dplanner.modules.canvas.layouts.placement import positions
    from dplanner.modules.canvas.layouts.sorts import waves
    from dplanner.planning.estimate import read as days_for

    estimated(cli, {"Kick-off": 1, "Two": 2})
    # Three seats: a stack's is its first member's, and its column is derived from it.
    assert "waves: 3 steps arranged" in cli("layout", "sort", "Stacks", "waves")
    library = reload(cli_library)
    project = next(p for p in library.projects if p.title == "Stacks")
    assert positions(library, project) == waves(library, project, days_for=days_for)


def test_show_says_when_each_wave_runs(cli, stacked):
    from dplanner.modules.canvas.layouts.sorts import EN_DASH

    estimated(cli, {"Kick-off": 1, "One": 1, "Two": 2, "Three": 0.5, "Wrap-up": 1})
    said = cli("layout", "show", "Stacks")
    # A stack runs its members one after another: One, Two and Three take 3.5 days.
    assert f"  1 {EN_DASH} 4.5 d  S2 S3 S4\n" in said
    assert f"  4.5 {EN_DASH} 5.5 d  S5\n" in said
    data = json.loads(cli("layout", "show", "Stacks", "--json"))
    assert [(w["wave"], w["start"], w["finish"]) for w in data["waves"]] == [
        (1, 0.0, 1.0),
        (2, 1.0, 4.5),
        (3, 4.5, 5.5),
    ]
