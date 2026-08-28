"""The release aspect: the label on disk, its CLI, the Release tab, and the Type toggle."""

import json
from io import StringIO

import pytest

from dplanner.cli.command import CliRegistry
from dplanner.cli.main import run
from dplanner.core.storage.local import LocalStorage
from dplanner.domain.model import Step
from dplanner.domain.seed import create_product
from dplanner.modules import default_cli_commands, default_module_formats
from dplanner.modules.step_release.aspect import (
    MODULE_ID,
    next_release_label,
    read,
    summary,
    write,
)

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


# -- the generated label -----------------------------------------------------------------------


def test_the_first_release_is_v1():
    assert next_release_label([]) == "v1"
    assert next_release_label(["", "  "]) == "v1"


def test_the_next_label_increments_the_highest():
    assert next_release_label(["v1", "v2"]) == "v3"
    assert next_release_label(["v2", "v1"]) == "v3"


def test_dotted_labels_keep_their_shape():
    assert next_release_label(["v1.0"]) == "v2.0"
    assert next_release_label(["v1.2.3"]) == "v2.0.0"


def test_the_prefix_is_preserved():
    assert next_release_label(["release 4"]) == "release 5"


def test_non_numeric_labels_fall_back_to_counting():
    assert next_release_label(["MVP"]) == "v2"
    assert next_release_label(["MVP", "Beta"]) == "v3"


def test_mixed_labels_follow_the_numbered_ones():
    assert next_release_label(["MVP", "v1"]) == "v2"


def test_a_generated_label_never_collides():
    labels = ["beta 1", "beta 2"]
    assert next_release_label(labels) not in labels


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


def test_set_without_label_generates_the_next_one(cli, workspace):
    cli("release", "set", "Build the core")
    cli("release", "set", "Ship the beta")
    steps = workspace / "projects" / "discovery" / "steps"
    first = json.loads((steps / "build-the-core" / "modules" / "step_release.json").read_text())
    second = json.loads((steps / "ship-the-beta" / "modules" / "step_release.json").read_text())
    assert first["label"] == "v1"
    assert second["label"] == "v2"


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


# -- the Type toggle ---------------------------------------------------------------------------


def select(services, step):
    from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri

    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("step", step.id)),))


@pytest.fixture
def second_step(services, panel_step):
    from dplanner.domain.commands import AddNodeCommand

    product = services.document
    project = product.project_of(panel_step.id)
    step = Step(title="Build the core")
    AddNodeCommand(project.id, step).redo(product)
    return step


def test_the_release_toggle_action_exists(services):
    spec = services.actions.spec("release.toggle")
    assert spec.menu == "Step" and spec.group == "type" and spec.submenu == "Type"


def test_a_release_step_shows_checked_and_a_plain_one_not(services, panel_step):
    select(services, panel_step)
    context = services.context.current()
    assert services.actions.spec("release.toggle").state(context).checked is False
    services.document.set_module_data(panel_step.id, MODULE_ID, write("MVP"))
    assert services.actions.spec("release.toggle").state(context).checked is True


def test_toggling_on_generates_the_next_label_undoably(services, panel_step, second_step):
    services.document.set_module_data(second_step.id, MODULE_ID, write("v1"))
    select(services, panel_step)
    services.actions.run("release.toggle", services.context.current())
    assert read(panel_step) == "v2"
    services.undo.undo()
    assert read(panel_step) == ""


def test_toggling_off_asks_first_and_clears(services, panel_step, monkeypatch):
    import dplanner.modules.step_release.module as release_module

    services.document.set_module_data(panel_step.id, MODULE_ID, write("MVP"))
    asked = []
    monkeypatch.setattr(
        release_module, "confirm", lambda *args: asked.append(args) or True
    )
    select(services, panel_step)
    services.actions.run("release.toggle", services.context.current())
    assert asked and read(panel_step) == ""
    services.undo.undo()
    assert read(panel_step) == "MVP"


def test_a_declined_confirm_changes_nothing(services, panel_step, monkeypatch):
    import dplanner.modules.step_release.module as release_module

    services.document.set_module_data(panel_step.id, MODULE_ID, write("MVP"))
    monkeypatch.setattr(release_module, "confirm", lambda *_args: False)
    select(services, panel_step)
    services.actions.run("release.toggle", services.context.current())
    assert read(panel_step) == "MVP"
    assert not services.undo.can_undo()


def test_with_no_step_selected_the_toggle_is_disabled(services):
    from dplanner.framework.context import SCOPE_SELECTION

    services.context.set_scope(SCOPE_SELECTION, ())
    state = services.actions.spec("release.toggle").state(services.context.current())
    assert not state.enabled
