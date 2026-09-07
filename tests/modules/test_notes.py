"""The note log: what reaches a step, the Notes card on the project panel, and the editor.

The derivation half runs with no Qt and no store — a plain library — because that is
also the shape the CLI and the briefing read it in.
"""

from datetime import date

import pytest

from dplanner.domain.commands import AddNodeCommand, SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.notes.card import FRESH_TITLE
from dplanner.modules.notes.editor import NoteDialog, NoteEditor
from dplanner.modules.notes.log import (
    MODULE_ID,
    Note,
    read_log,
    same_note,
    write_log,
)
from dplanner.modules.notes.reach import briefing_blocks, reaching


def build(edges):
    """A library with one project whose steps and requires-edges are given as a dict."""
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    steps = {}
    for name in edges:
        steps[name] = Step(title=name)
        library.add_child(project.id, steps[name])
    for name, sources in edges.items():
        if sources:
            library.set_edges(steps[name].id, "requires", [steps[s].id for s in sources])
    return library, project, steps


def log(library, project, *notes):
    library.set_module_data(project.id, MODULE_ID, write_log(list(notes)))


def key_of(step):
    return f"S{step.number}"


# -- what reaches a step -------------------------------------------------------------------------


def test_a_handoff_reaches_the_steps_after_the_one_it_was_made_on():
    library, project, steps = build({"A": [], "B": ["A"], "C": ["B"], "D": []})
    log(library, project, Note("N1", "handoff", "Keys", step=steps["A"].id))
    assert [n.id for n in reaching(library, steps["C"]).listed] == ["N1"]
    assert reaching(library, steps["D"]).listed == ()
    # The step itself sees its own note: a re-run is a pick-up too.
    assert [n.id for n in reaching(library, steps["A"]).listed] == ["N1"]


def test_a_decision_reaches_every_step_wherever_it_was_made():
    library, project, steps = build({"A": [], "B": []})
    log(library, project, Note("N1", "decision", "SQLite", step=steps["A"].id))
    assert [n.id for n in reaching(library, steps["B"]).listed] == ["N1"]


def test_reach_project_lifts_a_handoff_to_everyone_and_no_step_means_everyone():
    library, project, steps = build({"A": [], "B": []})
    log(
        library,
        project,
        Note("N1", "handoff", "Everyone", step=steps["A"].id, reach="project"),
        Note("N2", "handoff", "Nowhere in particular"),
    )
    assert [n.id for n in reaching(library, steps["B"]).listed] == ["N1", "N2"]


def test_a_note_addressed_to_a_step_is_carried_in_full_and_not_listed_twice():
    library, project, steps = build({"A": [], "B": []})
    note = Note(
        "N1", "later", "Retry logic is a stub", body="In client.py.", for_steps=(steps["B"].id,)
    )
    log(library, project, note)
    index = reaching(library, steps["B"])
    assert index.addressed == (note,) and index.listed == ()
    blocks = briefing_blocks(project, index, key_of)
    assert [b.heading for b in blocks] == ["Notes for this step"]
    assert "**N1 later · Retry logic is a stub**" in blocks[0].body
    assert "  In client.py." in blocks[0].body and blocks[0].carried == (note,)
    # A step it is not addressed to sees it in the index, its body left out.
    other = briefing_blocks(project, reaching(library, steps["A"]), key_of)
    assert [b.heading for b in other] == ["Notes so far"]
    assert "N1 · Retry logic is a stub" in other[0].body and "client.py" not in other[0].body


def test_a_superseded_note_leaves_the_index_and_the_index_groups_by_label():
    library, project, steps = build({"A": []})
    log(
        library,
        project,
        Note("N1", "decision", "Ship weekly", made="2026-09-05"),
        Note("N2", "decision", "Ship daily", made="2026-09-06", supersedes="N1"),
        Note("N3", "spec-change", "No remember-me box", step=steps["A"].id),
        Note("N4", "handoff", "Keys", step=steps["A"].id),
    )
    (block,) = briefing_blocks(project, reaching(library, steps["A"]), key_of)
    assert "Ship weekly" not in block.body
    assert block.body.index("Decisions standing (1):") < block.body.index("Handoffs from the steps")
    assert "- N2 · Ship daily (6 September)" in block.body
    assert "- N3 · No remember-me box (on S1)" in block.body
    assert "dplanner note show Discovery <id>" in block.body


def test_the_same_title_on_the_same_step_is_the_same_note():
    a = Note("N1", "handoff", "Done", step="s1")
    assert same_note([a], " done ", "s1") is a
    assert same_note([a], "Done", "s2") is None


def test_the_log_is_read_tolerantly_and_written_with_absence_for_the_defaults():
    entry = write_log(
        [Note("N1", "handoff", "Keys", step="s1", reach="downstream", for_steps=("s2",))]
    )
    assert entry == {
        "format": 1,
        "notes": [{"id": "N1", "label": "handoff", "title": "Keys", "step": "s1", "for": ["s2"]}],
    }
    project = Project(title="x")
    project.module_data[MODULE_ID] = {"notes": [{"id": "N1"}, {"nope": 1}, "junk"]}
    (note,) = read_log(project)
    assert note.label == "decision" and note.title == ""
    assert write_log([]) == {}


# -- the card and the editor ---------------------------------------------------------------------


