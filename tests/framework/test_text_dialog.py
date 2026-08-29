"""Expanding an editor is a second binding, not a copy.

The dialog binds the same ``TextField`` a panel editor is bound to; each binding sees the
other's commands as foreign changes, so the two editors track each other keystroke for
keystroke and one undo reverts both. Nothing lives only in the dialog — closing it can
lose nothing.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.fields import ModuleTextField
from dplanner.domain.model import Step
from dplanner.framework.prose_section import ProseSection
from dplanner.framework.text_dialog import ExpandedTextDialog

MODULE_ID = "step_description"


@pytest.fixture
def step(services, make_project):
    project = make_project("Discovery")
    step = Step(title="Deploy")
    AddNodeCommand(project.id, step).redo(services.document)
    return step


@pytest.fixture
def section(app, services, step):
    def field_for(target_id):
        if not services.document.has(target_id):
            return None
        return ModuleTextField(services.document, target_id, MODULE_ID)

    section = ProseSection(field_for, services.undo, "What this step is.")
    section.show_target(step.id)
    yield section
    section.dispose()


def dialog_for(services, step, parent=None):
    return ExpandedTextDialog(
        ModuleTextField(services.document, step.id, MODULE_ID),
        services.undo,
        title="Description",
        parent=parent,
    )


def test_both_editors_track_each_other_and_one_undo_reverts_both(services, step, section):
    dialog = dialog_for(services, step)
    dialog.edit.textCursor().insertText("Written large.")
    assert services.document.text(step.id, MODULE_ID) == "Written large."
    assert section.edit.toPlainText() == "Written large."

    # Moving focus between the editors ends the typing burst; emitted here directly
    # because the offscreen test never really focuses either widget.
    services.undo.break_coalescing()
    cursor = section.edit.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    cursor.insertText(" Refined inline.")
    assert dialog.edit.toPlainText() == "Written large. Refined inline."

    services.undo.undo()
    assert section.edit.toPlainText() == "Written large."
    assert dialog.edit.toPlainText() == "Written large."
    dialog.dispose()


def test_dispose_detaches_the_dialog_binding(services, step, section):
    dialog = dialog_for(services, step)
    dialog.dispose()
    section.edit.setPlainText("After the dialog closed.")
    assert dialog.edit.toPlainText() == ""  # No longer listening.
    assert services.document.text(step.id, MODULE_ID) == "After the dialog closed."


def test_the_expand_button_follows_whether_there_is_a_document(services, step, section):
    assert section.expand_button.isEnabled()
    section.show_target(None)
    assert not section.expand_button.isEnabled()


def test_the_dialog_parents_to_the_editor_window(app, services, step, section):
    # The nested-modal case: opened from inside the step details dialog, the parent is
    # whatever window hosts the editor — construction must accept it.
    dialog = dialog_for(services, step, parent=section.window())
    assert dialog.parent() is section.window()
    dialog.dispose()
