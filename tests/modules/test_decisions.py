"""The Decisions card on the project panel, and the editor it opens."""

from datetime import date

import pytest

from dplanner.domain.commands import AddNodeCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.decisions.card import FRESH_TITLE
from dplanner.modules.decisions.editor import DecisionDialog, DecisionEditor
from dplanner.modules.decisions.log import MODULE_ID, Decision, read_log, write_log


@pytest.fixture
def project(services, make_project):
    project = make_project("Discovery")
    AddNodeCommand(project.id, Step(title="Read the spec")).redo(services.document)
    records = [
        Decision(
            "D1", "Keep SQLite", body="One operator.", made="2026-09-05", step=project.steps[0].id
        ),
        Decision("D2", "Ship weekly", made="2026-09-06"),
        Decision("D3", "Ship daily", made="2026-09-07", supersedes="D2"),
    ]
    services.undo.push(SetModuleDataCommand(project.id, MODULE_ID, write_log(records)))
    return project


@pytest.fixture
def card(services, project):
    spec = next(s for s in services.detail_cards.sections() if s.id == "decisions.card")
    card = spec.factory()
    card.show_target(project.id)
    yield card
    card.dispose()


def rows(card):
    return [(row.title.text(), row.meta.text()) for row in card.rows]


def test_the_card_registers_and_the_project_panel_shows_it(services, project):
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )
    panel = services.window.dock.widget_for("project_editor.project")
    assert "Decisions" in [c.title.text() for c in panel._cards]


def test_the_rows_say_what_when_where_and_whether_it_stands(card):
    assert rows(card) == [
        ("Keep SQLite", "D1 · 5 September · on S1"),
        ("Ship weekly", "D2 · 6 September · superseded by D3"),
        ("Ship daily", "D3 · 7 September"),
    ]
    assert not card.empty.isVisibleTo(card)
    assert card.rows[0].toolTip() == "One operator."


def test_the_rows_follow_the_log_and_a_deleted_step_loses_its_key(services, project, card):
    from dplanner.domain.commands import RemoveNodeCommand

    services.undo.push(RemoveNodeCommand(project.steps[0].id))
    assert rows(card)[0][1] == "D1 · 5 September"
    services.undo.push(SetModuleDataCommand(project.id, MODULE_ID, {}))
    assert card.rows == () and card.empty.isVisibleTo(card)


def test_add_records_a_fresh_decision_and_opens_it_on_the_title(
    services, project, card, monkeypatch
):
    opened = []
    monkeypatch.setattr(DecisionDialog, "exec", lambda self: opened.append(self))
    fresh = card.add_decision()
    assert fresh == "D4"
    record = read_log(project)[-1]
    assert record.title == FRESH_TITLE and record.made == date.today().isoformat()
    (dialog,) = opened
    assert dialog.editor.title.text() == FRESH_TITLE and dialog.editor.title.selectedText()
    assert services.undo.undo_text() == "Add Decision"
    services.undo.undo()
    assert [r.id for r in read_log(project)] == ["D1", "D2", "D3"]


@pytest.fixture
def editor(services, project):
    editor = DecisionEditor(services.document, services.undo, lambda step: f"S{step.number}")
    editor.show_record(project.id, "D1")
    yield editor
    editor.dispose()


def test_the_editor_shows_the_record_and_commits_each_field_as_it_is_left(
    services, project, editor
):
    assert editor.title.text() == "Keep SQLite"
    assert editor.step.currentText() == "S1  Read the spec"
    assert [editor.supersedes.itemText(i) for i in range(editor.supersedes.count())] == [
        "—",
        "D2  Ship weekly",
        "D3  Ship daily",
    ]
    assert editor.body.edit.toPlainText() == "One operator."
    editor.title.setText("Keep the index in SQLite")
    editor.title.editingFinished.emit()
    editor.step.setCurrentIndex(0)
    editor.supersedes.setCurrentIndex(1)
    record = read_log(project)[0]
    assert (record.title, record.step, record.supersedes) == ("Keep the index in SQLite", "", "D2")
    assert services.undo.undo_text() == "Edit Decision D1"


def test_typing_the_reasoning_is_undoable_prose(services, project, editor):
    editor.body.edit.setFocus()
    editor.body.edit.moveCursor(editor.body.edit.textCursor().MoveOperation.End)
    editor.body.edit.insertPlainText(" Read-mostly.")
    assert read_log(project)[0].body == "One operator. Read-mostly."
    services.undo.undo()
    assert read_log(project)[0].body == "One operator."


def test_a_foreign_change_reloads_the_fields(services, project, editor):
    changed = [Decision("D1", "Renamed elsewhere")]
    services.undo.push(SetModuleDataCommand(project.id, MODULE_ID, write_log(changed)))
    assert editor.title.text() == "Renamed elsewhere"
    assert editor.step.currentIndex() == 0 and editor.supersedes.count() == 1
    assert editor.body.edit.toPlainText() == ""


def test_the_dialog_removes_the_decision_and_unlinks_what_superseded_it(services, project):
    dialog = DecisionDialog(
        services.document, services.undo, lambda step: f"S{step.number}", project.id, "D2"
    )
    dialog.remove_button.click()
    assert [r.id for r in read_log(project)] == ["D1", "D3"]
    assert read_log(project)[1].supersedes == ""
    assert services.undo.undo_text() == "Remove Decision D2"
    dialog.dispose()
    dialog.deleteLater()


def test_the_cli_and_the_card_share_one_log(services, project, card, cli):
    """The log the card shows is the file `dplanner decision add` writes — one shape,
    two writers."""
    entry = project.module_data[MODULE_ID]
    assert [row["id"] for row in entry["decisions"]] == ["D1", "D2", "D3"]
    assert entry["decisions"][2] == {
        "id": "D3",
        "title": "Ship daily",
        "made": "2026-09-07",
        "supersedes": "D2",
    }
