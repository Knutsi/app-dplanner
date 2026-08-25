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
from dplanner.domain.model import Project, Step, TextEdit
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


def seed_a_project(services):
    """Put content in an empty product, the way the CLI does: apply, do not push.

    Deliberately *not* through the undo stack. This is the setup, not the edit under test —
    and it is also exactly what an agent does before the user starts editing, so the state
    these tests begin from is the state a real session begins from.
    """
    from dplanner.domain.commands import AddNodeCommand

    product = services.document
    project = Project(title="Discovery", summary="what we do not know")
    AddNodeCommand(product.id, project).redo(product)
    for title in ("Read the spec", "Draft the model"):
        AddNodeCommand(project.id, Step(title=title)).redo(product)
    return project


def test_every_registered_activity_opens(workspace):
    session, _location, _root = workspace
    services = session.services
    project = seed_a_project(services)
    services.tabs.open("project", project.id)
    services.tabs.open("product")
    services.tabs.open("llm_calls")
    assert len(services.tabs.activities()) >= 3
    for activity in services.tabs.activities():
        assert activity.widget is not None
        activity.on_activated()


def test_the_index_lists_what_the_product_holds(workspace):
    session, _location, _root = workspace
    services = session.services
    seed_a_project(services)
    assert [s.id for s in services.index_segments.segments()] == ["projects"]


def test_a_mixed_edit_chain_undoes_back_to_an_identical_workspace(workspace, close_quietly):
    session, location, root = workspace
    services = session.services
    product = services.document
    project = seed_a_project(services)
    services.autosave.flush_now()
    before = fingerprint(root)
    assert before  # The workspace is really on disk.

    first, second = project.steps[0], project.steps[1]
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )

    # One of every kind of change this domain has, each through the undo stack.
    from dplanner.domain.commands import (
        AddNodeCommand,
        EditTextCommand,
        RemoveNodeCommand,
        SetEdgesCommand,
        SetFieldCommand,
        SetModuleDataCommand,
    )

    services.undo.push(SetFieldCommand(project.id, "title", "Renamed"))
    services.undo.break_coalescing()
    services.undo.push(SetFieldCommand(product.id, "repository", "git@example.com:w.git"))
    services.undo.break_coalescing()
    services.undo.push(EditTextCommand(TextEdit(first.id, "step_description", 0, "", "# Notes\n")))
    services.undo.break_coalescing()
    services.undo.push(SetModuleDataCommand(first.id, "step_estimation", {"days": 3.0}))
    services.undo.break_coalescing()
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    services.undo.break_coalescing()
    services.undo.push(AddNodeCommand(project.id, Step(title="Added")))
    services.undo.break_coalescing()
    services.undo.push(RemoveNodeCommand(first.id))
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
        reopened_titles = [getattr(n, "title", n.kind) for n in reopened.services.document.nodes()]
        assert reopened_titles == [getattr(n, "title", n.kind) for n in product.nodes()]
        assert fingerprint(root) == before
    finally:
        close_quietly(reopened)


def test_reopening_restores_the_same_workspace(workspace, close_quietly):
    session, location, _root = workspace
    seed_a_project(session.services)
    session.services.autosave.flush_now()
    original_ids = [node.id for node in session.services.document.nodes()]
    close_quietly(session)

    reopened = new_session()
    assert reopened.open_initial(location)
    assert reopened.services is not None
    try:
        assert [node.id for node in reopened.services.document.nodes()] == original_ids
    finally:
        close_quietly(reopened)


def test_opening_the_same_workspace_twice_is_refused_politely(workspace):
    session, location, _root = workspace
    window = session.window
    assert session.switch_to(location) is True
    assert session.window is window  # Not rebuilt: it was already open.
