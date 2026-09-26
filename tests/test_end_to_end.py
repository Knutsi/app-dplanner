"""The whole application, exercised the way a person would use it.

One test that opens every registered activity, makes a mixed set of edits, undoes them all,
closes, reopens, and asserts the project files on disk are byte-identical to how they
started. It catches the class of bug no unit test can: an aspect that is written but never
read back, a command whose undo is not quite the inverse, a file that is created and not
cleaned up.
"""

import hashlib
from pathlib import Path

from dplanner.app import new_session
from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step, TextEdit
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri


def fingerprint(root: Path) -> dict[str, str]:
    """Every file under ``root``, by relative path and content hash. The repository's own
    bookkeeping is skipped: undo restores the working tree, not git's internals."""
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


def seed_steps(services, project):
    """Put content in the seeded project, the way the CLI does: apply, do not push.

    Deliberately *not* through the undo stack. This is the setup, not the edit under test —
    and it is also exactly what an agent does before the user starts editing, so the state
    these tests begin from is the state a real session begins from.
    """
    library = services.document
    for title in ("Read the spec", "Draft the model"):
        AddNodeCommand(project.id, Step(title=title)).redo(library)
    return project


def test_every_registered_activity_opens(session, make_project):
    services = session.services
    project = seed_steps(services, make_project("Discovery"))
    services.tabs.open("project", project.id)
    services.tabs.open("order", project.id)
    services.tabs.open("llm_calls")
    services.tabs.open("telemetry")
    assert len(services.tabs.activities()) >= 4

    for activity in services.tabs.activities():
        assert activity.widget is not None
        activity.on_activated()


def test_the_index_lists_what_the_library_holds(session, make_project):
    services = session.services
    seed_steps(services, make_project("Discovery"))
    assert [s.id for s in services.index_segments.segments()] == [
        "projects",
        "tests",
        "docs",
        "archive",
    ]


def test_a_mixed_edit_chain_undoes_back_to_an_identical_workspace(
    session, make_project, library_file, library_repo
):
    services = session.services
    library = services.document
    project = seed_steps(services, make_project("Discovery"))
    services.autosave.flush_now()
    before = fingerprint(library_repo)
    assert before  # The project is really on disk.

    first, second = project.steps[0], project.steps[1]
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )

    # One of every kind of change this domain has, each through the undo stack.
    from dplanner.domain.commands import (
        EditTextCommand,
        RemoveNodeCommand,
        SetEdgesCommand,
        SetFieldCommand,
        SetModuleDataCommand,
    )

    services.undo.push(SetFieldCommand(project.id, "title", "Renamed"))
    services.undo.break_coalescing()
    services.undo.push(SetFieldCommand(project.id, "summary", "what we do not know"))
    services.undo.break_coalescing()
    services.undo.push(EditTextCommand(TextEdit(first.id, "step_description", 0, "", "# Notes\n")))
    services.undo.break_coalescing()
    services.undo.push(SetModuleDataCommand(first.id, "estimation", {"days": 3.0, "format": 1}))
    services.undo.break_coalescing()
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    services.undo.break_coalescing()
    services.undo.push(AddNodeCommand(project.id, Step(title="Added")))
    services.undo.break_coalescing()
    services.undo.push(RemoveNodeCommand(first.id))
    services.autosave.flush_now()
    assert fingerprint(library_repo) != before

    while services.undo.can_undo():
        services.undo.undo()
    services.autosave.flush_now()
    assert fingerprint(library_repo) == before

    # And it survives a full reload: what is on disk is what comes back.
    session.close()
    reopened = new_session()
    assert reopened.open_initial(library_file)
    assert reopened.services is not None
    try:
        reopened_titles = [getattr(n, "title", n.kind) for n in reopened.services.document.nodes()]
        assert reopened_titles == [getattr(n, "title", n.kind) for n in library.nodes()]
        assert fingerprint(library_repo) == before
    finally:
        reopened.close()


def test_reopening_restores_the_same_workspace(session, make_project, library_file):
    seed_steps(session.services, make_project("Discovery"))
    session.services.autosave.flush_now()
    original_ids = [node.id for node in session.services.document.nodes()]
    session.close()

    reopened = new_session()
    assert reopened.open_initial(library_file)
    assert reopened.services is not None
    try:
        assert [node.id for node in reopened.services.document.nodes()] == original_ids
    finally:
        reopened.close()
