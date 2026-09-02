"""``dplanner step duplicate`` end to end, over a real library. No ``qapp`` fixture."""

import json

import pytest

from dplanner.domain.assets import attach
from dplanner.domain.store import LibraryStore
from dplanner.modules.project_editor.positions import read_position
from dplanner.modules.testing.aspect import read as read_tests


@pytest.fixture
def cli(cli):
    """The shared CLI, with a two-step project already in place."""
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Read the spec", "--days", "2")
    cli(
        "step",
        "add",
        "Discovery",
        "Draft the model",
        "--after",
        "Read the spec",
        "--test",
        "Model parses",
    )
    return cli


def reload(library_path):
    return LibraryStore(library_path).load()


def test_duplicate_keeps_aspects_and_links_under_a_fresh_id(cli, cli_library):
    said = json.loads(cli("step", "duplicate", "Draft the model", "--json"))

    library = reload(cli_library)
    [row] = said["steps"]
    copy, original = library.step(row["id"]), library.step(row["from"])
    assert copy.title == "Draft the model" and copy.id != original.id
    assert copy.edges["requires"] == original.edges["requires"]
    assert [t.title for t in read_tests(copy)] == ["Model parses"]
    assert [t.id for t in read_tests(copy)] == ["T101"]  # The original keeps T100.
    assert read_position(copy) is not None and read_position(original) is None


def test_duplicate_into_another_project_drops_links_it_cannot_resolve(cli, cli_library):
    cli("project", "create", "Rollout")
    said = cli("step", "duplicate", "Draft the model", "--into", "Rollout")

    library = reload(cli_library)
    rollout = next(p for p in library.projects if p.title == "Rollout")
    assert [s.title for s in rollout.steps] == ["Draft the model"]
    assert "requires" not in rollout.steps[0].edges
    assert "Duplicated 'Draft the model' as" in said and "in Rollout" in said


def test_duplicate_carries_attachments(cli, cli_library):
    store = LibraryStore(cli_library)
    library = store.load()
    original = next(s for s in library.projects[0].steps if s.title == "Read the spec")
    name = attach(store.files(original.id, "step_description"), b"\x89PNG-ish", "shot.png")

    said = json.loads(cli("step", "duplicate", "Read the spec", "--json"))

    store = LibraryStore(cli_library)
    store.load()
    [row] = said["steps"]
    assert store.files(row["id"], "step_description").read_bytes(name) == b"\x89PNG-ish"


def test_several_steps_copy_as_one_batch_with_their_links_remapped(cli, cli_library):
    said = json.loads(cli("step", "duplicate", "Read the spec", "Draft the model", "--json"))

    library = reload(cli_library)
    copy_first, copy_second = (library.step(row["id"]) for row in said["steps"])
    assert copy_second.edges["requires"] == [copy_first.id]
    assert len(library.projects[0].steps) == 4