@pytest.fixture
def project(services, make_project):
    project = make_project("Discovery")
    AddNodeCommand(project.id, Step(title="Read the spec")).redo(services.document)
    AddNodeCommand(project.id, Step(title="Deploy")).redo(services.document)
    records = [
        Note(
            "N1",
            "decision",
            "Keep SQLite",
            body="One operator.",
            made="2026-09-05",
            step=project.steps[0].id,
        ),
        Note("N2", "decision", "Ship weekly", made="2026-09-06"),
        Note("N3", "decision", "Ship daily", made="2026-09-07", supersedes="N2"),
        Note(
            "N4",
            "handoff",
            "Keys in vault",
            step=project.steps[0].id,
            for_steps=(project.steps[1].id,),
        ),
    ]
    services.undo.push(SetModuleDataCommand(project.id, MODULE_ID, write_log(records)))
    return project


@pytest.fixture
def card(services, project):
    spec = next(s for s in services.detail_cards.sections() if s.id == "notes.card")
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
    assert "Notes" in [c.title.text() for c in panel._cards]


def test_the_rows_say_what_when_where_for_whom_and_whether_it_stands(card):
    assert rows(card) == [
        ("Keep SQLite", "N1 · decision · 5 September · on S1"),
        ("Ship weekly", "N2 · decision · 6 September · superseded by N3"),
        ("Ship daily", "N3 · decision · 7 September"),
        ("Keys in vault", "N4 · handoff · on S1 · for S2"),
    ]
    assert not card.empty.isVisibleTo(card)
    assert card.rows[0].toolTip() == "One operator."


def test_the_rows_follow_the_log(services, project, card):
    services.undo.push(SetModuleDataCommand(project.id, MODULE_ID, {}))
    assert card.rows == () and card.empty.isVisibleTo(card)


def test_add_records_a_fresh_note_and_opens_it_on_the_title(services, project, card, monkeypatch):
    opened = []
    monkeypatch.setattr(NoteDialog, "exec", lambda self: opened.append(self))
    fresh = card.add_note()
    assert fresh == "N5"
    record = read_log(project)[-1]
    assert record.title == FRESH_TITLE and record.made == date.today().isoformat()
    assert record.label == "decision"
    (dialog,) = opened
    assert dialog.editor.title.text() == FRESH_TITLE and dialog.editor.title.selectedText()
    assert services.undo.undo_text() == "Add Note"
    services.undo.undo()
    assert [r.id for r in read_log(project)] == ["N1", "N2", "N3", "N4"]


@pytest.fixture
def editor(services, project):
    editor = NoteEditor(services.document, services.undo, lambda step: f"S{step.number}")
    editor.show_record(project.id, "N4")
    yield editor
    editor.dispose()


def test_the_editor_shows_the_record_and_commits_each_field_as_it_is_left(
    services, project, editor
):
    assert editor.label.currentText() == "handoff"
    assert editor.title.text() == "Keys in vault"
    assert editor.step.currentText() == "S1  Read the spec"
    assert editor.addressed.text() == "S2"
    assert editor.everyone.isEnabled() and not editor.everyone.isChecked()
    editor.title.setText("Keys in 1Password")
    editor.title.editingFinished.emit()
    editor.everyone.setChecked(True)
    editor.addressed.setText("S1 S2 nobody")
    editor.addressed.editingFinished.emit()
    editor.label.setCurrentIndex(editor.label.findData("later"))
    record = read_log(project)[3]
    assert record.title == "Keys in 1Password" and record.label == "later"
    assert record.for_steps == (project.steps[0].id, project.steps[1].id)
    # A label that reaches everyone by default has nothing for the box to lift.
    assert not editor.everyone.isEnabled() and editor.everyone.isChecked()
    assert record.reach == ""
    assert services.undo.undo_text() == "Edit Note N4"


def test_lifting_a_handoff_to_everyone_is_stored_only_as_the_exception(services, project, editor):
    editor.everyone.setChecked(True)
    assert read_log(project)[3].reach == "project"
    editor.everyone.setChecked(False)
    assert read_log(project)[3].reach == ""


def test_typing_the_body_is_undoable_prose(services, project, editor):
    editor.body.edit.setFocus()
    editor.body.edit.insertPlainText("Ask ops.")
    assert read_log(project)[3].body == "Ask ops."
    services.undo.undo()
    assert read_log(project)[3].body == ""


def test_a_foreign_change_reloads_the_fields(services, project, editor):
    changed = [Note("N4", "spec-change", "Renamed elsewhere")]
    services.undo.push(SetModuleDataCommand(project.id, MODULE_ID, write_log(changed)))
    assert editor.title.text() == "Renamed elsewhere"
    assert editor.label.currentText() == "spec-change"
    assert editor.step.currentIndex() == 0 and editor.supersedes.count() == 1
    assert editor.addressed.text() == ""


def test_the_dialog_removes_the_note_and_unlinks_what_superseded_it(services, project):
    dialog = NoteDialog(
        services.document, services.undo, lambda step: f"S{step.number}", project.id, "N2"
    )
    dialog.remove_button.click()
    assert [r.id for r in read_log(project)] == ["N1", "N3", "N4"]
    assert read_log(project)[1].supersedes == ""
    assert services.undo.undo_text() == "Remove Note N2"
    dialog.dispose()
    dialog.deleteLater()
