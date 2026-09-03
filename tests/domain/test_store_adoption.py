"""Adopting another writer's changes into a live library, entry by entry.

The scenario: an agent runs ``dplanner`` against a project a window has open. The window's
store reads what changed into the model it already holds — through the mutators, with
``OUTSIDE_ORIGIN`` — rather than the application being rebuilt. A second ``LibraryStore``
over the same library file is exactly what the CLI is.
"""

import json
from types import SimpleNamespace

import pytest

from dplanner.core.storage.locations import init_repo
from dplanner.domain.library_file import write_library_file
from dplanner.domain.migrations import FORMAT
from dplanner.domain.model import Step
from dplanner.domain.seed import seed_project
from dplanner.domain.store import OUTSIDE_ORIGIN, Conflict, LibraryStore, StaleWorkspaceError


@pytest.fixture
def repo(tmp_path):
    return init_repo(tmp_path / "repo")


@pytest.fixture
def project_dir(repo):
    return seed_project(repo / "discovery", "Discovery")


@pytest.fixture
def store(tmp_path, project_dir):
    path = tmp_path / "library.json"
    write_library_file(path, [project_dir])
    return LibraryStore(path)


@pytest.fixture
def library(store):
    library = store.load()
    project = library.projects[0]
    library.add_child(project.id, Step(title="Read the spec"))
    library.add_child(project.id, Step(title="Draft the model"))
    step = find(library, "Read the spec")
    library.set_text(step.id, "step_description", "First line.\nSecond line.\n")
    store.flush({(project.id, "structure"), (step.id, "module_text")})
    return library


def find(library, title):
    return next(node for node in library.nodes() if getattr(node, "title", None) == title)


def other_writer(store):
    """The CLI: a second store over the same library file."""
    other = LibraryStore(store.library_path)
    return other, other.load()


def read(path):
    return json.loads(path.read_text())


# -- one entry at a time -----------------------------------------------------------------------


def test_adopting_an_outside_title_updates_the_model_in_place(store, library):
    other, theirs = other_writer(store)
    step_id = find(theirs, "Read the spec").id
    theirs.set_field(step_id, "title", "Written by an agent")
    other.flush({(step_id, "meta")})
    assert store.changed_underneath()

    adoption = store.adopt_outside_changes()

    assert adoption.applied == 1 and not adoption.conflicts and not adoption.rebuild_required
    assert store.library is library  # The same aggregate every view is subscribed to.
    assert find(library, "Written by an agent")
    assert not store.changed_underneath()
    step = find(library, "Written by an agent")
    library.set_field(step.id, "title", "Then edited here")
    store.flush({(step.id, "meta")})  # Seen, so the next write is not refused.


def test_adoption_emits_with_the_outside_origin_and_never_dirties(store, library):
    other, theirs = other_writer(store)
    theirs.set_field(theirs.projects[0].id, "summary", "from outside")
    other.flush({(theirs.projects[0].id, "meta")})
    origins, marks = [], []
    library.field_changed.connect(lambda _n, _f, origin: origins.append(origin))
    store.dirty.connect(lambda owner, aspect: marks.append((owner, aspect)))

    store.adopt_outside_changes()

    assert origins == [OUTSIDE_ORIGIN]
    assert marks == []  # A change read off disk is not something to write back.


def test_prose_is_adopted_as_hunks_not_a_replacement(store, library):
    """An editor open on the document splices each hunk around the caret; a whole-document
    replacement would drop the caret to the start."""
    step = find(library, "Read the spec")
    other, theirs = other_writer(store)
    theirs.set_text(step.id, "step_description", "First line.\nSecond line, amended.\n")
    other.flush({(step.id, "module_text")})
    edits = []
    library.text_edited.connect(lambda edit, _o: edits.append(edit))

    store.adopt_outside_changes()

    assert library.text(step.id, "step_description") == "First line.\nSecond line, amended.\n"
    assert all(edit.pos > 0 for edit in edits)
    assert all(edit.removed != "First line.\nSecond line.\n" for edit in edits)


