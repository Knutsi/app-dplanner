"""The three step aspects, through the CLI — the only surface they have yet.

No ``qapp`` fixture: an aspect's ``aspect.py`` and ``cli.py`` are Qt-free by rule, and this
file exercising them without one is what proves it beyond the import check.
"""

import json
from datetime import date
from io import StringIO

import pytest

from dplanner.cli.command import CliRegistry
from dplanner.cli.main import run
from dplanner.core.module_data import stamped
from dplanner.core.storage.local import LocalStorage
from dplanner.domain.seed import create_product
from dplanner.domain.store import ProductStore
from dplanner.modules import default_cli_commands, default_module_formats
from dplanner.modules.estimation.aspect import DATA_FORMAT, read, write


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
    invoke("step", "add", "Discovery", "Read the spec")
    return invoke


def reload(workspace):
    return ProductStore(LocalStorage(workspace)).load()


def first_step(product):
    return product.projects[0].steps[0]


# -- discovery ---------------------------------------------------------------------------------


def test_aspect_list_names_every_aspect(cli):
    ids = {row["id"] for row in json.loads(cli("aspect", "list", "--json"))["aspects"]}
    assert ids == {
        "estimation",
        "spec",
        "step_ticket",
        "step_description",
        "step_agent_instruction",
        "step_status",
        "step_release",
        "step_handoff",
    }


def test_aspect_list_needs_no_product(tmp_path):
    """An agent asks what a step can carry before it has opened anything."""
    registry = CliRegistry()
    registry.register_all(default_cli_commands())
    out = StringIO()
    assert run(registry, default_module_formats(), ["aspect", "list"], out, StringIO()) == 0
    assert "Estimate" in out.getvalue()


# -- estimation --------------------------------------------------------------------------------


def test_an_estimate_is_written_and_read_back(cli, workspace):
    cli("estimate", "set", "Read the spec", "--days", "3")
    assert read(first_step(reload(workspace))) == 3.0


def test_an_integer_estimate_is_stored_as_a_float(cli, workspace):
    """FORMAT.md's normalisation rule, on the module-data axis.

    An int would write as `3` where a reloaded float writes as `3.0`, making a file's bytes
    depend on whether the workspace had been reopened since it was written.
    """
    assert write(3)["days"] == 3.0
    cli("estimate", "set", "Read the spec", "--days", "3")
    path = workspace / "projects/discovery/steps/read-the-spec/modules/estimation.json"
    assert json.loads(path.read_text())["days"] == 3.0
    assert '"days": 3.0' in path.read_text()


def test_unestimated_is_not_zero(cli, workspace):
    """ "We have not estimated this" and "this is free" are different claims."""
    assert read(first_step(reload(workspace))) is None
    assert "1 unestimated" in cli("estimate", "rollup", "Discovery")


def test_clearing_an_estimate_leaves_no_file(cli, workspace):
    modules = workspace / "projects/discovery/steps/read-the-spec/modules"
    cli("estimate", "set", "Read the spec", "--days", "3")
    assert (modules / "estimation.json").is_file()
    cli("estimate", "clear", "Read the spec")
    assert not modules.exists()


def test_a_negative_estimate_is_refused(cli):
    assert "cannot be negative" in cli("estimate", "set", "Read the spec", "--days", "-1", expect=1)


def test_data_newer_than_this_build_is_left_alone(cli, workspace):
    """An older build must keep a shared workspace readable and never overwrite newer data."""
    path = workspace / "projects/discovery/steps/read-the-spec/modules/estimation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    future = {"days": 4.0, "invented_later": True, "format": DATA_FORMAT.version + 5}
    path.write_text(json.dumps(future))

    cli("project", "list")  # Any verb: opening runs the module-data migrations.
    assert json.loads(path.read_text()) == future


def test_a_step_estimation_entry_is_taken_over_and_loses_its_confidence(cli, workspace):
    """`step_estimation` retired into `estimation`; its data comes with, its confidence does not.

    The on-disk id was always the contract between the two modules, which is why the rename
    needs no import and no product-format migration.
    """
    modules = workspace / "projects/discovery/steps/read-the-spec/modules"
    modules.mkdir(parents=True, exist_ok=True)
    (modules / "step_estimation.json").write_text(
        json.dumps({"days": 3.0, "confidence": "low", "format": 1})
    )

    cli("project", "list")  # Any verb: opening runs the module-data migrations.
    assert not (modules / "step_estimation.json").exists()
    assert json.loads((modules / "estimation.json").read_text()) == {"days": 3.0, "format": 1}
    assert read(first_step(reload(workspace))) == 3.0


def test_a_step_estimation_entry_newer_than_that_module_ever_wrote_is_not_taken_over(
    cli, workspace
):
    """Somebody else's newer data is not ours to convert, however familiar the name."""
    modules = workspace / "projects/discovery/steps/read-the-spec/modules"
    modules.mkdir(parents=True, exist_ok=True)
    future = {"days": 3.0, "format": 9}
    (modules / "step_estimation.json").write_text(json.dumps(future))

    cli("project", "list")
    assert json.loads((modules / "step_estimation.json").read_text()) == future
    assert not (modules / "estimation.json").exists()


