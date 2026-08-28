"""``dplanner layout …`` end to end, over a real workspace. No ``qapp`` fixture."""

import json
from io import StringIO

import pytest

from dplanner.cli.command import CliRegistry
from dplanner.cli.main import run
from dplanner.core.storage.local import LocalStorage
from dplanner.domain.store import ProductStore
from dplanner.modules import default_cli_commands, default_module_formats
from dplanner.modules.project_editor.positions import read_position


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
    invoke("step", "add", "Discovery", "Read the spec")
    invoke("step", "add", "Discovery", "Draft the model")
    return invoke


def reload(workspace):
    return ProductStore(LocalStorage(workspace)).load()


def test_save_list_apply_round_trip(cli, workspace):
    assert "created" in cli("layout", "save", "Discovery", "plan")
    assert "updated" in cli("layout", "save", "Discovery", "plan")

    listed = json.loads(cli("layout", "list", "Discovery", "--json"))
    assert listed["layouts"] == [{"name": "plan", "steps": 2, "regions": 0}]

    cli("layout", "apply", "Discovery", "plan")
    library = reload(workspace)
    for step in library.projects[0].steps:
        assert read_position(step) is not None


def test_apply_leaves_a_later_step_unplaced(cli, workspace):
    cli("layout", "save", "Discovery", "plan")
    cli("step", "add", "Discovery", "Ship it")
    cli("layout", "apply", "Discovery", "plan")
    library = reload(workspace)
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
