"""The feature editor: every field through the undo stack, passages as a list with one
set of fields, images beside the project."""

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
    records = [
        FeatureRecord(
            "f1",
            "Bulk import",
            sources=(
                FeatureSource("spec", "must import", 2, "0123456789abcdef"),
                FeatureSource("other", "and export"),
            ),
        )
    ]
    services.undo.push(SetModuleDataCommand(project.id, MODULE_ID, write_catalogue(records)))
    return project


@pytest.fixture
def editor(services, project):
    editor = FeatureEditor(
        services.document,
        services.undo,
        services.repo.files,
        lambda _pid: ["spec", "other"],
        digest_of=lambda _pid, name: f"digest-of-{name}",
    )
    editor.show_record(project.id, "f1")
    yield editor
    editor.dispose()


def record(project):
    return read_catalogue(project)[0]


def test_the_fields_show_the_record_and_the_picked_passage(editor):
    assert editor.title.text() == "Bulk import"
    assert editor.passages.count() == 2 and editor.passages.currentRow() == 0
    assert editor.passages.item(0).text() == "spec p.2"
    assert editor.document.currentText() == "spec" and editor.page.value() == 2
    assert editor.quote.toPlainText() == "must import"
    editor.passages.setCurrentRow(1)
    assert editor.document.currentText() == "other" and editor.page.value() == 0
    assert editor.quote.toPlainText() == "and export"
    assert editor.description.edit.toPlainText() == ""


def test_the_title_and_the_picked_passage_commit_as_they_are_left(services, project, editor):
    editor.title.setText("CSV import")
    editor.title.editingFinished.emit()
    assert record(project).title == "CSV import"
    editor.quote.setPlainText("must import a CSV")
    editor.quote.editing_finished.emit()
    editor.page.setValue(5)
    # A changed quote is stamped with the document as it is now; a page alone is not.
    assert record(project).sources[0] == FeatureSource(
        "spec", "must import a CSV", 5, "digest-of-spec"
    )
    assert record(project).sources[1] == FeatureSource("other", "and export")
    assert services.undo.undo_text() == "Edit Feature f1"


def test_add_and_remove_passages(services, project, editor):
    editor.add_passage.click()
    assert len(record(project).sources) == 3 and editor.passages.currentRow() == 2
    assert record(project).sources[2] == FeatureSource("spec")
    editor.quote.setPlainText("a third place")
    editor.quote.editing_finished.emit()
    assert record(project).sources[2].quote == "a third place"
    assert editor.passages.item(2).text() == "spec"
    editor.passages.setCurrentRow(0)
    editor.remove_passage.click()
    assert [s.quote for s in record(project).sources] == ["and export", "a third place"]
    # Consecutive edits to one record coalesce into one undo step, by the label.
    services.undo.undo()
    assert [s.quote for s in record(project).sources] == ["must import", "and export"]


def test_without_a_passage_the_fields_are_quiet(services, project, editor):
    editor.passages.setCurrentRow(0)
    editor.remove_passage.click()
    editor.remove_passage.click()
    assert record(project).sources == ()
    assert not editor.quote.isEnabled() and not editor.remove_passage.isEnabled()
    assert editor.add_passage.isEnabled()


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
    assert editor.passages.count() == 0 and editor.document.currentText() == ""


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
