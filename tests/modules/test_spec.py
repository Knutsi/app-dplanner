"""The spec module's Qt half: the Specs tab, its entry in the index, and the viewers.

The headless half — the index shape, import/replace semantics, the verbs — is covered
without Qt in ``tests/cli/test_spec.py``; everything here needs a built application.
"""

from pathlib import Path

import pypdfium2 as pdfium
import pytest

from dplanner.domain.commands import RemoveNodeCommand, SetModuleDataCommand
from dplanner.framework.builder import INDEX_PANEL_ID
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.spec.activity import SpecsActivity
from dplanner.modules.spec.aspect import MODULE_ID
from dplanner.modules.spec.documents import (
    SpecIndex,
    attach_asset,
    import_document,
    write_index,
)
from dplanner.modules.spec.viewer import PdfPageView


def one_pixel_png(tmp_path: Path) -> bytes:
    from PySide6.QtGui import QColor, QImage

    image = QImage(1, 1, QImage.Format.Format_RGB32)
    image.fill(QColor("black"))
    path = tmp_path / "one-pixel.png"
    assert image.save(str(path))
    return path.read_bytes()


@pytest.fixture
def project(make_project):
    return make_project("Discovery")


def imported(services, project, name, data, filename):
    """Import a document the way both surfaces do: blob into the area, index as a command."""
    area = services.repo.files(project.id, MODULE_ID)
    docs, document, _outcome = import_document(area, [], name, data, filename, "2026-08-27")
    entry = write_index(SpecIndex(documents=docs, assets=[]))
    SetModuleDataCommand(project.id, MODULE_ID, entry).redo(services.document)
    return document


def select(services, project):
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )
    return services.context.current()


# -- the entry in the index --------------------------------------------------------------------


def test_the_specs_entry_opens_the_specs_tab(services, project):
    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    row = panel.tree.topLevelItem(0).child(0)
    entries = [row.child(i).text(0) for i in range(row.childCount())]
    assert entries == [
        "Steps",
        "Order",
        "Specs",
        "Coverage",
        "Assets",
        "Ready to start",
        "Time Estimates",
    ]
    panel.tree.itemActivated.emit(row.child(2), 0)
    panel.tree.itemActivated.emit(row.child(2), 0)  # Dedupes on the activity uri.
    assert [a.title for a in services.tabs.activities()] == ["Discovery — Specs"]


def test_the_spec_verbs_follow_the_project(services, project):
    bare = services.context.current()
    for action_id in ("spec.add", "spec.open", "spec.remove", "spec.open_external"):
        found = services.actions.spec(action_id).state(bare)
        assert found.visible and not found.enabled
    chosen = select(services, project)
    for action_id in ("spec.add", "spec.open"):
        assert services.actions.spec(action_id).state(chosen).enabled
    # The document verbs stay greyed until the Specs tab publishes a selected document.
    for action_id in ("spec.remove", "spec.open_external"):
        assert not services.actions.spec(action_id).state(chosen).enabled


def test_the_tab_closes_with_its_project(services, project):
    services.actions.run("spec.open", select(services, project))
    assert services.tabs.activities()
    RemoveNodeCommand(project.id).redo(services.document)
    assert services.tabs.activities() == []


# -- the tab -----------------------------------------------------------------------------------


def test_the_tab_lists_documents_and_follows_the_model(services, project):
    services.actions.run("spec.open", select(services, project))
    activity = services.tabs.activities()[0]
    assert isinstance(activity, SpecsActivity)
    assert len(activity.rows()) == 1  # The pinned Topology row; no documents yet.
    imported(services, project, "auth", b"# Auth\n", "auth.md")
    assert [activity.row_item(i).text(0) for i in range(len(activity.rows()))] == [
        "Topology",
        "auth",
    ]


def test_a_markdown_document_shows_its_source_and_its_pictures_under_it(
    services, project, tmp_path
):
    """A plain-text editor cannot draw a picture and does not pretend to: the link is the
    text, and the gallery under the editor is where the figure is shown."""
    area = services.repo.files(project.id, MODULE_ID)
    asset = attach_asset(area, one_pixel_png(tmp_path), "dot.png")
    imported(services, project, "auth", f"# Auth\n\n![dot]({asset})\n".encode(), "auth.md")
    services.actions.run("spec.open", select(services, project))
    activity = services.tabs.activities()[0]
    activity.select_document("auth")
    assert f"![dot]({asset})" in activity._editor.toPlainText()
    assert activity._figures._files == [asset]


def test_a_pdf_document_renders_pages(services, project):
    import io

    doc = pdfium.PdfDocument.new()
    doc.new_page(200, 100)
    buffer = io.BytesIO()
    doc.save(buffer)
    imported(services, project, "spec", buffer.getvalue(), "spec.pdf")
    services.actions.run("spec.open", select(services, project))
    activity = services.tabs.activities()[0]
    view = activity.widget.findChild(PdfPageView)
    assert len(view._pages) == 1


