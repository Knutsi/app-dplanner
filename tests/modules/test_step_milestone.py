"""The milestone aspect: the label on disk, its CLI, the Milestone tab, and the Type toggle."""

import json

import pytest

from dplanner.domain.model import Step
from dplanner.modules.step_milestone.aspect import (
    MODULE_ID,
    next_milestone_label,
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
    assert summary(step) == "milestone MVP"


def test_a_blank_label_writes_nothing():
    """Absence encodes the default: no label, no file."""
    assert write("") == {}
    assert write("   ") == {}


# -- the generated label -----------------------------------------------------------------------


def test_the_first_release_is_v1():
    assert next_milestone_label([]) == "v1"
    assert next_milestone_label(["", "  "]) == "v1"


def test_the_next_label_increments_the_highest():
    assert next_milestone_label(["v1", "v2"]) == "v3"
    assert next_milestone_label(["v2", "v1"]) == "v3"


def test_dotted_labels_keep_their_shape():
    assert next_milestone_label(["v1.0"]) == "v2.0"
    assert next_milestone_label(["v1.2.3"]) == "v2.0.0"


def test_the_prefix_is_preserved():
    assert next_milestone_label(["milestone 4"]) == "milestone 5"


def test_non_numeric_labels_fall_back_to_counting():
    assert next_milestone_label(["MVP"]) == "v2"
    assert next_milestone_label(["MVP", "Beta"]) == "v3"


def test_mixed_labels_follow_the_numbered_ones():
    assert next_milestone_label(["MVP", "v1"]) == "v2"


def test_a_generated_label_never_collides():
    labels = ["beta 1", "beta 2"]
    assert next_milestone_label(labels) not in labels


# -- the CLI -----------------------------------------------------------------------------------


@pytest.fixture
def cli(cli):
    """The shared CLI over a seeded project — the conftest fixture, pre-populated."""
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Build the core")
    cli("step", "add", "Discovery", "Ship the beta", "--after", "Build the core")
    return cli


def test_set_and_clear(cli, workspace):
    cli("milestone", "set", "Ship the beta", "--label", "MVP")
    step_dir = workspace / "discovery" / "steps" / "ship-the-beta"
    entry = json.loads((step_dir / "modules" / "step_milestone.json").read_text())
    assert entry["label"] == "MVP"
    cli("milestone", "clear", "Ship the beta")
    assert not (step_dir / "modules" / "step_milestone.json").exists()


def test_clearing_a_step_that_is_not_a_release_says_so(cli):
    # Already clear is success — state-clearing verbs must survive batches.
    assert "not a milestone" in cli("milestone", "clear", "Build the core")


def test_set_without_label_generates_the_next_one(cli, workspace):
    cli("milestone", "set", "Build the core")
    cli("milestone", "set", "Ship the beta")
    steps = workspace / "discovery" / "steps"
    first = json.loads((steps / "build-the-core" / "modules" / "step_milestone.json").read_text())
    second = json.loads((steps / "ship-the-beta" / "modules" / "step_milestone.json").read_text())
    assert first["label"] == "v1"
    assert second["label"] == "v2"


def test_list_is_the_roadmap_in_working_order(cli):
    cli("milestone", "set", "Ship the beta", "--label", "MVP")
    rows = json.loads(cli("milestone", "list", "Discovery", "--json"))["milestones"]
    assert [(row["label"], row["title"]) for row in rows] == [("MVP", "Ship the beta")]
    text = cli("milestone", "list", "Discovery")
    assert "MVP" in text and "Ship the beta" in text


# -- the takeover from `step_release` ----------------------------------------------------------


def test_a_step_release_entry_becomes_a_milestone_at_open(cli, workspace):
    """`step_release` retired into `step_milestone`; the on-disk id was always the contract.

    A rename costs no library-format migration and no import, and it is one-way: the old
    file is gone after the first open by a build that has the change.
    """
    modules = workspace / "discovery" / "steps" / "ship-the-beta" / "modules"
    modules.mkdir(parents=True, exist_ok=True)
    (modules / "step_release.json").write_text(json.dumps({"label": "MVP", "format": 1}))

    cli("project", "list")  # Any verb: opening runs the module-data migrations.
    assert not (modules / "step_release.json").exists()
    assert json.loads((modules / "step_milestone.json").read_text()) == {
        "label": "MVP",
        "format": 1,
    }


def test_a_milestone_already_written_wins_over_the_retired_entry(cli, workspace):
    """A project half-written by both builds keeps the newer answer."""
    cli("milestone", "set", "Ship the beta", "--label", "v2")
    modules = workspace / "discovery" / "steps" / "ship-the-beta" / "modules"
    (modules / "step_release.json").write_text(json.dumps({"label": "MVP", "format": 1}))

    cli("project", "list")
    assert not (modules / "step_release.json").exists()
    assert json.loads((modules / "step_milestone.json").read_text())["label"] == "v2"


# -- the Milestone tab ---------------------------------------------------------------------------


@pytest.fixture
def panel_step(services, make_project):
    from dplanner.domain.commands import AddNodeCommand

    project = make_project("Discovery")
    step = Step(title="Ship the beta")
    AddNodeCommand(project.id, step).redo(services.document)
    return step


@pytest.fixture
def section(services, panel_step):
    from dplanner.modules.step_milestone.section import MilestoneSection

    section = MilestoneSection(services.document, services.undo)
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

    library = services.document
    project = library.project_of(panel_step.id)
    step = Step(title="Build the core")
    AddNodeCommand(project.id, step).redo(library)
    return step


def test_the_release_toggle_action_exists(services):
    spec = services.actions.spec("milestone.toggle")
    assert spec.menu == "Step" and spec.group == "type" and spec.submenu == "Type"


def test_a_release_step_shows_checked_and_a_plain_one_not(services, panel_step):
    select(services, panel_step)
    context = services.context.current()
    assert services.actions.spec("milestone.toggle").state(context).checked is False
    services.document.set_module_data(panel_step.id, MODULE_ID, write("MVP"))
    assert services.actions.spec("milestone.toggle").state(context).checked is True


def test_toggling_on_generates_the_next_label_undoably(services, panel_step, second_step):
    services.document.set_module_data(second_step.id, MODULE_ID, write("v1"))
    select(services, panel_step)
    services.actions.run("milestone.toggle", services.context.current())
    assert read(panel_step) == "v2"
    services.undo.undo()
    assert read(panel_step) == ""


def test_toggling_off_asks_first_and_clears(services, panel_step, monkeypatch):
    import dplanner.modules.step_milestone.module as release_module

    services.document.set_module_data(panel_step.id, MODULE_ID, write("MVP"))
    asked = []

    def yes(*args: object) -> bool:
        asked.append(args)
        return True

    monkeypatch.setattr(release_module, "confirm", yes)
    select(services, panel_step)
    services.actions.run("milestone.toggle", services.context.current())
    assert asked and read(panel_step) == ""
    services.undo.undo()
    assert read(panel_step) == "MVP"


def test_a_declined_confirm_changes_nothing(services, panel_step, monkeypatch):
    import dplanner.modules.step_milestone.module as release_module

    services.document.set_module_data(panel_step.id, MODULE_ID, write("MVP"))
    monkeypatch.setattr(release_module, "confirm", lambda *_args: False)
    select(services, panel_step)
    services.actions.run("milestone.toggle", services.context.current())
    assert read(panel_step) == "MVP"
    assert not services.undo.can_undo()


def test_with_no_step_selected_the_toggle_is_disabled(services):
    from dplanner.framework.context import SCOPE_SELECTION

    services.context.set_scope(SCOPE_SELECTION, ())
    state = services.actions.spec("milestone.toggle").state(services.context.current())
    assert not state.enabled
