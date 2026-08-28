"""``dplanner region …`` end to end, over a real workspace. No ``qapp`` fixture."""

import json
from io import StringIO

import pytest

from dplanner.cli.command import CliRegistry
from dplanner.cli.main import run
from dplanner.core.storage.local import LocalStorage
from dplanner.domain.store import ProductStore
from dplanner.modules import default_cli_commands, default_module_formats
from dplanner.modules.project_editor.placement import positions
from dplanner.modules.project_editor.positions import NODE_H, NODE_W
from dplanner.modules.project_editor.regions import read_regions


@pytest.fixture
def cli(workspace):
    registry = CliRegistry()
    registry.register_all(default_cli_commands())

    def invoke(*argv, expect=0):
        out, err = StringIO(), StringIO()
        code = run(
            registry, default_module_formats(), ["--workspace", str(workspace), *argv], out, err
        )
        assert code == expect, f"exit {code}: {err.getvalue()}{out.getvalue()}"
        return out.getvalue() + err.getvalue()

    invoke("project", "create", "Discovery")
    invoke("step", "add", "Discovery", "Design schema")
    invoke("step", "add", "Discovery", "Write migrations")
    invoke("step", "add", "Discovery", "Ship it")
    return invoke


def reload_project(workspace):
    return ProductStore(LocalStorage(workspace)).load().projects[0]


def test_add_around_steps_wraps_them_where_they_sit(cli, workspace):
    said = cli("region", "add", "Discovery", "Database setup", "--steps", "schema", "migrations")
    # The report names what the rectangle actually covers, so a caught neighbour is visible.
    assert "2 steps: Design schema, Write migrations" in said

    library = ProductStore(LocalStorage(workspace)).load()
    project = library.projects[0]
    region = read_regions(project)[0]
    assert region.title == "Database setup"
    placed = positions(library, project)
    schema, migrations, ship = project.steps
    assert region.contains_centre(*placed[schema.id], NODE_W, NODE_H)
    assert region.contains_centre(*placed[migrations.id], NODE_W, NODE_H)
    assert not region.contains_centre(*placed[ship.id], NODE_W, NODE_H)


def test_add_needs_exactly_one_way_of_saying_where(cli):
    assert "either --steps or --rect" in cli("region", "add", "Discovery", "DB", expect=1)
    said = cli(
        "region", "add", "Discovery", "DB", "--steps", "schema", "--rect", "0", "0", "9", "9",
        expect=1,
    )
    assert "either --steps or --rect" in said


def test_add_at_a_rect_and_list(cli):
    cli("region", "add", "Discovery", "Finalize release", "--rect", "400", "8", "320", "240")
    listed = json.loads(cli("region", "list", "Discovery", "--json"))
    assert len(listed["regions"]) == 1
    row = listed["regions"][0]
    assert row["title"] == "Finalize release"
    assert (row["x"], row["y"], row["w"], row["h"]) == (400.0, 8.0, 320.0, 240.0)


def test_list_names_the_steps_each_region_covers(cli):
    cli("region", "add", "Discovery", "Database setup", "--steps", "schema", "migrations")
    cli("region", "add", "Discovery", "Elsewhere", "--rect", "5000", "5000", "100", "100")

    said = cli("region", "list", "Discovery")
    assert "Database setup  (2 steps: Design schema, Write migrations)" in said
    assert "Elsewhere  (empty)" in said

    listed = json.loads(cli("region", "list", "Discovery", "--json"))
    by_title = {row["title"]: row for row in listed["regions"]}
    assert [s["title"] for s in by_title["Database setup"]["steps"]] == [
        "Design schema",
        "Write migrations",
    ]
    assert by_title["Elsewhere"]["steps"] == []


def test_fit_rewraps_in_place_and_keeps_the_id(cli, workspace):
    cli("region", "add", "Discovery", "Database setup", "--rect", "5000", "5000", "100", "100")
    before = read_regions(reload_project(workspace))[0]

    said = cli("region", "fit", "Discovery", "Database setup", "--steps", "schema", "migrations")
    assert "2 steps: Design schema, Write migrations" in said

    library = ProductStore(LocalStorage(workspace)).load()
    project = library.projects[0]
    after = read_regions(project)[0]
    assert after.id == before.id  # a saved layout's rect entry still points at it
    assert after.title == "Database setup"
    placed = positions(library, project)
    schema, migrations, _ship = project.steps
    assert after.contains_centre(*placed[schema.id], NODE_W, NODE_H)
    assert after.contains_centre(*placed[migrations.id], NODE_W, NODE_H)

    assert "no region matches" in cli(
        "region", "fit", "Discovery", "ghost", "--steps", "schema", expect=1
    )


def test_rename_and_delete_find_a_region_by_title_or_id(cli, workspace):
    cli("region", "add", "Discovery", "Database setup", "--rect", "0", "0", "100", "100")
    cli("region", "add", "Discovery", "Finalize release", "--rect", "200", "0", "100", "100")

    cli("region", "rename", "Discovery", "Database setup", "Data layer")
    titles = {region.title for region in read_regions(reload_project(workspace))}
    assert titles == {"Data layer", "Finalize release"}

    region_id = read_regions(reload_project(workspace))[0].id
    cli("region", "delete", "Discovery", region_id[:8])
    assert [r.title for r in read_regions(reload_project(workspace))] == ["Finalize release"]


def test_an_ambiguous_or_unknown_region_is_refused(cli):
    cli("region", "add", "Discovery", "Setup one", "--rect", "0", "0", "100", "100")
    cli("region", "add", "Discovery", "Setup two", "--rect", "200", "0", "100", "100")
    assert "ambiguous" in cli("region", "delete", "Discovery", "Setup", expect=1)
    assert "no region matches" in cli("region", "delete", "Discovery", "ghost", expect=1)
