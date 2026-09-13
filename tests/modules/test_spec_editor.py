"""The Specs tab's editor and its editing sessions.

The editor is the prose stack's — plain text, a highlighter, a markdown strip, and an
arriving file attached beside the document and linked at the caret. So the widget half of
this file tests *behaviour through the tab* rather than a widget of its own: there is no
spec-specific editor left to unit-test, which is the point of the change.

The session tests drive the built application the way ``tests/modules/test_spec.py`` does.
"""

# -- editing sessions in the built application -------------------------------------------------

import pytest

from dplanner.core.png import encode_rgb
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.spec.aspect import MODULE_ID
from dplanner.modules.spec.documents import (
    SpecIndex,
    import_document,
    read_index,
    write_index,
)


def png_bytes() -> bytes:
    return encode_rgb(2, 2, 6, b"\x00" * 12)


@pytest.fixture
def project(make_project):
    return make_project("Discovery")


def imported(services, project, name, data, filename):
    area = services.repo.files(project.id, MODULE_ID)
    existing = read_index(services.document.project(project.id)).documents
    docs, document, _outcome = import_document(area, existing, name, data, filename, "2026-08-27")
    entry = write_index(SpecIndex(documents=docs, assets=[]))
    SetModuleDataCommand(project.id, MODULE_ID, entry).redo(services.document)
    return document


def select(services, project):
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )
    return services.context.current()


def specs_tab(services, project):
    services.actions.run("spec.open", select(services, project))
    return services.tabs.activities()[0]


def current_doc(services, project, name):
    documents = read_index(services.document.project(project.id)).documents
    return next(doc for doc in documents if doc.name == name)


