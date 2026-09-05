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
from dplanner.domain.store import LibraryStore
from dplanner.modules import default_cli_commands, default_module_formats
from dplanner.modules.estimation.aspect import DATA_FORMAT, read, write


@pytest.fixture
def cli(cli):
    """The shared CLI over a seeded project — the conftest fixture, pre-populated."""
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Read the spec")
    return cli


@pytest.fixture
def reload(cli_library):
    return lambda: LibraryStore(cli_library).load()


def first_step(library):
    return library.projects[0].steps[0]


# -- discovery ---------------------------------------------------------------------------------


def test_aspect_list_names_every_aspect(cli):
    ids = {row["id"] for row in json.loads(cli("aspect", "list", "--json"))["aspects"]}
    assert ids == {
        "estimation",
        "github",
        "spec",
        "step_ticket",
        "step_description",
        "docs",
        "docs_compiled",
        "step_agent_instruction",
        "step_agent_run",
        "step_status",
        "step_milestone",
        "step_handoff",
        "step_check",
        "feature",
        "testing",
    }


def test_aspect_list_needs_no_product(tmp_path):
    """An agent asks what a step can carry before it has opened anything."""
    registry = CliRegistry()
    registry.register_all(default_cli_commands())
    out = StringIO()
    assert run(registry, default_module_formats(), ["aspect", "list"], out, StringIO()) == 0
    assert "Estimate" in out.getvalue()


# -- estimation --------------------------------------------------------------------------------


def test_an_estimate_is_written_and_read_back(cli, reload):
    cli("estimate", "set", "Read the spec", "--days", "3")
    assert read(first_step(reload())) == 3.0


def test_an_integer_estimate_is_stored_as_a_float(cli, workspace):
    """FORMAT.md's normalisation rule, on the module-data axis.

    An int would write as `3` where a reloaded float writes as `3.0`, making a file's bytes
    depend on whether the workspace had been reopened since it was written.
    """
    assert write(3)["days"] == 3.0
    cli("estimate", "set", "Read the spec", "--days", "3")
    path = workspace / "discovery/steps/read-the-spec/modules/estimation.json"
    assert json.loads(path.read_text())["days"] == 3.0
    assert '"days": 3.0' in path.read_text()


def test_an_estimate_remembers_what_it_was(cli, reload, workspace):
    """Each write carries the values before it, one row per day they changed — the first
    change of a day only — and `estimate show` reads them back."""
    from datetime import date

    from dplanner.modules.estimation.aspect import read_history, write

    cli("estimate", "set", "Read the spec", "--days", "3")
    cli("estimate", "set", "Read the spec", "--days", "5")
    cli("estimate", "set", "Read the spec", "--days", "4")
    step = first_step(reload())
    assert read(step) == 4.0
    assert read_history(step) == [(date.today(), 3.0)]  # the day's first value, kept
    entry = json.loads(
        (workspace / "discovery/steps/read-the-spec/modules/estimation.json").read_text()
    )
    assert entry == {
        "days": 4.0,
        "history": [{"day": date.today().isoformat(), "days": 3.0}],
        "format": 2,
    }
    said = cli("estimate", "show", "Read the spec")
    assert said.splitlines()[0] == "Read the spec: 4 days"
    assert said.splitlines()[1].startswith("  was 3 days until")
    shown = json.loads(cli("estimate", "show", "Read the spec", "--json"))
    assert shown["days"] == 4.0 and shown["history"] == [
        {"day": date.today().isoformat(), "days": 3.0}
    ]
    # Another day's change adds a row; the same value again adds nothing.
    later = write(6.0, previous=entry, today=date(2030, 1, 2))
    assert later["history"] == [
        {"day": date.today().isoformat(), "days": 3.0},
        {"day": "2030-01-02", "days": 4.0},
    ]
    assert write(6.0, previous=later, today=date(2030, 1, 3)) == later
    # Unsizing leaves nothing behind, history included: an unsized step has no file.
    assert write(None, previous=later) == {}


def test_unestimated_is_not_zero(cli, reload):
    """ "We have not estimated this" and "this is free" are different claims."""
    assert read(first_step(reload())) is None
    assert "1 unestimated" in cli("estimate", "rollup", "Discovery")


def test_clearing_an_estimate_records_that_the_step_has_no_work(cli, workspace):
    """An estimate defaults to *on*, so an absent entry means "not sized yet".

    Removing the entry would leave lint asking; what a person means by clearing it on a
    milestone is that there is no work to size, and that is what gets written.
    """
    import json

    modules = workspace / "discovery/steps/read-the-spec/modules"
    cli("estimate", "set", "Read the spec", "--days", "3")
    assert json.loads((modules / "estimation.json").read_text())["days"] == 3.0
    cli("estimate", "clear", "Read the spec")
    assert json.loads((modules / "estimation.json").read_text())["off"] is True
    findings = json.loads(cli("project", "lint", "--json", expect=1))["findings"]
    assert not [row for row in findings if row["check"] == "estimate.missing"]


def test_clearing_a_description_records_that_the_step_wants_none(cli, workspace):
    import json

    modules = workspace / "discovery/steps/read-the-spec/modules"
    prose = workspace / "prose.md"
    prose.write_text("Prose.")
    cli("describe", "set", "Read the spec", "--file", str(prose))
    cli("describe", "clear", "Read the spec")
    assert json.loads((modules / "step_description.json").read_text())["off"] is True
    assert not (modules / "step_description.md").exists()
    findings = json.loads(cli("project", "lint", "--json", expect=1))["findings"]
    assert not [row for row in findings if row["check"] == "description.missing"]


