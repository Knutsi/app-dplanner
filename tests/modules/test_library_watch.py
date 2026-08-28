"""Two writers, one workspace — the window's half.

The scenario DPlanner is built for: an agent runs `dplanner …` against the same folder a
window has open. These assert the two outcomes that matter — take the change when nothing is
owed, and refuse to erase anybody when something is.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand, SetFieldCommand
from dplanner.domain.model import Project
from dplanner.domain.store import ProductStore, StaleWorkspaceError


def module(session):
    return next(m for m in session.services.modules if m.id == "library_watch")


def another_writer(session, title="Written by an agent"):
    """A second store over the same folder — exactly what the CLI is."""
    other_store = ProductStore(session.services.storage)
    other = other_store.load()
    project = Project(title=title)
    AddNodeCommand(other.id, project).redo(other)
    other_store.flush({(other.id, "structure")})
    return other_store


@pytest.fixture
def watcher(session):
    return module(session)._watcher


def test_a_clean_window_takes_the_change(session, watcher):
    """Nothing unflushed here, so the other writer's work is simply read back."""
    another_writer(session)
    watcher._check()
    assert [p.title for p in session.services.document.projects] == ["Written by an agent"]


def test_no_reload_while_this_window_owes_a_write(session, watcher):
    """Reporting our own pending write as somebody else's edit would be a lie."""
    services = session.services
    services.undo.push(SetFieldCommand(services.document.id, "name", "Typed here"))
    assert services.autosave.has_pending()
    watcher._check()
    assert services.document.name == "Typed here"


def test_the_store_refuses_to_erase_the_other_writer(session):
    """The backstop: if a flush does race, nothing is overwritten."""
    services = session.services
    services.undo.push(SetFieldCommand(services.document.id, "name", "Typed here"))
    another_writer(session)

    with pytest.raises(StaleWorkspaceError):
        services.repo.flush({(services.document.id, "meta")})


def test_a_refused_write_keeps_the_edits_and_stops_retrying(session):
    """Dropping the marks would lose the user's typing; retrying every 1.5 s would make one
    problem endless. Autosave does neither."""
    services = session.services
    services.undo.push(SetFieldCommand(services.document.id, "name", "Typed here"))
    another_writer(session)

    services.autosave.flush_now()
    assert services.autosave.has_pending()  # The batch went back.
    assert module(session)._conflicted  # And somebody was told.

    services.autosave.flush_now()  # Paused: this does nothing rather than raising again.
    assert services.autosave.has_pending()


def test_reload_is_offered_and_discards_what_was_typed(session, monkeypatch):
    services = session.services
    services.undo.push(SetFieldCommand(services.document.id, "name", "Typed here"))
    another_writer(session)
    services.autosave.flush_now()

    from dplanner.modules.library_watch import module as watch_module

    monkeypatch.setattr(watch_module, "confirm", lambda *_args: True)
    assert services.actions.spec("library_watch.reload").state(services.context.current()).enabled
    services.actions.run("library_watch.reload", services.context.current())

    assert session.services.document.name != "Typed here"
    assert [p.title for p in session.services.document.projects] == ["Written by an agent"]
