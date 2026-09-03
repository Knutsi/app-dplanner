"""The feature editor: every field through the undo stack, images beside the project."""

import pytest

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.modules.feature.aspect import MODULE_ID
from dplanner.modules.feature.catalogue import (
    FeatureRecord,
    FeatureSource,
    read_catalogue,
    write_catalogue,
)
from dplanner.modules.feature.editor import FeatureEditor


@pytest.fixture
def project(services, make_project):
    project = make_project("Discovery")
    records = [FeatureRecord("f1", "Bulk import", source=FeatureSource("spec", "must import", 2))]
    services.undo.push(SetModuleDataCommand(project.id, MODULE_ID, write_catalogue(records)))
    return project


@pytest.fixture
def editor(services, project):
    editor = FeatureEditor(
        services.document, services.undo, services.repo.files, lambda _pid: ["spec", "other"]
    )
    editor.show_record(project.id, "f1")
    yield editor
    editor.dispose()


def record(project):
    return read_catalogue(project)[0]


def test_the_fields_show_the_record(editor):
    assert editor.title.text() == "Bulk import"
    assert editor.document.currentText() == "spec" and editor.page.value() == 2
    assert editor.quote.toPlainText() == "must import"
    assert editor.description.edit.toPlainText() == ""


def test_the_title_and_source_commit_as_they_are_left(services, project, editor):
    editor.title.setText("CSV import")
    editor.title.editingFinished.emit()
    assert record(project).title == "CSV import"
    editor.quote.setPlainText("must import a CSV")
    editor.quote.editing_finished.emit()
    editor.page.setValue(5)
    assert record(project).source == FeatureSource("spec", "must import a CSV", 5)
    editor.document.setCurrentIndex(0)  # Blank: no source at all.
    assert record(project).source is None
    assert services.undo.undo_text() == "Edit Feature f1"


def test_typing_the_description_is_undoable_prose(services, project, editor):
    editor.description.edit.setFocus()
    editor.description.edit.insertPlainText("Night ")
    editor.description.edit.insertPlainText("mode.")
    assert record(project).description == "Night mode."
    services.undo.undo()
    assert record(project).description == ""


def test_a_foreign_change_reloads_the_fields(services, project, editor):
    changed = [FeatureRecord("f1", "Renamed elsewhere")]
    services.undo.push(SetModuleDataCommand(project.id, MODULE_ID, write_catalogue(changed)))
    assert editor.title.text() == "Renamed elsewhere"
    assert editor.document.currentText() == ""


def test_attaching_an_image_names_it_in_the_record(services, project, editor):
    name = editor.attach_bytes(b"\x89PNG-pretend", "mock.png")
    assert name is not None and name.startswith("assets/")
    assert record(project).images == (name,)
    assert editor.gallery._names == [name]
    editor.attach_bytes(b"\x89PNG-pretend", "mock.png")  # The same bytes are one entry.
    assert record(project).images == (name,)

    editor._remove_image(name)
    assert record(project).images == ()
    # The file stays for `asset prune`; only the reference went.
    assert services.repo.files(project.id, MODULE_ID).read_bytes(name) is not None


def test_showing_nothing_disables_the_editor(editor):
    editor.show_record(None, None)
    assert not editor.isEnabled() and editor.title.text() == ""
