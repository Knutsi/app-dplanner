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
from dplanner.modules.spec.activity import NAME_ROLE, SpecsActivity
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
    assert entries == ["Steps", "Order", "Specs", "Assets", "Progression", "Time Estimates"]
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
    assert activity.list.count() == 1  # The pinned Topology row; no documents yet.
    imported(services, project, "auth", b"# Auth\n", "auth.md")
    assert [activity.list.item(i).text() for i in range(activity.list.count())] == [
        "Topology",
        "auth",
    ]


def test_a_markdown_document_renders_with_its_area_images(services, project, tmp_path):
    area = services.repo.files(project.id, MODULE_ID)
    asset = attach_asset(area, one_pixel_png(tmp_path), "dot.png")
    imported(services, project, "auth", f"![]({asset})".encode(), "auth.md")
    services.actions.run("spec.open", select(services, project))
    activity = services.tabs.activities()[0]
    # Markdown opens in the editor; its images resolve through the area exactly as the
    # viewer's did.
    image = activity._editor.loadResource(2, asset)
    assert image is not None and not image.isNull()


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
    from PySide6.QtWidgets import QPushButton

    from dplanner.framework.toolbar import ActionToolbar

    activity = opened(services, project)
    assert activity.widget.findChild(ActionToolbar) is activity.toolbar
    assert activity.widget.findChild(QPushButton) is None


def test_the_active_tab_publishes_the_selected_document(services, project):
    activity = opened(services, project)
    assert services.context.current().selected_entity("spec_document") is None
    imported(services, project, "auth", b"body", "auth.txt")
    assert activity.list.currentItem() is not None
    assert services.context.current().selected_entity("spec_document") == "auth"


def test_a_background_tab_does_not_speak_for_the_user(services, project):
    activity = opened(services, project)
    imported(services, project, "auth", b"body", "auth.txt")
    activity.on_deactivated()
    services.context.clear_scope(SCOPE_SELECTION)
    activity.list.setCurrentRow(0)
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
    assert activity.list.item(1).data(NAME_ROLE) == "auth"