def test_spec_new_creates_selects_and_edits(services, project, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(
        QInputDialog, "getText", staticmethod(lambda *_a, **_k: ("Auth flow", True))
    )
    services.actions.run("spec.new", select(services, project))
    document = current_doc(services, project, "auth-flow")
    assert document.kind == "markdown"
    activity = services.tabs.activities()[0]
    assert activity.is_editing and activity._views.currentWidget() is activity._editor_page
    assert activity._editor.toPlainText().startswith("# Auth flow")
    # Undo removes the index entry (the blob stays, as every replace's does).
    services.undo.undo()
    assert read_index(services.document.project(project.id)).documents == []


def test_a_session_flushes_as_one_replace_and_prunes_its_churn(services, project):
    base = imported(services, project, "auth", b"# Auth\n", "auth.md")
    activity = specs_tab(services, project)
    activity.select_document("auth")  # A markdown row opens in the editor: the session.
    assert activity.is_editing and activity._views.currentWidget() is activity._editor_page
    area = services.repo.files(project.id, MODULE_ID)

    activity._editor.insertPlainText("one ")
    activity._flush_edit()
    first = current_doc(services, project, "auth")
    assert first.file != base.file and first.previous == base.file

    activity._editor.insertPlainText("two ")
    activity._flush_edit()
    second = current_doc(services, project, "auth")
    # Still one replace: previous stays the session base, and the intermediate is pruned.
    assert second.previous == base.file
    assert area.read_bytes(first.file) is None
    assert area.read_bytes(base.file) == b"# Auth\n"

    activity.end_session()
    assert not activity.is_editing
    # One undo entry for the whole session: undo restores the pre-session index.
    services.undo.undo()
    restored = current_doc(services, project, "auth")
    assert restored.file == base.file and area.read_bytes(base.file) == b"# Auth\n"


def test_opening_a_document_without_typing_saves_nothing(services, project):
    base = imported(services, project, "auth", b"# Auth\n", "auth.md")
    activity = specs_tab(services, project)
    activity.select_document("auth")
    activity._flush_edit()
    activity.end_session()
    document = current_doc(services, project, "auth")
    assert document.file == base.file
    assert document.previous is None  # Never replaced: opening is not an edit.


def test_text_edits_too_now_that_nothing_round_trips_it(services, project):
    """Plain text was read-only because a rich-text round-trip handed it back as markdown.
    A plain-text editor round-trips it exactly, so it edits like any other document this
    project owns — with the markdown strip off, because a .txt is text and nothing else."""
    imported(services, project, "guide", b"plain text", "guide.txt")
    imported(services, project, "auth", b"# Auth\n", "auth.md")
    activity = specs_tab(services, project)
    activity.select_document("guide")
    assert activity.is_editing and activity._views.currentWidget() is activity._editor_page
    assert not activity._tools.isVisibleTo(activity._editor_page)
    activity.select_document("auth")
    assert activity.is_editing and activity._tools.isVisibleTo(activity._editor_page)
    assert "spec.edit" not in {spec.id for spec in services.actions.all_specs()}


def test_a_pdf_still_only_renders(services, project):
    """The one document that is not text at all, and so has no editor to open."""
    from tests.cli.spec_helpers import tiny_pdf

    imported(services, project, "book", tiny_pdf("A page of it."), "book.pdf")
    activity = specs_tab(services, project)
    activity.select_document("book")
    assert not activity.is_editing and activity._views.currentWidget() is activity._pdf


def test_the_idle_flush_persists_without_leaving_the_editor(services, project):
    """Nothing waits for a Done: a pause in typing writes the blob and the index, and the
    editor stays where it is, caret and all."""
    base = imported(services, project, "auth", b"# Auth\n", "auth.md")
    activity = specs_tab(services, project)
    activity.select_document("auth")
    activity._editor.insertPlainText("typed ")
    activity._flush_timer.timeout.emit()  # What the pause does.
    saved = current_doc(services, project, "auth")
    assert saved.file != base.file and saved.previous == base.file
    assert activity.is_editing and activity._views.currentWidget() is activity._editor_page
    assert "typed" in activity._editor.toPlainText()


def test_switching_documents_ends_the_session_with_a_flush(services, project):
    imported(services, project, "auth", b"# Auth\n", "auth.md")
    imported(services, project, "other", b"# Other\n", "other.md")
    activity = specs_tab(services, project)
    activity.select_document("auth")
    activity._editor.insertPlainText("typed ")
    activity.select_document("other")
    assert current_doc(services, project, "auth").previous is not None
    # …and the other document has a session of its own now.
    assert activity.is_editing and activity._editor.toPlainText().startswith("# Other")


def test_picking_the_topology_row_ends_the_session(services, project):
    imported(services, project, "auth", b"# Auth\n", "auth.md")
    activity = specs_tab(services, project)
    activity.select_document("auth")
    activity._editor.insertPlainText("typed ")
    activity.select_row(0)
    assert not activity.is_editing
    assert activity._views.currentWidget() is activity._topology_page
    assert current_doc(services, project, "auth").previous is not None


def test_a_foreign_change_to_the_edited_document_reopens_it_as_it_is(services, project):
    imported(services, project, "auth", b"# Auth\n", "auth.md")
    activity = specs_tab(services, project)
    activity.select_document("auth")
    activity._editor.insertPlainText("unsaved ")
    imported(services, project, "auth", b"# Auth v2\n", "auth.md")  # An agent, say.
    # The model is the authority: the foreign replace stands, the unflushed typing is
    # gone, and the document is open again as it now is — a fresh session.
    assert activity.is_editing and activity._views.currentWidget() is activity._editor_page
    body = activity._editor.toPlainText()
    assert "v2" in body and "unsaved" not in body
    assert current_doc(services, project, "auth").previous is not None


def test_a_pasted_image_is_indexed_at_save(services, project):
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QImage

    imported(services, project, "auth", b"# Auth\n", "auth.md")
    activity = specs_tab(services, project)
    activity.select_document("auth")
    mime = QMimeData()
    mime.setImageData(QImage.fromData(png_bytes()))
    activity._editor.insertFromMimeData(mime)
    activity.end_session()
    index = read_index(services.document.project(project.id))
    assert len(index.assets) == 1 and index.assets[0].file.startswith("assets/")
    assert index.assets[0].id == "a1"


def test_closing_the_tab_flushes_the_session(services, project):
    base = imported(services, project, "auth", b"# Auth\n", "auth.md")
    activity = specs_tab(services, project)
    activity.select_document("auth")
    activity._editor.insertPlainText("typed ")
    services.tabs.close_activity(activity)
    saved = current_doc(services, project, "auth")
    assert saved.file != base.file and saved.previous == base.file


def test_the_expanded_window_types_into_the_same_session(services, project, monkeypatch):
    """The dialog shows the editor's own document, so what is typed in the window is what
    the session flushes — there is no copying back, because there was no copy."""
    from dplanner.framework.text_dialog import ExpandedTextDialog

    base = imported(services, project, "auth", b"# Auth\n", "auth.md")
    activity = specs_tab(services, project)
    activity.select_document("auth")

    opened: list[ExpandedTextDialog] = []

    def caught(dialog):
        opened.append(dialog)
        return 0

    monkeypatch.setattr(ExpandedTextDialog, "exec", caught)
    activity._expand.click()
    dialog = opened[0]
    dialog.edit.textCursor().insertText("written in the window\n")
    assert "written in the window" in activity._editor.toPlainText()

    activity.end_session()
    saved = current_doc(services, project, "auth")
    area = services.repo.files(project.id, MODULE_ID)
    assert b"written in the window" in (area.read_bytes(saved.file) or b"")
    assert saved.previous == base.file  # Still one replace, pinned to the session's base.


def test_a_pasted_picture_appears_under_the_editor_at_once(services, project):
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QImage

    imported(services, project, "auth", b"# Auth\n", "auth.md")
    activity = specs_tab(services, project)
    activity.select_document("auth")
    assert activity._figures._files == []
    mime = QMimeData()
    mime.setImageData(QImage.fromData(png_bytes()))
    activity._editor.insertFromMimeData(mime)
    linked = activity._figures._files
    assert len(linked) == 1 and f"![image]({linked[0]})" in activity._editor.toPlainText()
