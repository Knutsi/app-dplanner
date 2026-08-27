"""The spec module's Qt half: the Specs tab, its entry in the index, and the viewers.

The headless half — the index shape, import/replace semantics, the verbs — is covered
without Qt in ``tests/cli/test_spec.py``; everything here needs a built application.
"""

from pathlib import Path

import pypdfium2 as pdfium
import pytest

from dplanner.domain.commands import AddNodeCommand, RemoveNodeCommand, SetModuleDataCommand
from dplanner.domain.model import Project
from dplanner.framework.builder import INDEX_PANEL_ID
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.spec.activity import SpecsActivity
from dplanner.modules.spec.aspect import MODULE_ID
from dplanner.modules.spec.documents import attach_asset, import_document, write_index
from dplanner.modules.spec.viewer import PdfPageView, SpecTextBrowser


def one_pixel_png(tmp_path: Path) -> bytes:
    from PySide6.QtGui import QColor, QImage

    image = QImage(1, 1, QImage.Format.Format_RGB32)
    image.fill(QColor("black"))
    path = tmp_path / "one-pixel.png"
    assert image.save(str(path))
    return path.read_bytes()


@pytest.fixture
def project(services):
    project = Project(title="Discovery")
    AddNodeCommand(services.document.id, project).redo(services.document)
    return project


def imported(services, project, name, data, filename):
    """Import a document the way both surfaces do: blob into the area, index as a command."""
    area = services.repo.files(project.id, MODULE_ID)
    docs, document, _outcome = import_document(area, [], name, data, filename, "2026-08-27")
    SetModuleDataCommand(project.id, MODULE_ID, write_index(docs, [])).redo(services.document)
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
    assert entries == ["Specs"]
    panel.tree.itemActivated.emit(row.child(0), 0)
    panel.tree.itemActivated.emit(row.child(0), 0)  # Dedupes on the activity uri.
    assert [a.title for a in services.tabs.activities()] == ["Discovery — Specs"]


def test_the_spec_verbs_follow_the_project(services, project):
    bare = services.context.current()
    for action_id in ("spec.add", "spec.open"):
        assert not services.actions.spec(action_id).state(bare).visible
    chosen = select(services, project)
    for action_id in ("spec.add", "spec.open"):
        assert services.actions.spec(action_id).state(chosen).enabled


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
    assert activity.list.count() == 0
    imported(services, project, "auth", b"# Auth\n", "auth.md")
    assert [activity.list.item(i).text() for i in range(activity.list.count())] == ["auth"]


def test_a_markdown_document_renders_with_its_area_images(services, project, tmp_path):
    area = services.repo.files(project.id, MODULE_ID)
    asset = attach_asset(area, one_pixel_png(tmp_path), "dot.png")
    imported(services, project, "auth", f"![]({asset})".encode(), "auth.md")
    services.actions.run("spec.open", select(services, project))
    activity = services.tabs.activities()[0]
    browser = activity.widget.findChild(SpecTextBrowser)
    image = browser.loadResource(2, asset)
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


def test_a_missing_blob_is_a_notice_not_a_crash(services, project):
    document = imported(services, project, "auth", b"body", "auth.txt")
    services.repo.files(project.id, MODULE_ID).remove(document.file)
    services.actions.run("spec.open", select(services, project))
    activity = services.tabs.activities()[0]
    assert "missing" in activity._notice.text()