def test_a_negative_estimate_is_refused(cli):
    assert "cannot be negative" in cli("estimate", "set", "Read the spec", "--days", "-1", expect=1)


def test_data_newer_than_this_build_is_left_alone(cli, workspace):
    """An older build must keep a shared workspace readable and never overwrite newer data."""
    path = workspace / "discovery/steps/read-the-spec/modules/estimation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    future = {"days": 4.0, "invented_later": True, "format": DATA_FORMAT.version + 5}
    path.write_text(json.dumps(future))

    cli("project", "list")  # Any verb: opening runs the module-data migrations.
    assert json.loads(path.read_text()) == future


def test_a_step_estimation_entry_is_taken_over_and_loses_its_confidence(cli, workspace, reload):
    """`step_estimation` retired into `estimation`; its data comes with, its confidence does not.

    The on-disk id was always the contract between the two modules, which is why the rename
    needs no import and no library-format migration.
    """
    modules = workspace / "discovery/steps/read-the-spec/modules"
    modules.mkdir(parents=True, exist_ok=True)
    (modules / "step_estimation.json").write_text(
        json.dumps({"days": 3.0, "confidence": "low", "format": 1})
    )

    cli("project", "list")  # Any verb: opening runs the module-data migrations.
    assert not (modules / "step_estimation.json").exists()
    assert json.loads((modules / "estimation.json").read_text()) == {"days": 3.0, "format": 2}
    assert read(first_step(reload())) == 3.0


def test_a_step_estimation_entry_newer_than_that_module_ever_wrote_is_not_taken_over(
    cli, workspace
):
    """Somebody else's newer data is not ours to convert, however familiar the name."""
    modules = workspace / "discovery/steps/read-the-spec/modules"
    modules.mkdir(parents=True, exist_ok=True)
    future = {"days": 3.0, "format": 9}
    (modules / "step_estimation.json").write_text(json.dumps(future))

    cli("project", "list")
    assert json.loads((modules / "step_estimation.json").read_text()) == future
    assert not (modules / "estimation.json").exists()


def test_older_data_is_migrated_by_the_cli_too(cli, workspace, cli_library, monkeypatch):
    """`migrate_module_data` runs in AppBuilder; a CLI that skipped it would stamp one node
    at the current format while its siblings stayed behind."""
    from dplanner.core.module_data import ModuleDataFormat

    path = workspace / "discovery/steps/read-the-spec/modules/m.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"old": 1}))

    bumped = ModuleDataFormat("m", version=2, migrations=(lambda d: {"new": d["old"]},))
    monkeypatch.setattr("dplanner.modules.default_module_formats", lambda: [bumped])
    registry = CliRegistry()
    registry.register_all(default_cli_commands())
    assert run(registry, [bumped], ["--library", str(cli_library), "project", "list"]) == 0
    assert json.loads(path.read_text()) == stamped({"new": 1}, 2)


# -- the schedule ------------------------------------------------------------------------------


def test_a_start_date_is_stored_on_the_project_not_the_step(cli, workspace):
    """A step's estimate and a project's start date are one module, on two node kinds."""
    cli("schedule", "start", "Discovery", "--date", "2026-09-07")
    path = workspace / "discovery/modules/estimation.json"
    assert json.loads(path.read_text()) == {"start": "2026-09-07", "format": 2}

    cli("schedule", "start", "Discovery", "--clear")
    assert not path.exists()


def test_a_start_date_has_to_be_a_date(cli):
    assert "ISO-8601" in cli("schedule", "start", "Discovery", "--date", "soon", expect=1)
    assert "either --date or --clear" in cli("schedule", "start", "Discovery", expect=1)


def test_the_schedule_dates_each_step_from_the_start(cli, reload):
    cli("estimate", "set", "Read the spec", "--days", "3")
    cli("schedule", "start", "Discovery", "--date", "2026-09-07")  # A Monday.

    report = json.loads(cli("schedule", "show", "Discovery", "--json"))
    assert report["start"] == "2026-09-07"
    assert report["finish"] == "2026-09-09"
    assert report["steps"][0] == {
        "index": 1,
        "id": first_step(reload()).id,
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


def test_a_ticket_records_where_the_work_is_tracked(cli, reload):
    cli("ticket", "set", "Read the spec", "--system", "jira", "--key", "WID-14")
    entry = first_step(reload()).module_data["step_ticket"]
    assert entry["key"] == "WID-14"


def test_an_empty_ticket_is_refused_rather_than_stored(cli):
    assert "nothing to set" in cli("ticket", "set", "Read the spec", expect=1)


# -- description -------------------------------------------------------------------------------


def test_prose_is_a_markdown_file_beside_the_step(cli, workspace, reload, tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("# Read it\n\nTwice.\n")
    cli("describe", "set", "Read the spec", "--file", str(source))

    document = workspace / "discovery/steps/read-the-spec/modules/step_description.md"
    assert document.read_text() == "# Read it\n\nTwice.\n"
    assert first_step(reload()).module_text["step_description"].startswith("# Read it")


def test_an_image_lands_in_the_modules_file_area(cli, workspace, tmp_path):
    image = tmp_path / "diagram.png"
    image.write_bytes(b"\x89PNG-pretend")
    printed = cli("describe", "attach", "Read the spec", str(image))

    name = printed.splitlines()[0]
    assert name.startswith("assets/") and name.endswith(".png")
    area = workspace / "discovery/steps/read-the-spec/modules/step_description"
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
