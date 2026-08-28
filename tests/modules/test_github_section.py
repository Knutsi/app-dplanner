"""The GitHub tab, as the panel drives it: typing gh-less, picking from fetched lists.

The loader is never started here — the test library has no repository URL, so the section
spawns no subprocess; the fetched lists are handed to ``_on_lists`` directly.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Project, Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.github.aspect import MODULE_ID, read
from dplanner.modules.github.gh import PrInfo
from dplanner.modules.github.section import MERGED_COLOUR
from dplanner.modules.step_properties.module import PANEL_ID

MERGED = PrInfo(number=12, title="Add login flow", state="merged", url="u12", head_ref="feat/login")
OPEN = PrInfo(number=7, title="Fix crash", state="open", url="u7", head_ref="fix/crash")


@pytest.fixture
def project(services):
    library = services.document
    project = Project(title="Discovery")
    AddNodeCommand(library.id, project).redo(library)
    AddNodeCommand(project.id, Step(title="Read the spec")).redo(library)
    return project


@pytest.fixture
def editor(services, project):
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("step", project.steps[0].id)),)
    )
    panel = services.window.dock.widget_for(PANEL_ID)
    labels = [panel.tab_bar.tabText(i) for i in range(panel.tab_bar.count())]
    return panel._pages.widget(labels.index("GitHub"))


def test_a_typed_branch_goes_through_the_undo_stack(services, project, editor):
    step = project.steps[0]
    editor.branch_edit.setEditText("feat/login")
    editor.branch_edit.lineEdit().editingFinished.emit()

    assert services.document.step(step.id).module_data[MODULE_ID]["branch"] == "feat/login"
    assert services.undo.undo_text() == "Set GitHub Refs"
    services.undo.undo()
    assert MODULE_ID not in services.document.step(step.id).module_data


def test_a_typed_pr_is_recorded_with_no_state_until_something_checks(services, project, editor):
    step = project.steps[0]
    editor.pr_edit.setEditText("#12")
    editor.pr_edit.lineEdit().editingFinished.emit()

    entry = services.document.step(step.id).module_data[MODULE_ID]
    assert entry["pr_number"] == 12 and "pr_state" not in entry


def test_clearing_both_fields_removes_the_entry(services, project, editor):
    step = project.steps[0]
    editor.branch_edit.setEditText("feat/login")
    editor.branch_edit.lineEdit().editingFinished.emit()
    editor.branch_edit.setEditText("")
    editor.branch_edit.lineEdit().editingFinished.emit()
    assert MODULE_ID not in services.document.step(step.id).module_data


def loaded(editor, branches, prs, message=""):
    """Hand the editor a fetch result the way its loader would, for its current repo."""
    editor._loaded_repo = "acme/widget"
    editor._on_lists("acme/widget", branches, prs, message)


def test_fetched_lists_fill_the_pickers_and_mark_merged_prs_green(editor):
    loaded(editor, ["main", "feat/login"], [OPEN, MERGED])
    assert [editor.branch_edit.itemText(i) for i in range(editor.branch_edit.count())] == [
        "main",
        "feat/login",
    ]
    assert "✓ merged" in editor.pr_edit.itemText(1)
    from PySide6.QtCore import Qt

    brush = editor.pr_edit.itemData(1, Qt.ItemDataRole.ForegroundRole)
    assert brush is not None and brush.color() == MERGED_COLOUR


def test_picking_a_listed_pr_records_its_state_title_url_and_branch(services, project, editor):
    step = project.steps[0]
    loaded(editor, [], [OPEN, MERGED])
    editor.pr_edit.setCurrentIndex(1)
    editor.pr_edit.activated.emit(1)

    refs = read(services.document.step(step.id))
    assert refs is not None
    assert refs.pr_number == 12 and refs.pr_state == "merged" and refs.branch == "feat/login"


def test_a_failed_fetch_leaves_the_fields_typeable_and_says_why(editor):
    loaded(editor, [], [], "gh not found on PATH")
    assert "type values manually" in editor.status.text()
    assert editor.pr_edit.isEditable() and editor.branch_edit.isEditable()


def test_no_repository_means_no_fetch_and_a_hint(editor):
    """The fixture library has no repository URL, so showing a step must not have started
    a loader — the status explains what to set instead."""
    assert editor._loaded_repo is None
    assert "repository" in editor.status.text()