def test_a_rendered_page_is_a_png_qt_can_decode(services, project):
    """The stdlib encoder in core/png.py, validated by a real decoder."""
    import io

    from PySide6.QtGui import QImage

    from dplanner.modules.spec.pdf import render_page

    doc = pdfium.PdfDocument.new()
    doc.new_page(200, 100)
    buffer = io.BytesIO()
    doc.save(buffer)
    image = QImage.fromData(render_page(buffer.getvalue(), 1, 1.0))
    assert not image.isNull() and image.width() == 200 and image.height() == 100


def test_a_missing_blob_is_a_notice_not_a_crash(services, project):
    document = imported(services, project, "auth", b"body", "auth.txt")
    services.repo.files(project.id, MODULE_ID).remove(document.file)
    services.actions.run("spec.open", select(services, project))
    activity = services.tabs.activities()[0]
    assert "missing" in activity._notice.text()


# -- the tab as a management surface -----------------------------------------------------------


def opened(services, project):
    services.actions.run("spec.open", select(services, project))
    activity = services.tabs.activities()[0]
    assert isinstance(activity, SpecsActivity)
    return activity


def test_the_toolbar_replaced_the_add_button(services, project):
    """The + button is the one way in: its arrow drops the Add Spec child menu, so
    Import is a menu entry rather than a second glyph, and the strip's Connect button
    stays off screen while no source is shown."""
    from dplanner.framework.toolbar import Toolbar

    activity = opened(services, project)
    assert activity.toolbar in activity.widget.findChildren(Toolbar)
    assert activity.toolbar.button_for("spec.add") is None
    popup = activity.toolbar.menu_for("spec.new")
    assert popup is not None
    entries = [
        entry.text().replace("&", "") for entry in popup.actions() if not entry.isSeparator()
    ]
    assert entries == [
        "New Spec Document…",
        "Import Spec Document…",
        # Greyed with its reason: the project names no specs location yet.
        "From Location… — the project names no specs location — Project ▸ Settings…",
        "Folder on This Computer…",
        "Git Repository…",
        "Confluence Page…",
        "Confluence Folder…",
    ]
    assert activity._source_strip.isHidden()


def test_the_active_tab_publishes_the_selected_document(services, project):
    activity = opened(services, project)
    assert services.context.current().selected_entity("spec_document") is None
    imported(services, project, "auth", b"body", "auth.txt")
    assert activity.current_row() >= 0
    assert services.context.current().selected_entity("spec_document") == "auth"


def test_a_background_tab_does_not_speak_for_the_user(services, project):
    activity = opened(services, project)
    imported(services, project, "auth", b"body", "auth.txt")
    activity.on_deactivated()
    services.context.clear_scope(SCOPE_SELECTION)
    activity.select_row(0)
    assert services.context.current().selected_entity("spec_document") is None


def test_remove_takes_the_document_and_undoes(services, project, monkeypatch):
    from dplanner.modules.spec import module as spec_module
    from dplanner.modules.spec.documents import read_index

    monkeypatch.setattr(spec_module, "confirm", lambda *a, **k: True)
    opened(services, project)
    imported(services, project, "auth", b"body", "auth.txt")
    docs = read_index(services.document.project(project.id)).documents

    services.actions.run("spec.remove", services.context.current())
    assert read_index(services.document.project(project.id)).documents == []
    # The blob outlives the index entry — that is what makes the removal undoable.
    assert services.repo.files(project.id, MODULE_ID).read_bytes(docs[0].file) == b"body"
    services.undo.undo()
    assert [doc.name for doc in read_index(services.document.project(project.id)).documents] == [
        "auth"
    ]


def test_the_viewer_survives_an_index_edit_that_keeps_the_blob(services, project):
    from dplanner.modules.spec.documents import SpecAsset, read_index

    activity = opened(services, project)
    imported(services, project, "auth", b"body", "auth.txt")
    shown = activity._shown
    assert shown is not None
    docs = read_index(services.document.project(project.id)).documents
    figure = SpecAsset(id="a1", file="assets/0000.png", document="auth", page=1)
    marked = SpecIndex(documents=docs, assets=[figure])
    SetModuleDataCommand(project.id, MODULE_ID, write_index(marked)).redo(services.document)
    # An assets-only edit repaints the list but never rebuilds the viewer.
    assert activity._shown is shown
    assert activity.rows()[1] == ("auth", 0)


def test_the_tree_and_the_editor_are_reachable_from_the_keyboard(services, project):
    """Tab walks the surface in reading order. The strips are deliberately not in it —
    their buttons take no focus, because a verb that moved the caret away from what it was
    aimed at would be useless, and their keys live on the editor instead."""
    from PySide6.QtCore import Qt

    imported(services, project, "auth", b"# Auth\n", "auth.md")
    activity = opened(services, project)
    activity.select_document("auth")
    assert activity.list.focusPolicy() != Qt.FocusPolicy.NoFocus
    assert activity._editor.focusPolicy() != Qt.FocusPolicy.NoFocus
    assert activity.list.nextInFocusChain() is not None
    # Inside the editor Tab stays Qt's own: a markdown document needs one for a nested
    # list and for a code block.
    assert not activity._editor.tabChangesFocus()