def test_a_module_entry_added_changed_and_removed_outside(store, library, project_dir):
    step = find(library, "Read the spec")
    other, theirs = other_writer(store)
    theirs.set_module_data(step.id, "estimation", {"days": 2.0})
    other.flush({(step.id, "module_data")})
    store.adopt_outside_changes()
    assert library.step(step.id).module_data["estimation"] == {"days": 2.0}

    theirs.set_module_data(step.id, "estimation", {"days": 3.0})
    other.flush({(step.id, "module_data")})
    store.adopt_outside_changes()
    assert library.step(step.id).module_data["estimation"] == {"days": 3.0}

    theirs.set_module_data(step.id, "estimation", {})
    other.flush({(step.id, "module_data")})
    store.adopt_outside_changes()
    assert "estimation" not in library.step(step.id).module_data
    assert not (project_dir / "steps" / "read-the-spec" / "modules" / "estimation.json").exists()


def test_a_file_in_a_module_area_is_seen_and_changes_nothing(store, library, project_dir):
    area = project_dir / "steps" / "read-the-spec" / "modules" / "step_description"
    area.mkdir()
    (area / "diagram.png").write_bytes(b"png")
    assert store.changed_underneath()

    adoption = store.adopt_outside_changes()

    assert adoption.applied == 0 and not adoption.conflicts
    assert not store.changed_underneath()


# -- structure ---------------------------------------------------------------------------------


def test_a_step_added_outside_arrives_with_its_folder_and_can_be_flushed(
    store, library, project_dir
):
    project = library.projects[0]
    other, theirs = other_writer(store)
    theirs.add_child(theirs.projects[0].id, Step(title="Added by an agent"))
    other.flush({(theirs.projects[0].id, "structure")})

    store.adopt_outside_changes()

    step = find(library, "Added by an agent")
    assert [s.title for s in project.steps] == [
        "Read the spec",
        "Draft the model",
        "Added by an agent",
    ]
    library.set_field(step.id, "title", "Renamed here")
    store.flush({(step.id, "meta")})
    assert (
        read(project_dir / "steps" / "added-by-an-agent" / "step.json")["title"] == "Renamed here"
    )
    assert not (project_dir / "steps" / "renamed-here").exists()


def test_a_step_removed_outside_is_removed_here(store, library):
    step = find(library, "Draft the model")
    other, theirs = other_writer(store)
    theirs.remove_child(step.id)
    other.flush({(theirs.projects[0].id, "structure")})

    adoption = store.adopt_outside_changes()

    assert adoption.applied >= 1
    assert not library.has(step.id)
    assert [s.title for s in library.projects[0].steps] == ["Read the spec"]
    assert not store.changed_underneath()


def test_a_reorder_in_the_project_file_reorders_the_model(store, library):
    project = library.projects[0]
    other, theirs = other_writer(store)
    steps = theirs.projects[0].steps
    theirs.reorder_children(theirs.projects[0].id, [steps[1].id, steps[0].id])
    other.flush({(theirs.projects[0].id, "structure")})

    store.adopt_outside_changes()

    assert [s.title for s in project.steps] == ["Draft the model", "Read the spec"]


def test_library_membership_is_adopted(store, library, repo):
    other, theirs = other_writer(store)
    directory = seed_project(repo / "billing", "Billing")
    theirs.add_child(theirs.id, other.attach(directory))
    other.flush({(theirs.id, "structure")})

    store.adopt_outside_changes()

    assert [p.title for p in library.projects] == ["Discovery", "Billing"]
    billing = find(library, "Billing")
    assert store.repo_for(billing.id) is not None
    assert not store.changed_underneath()

    write_library_file(store.library_path, [store.project_dir(library.projects[0].id)])
    store.adopt_outside_changes()
    assert [p.title for p in library.projects] == ["Discovery"]
    assert not store.changed_underneath()


# -- conflicts ---------------------------------------------------------------------------------


def test_an_entry_this_window_changed_is_a_conflict_not_an_adoption(store, library):
    step = find(library, "Read the spec")
    library.set_field(step.id, "title", "Typed here")  # Unflushed.
    other, theirs = other_writer(store)
    theirs.set_field(step.id, "title", "Written by an agent")
    other.flush({(step.id, "meta")})

    adoption = store.adopt_outside_changes()

    (conflict,) = adoption.conflicts
    assert conflict == Conflict(
        library.projects[0].id, "steps/read-the-spec/step.json", step.id, "meta"
    )
    assert library.step(step.id).title == "Typed here"
    with pytest.raises(StaleWorkspaceError):
        store.flush({(step.id, "meta")})  # Still refused: the other writer is not erased.

    taken = store.adopt_outside_changes(take=[conflict])
    assert not taken.conflicts
    assert library.step(step.id).title == "Written by an agent"
    store.flush({(step.id, "meta")})


