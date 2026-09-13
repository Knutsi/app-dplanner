"""The Feature tab's editor: the passages a feature was read from, as a list with one set
of fields, each committed through the undo stack as it is left.

Its name and its prose belong to the step now — the Details tab's — so what is here is
the one fact nothing else can hold.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.modules.feature.aspect import MODULE_ID, FeatureSource, read, write
from dplanner.modules.feature.editor import FeatureEditor


def cites(step):
    """The step's passages, asserted present — every test here is on a feature step."""
    found = read(step)
    assert found is not None
    return found


@pytest.fixture
def step(services, make_project):
    project = make_project("Discovery")
    step = Step(title="Bulk import")
    AddNodeCommand(project.id, step).redo(services.document)
    services.undo.push(
        SetModuleDataCommand(
            step.id,
            MODULE_ID,
            write(
                (
                    FeatureSource("spec", "must import", 2, "0123456789abcdef"),
                    FeatureSource("other", "and export"),
                )
            ),
        )
    )
    return step


@pytest.fixture
def editor(services, step):
    editor = FeatureEditor(
        services.document,
        services.undo,
        lambda _pid: ["spec", "other"],
        digest_of=lambda _pid, name: f"digest-of-{name}",
    )
    editor.show_target(step.id)
    yield editor
    editor.dispose()


def test_the_fields_show_the_picked_passage(editor):
    assert editor.passages.count() == 2 and editor.passages.currentRow() == 0
    assert editor.passages.item(0).text() == "spec p.2"
    assert editor.document.currentText() == "spec" and editor.page.value() == 2
    assert editor.quote.toPlainText() == "must import"
    editor.passages.setCurrentRow(1)
    assert editor.document.currentText() == "other" and editor.page.value() == 0
    assert editor.quote.toPlainText() == "and export"


def test_the_picked_passage_commits_as_it_is_left(services, step, editor):
    editor.quote.setPlainText("must import a CSV")
    editor.quote.editing_finished.emit()
    editor.page.setValue(5)
    # A changed quote is stamped with the document as it is now; a page alone is not.
    assert cites(step)[0] == FeatureSource("spec", "must import a CSV", 5, "digest-of-spec")
    assert cites(step)[1] == FeatureSource("other", "and export")
    assert services.undo.undo_text() == "Edit Passages"


def test_add_and_remove_passages(services, step, editor):
    editor.add_passage.click()
    assert len(cites(step)) == 3 and editor.passages.currentRow() == 2
    assert cites(step)[2] == FeatureSource("spec")
    editor.quote.setPlainText("a third place")
    editor.quote.editing_finished.emit()
    assert cites(step)[2].quote == "a third place"
    assert editor.passages.item(2).text() == "spec"
    editor.passages.setCurrentRow(0)
    editor.remove_passage.click()
    assert [s.quote for s in cites(step)] == ["and export", "a third place"]
    # Consecutive edits to one step coalesce into one undo step, by the label.
    services.undo.undo()
    assert [s.quote for s in cites(step)] == ["must import", "and export"]


def test_without_a_passage_the_fields_are_quiet(step, editor):
    editor.passages.setCurrentRow(0)
    editor.remove_passage.click()
    editor.remove_passage.click()
    assert cites(step) == ()
    assert not editor.quote.isEnabled() and not editor.remove_passage.isEnabled()
    assert editor.add_passage.isEnabled()


def test_a_foreign_change_reloads_the_fields(services, step, editor):
    services.undo.push(SetModuleDataCommand(step.id, MODULE_ID, write()))
    assert editor.passages.count() == 0 and editor.document.currentText() == ""


def test_it_answers_for_its_own_step_and_nothing_else(step, editor):
    assert editor.focus_entity("feature", step.id) is True
    assert editor.focus_entity("feature", "somebody else") is False
    assert editor.focus_entity("test", step.id) is False


def test_showing_a_plain_step_disables_the_editor(services, make_project, editor):
    plain = Step(title="Plain")
    AddNodeCommand(make_project("Other").id, plain).redo(services.document)
    editor.show_target(plain.id)
    assert not editor.isEnabled() and editor.passages.count() == 0
    editor.show_target(None)
    assert not editor.isEnabled()
