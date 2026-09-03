"""The spec markdown editor: Qt's round-trip, images through the area, editing sessions.

The widget-only tests build a bare ``SpecMarkdownEditor`` over a real file area — the
first of them pins that PySide6 dispatches ``loadResource`` from the document, which is
the one platform assumption the editor stands on. The session tests drive the built
application the way ``tests/modules/test_spec.py`` does.
"""

from pathlib import Path

import pytest

from dplanner.core.storage.local import LocalStorage
from dplanner.domain.store import ModuleFileArea
from dplanner.modules.spec.documents import attach_asset
from dplanner.modules.spec.editor import SpecMarkdownEditor


def one_pixel_png() -> bytes:
    from PySide6.QtCore import QBuffer
    from PySide6.QtGui import QColor, QImage

    image = QImage(1, 1, QImage.Format.Format_RGB32)
    image.fill(QColor("black"))
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")  # type: ignore[call-overload]  # Stubs say bytes; runtime wants str.
    buffer.close()
    return bytes(buffer.data().data())


@pytest.fixture
def area(tmp_path: Path) -> ModuleFileArea:
    return ModuleFileArea(LocalStorage(tmp_path / "ws"), "modules/spec", lambda _p: None)


@pytest.fixture
def editor(qapp, area):
    widget = SpecMarkdownEditor()
    yield widget
    widget.deleteLater()


# -- the round-trip and the resource seam ------------------------------------------------------


def test_an_area_image_resolves_and_survives_the_round_trip(editor, area):
    """Pins that PySide6 dispatches ``loadResource`` — the editor's one platform bet —
    and that a bare `![](…)` image is not dropped by the exporter (it gains an alt)."""
    asset = attach_asset(area, one_pixel_png(), "dot.png")
    editor.open_markdown(area, f"# Title\n\n![]({asset})\n")
    image = editor.loadResource(2, asset)
    assert image is not None and not image.isNull()
    body = editor.body()
    assert f"![image]({asset})" in body and body.startswith("# Title")


def test_opening_a_document_leaves_it_unmodified(editor, area):
    editor.open_markdown(area, "plain *markdown*\n")
    assert not editor.document().isModified()
    editor.insertPlainText("x")
    assert editor.document().isModified()


# -- images in ---------------------------------------------------------------------------------


def test_pasting_an_image_attaches_and_embeds_it(editor, area):
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QImage

    editor.open_markdown(area, "before\n")
    mime = QMimeData()
    mime.setImageData(QImage.fromData(one_pixel_png()))
    assert editor.canInsertFromMimeData(mime)
    editor.insertFromMimeData(mime)
    names = area.names("assets")
    assert len(names) == 1
    assert f"![image](assets/{names[0]})" in editor.body()
    assert editor.document().isModified()


def test_dropping_an_image_file_attaches_and_embeds_it(editor, area, tmp_path):
    from PySide6.QtCore import QMimeData, QUrl

    path = tmp_path / "diagram.png"
    path.write_bytes(one_pixel_png())
    editor.open_markdown(area, "")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    assert editor.canInsertFromMimeData(mime)
    editor.insertFromMimeData(mime)
    names = area.names("assets")
    assert len(names) == 1 and names[0].endswith(".png")
    assert f"![image](assets/{names[0]})" in editor.body()


def test_plain_text_paste_still_pastes(editor, area):
    from PySide6.QtCore import QMimeData

    editor.open_markdown(area, "")
    mime = QMimeData()
    mime.setText("hello")
    editor.insertFromMimeData(mime)
    assert "hello" in editor.body()


# -- formatting --------------------------------------------------------------------------------


def test_a_heading_reads_back_as_markdown_and_looks_like_one(editor, area):
    editor.open_markdown(area, "title line\n")
    editor.set_heading(2)
    assert editor.body().startswith("## title line")
    # The visual half: the block's char format carries the importer's size adjustment.
    from PySide6.QtGui import QTextCursor, QTextFormat

    cursor = QTextCursor(editor.document().firstBlock())
    cursor.select(QTextCursor.SelectionType.LineUnderCursor)
    adjustment = cursor.charFormat().property(QTextFormat.Property.FontSizeAdjustment)
    assert adjustment == 2  # 4 - level, what Qt's own importer writes for h2.


def test_bold_italic_and_lists_read_back_as_markdown(editor, area):
    from PySide6.QtGui import QTextCursor

    editor.open_markdown(area, "word\n")
    cursor = editor.textCursor()
    cursor.select(QTextCursor.SelectionType.Document)
    editor.setTextCursor(cursor)
    editor.toggle_bold()
    assert "**word**" in editor.body()
    editor.toggle_bold()
    editor.toggle_italic()
    assert "*word*" in editor.body()
    editor.toggle_italic()
    editor.bullet_list()
    assert editor.body().lstrip().startswith(("- word", "* word"))


# -- editing sessions in the built application -------------------------------------------------


from dplanner.domain.commands import SetModuleDataCommand  # noqa: E402
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri  # noqa: E402
from dplanner.modules.spec.aspect import MODULE_ID  # noqa: E402
from dplanner.modules.spec.documents import (  # noqa: E402
    SpecIndex,
    import_document,
    read_index,
    write_index,
)


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
    assert activity._editor.body().startswith("# Auth flow")
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


def test_only_markdown_opens_in_the_editor(services, project):
    """A PDF is not text and plain text through a rich-text round-trip would come back as
    markdown, so those two stay read-only; markdown has no read mode at all."""
    imported(services, project, "guide", b"plain text", "guide.txt")
    imported(services, project, "auth", b"# Auth\n", "auth.md")
    activity = specs_tab(services, project)
    activity.select_document("guide")
    assert not activity.is_editing and activity._views.currentWidget() is activity._text
    activity.select_document("auth")
    assert activity.is_editing and activity._views.currentWidget() is activity._editor_page
    assert "spec.edit" not in {spec.id for spec in services.actions.all_specs()}


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
    assert "typed" in activity._editor.body()


def test_switching_documents_ends_the_session_with_a_flush(services, project):
    imported(services, project, "auth", b"# Auth\n", "auth.md")
    imported(services, project, "other", b"# Other\n", "other.md")
    activity = specs_tab(services, project)
    activity.select_document("auth")
    activity._editor.insertPlainText("typed ")
    activity.select_document("other")
    assert current_doc(services, project, "auth").previous is not None
    # …and the other document has a session of its own now.
    assert activity.is_editing and activity._editor.body().startswith("# Other")


def test_picking_the_topology_row_ends_the_session(services, project):
    imported(services, project, "auth", b"# Auth\n", "auth.md")
    activity = specs_tab(services, project)
    activity.select_document("auth")
    activity._editor.insertPlainText("typed ")
    activity.list.setCurrentRow(0)
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
    assert "v2" in activity._editor.body() and "unsaved" not in activity._editor.body()
    assert current_doc(services, project, "auth").previous is not None


def test_a_pasted_image_is_indexed_at_save(services, project):
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QImage

    imported(services, project, "auth", b"# Auth\n", "auth.md")
    activity = specs_tab(services, project)
    activity.select_document("auth")
    mime = QMimeData()
    mime.setImageData(QImage.fromData(one_pixel_png()))
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
