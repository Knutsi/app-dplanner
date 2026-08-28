"""Two writers, one library — the window's half.

The scenario DPlanner is built for: an agent runs `dplanner …` against a project a window
has open. These assert the two outcomes that matter — take the change when nothing is owed,
and refuse to erase anybody when something is. The watch spans the project directories *and*
the library file itself, so another instance adding a project arrives the same way an
agent's edit does.
"""

import pytest

from dplanner.domain.commands import SetFieldCommand
from dplanner.domain.seed import seed_project
from dplanner.domain.store import LibraryStore, StaleWorkspaceError


def module(session):
    return next(m for m in session.services.modules if m.id == "library_watch")


def agent_adds_a_project(library_file, library_repo, title="Written by an agent"):
    """A second store over the same library file — exactly what another instance is.

    Adding a project rewrites the library file, not any directory this window watches a
    node in — the change a watch on project dirs alone would miss.
    """
    other_store = LibraryStore(library_file)
    other = other_store.load()
    directory = seed_project(library_repo / "agent-project", title)
    project = other_store.attach(directory)
    other.add_child(other.id, project)
    other_store.flush({(other.id, "structure")})


def agent_edits_the_project(library_file, title="Agent titled"):
    """A second store editing a project this window has open — exactly what the CLI is."""
    other_store = LibraryStore(library_file)
    other = other_store.load()
    project = other.projects[0]
    other.set_field(project.id, "title", title)
    other_store.flush({(project.id, "meta")})


@pytest.fixture
def watcher(session):
    return module(session)._watcher


@pytest.fixture
def project(services, make_project):
    """One flushed project, so the window starts clean with nothing pending."""
    project = make_project("Discovery")
    services.autosave.flush_now()
    return project


def test_a_clean_window_takes_an_edit_inside_a_project(session, project, watcher, library_file):
    """Nothing unflushed here, so the other writer's work is simply read back."""
    agent_edits_the_project(library_file)
    watcher._check()
    assert [p.title for p in session.services.document.projects] == ["Agent titled"]


def test_a_change_to_the_library_file_itself_reloads_too(
    session, project, watcher, library_file, library_repo
):
    """Another instance adding a project touches only the library file — and still lands."""
    agent_adds_a_project(library_file, library_repo)
    watcher._check()
    titles = [p.title for p in session.services.document.projects]
    assert titles == ["Discovery", "Written by an agent"]


def test_no_reload_while_this_window_owes_a_write(
    session, project, watcher, library_file, library_repo
):
    """Reporting our own pending write as somebody else's edit would be a lie."""
    services = session.services
    services.undo.push(SetFieldCommand(project.id, "title", "Typed here"))
    assert services.autosave.has_pending()
    agent_adds_a_project(library_file, library_repo)
    watcher._check()
    assert [p.title for p in services.document.projects] == ["Typed here"]


def test_the_store_refuses_to_erase_the_other_writer(session, project, library_file):
    """The backstop: if a flush does race, nothing is overwritten."""
    services = session.services
    services.undo.push(SetFieldCommand(project.id, "title", "Typed here"))
    agent_edits_the_project(library_file)

    with pytest.raises(StaleWorkspaceError):
        services.repo.flush({(project.id, "meta")})


def test_a_refused_write_keeps_the_edits_and_stops_retrying(session, project, library_file):
    """Dropping the marks would lose the user's typing; retrying every 1.5 s would make one
    problem endless. Autosave does neither."""
    services = session.services
    services.undo.push(SetFieldCommand(project.id, "title", "Typed here"))
    agent_edits_the_project(library_file)

    services.autosave.flush_now()
    assert services.autosave.has_pending()  # The batch went back.
    assert module(session)._conflicted  # And somebody was told.

    services.autosave.flush_now()  # Paused: this does nothing rather than raising again.
    assert services.autosave.has_pending()


def test_reload_is_offered_and_discards_what_was_typed(session, project, library_file, monkeypatch):
    services = session.services
    services.undo.push(SetFieldCommand(project.id, "title", "Typed here"))
    agent_edits_the_project(library_file)
    services.autosave.flush_now()

    from dplanner.modules.library_watch import module as watch_module

    monkeypatch.setattr(watch_module, "confirm", lambda *_args: True)
    assert services.actions.spec("library_watch.reload").state(services.context.current()).enabled
    services.actions.run("library_watch.reload", services.context.current())

    assert [p.title for p in session.services.document.projects] == ["Agent titled"]