def test_older_data_is_migrated_by_the_cli_too(cli, workspace, monkeypatch):
    """`migrate_module_data` runs in AppBuilder; a CLI that skipped it would stamp one node
    at the current format while its siblings stayed behind."""
    from dplanner.core.module_data import ModuleDataFormat

    path = workspace / "projects/discovery/steps/read-the-spec/modules/m.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"old": 1}))

    bumped = ModuleDataFormat("m", version=2, migrations=(lambda d: {"new": d["old"]},))
    monkeypatch.setattr("dplanner.modules.default_module_formats", lambda: [bumped])
    registry = CliRegistry()
    registry.register_all(default_cli_commands())
    assert run(registry, [bumped], ["--workspace", str(workspace), "project", "list"]) == 0
    assert json.loads(path.read_text()) == stamped({"new": 1}, 2)


# -- the schedule ------------------------------------------------------------------------------


def test_a_start_date_is_stored_on_the_project_not_the_step(cli, workspace):
    """A step's estimate and a project's start date are one module, on two node kinds."""
    cli("schedule", "start", "Discovery", "--date", "2026-09-07")
    path = workspace / "projects/discovery/modules/estimation.json"
    assert json.loads(path.read_text()) == {"start": "2026-09-07", "format": 1}

    cli("schedule", "start", "Discovery", "--clear")
    assert not path.exists()


def test_a_start_date_has_to_be_a_date(cli):
    assert "ISO-8601" in cli("schedule", "start", "Discovery", "--date", "soon", expect=1)
    assert "either --date or --clear" in cli("schedule", "start", "Discovery", expect=1)


def test_the_schedule_dates_each_step_from_the_start(cli, workspace):
    cli("estimate", "set", "Read the spec", "--days", "3")
    cli("schedule", "start", "Discovery", "--date", "2026-09-07")  # A Monday.

    report = json.loads(cli("schedule", "show", "Discovery", "--json"))
    assert report["start"] == "2026-09-07"
    assert report["finish"] == "2026-09-09"
    assert report["steps"][0] == {
        "index": 1,
        "id": first_step(reload(workspace)).id,
        "title": "Read the spec",
        "days": 3.0,
        "accumulated": 3.0,
        "date": "2026-09-09",
    }


def test_a_project_nobody_dated_starts_today(cli):
    """ "If you start now" is the useful answer to a plan with no date on it — and it is
    derived, so the workspace still holds no start date afterwards."""
    cli("estimate", "set", "Read the spec", "--days", "3")
    shown = json.loads(cli("schedule", "show", "Discovery", "--json"))

    assert shown["start"] == date.today().isoformat()
    assert shown["steps"][0]["date"]


def test_the_schedule_counts_what_nobody_has_sized(cli):
    """A total that silently treats an unestimated step as free understates the plan."""
    assert "1 unestimated" in cli("schedule", "show", "Discovery")
    assert json.loads(cli("schedule", "show", "Discovery", "--json"))["unestimated"] == 1


# -- ticket ------------------------------------------------------------------------------------


def test_a_ticket_records_where_the_work_is_tracked(cli, workspace):
    cli("ticket", "set", "Read the spec", "--system", "jira", "--key", "WID-14")
    entry = first_step(reload(workspace)).module_data["step_ticket"]
    assert entry["key"] == "WID-14"


def test_an_empty_ticket_is_refused_rather_than_stored(cli):
    assert "nothing to set" in cli("ticket", "set", "Read the spec", expect=1)


# -- description -------------------------------------------------------------------------------


def test_prose_is_a_markdown_file_beside_the_step(cli, workspace, tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("# Read it\n\nTwice.\n")
    cli("describe", "set", "Read the spec", "--file", str(source))

    document = workspace / "projects/discovery/steps/read-the-spec/modules/step_description.md"
    assert document.read_text() == "# Read it\n\nTwice.\n"
    assert first_step(reload(workspace)).module_text["step_description"].startswith("# Read it")


def test_an_image_lands_in_the_modules_file_area(cli, workspace, tmp_path):
    image = tmp_path / "diagram.png"
    image.write_bytes(b"\x89PNG-pretend")
    printed = cli("describe", "attach", "Read the spec", str(image))

    name = printed.splitlines()[0]
    assert name.startswith("assets/") and name.endswith(".png")
    area = workspace / "projects/discovery/steps/read-the-spec/modules/step_description"
    assert (area / name).read_bytes() == b"\x89PNG-pretend"
    assert json.loads(cli("describe", "assets", "Read the spec", "--json"))["assets"] == [name]


def test_the_same_image_twice_is_one_file(cli, workspace, tmp_path):
    """Content-addressed, so re-attaching is a no-op and a markdown link never churns."""
    for name in ("a.png", "b.png"):
        image = tmp_path / name
        image.write_bytes(b"identical bytes")
        cli("describe", "attach", "Read the spec", str(image))
    assert len(json.loads(cli("describe", "assets", "Read the spec", "--json"))["assets"]) == 1


def test_prose_and_assets_survive_a_round_trip(cli, workspace, tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("# Kept\n")
    image = tmp_path / "diagram.png"
    image.write_bytes(b"png")
    cli("describe", "set", "Read the spec", "--file", str(source))
    cli("describe", "attach", "Read the spec", str(image))

    # Any later verb reopens, rewrites the node, and must leave both untouched.
    cli("step", "rename", "Read the spec", "--title", "Read the whole spec")
    assert "# Kept" in cli("describe", "show", "Read the whole spec")
    assert json.loads(cli("describe", "assets", "Read the whole spec", "--json"))["assets"]
