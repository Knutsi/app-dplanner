"""Two writers, one library — the window's half.

The scenario DPlanner is built for: an agent runs `dplanner …` against a project a window
has open. These assert the outcomes that matter — the change lands in the running window
with nothing of the user's thrown away, an entry both sides changed is put to the user
rather than decided for them, and the rebuild is never the answer to an ordinary edit. The
watch spans the project directories *and* the library file itself, so another instance
adding a project arrives the same way an agent's edit does.
"""

import json
from pathlib import Path
from typing import ClassVar

import pytest

from dplanner.domain.commands import AddNodeCommand, SetFieldCommand
from dplanner.domain.model import Step
from dplanner.domain.seed import seed_project
from dplanner.domain.store import LibraryStore, StaleWorkspaceError
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.library_watch import module as watch_module
from dplanner.modules.library_watch.view import AGENT, LATER, MINE, THEIRS
from dplanner.modules.step_agent_instruction import launcher


def module(session):
    return next(m for m in session.services.modules if m.id == "library_watch")


def run_tracker(session):
    return next(m for m in session.services.modules if m.id == "step_agent_run")


def other_writer(library_file):
    """A second store over the same library file — exactly what the CLI is."""
    other = LibraryStore(library_file)
    return other, other.load()


def agent_adds_a_project(library_file, library_repo, title="Written by an agent"):
    """Adding a project rewrites the library file, not any directory this window watches a
    node in — the change a watch on project dirs alone would miss."""
    other_store, other = other_writer(library_file)
    directory = seed_project(library_repo / "agent-project", title)
    project = other_store.attach(directory)
    other.add_child(other.id, project)
    other_store.flush({(other.id, "structure")})


def agent_edits_the_project(library_file, title="Agent titled"):
    other_store, other = other_writer(library_file)
    project = other.projects[0]
    other.set_field(project.id, "title", title)
    other_store.flush({(project.id, "meta")})


def agent_edits_a_step(library_file, step_id, title="Agent titled step"):
    other_store, other = other_writer(library_file)
    other.set_field(step_id, "title", title)
    other_store.flush({(step_id, "meta")})


def agent_adds_a_step(library_file, title="Added by an agent"):
    other_store, other = other_writer(library_file)
    project = other.projects[0]
    other.add_child(project.id, Step(title=title))
    other_store.flush({(project.id, "structure")})


def agent_removes_a_step(library_file, step_id):
    other_store, other = other_writer(library_file)
    project = other.project_of(step_id)
    other.remove_child(step_id)
    other_store.flush({(project.id, "structure")})


class FakeDialog:
    """Stands in for the modal: answers what the test decided, records that it was asked."""

    asked: ClassVar[list[list[str]]] = []
    refusals: ClassVar[list[str]] = []
    answer = LATER

    def __init__(self, rows, agent_refusal, _parent):
        FakeDialog.asked.append(list(rows))
        FakeDialog.refusals.append(agent_refusal)

    def choose(self):
        return FakeDialog.answer


@pytest.fixture(autouse=True)
def _no_real_modal(monkeypatch):
    """A conflict raises the dialog through a zero-timer; a real one would hang the run."""
    FakeDialog.asked, FakeDialog.refusals, FakeDialog.answer = [], [], LATER
    monkeypatch.setattr(watch_module, "ConflictDialog", FakeDialog)


@pytest.fixture
def watcher(session):
    return module(session)._watcher


@pytest.fixture
def project(services, make_project):
    """One flushed project, so the window starts clean with nothing pending."""
    project = make_project("Discovery")
    services.autosave.flush_now()
    return project


@pytest.fixture
def step(services, project):
    services.undo.push(AddNodeCommand(project.id, Step(title="Read the spec")))
    services.autosave.flush_now()
    return project.steps[0]


# -- the change lands in place -----------------------------------------------------------------


def test_a_clean_window_takes_an_edit_inside_a_project(session, project, watcher, library_file):
    window = session.window
    agent_edits_the_project(library_file)
    watcher._check()
    assert [p.title for p in session.services.document.projects] == ["Agent titled"]
    assert session.window is window  # Taken in place, not rebuilt.


def test_a_change_to_the_library_file_itself_lands_too(
    session, project, watcher, library_file, library_repo
):
    """Another instance adding a project touches only the library file — and still lands."""
    window = session.window
    agent_adds_a_project(library_file, library_repo)
    watcher._check()
    titles = [p.title for p in session.services.document.projects]
    assert titles == ["Discovery", "Written by an agent"]
    assert session.window is window


def test_the_rebuild_is_never_the_answer_to_an_ordinary_edit(
    session, project, watcher, library_file, monkeypatch
):
    monkeypatch.setattr(session, "reload", lambda: pytest.fail("rebuilt for an ordinary edit"))
    agent_edits_the_project(library_file)
    watcher._check()
    assert session.services.document.projects[0].title == "Agent titled"


def test_an_outside_edit_keeps_the_undo_history(session, step, watcher, library_file):
    services = session.services
    services.undo.push(SetFieldCommand(step.id, "title", "Renamed here"))
    services.autosave.flush_now()
    agent_adds_a_step(library_file)
    watcher._check()

    assert [s.title for s in services.document.projects[0].steps] == [
        "Renamed here",
        "Added by an agent",
    ]
    assert services.undo.can_undo()
    services.undo.undo()
    assert services.document.step(step.id).title == "Read the spec"


def test_an_outside_removal_drops_only_the_undo_entries_that_name_it(
    session, step, watcher, library_file
):
    services = session.services
    services.undo.push(SetFieldCommand(step.id, "title", "Renamed here"))
    services.autosave.flush_now()
    agent_removes_a_step(library_file, step.id)
    watcher._check()

    assert not services.document.has(step.id)
    services.undo.undo()  # Names a step that is gone: dropped, not raised.
    assert not services.document.has(step.id)


