"""The four aspect editors, as a panel drives them.

The thing worth proving is not that a spin box works. It is the seam: four modules that have
never heard of each other or of the panel end up as four tabs, each writing through the undo
stack, each ignoring the echo of its own write.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand, SetModuleDataCommand
from dplanner.domain.model import Step, TextEdit
from dplanner.modules.estimation.aspect import read as read_estimate


@pytest.fixture
def project(services, make_project):
    project = make_project("Discovery")
    AddNodeCommand(project.id, Step(title="Read the spec")).redo(services.document)
    return project


@pytest.fixture
def panel(step_editor, project):
    """The step editor, opened on a step the way a double-click opens it — the one host
    there is, and the one place these four tabs ever appear together."""
    return step_editor(project.steps[0].id)


# The editors that moved onto the Details tab, by the label the tests know them as.
DETAILS_BLOCKS = {"Estimate": "estimation.details", "Description": "step_description.details"}


def section(panel, label):
    """An aspect editor by its label — a tab of the panel, or a block on its Details tab."""
    labels = [panel.tab_bar.tabText(i) for i in range(panel.tab_bar.count())]
    if label in DETAILS_BLOCKS:
        return panel._pages.widget(labels.index("Details")).block(DETAILS_BLOCKS[label])
    return panel._pages.widget(labels.index(label))


# -- the seam ------------------------------------------------------------------------------


def test_every_registered_aspect_became_a_tab_or_a_details_block(services, panel):
    assert [panel.tab_bar.tabText(i) for i in range(panel.tab_bar.count())] == [
        "Details",
        "Ticket",
        "Docs",
        "Tests",
        "Covers",
        "Agent",
        "Feature",
        "Milestone",
        "GitHub",
    ]
    details = panel._pages.widget(0)
    assert [block.section.id for block in details._blocks] == [
        "step_properties.name",
        "estimation.details",
        "step_description.details",
        "spec.figures",
    ]


# -- estimation ----------------------------------------------------------------------------


def test_an_estimate_is_written_through_the_undo_stack(services, project, panel):
    step = project.steps[0]
    editor = section(panel, "Estimate")
    editor.days.setValue(3.0)
    editor.days.editingFinished.emit()

    assert read_estimate(services.document.step(step.id)) == 3.0
    services.undo.undo()
    assert read_estimate(services.document.step(step.id)) is None


def test_clearing_an_estimate_removes_the_entry(services, project, panel):
    """The box's dash — one step under zero — is "not estimated"; zero itself is a value."""
    from dplanner.modules.estimation.quick_input import UNESTIMATED

    step = project.steps[0]
    editor = section(panel, "Estimate")
    editor.days.setValue(3.0)
    editor.days.editingFinished.emit()
    editor.days.setValue(UNESTIMATED)
    editor.days.editingFinished.emit()
    assert "estimation" not in services.document.step(step.id).module_data
    assert editor.days.text() == "—"


def test_a_step_that_adds_no_time_is_a_claim_with_its_own_chip(services, project, panel):
    """*Does not add time* writes an explicit zero — counted, where an unsized step is
    missing — and the box prints it as 0, not as the dash."""
    step = project.steps[0]
    editor = section(panel, "Estimate")
    editor._input.free.click()
    assert read_estimate(services.document.step(step.id)) == 0.0
    assert editor.days.value() == 0.0 and editor.days.text() == "0 days"
    assert [b.text() for b in editor.chips.buttons() if b.isChecked()] == ["Does not add time"]
    editor.chips.button(4).click()  # a day
    assert read_estimate(services.document.step(step.id)) == 1.0
    assert not editor._input.free.isChecked()


def test_a_change_made_elsewhere_reaches_the_estimate(services, project, panel):
    step = project.steps[0]
    services.undo.push(SetModuleDataCommand(step.id, "estimation", {"days": 5.0, "format": 1}))
    assert section(panel, "Estimate").days.value() == 5.0