def test_keeping_ours_lets_the_next_flush_win(store, library, project_dir):
    step = find(library, "Read the spec")
    library.set_field(step.id, "title", "Typed here")
    other, theirs = other_writer(store)
    theirs.set_field(step.id, "title", "Written by an agent")
    other.flush({(step.id, "meta")})
    (conflict,) = store.adopt_outside_changes().conflicts

    store.mark_seen([conflict])
    store.flush({(step.id, "meta")})

    assert read(project_dir / "steps" / "read-the-spec" / "step.json")["title"] == "Typed here"
    assert not store.changed_underneath()


def test_a_conflict_is_per_entry(store, library):
    """A local estimate and an outside status on the same step are two entries."""
    step = find(library, "Read the spec")
    library.set_module_data(step.id, "estimation", {"days": 1.0})  # Unflushed.
    other, theirs = other_writer(store)
    theirs.set_module_data(step.id, "step_status", {"status": "done"})
    other.flush({(step.id, "module_data")})

    adoption = store.adopt_outside_changes()

    assert not adoption.conflicts
    assert library.step(step.id).module_data["step_status"] == {"status": "done"}
    assert library.step(step.id).module_data["estimation"] == {"days": 1.0}
    store.flush({(step.id, "module_data")})
    assert not store.changed_underneath()


def test_a_flushed_edit_is_no_longer_ours(store, library):
    step = find(library, "Read the spec")
    library.set_field(step.id, "title", "Typed here")
    store.flush({(step.id, "meta")})
    other, theirs = other_writer(store)
    theirs.set_field(step.id, "title", "Then an agent")
    other.flush({(step.id, "meta")})

    assert not store.adopt_outside_changes().conflicts
    assert library.step(step.id).title == "Then an agent"


def test_a_deleted_step_this_window_edited_is_a_conflict(store, library):
    step = find(library, "Draft the model")
    library.set_text(step.id, "step_description", "typing")
    other, theirs = other_writer(store)
    theirs.remove_child(step.id)
    other.flush({(theirs.projects[0].id, "structure")})

    adoption = store.adopt_outside_changes()

    assert [c.node_id for c in adoption.conflicts] == [step.id]
    assert library.has(step.id)
    store.adopt_outside_changes(take=adoption.conflicts)
    assert not library.has(step.id)


def test_an_edge_that_would_cycle_with_a_local_link_is_a_conflict(store, library):
    spec, draft = find(library, "Read the spec"), find(library, "Draft the model")
    library.set_edges(draft.id, "requires", [spec.id])  # Unflushed: draft waits on spec.
    other, theirs = other_writer(store)
    theirs.set_edges(spec.id, "requires", [draft.id])  # Outside: spec waits on draft.
    other.flush({(spec.id, "meta")})

    adoption = store.adopt_outside_changes()

    assert [c.node_id for c in adoption.conflicts] == [spec.id]
    assert library.step(spec.id).edges == {}


# -- what cannot be adopted --------------------------------------------------------------------


def test_a_torn_file_is_left_for_the_next_call(store, library, project_dir):
    step = find(library, "Read the spec")
    path = project_dir / "steps" / "read-the-spec" / "step.json"
    good = path.read_text()
    path.write_text(good[: len(good) // 2])  # A writer halfway through.

    adoption = store.adopt_outside_changes()

    assert adoption.deferred == (library.projects[0].id,)
    assert library.step(step.id).title == "Read the spec"
    assert store.changed_underneath()

    meta = json.loads(good)
    meta["title"] = "Written whole"
    path.write_text(json.dumps(meta))
    assert store.adopt_outside_changes().applied == 1
    assert library.step(step.id).title == "Written whole"


def test_a_torn_library_file_is_not_an_emptied_library(store, library):
    store.library_path.write_text("{")
    adoption = store.adopt_outside_changes()
    assert adoption.deferred == () and adoption.applied == 0
    assert [p.title for p in library.projects] == ["Discovery"]
    assert store.changed_underneath()


def test_a_pending_migration_asks_for_a_rebuild(store, library, project_dir, monkeypatch):
    step = find(library, "Read the spec")
    (project_dir / "steps" / "read-the-spec" / "modules" / "note.json").write_text('{"x": 1}')
    monkeypatch.setattr(FORMAT, "pending", lambda found: (SimpleNamespace(node=None, whole=None),))

    adoption = store.adopt_outside_changes()

    assert adoption.rebuild_required
    assert "note" not in library.step(step.id).module_data
