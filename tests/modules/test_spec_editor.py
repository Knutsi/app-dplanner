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
    docs, document, _outcome = import_document(
        area, existing, name, data, filename, "2026-08-27"
    )
    entry = write_index(SpecIndex(documents=docs, requirements=[], assets=[]))
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
    activity.select_document("auth")
    activity.begin_edit()
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

    activity.end_edit()
    assert not activity.is_editing
    # One undo entry for the whole session: undo restores the pre-session index.
    services.undo.undo()
    restored = current_doc(services, project, "auth")
    assert restored.file == base.file and area.read_bytes(base.file) == b"# Auth\n"


def test_opening_the_editor_without_typing_saves_nothing(services, project):
    base = imported(services, project, "auth", b"# Auth\n", "auth.md")
    activity = specs_tab(services, project)
    activity.select_document("auth")
    activity.begin_edit()
    activity._flush_edit()
    activity.end_edit()
    document = current_doc(services, project, "auth")
    assert document.file == base.file
    assert document.previous is None  # Never replaced: entering edit mode is not an edit.


def test_edit_state_teaches_its_preconditions(services, project):
    imported(services, project, "guide", b"plain text", "guide.txt")
    activity = specs_tab(services, project)
    activity.select_document("guide")
    state = services.actions.spec("spec.edit").state(services.context.current())
    assert not state.enabled and "only markdown" in state.label
    imported(services, project, "auth", b"# Auth\n", "auth.md")
    activity.select_document("auth")
    state = services.actions.spec("spec.edit").state(services.context.current())
    assert state.enabled and state.checked is False
    services.actions.run("spec.edit", services.context.current())
    assert activity.is_editing
    state = services.actions.spec("spec.edit").state(services.context.current())
    assert state.checked is True
    services.actions.run("spec.edit", services.context.current())
    assert not activity.is_editing


def test_switching_documents_ends_the_session_with_a_flush(services, project):
    imported(services, project, "auth", b"# Auth\n", "auth.md")
    imported(services, project, "other", b"# Other\n", "other.md")
    activity = specs_tab(services, project)
    activity.select_document("auth")
    activity.begin_edit()
    activity._editor.insertPlainText("typed ")
    activity.select_document("other")
    assert not activity.is_editing
    assert current_doc(services, project, "auth").previous is not None


def test_a_foreign_change_to_the_edited_document_ends_the_session(services, project):
    imported(services, project, "auth", b"# Auth\n", "auth.md")
    activity = specs_tab(services, project)
    activity.select_document("auth")
    activity.begin_edit()
    activity._editor.insertPlainText("unsaved ")
    imported(services, project, "auth", b"# Auth v2\n", "auth.md")  # An agent, say.
    assert not activity.is_editing
    assert activity._views.currentWidget() is not activity._editor_page
    # The model is the authority: the foreign replace stands, the unflushed typing is gone.
    assert b"v2" in services.repo.files(project.id, MODULE_ID).read_bytes(
        current_doc(services, project, "auth").file
    )


def test_a_pasted_image_is_indexed_at_save(services, project):
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QImage

    imported(services, project, "auth", b"# Auth\n", "auth.md")
    activity = specs_tab(services, project)
    activity.select_document("auth")
    activity.begin_edit()
    mime = QMimeData()
    mime.setImageData(QImage.fromData(one_pixel_png()))
    activity._editor.insertFromMimeData(mime)
    activity.end_edit()
    index = read_index(services.document.project(project.id))
    assert len(index.assets) == 1 and index.assets[0].file.startswith("assets/")
    assert index.assets[0].id == "a1"


def test_done_with_no_edits_still_returns_to_the_viewer(services, project):
    """View → edit → Done without typing: the render cache must not strand the editor page.

    The cache's early-return assumes the shown widget is right; after a no-op session it
    is the editor page. This is the bug where Done uncheck the toggle but changed nothing.
    """
    imported(services, project, "auth", b"# Auth\n", "auth.md")
    activity = specs_tab(services, project)
    activity.select_document("auth")  # Renders the viewer, warming the cache.
    assert activity._views.currentWidget() is activity._text
    activity.begin_edit()
    assert activity._views.currentWidget() is activity._editor_page
    activity.end_edit()
    assert activity._views.currentWidget() is activity._text