def test_a_quick_pick_chip_sets_the_estimate_in_one_gesture(services, project, panel):
    """Most steps are one of a handful of sizes; typing a half day is three gestures."""
    editor = section(panel, "Estimate")
    editor.chips.button(2).click()  # ½ a day — ids count quarter-days.

    assert read_estimate(services.document.step(project.steps[0].id)) == 0.5
    services.undo.undo()
    assert read_estimate(services.document.step(project.steps[0].id)) is None

    editor.chips.button(1).click()  # ¼ — one agent task, about two hours.
    assert read_estimate(services.document.step(project.steps[0].id)) == 0.25


def test_the_chip_matching_the_value_is_the_checked_one(services, project, panel):
    """The row displays the estimate as well as sets it — and says nothing about 4 days."""
    step = project.steps[0]
    services.undo.push(SetModuleDataCommand(step.id, "estimation", {"days": 5.0, "format": 1}))
    editor = section(panel, "Estimate")
    assert [b.text() for b in editor.chips.buttons() if b.isChecked()] == ["5"]

    services.undo.push(SetModuleDataCommand(step.id, "estimation", {"days": 4.0, "format": 1}))
    assert [b.text() for b in editor.chips.buttons() if b.isChecked()] == []


def test_the_editor_ignores_the_echo_of_its_own_write_while_editing(services, project, panel):
    """The origin fix, exercised: without it the editor reloads the field the user is
    still typing in. "Still typing" is focus — an echo landing while the field is *not*
    being edited may reload, and an undo (which never carries the editor's origin)
    always does."""
    editor = section(panel, "Estimate")
    editor.days.setFocus()
    editor.days.setValue(2.0)
    editor.days.editingFinished.emit()
    editor.days.setValue(7.0)  # Typed, not yet committed — the field has focus.
    services.document.set_module_data(
        project.steps[0].id, "estimation", {"days": 2.0, "format": 1}, editor
    )
    assert editor.days.value() == 7.0


# -- ticket --------------------------------------------------------------------------------


def test_a_ticket_is_written_and_undone(services, project, panel):
    step = project.steps[0]
    editor = section(panel, "Ticket")
    editor.edits["key"].setText("WID-14")
    editor.edits["key"].editingFinished.emit()

    assert services.document.step(step.id).module_data["step_ticket"]["key"] == "WID-14"
    services.undo.undo()
    assert "step_ticket" not in services.document.step(step.id).module_data


# -- prose ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "key"),
    [("Description", "step_description"), ("Agent", "step_agent_instruction")],
)
def test_prose_binds_both_ways(services, project, panel, label, key):
    step = project.steps[0]
    editor = section(panel, label)
    editor.edit.setPlainText("# Notes")
    assert services.document.text(step.id, key) == "# Notes"

    services.undo.push(EditText(step.id, key, "# Notes", "# Rewritten"))
    assert editor.edit.toPlainText() == "# Rewritten"


def EditText(node_id, key, before, after):  # noqa: N802 - reads as a constructor
    from dplanner.domain.commands import EditTextCommand

    return EditTextCommand(TextEdit(node_id, key, 0, before, after))


def test_prose_detaches_when_nothing_is_selected(services, project, panel):
    """A binding left pointing at a deselected step would reach the model on the next
    keystroke and fail to find it."""
    editor = section(panel, "Description")
    editor.edit.setPlainText("something")
    panel.show_step(None)
    assert not editor.isEnabled()
    assert editor.edit.toPlainText() == ""


def test_an_undo_reaches_the_estimate_even_while_its_field_is_focused(services, project, panel):
    """The drift this suite once missed: the Estimate editor's hand-rolled echo guard
    swallowed *every* origin-self event, so an undo made with the field focused never
    refreshed it. An undo carries UNDO_ORIGIN, never the editor, so focus must not
    matter."""
    editor = section(panel, "Estimate")
    editor.days.setFocus()
    editor.days.setValue(2.0)
    editor.days.editingFinished.emit()
    # An unrelated edit in between, so the two estimates cannot coalesce into one entry.
    ticket = section(panel, "Ticket")
    ticket.edits["key"].setText("WID-14")
    ticket.edits["key"].editingFinished.emit()
    editor.days.setValue(5.0)
    editor.days.editingFinished.emit()

    services.undo.undo()
    assert editor.days.value() == 2.0
