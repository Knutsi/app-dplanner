"""The session: refresh in place, and the rebuild that is left as the fallback."""

from PySide6.QtCore import QSize

from dplanner.domain.commands import SetFieldCommand
from dplanner.domain.store import LibraryStore


def test_a_rebuild_stands_where_the_window_it_replaces_stood(session, make_project):
    make_project("Discovery")
    session.services.autosave.flush_now()
    session.window.resize(QSize(760, 560))

    assert session.reload()

    assert session.window.size() == QSize(760, 560)


def test_refresh_takes_an_outside_change_without_a_rebuild(session, make_project, library_file):
    project = make_project("Discovery")
    session.services.autosave.flush_now()
    window = session.window
    other = LibraryStore(library_file)
    theirs = other.load()
    theirs.set_field(project.id, "summary", "from outside")
    other.flush({(project.id, "meta")})

    result = session.refresh()

    assert not result.rebuilt and result.adoption is not None and result.adoption.applied == 1
    assert session.window is window
    assert session.services.document.projects[0].summary == "from outside"


def test_refresh_forgets_history_only_when_something_was_taken(session, make_project, library_file):
    project = make_project("Discovery")
    services = session.services
    services.undo.push(SetFieldCommand(project.id, "title", "Typed here"))
    services.autosave.flush_now()

    session.refresh(forget_history=True)
    assert services.undo.can_undo()  # Nothing changed on disk: nothing to forget.

    other = LibraryStore(library_file)
    theirs = other.load()
    theirs.set_field(project.id, "summary", "from outside")
    other.flush({(project.id, "meta")})
    session.refresh(forget_history=True)
    assert not services.undo.can_undo()
