"""The feature aspect: the marker on disk, its CLI, and the Type toggle.

There is no section fixture, because there is no Feature tab: what a feature gathers is
rendered by the tests module, which owns lists of tests. See ``test_testing.py``.
"""

import json

import pytest

from dplanner.domain.model import Step
from dplanner.modules.step_feature.aspect import MODULE_ID, read, summary, write

# -- the aspect, with no application at all ----------------------------------------------------


def test_absence_reads_as_not_a_feature():
    assert read(Step(title="A")) is False
    assert summary(Step(title="A")) == ""


def test_the_marker_is_the_whole_shape():
    step = Step(title="A")
    step.module_data[MODULE_ID] = write(True)
    assert read(step) is True
    assert summary(step) == "feature"


def test_off_writes_nothing():
    """Absence encodes the default: not a feature, no file."""
    assert write(False) == {}


# -- the CLI -----------------------------------------------------------------------------------


@pytest.fixture
def cli(cli):
    """The shared CLI over a seeded project — the conftest fixture, pre-populated."""
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Build the core")
    cli("step", "add", "Discovery", "Bulk import", "--after", "Build the core")
    return cli


def test_set_and_clear(cli, workspace):
    cli("feature", "set", "Bulk import")
    entry = workspace / "discovery" / "steps" / "bulk-import" / "modules" / "step_feature.json"
    assert json.loads(entry.read_text())["on"] is True
    cli("feature", "clear", "Bulk import")
    assert not entry.exists()


def test_setting_twice_is_success(cli):
    cli("feature", "set", "Bulk import")
    # Already set is success — state-setting verbs must survive batches.
    assert "already a feature" in cli("feature", "set", "Bulk import")


def test_clearing_a_step_that_is_not_a_feature_says_so(cli):
    assert "not a feature" in cli("feature", "clear", "Build the core")


def test_list_is_the_features_in_working_order(cli):
    cli("feature", "set", "Bulk import")
    rows = json.loads(cli("feature", "list", "Discovery", "--json"))["features"]
    assert [row["title"] for row in rows] == ["Bulk import"]
    assert "Bulk import" in cli("feature", "list", "Discovery")
    cli("feature", "clear", "Bulk import")
    assert "No features marked yet." in cli("feature", "list", "Discovery")


# -- the Type toggle ---------------------------------------------------------------------------


def select(services, step):
    from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri

    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("step", step.id)),))


@pytest.fixture
def step(services, make_project):
    from dplanner.domain.commands import AddNodeCommand

    project = make_project("Discovery")
    step = Step(title="Bulk import")
    AddNodeCommand(project.id, step).redo(services.document)
    return step


def test_the_feature_toggle_sits_in_the_type_submenu(services):
    spec = services.actions.spec("feature.toggle")
    assert spec.menu == "Step" and spec.group == "type" and spec.submenu == "Type"


def test_a_feature_shows_checked_and_a_plain_step_not(services, step):
    select(services, step)
    context = services.context.current()
    assert services.actions.spec("feature.toggle").state(context).checked is False
    services.document.set_module_data(step.id, MODULE_ID, write(True))
    assert services.actions.spec("feature.toggle").state(context).checked is True


def test_toggling_is_one_undoable_command_either_way(services, step):
    select(services, step)
    services.actions.run("feature.toggle", services.context.current())
    assert read(step) is True
    services.actions.run("feature.toggle", services.context.current())
    assert read(step) is False
    services.undo.undo()
    assert read(step) is True