def test_an_outside_edit_keeps_the_selection(session, step, watcher, library_file):
    services = session.services
    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("step", step.id)),))
    agent_edits_the_project(library_file)
    watcher._check()
    assert services.context.current().selected_entity("step") == step.id


def test_an_unrelated_outside_change_lands_even_while_this_window_owes_a_write(
    session, project, watcher, library_file, library_repo
):
    """A pending write here and an outside change elsewhere are not in each other's way."""
    services = session.services
    services.undo.push(SetFieldCommand(project.id, "title", "Typed here"))
    assert services.autosave.has_pending()
    agent_adds_a_project(library_file, library_repo)
    watcher._check()
    assert [p.title for p in services.document.projects] == ["Typed here", "Written by an agent"]
    services.autosave.flush_now()
    assert not services.autosave.has_pending()


# -- the refusal, and what clears it -----------------------------------------------------------


def test_the_store_refuses_to_erase_the_other_writer(session, project, library_file):
    """The backstop: if a flush does race, nothing is overwritten."""
    services = session.services
    services.undo.push(SetFieldCommand(project.id, "title", "Typed here"))
    agent_edits_the_project(library_file)

    with pytest.raises(StaleWorkspaceError):
        services.repo.flush({(project.id, "meta")})


def test_a_refused_write_that_taking_the_change_clears_resumes_autosave(
    session, step, library_file
):
    """The window edited one entry, the agent another in the same project: the flush is
    refused once, the agent's entry is taken, and the retry writes ours."""
    services = session.services
    project = services.document.projects[0]
    services.undo.push(SetFieldCommand(project.id, "title", "Typed here"))
    agent_edits_a_step(library_file, step.id)

    services.autosave.flush_now()

    assert services.document.step(step.id).title == "Agent titled step"
    assert not FakeDialog.asked
    services.autosave.flush_now()
    assert not services.autosave.has_pending()


# -- an entry both sides changed ---------------------------------------------------------------


def collide(session, project, library_file):
    services = session.services
    services.undo.push(SetFieldCommand(project.id, "title", "Typed here"))
    agent_edits_the_project(library_file)
    services.autosave.flush_now()  # Refused → refresh → one conflict.
    return module(session)


def test_a_conflict_keeps_the_edit_pauses_autosave_and_asks(session, project, library_file):
    watch = collide(session, project, library_file)
    services = session.services

    assert services.autosave.has_pending()
    assert services.document.projects[0].title == "Typed here"
    assert [c.entry for c in watch._conflicts] == ["meta"]
    services.autosave.flush_now()  # Paused: does nothing rather than raising again.
    assert services.autosave.has_pending()

    watch._ask()
    assert FakeDialog.asked == [["Typed here · title and summary"]]
    assert FakeDialog.refusals == [watch_module.NO_STEP]  # A project entry: no agent.
    assert not watch._button.isHidden()  # Later leaves the question reachable.


def test_taking_theirs_adopts_and_resumes(session, project, library_file):
    watch = collide(session, project, library_file)
    FakeDialog.answer = THEIRS
    watch._ask()

    assert session.services.document.projects[0].title == "Agent titled"
    session.services.autosave.flush_now()
    assert not session.services.autosave.has_pending()
    assert not watch._conflicts and watch._button.isHidden()


def test_keeping_mine_writes_over_theirs_and_resumes(session, project, library_file):
    watch = collide(session, project, library_file)
    FakeDialog.answer = MINE
    watch._ask()

    session.services.autosave.flush_now()
    meta = json.loads((session.services.repo.project_dir(project.id) / "project.dproj").read_text())
    assert meta["title"] == "Typed here"
    assert not session.services.autosave.has_pending()
    assert not session.services.repo.changed_underneath()


def test_resolving_with_an_agent_hands_over_both_versions_and_yields(
    session, step, library_file, monkeypatch
):
    services = session.services
    services.undo.push(SetFieldCommand(step.id, "title", "Typed here"))
    agent_edits_a_step(library_file, step.id)
    services.autosave.flush_now()
    watch = module(session)
    assert [c.node_id for c in watch._conflicts] == [step.id]

    spawned = []
    monkeypatch.setattr(launcher, "resolve_command", lambda *_a, **_k: ["true"])
    monkeypatch.setattr(launcher, "spawn", lambda command, _workdir: spawned.append(command))
    FakeDialog.answer = AGENT
    watch._ask()

    assert FakeDialog.refusals == [""]
    assert spawned
    (run,) = run_tracker(session).runs()
    assert run.step_id == step.id
    run_dir = Path(run.exit_file).parent
    mine = json.loads((run_dir / "mine" / "steps" / "read-the-spec" / "step.json").read_text())
    assert mine["title"] == "Typed here"
    prompt = (run_dir / "prompt.md").read_text()
    assert "steps/read-the-spec/step.json" in prompt and "agent-state clear" in prompt
    # The window yielded: the plan on disk is the truth until the agent writes the merge.
    assert services.document.step(step.id).title == "Agent titled step"
    services.autosave.flush_now()
    assert not services.autosave.has_pending()


def test_reload_is_offered_and_discards_what_was_typed(session, project, library_file, monkeypatch):
    services = session.services
    services.undo.push(SetFieldCommand(project.id, "title", "Typed here"))
    agent_edits_the_project(library_file)
    services.autosave.flush_now()

    monkeypatch.setattr(watch_module, "confirm", lambda *_args: True)
    assert services.actions.spec("library_watch.reload").state(services.context.current()).enabled
    services.actions.run("library_watch.reload", services.context.current())

    assert [p.title for p in session.services.document.projects] == ["Agent titled"]
