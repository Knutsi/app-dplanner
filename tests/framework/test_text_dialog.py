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
from dplanner.framework.prose_edit import ProseEdit
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
    return ExpandedTextDialog.over_field(
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


def test_the_expanded_editor_attaches_a_paste_where_the_inline_one_does(services, step):
    """The dialog is handed the same attach callable, so a picture pasted in the big window
    lands in the same area and refreshes the gallery still sitting behind it."""
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QImage

    from dplanner.core.png import encode_rgb
    from dplanner.domain.assets import assets

    def field_for(target_id):
        return ModuleTextField(services.document, target_id, MODULE_ID)

    section = ProseSection(
        field_for, services.undo, "What this step is.", attach_title="Attach to Description"
    )
    section.show_target(step.id)
    section.set_area(lambda: services.repo.files(step.id, MODULE_ID))

    dialog = ExpandedTextDialog.over_field(
        ModuleTextField(services.document, step.id, MODULE_ID),
        services.undo,
        title="Description",
        attach=section.gallery.attach_bytes if section.gallery else None,
    )
    mime = QMimeData()
    mime.setImageData(QImage.fromData(encode_rgb(2, 2, 6, b"\x00" * 12)))
    dialog.edit.insertFromMimeData(mime)

    names = assets(services.repo.files(step.id, MODULE_ID))
    assert len(names) == 1
    # The inline editor tracks it through the foreign-change path, and so does the gallery.
    assert section.edit.toPlainText() == f"![image]({names[0]})"
    assert section.gallery is not None and section.gallery._names == names
    dialog.dispose()
    section.dispose()


def test_over_document_is_two_views_of_one_buffer(app, services):
    """Where the buffer is the authority — the Specs tab's editing session — the dialog
    shows the same QTextDocument, so the two are one document rather than two in step."""
    inline = ProseEdit()
    inline.setPlainText("# Auth\n")
    dialog = ExpandedTextDialog.over_document(
        inline.document(), services.undo, title="Spec", parent=None
    )
    try:
        dialog.edit.textCursor().insertText("body from the dialog\n")
        assert "body from the dialog" in inline.toPlainText()
        inline.textCursor().insertText("and from the page\n")
        assert "and from the page" in dialog.edit.toPlainText()
        # One buffer means one undo history: the dialog undoes what the page typed.
        dialog.edit.undo()
        assert "and from the page" not in inline.toPlainText()
    finally:
        dialog.dispose()
        dialog.deleteLater()
        app.processEvents()
    # The borrowed view is gone; the owner still owns its text and still takes typing.
    inline.textCursor().insertText("after the dialog\n")
    assert "after the dialog" in inline.toPlainText()
    inline.deleteLater()


def test_both_ways_in_carry_the_markdown_strip(app, services, step):
    over_field = dialog_for(services, step)
    inline = ProseEdit()
    over_document = ExpandedTextDialog.over_document(inline.document(), services.undo, title="Spec")
    try:
        for dialog in (over_field, over_document):
            assert [a.text() for a in dialog.tools.verbs()][:2] == ["Bold", "Italic"]
    finally:
        for dialog in (over_field, over_document):
            dialog.dispose()
            dialog.deleteLater()
        inline.deleteLater()
