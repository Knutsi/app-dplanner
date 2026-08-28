"""``dplanner region …`` end to end, over a real workspace. No ``qapp`` fixture."""

import json
from io import StringIO

import pytest

from dplanner.cli.command import CliRegistry
from dplanner.cli.main import run
from dplanner.core.storage.local import LocalStorage
from dplanner.domain.seed import create_product
from dplanner.domain.store import ProductStore
from dplanner.modules import default_cli_commands, default_module_formats
from dplanner.modules.project_editor.layout import positions
from dplanner.modules.project_editor.positions import NODE_H, NODE_W
from dplanner.modules.project_editor.regions import read_regions


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "widget"
    create_product(LocalStorage(root))
    return root


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
    assert "2 steps inside" in said

    product = ProductStore(LocalStorage(workspace)).load()
    project = product.projects[0]
    region = read_regions(project)[0]
    assert region.title == "Database setup"
    placed = positions(product, project)
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
