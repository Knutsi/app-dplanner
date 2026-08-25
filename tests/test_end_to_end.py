"""The whole application, exercised the way a person would use it.

One test that opens every registered activity, makes a mixed set of edits, undoes them all,
closes, reopens, and asserts the workspace on disk is byte-identical to how it started. It
catches the class of bug no unit test can: an aspect that is written but never read back, a
command whose undo is not quite the inverse, a file that is created and not cleaned up.
"""

import hashlib
from pathlib import Path

import pytest

from dplanner.app import new_session
from dplanner.core.storage.locations import StorageLocation
from dplanner.domain.model import Task
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri


def fingerprint(root: Path) -> dict[str, str]:
    """Every file under ``root``, by relative path and content hash."""
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def workspace(app, tmp_path, close_quietly):
    location = StorageLocation(scheme="", target=str(tmp_path / "workspace"))
    session = new_session()
    assert session.open_initial(location)
    yield session, location, tmp_path / "workspace"
    close_quietly(session)


def test_every_registered_activity_opens(workspace):
    session, _location, _root = workspace
    services = session.services
    plan = services.document
    services.tabs.open("task", plan.root.children[0].id)
    services.tabs.open("llm_calls")
    assert len(services.tabs.activities()) >= 2
    for activity in services.tabs.activities():
        assert activity.widget is not None
        activity.on_activated()


def test_a_mixed_edit_chain_undoes_back_to_an_identical_workspace(workspace, close_quietly):
    session, location, root = workspace
    services = session.services
    plan = services.document
    services.autosave.flush_now()
    before = fingerprint(root)
    assert before  # The seeded workspace is really on disk.

    first = plan.root.children[0]
    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("task", first.id)),))

    # Four different kinds of change, each through the undo stack.
    from dplanner.domain.commands import (
        AddTaskCommand,
        RemoveTaskCommand,
        SetFieldCommand,
        SetNotesCommand,
        SetTitleCommand,
    )

    services.undo.push(SetTitleCommand(first.id, "Renamed"))
    services.undo.break_coalescing()
    services.undo.push(SetNotesCommand(first.id, "a note"))
    services.undo.break_coalescing()
    services.undo.push(SetFieldCommand(first.id, "assignee", "knut"))
    services.undo.break_coalescing()
    added = Task(title="Added")
    services.undo.push(AddTaskCommand(plan.root.id, added))
    services.undo.break_coalescing()
    services.undo.push(RemoveTaskCommand(plan.root.children[1].id))
    services.autosave.flush_now()
    assert fingerprint(root) != before

    while services.undo.can_undo():
        services.undo.undo()
    services.autosave.flush_now()
    assert fingerprint(root) == before

    # And it survives a full reload: what is on disk is what comes back.
    close_quietly(session)
    reopened = new_session()
    assert reopened.open_initial(location)
    assert reopened.services is not None
    try:
        titles = [task.title for task in reopened.services.document.tasks()]
        assert titles == [task.title for task in plan.tasks()]
        assert fingerprint(root) == before
    finally:
        close_quietly(reopened)


def test_reopening_restores_the_same_workspace(workspace, close_quietly):
    session, location, _root = workspace
    original_ids = [task.id for task in session.services.document.tasks()]
    close_quietly(session)

    reopened = new_session()
    assert reopened.open_initial(location)
    assert reopened.services is not None
    try:
        assert [task.id for task in reopened.services.document.tasks()] == original_ids
    finally:
        close_quietly(reopened)


def test_opening_the_same_workspace_twice_is_refused_politely(workspace):
    session, location, _root = workspace
    window = session.window
    assert session.switch_to(location) is True
    assert session.window is window  # Not rebuilt: it was already open.
