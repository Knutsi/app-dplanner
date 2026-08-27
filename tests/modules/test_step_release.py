"""The release aspect: the label on disk, its CLI, and the Release tab."""

import json
from io import StringIO

import pytest

from dplanner.cli.command import CliRegistry
from dplanner.cli.main import run
from dplanner.core.storage.local import LocalStorage
from dplanner.domain.model import Step
from dplanner.domain.seed import create_product
from dplanner.modules import default_cli_commands, default_module_formats
from dplanner.modules.step_release.aspect import MODULE_ID, read, summary, write

# -- the aspect, with no application at all ----------------------------------------------------


def test_absence_reads_as_not_a_release():
    assert read(Step(title="A")) == ""


def test_write_and_read_round_trip():
    step = Step(title="A")
    step.module_data[MODULE_ID] = write("MVP")
    assert read(step) == "MVP"
    assert summary(step) == "release MVP"


def test_a_blank_label_writes_nothing():
    """Absence encodes the default: no label, no file."""
    assert write("") == {}
    assert write("   ") == {}


# -- the CLI -----------------------------------------------------------------------------------


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
    invoke("step", "add", "Discovery", "Build the core")
    invoke("step", "add", "Discovery", "Ship the beta", "--after", "Build the core")
    return invoke


def test_set_and_clear(cli, workspace):
    cli("release", "set", "Ship the beta", "--label", "MVP")
    step_dir = workspace / "projects" / "discovery" / "steps" / "ship-the-beta"
    entry = json.loads((step_dir / "modules" / "step_release.json").read_text())
    assert entry["label"] == "MVP"
    cli("release", "clear", "Ship the beta")
    assert not (step_dir / "modules" / "step_release.json").exists()


def test_clearing_a_step_that_is_not_a_release_says_so(cli):
    assert "is not a release" in cli("release", "clear", "Build the core", expect=1)


def test_list_is_the_roadmap_in_working_order(cli):
    cli("release", "set", "Ship the beta", "--label", "MVP")
    rows = json.loads(cli("release", "list", "Discovery", "--json"))["releases"]
    assert [(row["label"], row["title"]) for row in rows] == [("MVP", "Ship the beta")]
    text = cli("release", "list", "Discovery")
    assert "MVP" in text and "Ship the beta" in text


# -- the Release tab ---------------------------------------------------------------------------


@pytest.fixture
def panel_step(services):
    from dplanner.domain.commands import AddNodeCommand
    from dplanner.domain.model import Project

    product = services.document
    project = Project(title="Discovery")
    AddNodeCommand(product.id, project).redo(product)
    step = Step(title="Ship the beta")
    AddNodeCommand(project.id, step).redo(product)
    return step


@pytest.fixture
def section(services, panel_step):
    from dplanner.modules.step_release.section import ReleaseSection

    section = ReleaseSection(services.document, services.undo)
    section.show_target(panel_step.id)
    yield section
    section.dispose()


def test_typing_a_label_commits_one_undoable_command(services, panel_step, section):
    section.label.setText("MVP")
    section.label.editingFinished.emit()
    assert read(panel_step) == "MVP"
    services.undo.undo()
    assert read(panel_step) == ""


def test_a_change_from_elsewhere_reaches_the_widget(services, panel_step, section):
    from dplanner.domain.commands import SetModuleDataCommand

    services.undo.push(SetModuleDataCommand(panel_step.id, MODULE_ID, write("v2")))
    assert section.label.text() == "v2"


def test_committing_the_same_value_pushes_nothing(services, panel_step, section):
    section.label.setText("")
    section.label.editingFinished.emit()
    assert not services.undo.can_undo()
