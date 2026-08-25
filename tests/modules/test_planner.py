"""The planner's own three modules: the tree, the editor and the properties panel."""

import pytest

from dplanner.framework.context import (
    SCOPE_SELECTION,
    Context,
    ContextNode,
    selection_uri,
)


def select(services, task_id):
    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("task", task_id)),))
    return services.context.current()


def by_title(services, title):
    return next(task for task in services.document.tasks() if task.title == title)


# -- the tree ----------------------------------------------------------------------------------


def test_the_tree_contributes_a_sidebar_page(services):
    assert "plan" in [panel.id for panel in services.sidebar_panels.panels()]


def test_delete_is_offered_for_a_task_and_refused_for_the_project(services):
    plan = services.document
    delete = services.actions.spec("plan_tree.delete")
    assert not delete.state(select(services, plan.root.id)).enabled
    assert delete.state(select(services, plan.root.children[0].id)).enabled


def test_actions_are_hidden_when_nothing_is_selected(services):
    """A pure function of the context: no widgets consulted, none needed."""
    assert not services.actions.spec("plan_tree.rename").state(Context({})).visible


def test_status_cannot_be_set_on_a_phase(services):
    """A phase's state is derived from its children, so offering to set it would let the
    plan disagree with itself."""
    phase = by_title(services, "Discovery")
    leaf = by_title(services, "First slice")
    spec = services.actions.spec("plan_tree.status_doing")
    assert not spec.state(select(services, phase.id)).enabled
    assert spec.state(select(services, leaf.id)).enabled


def test_the_status_action_reports_what_is_current(services):
    leaf = by_title(services, "Interviews")  # Seeded as done.
    assert services.actions.spec("plan_tree.status_done").state(select(services, leaf.id)).checked


def test_marking_done_is_undoable(services):
    leaf = by_title(services, "First slice")
    services.actions.run("plan_tree.toggle_done", select(services, leaf.id))
    assert leaf.status == "done"
    services.undo.undo()
    assert leaf.status == "todo"


def test_adding_a_task_is_undoable(services):
    plan = services.document
    before = len(plan.root.children)
    services.actions.run("plan_tree.new", select(services, plan.root.id))
    assert len(plan.root.children) == before + 1
    services.undo.undo()
    assert len(plan.root.children) == before


# -- the editor --------------------------------------------------------------------------------


def test_the_editor_opens_one_tab_per_task(services):
    first, second = by_title(services, "Discovery"), by_title(services, "Build")
    services.tabs.open("task", first.id)
    services.tabs.open("task", second.id)
    services.tabs.open("task", first.id)  # Again: the URI deduplicates.
    assert len(services.tabs.activities()) == 2


def test_a_retitle_retitles_the_tab(services):
    task = by_title(services, "Build")
    activity = services.tabs.open("task", task.id)
    services.document.set_title(task.id, "Ship it")
    assert activity.title == "Ship it"


def test_typing_a_description_goes_through_the_undo_stack(services):
    from PySide6.QtGui import QTextCursor

    task = by_title(services, "Build")
    activity = services.tabs.open("task", task.id)
    editor = activity.widget.widget(0)
    original = task.description

    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    cursor.insertText("what it is")
    assert task.description == original + "what it is"

    services.undo.undo()
    assert task.description == original
    assert editor.toPlainText() == original  # The view followed the model back.


# -- the properties panel ------------------------------------------------------------------------


@pytest.fixture
def card(services):
    section = next(s for s in services.inspector_sections.sections() if s.id.startswith("task_"))
    widget = section.factory()
    yield widget
    widget.dispose()


def test_editing_a_field_pushes_a_command(services, card):
    task = by_title(services, "First slice")
    card.show_target(task.id)
    card._assignee.setText("knut")
    card._assignee.editingFinished.emit()
    assert task.assignee == "knut"
    services.undo.undo()
    assert task.assignee == ""


def test_an_estimate_of_zero_means_not_estimated(services, card):
    """Not the same claim as "this is free" — and the roll-up counts them differently."""
    task = by_title(services, "First slice")
    card.show_target(task.id)
    card._estimate.setValue(0.0)
    card._estimate.editingFinished.emit()
    assert task.estimate_days is None


def test_a_phase_shows_its_roll_up_and_cannot_be_estimated(services, card):
    card.show_target(by_title(services, "Discovery").id)
    assert not card._estimate.isEnabled()
    assert not card._status.isEnabled()
    assert "rolled up" in card._estimate.specialValueText()


def test_the_panel_lists_what_a_task_waits_on(services, card):
    card.show_target(by_title(services, "First slice").id)
    assert card._waiting.count() == 1
    assert "Write up findings" in card._waiting.item(0).text()
    assert "Blocked" in card._note.text()


def test_finishing_a_blocker_unblocks_the_note(services, card):
    plan = services.document
    card.show_target(by_title(services, "First slice").id)
    plan.set_field(by_title(services, "Write up findings").id, "status", "done")
    assert "Everything it waits on is done" in card._note.text()


def test_the_panel_ignores_the_echo_of_its_own_edit(services, card):
    """The origin check: the widget already shows the change, so it must not reload."""
    task = by_title(services, "First slice")
    card.show_target(task.id)
    card._assignee.setText("knut")
    card._assignee.editingFinished.emit()
    assert card._assignee.text() == "knut"
