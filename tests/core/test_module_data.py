"""Module data: versions, migrations, takeovers, and what happens to data we don't own."""

import pytest

from dplanner.core.module_data import (
    ModuleDataFormat,
    Takeover,
    data_version,
    migrate_module_data,
    stamped,
)
from dplanner.domain.model import Library, Project


class FakeRepo:
    """The narrow face migrate_module_data needs, over a plain library."""

    def __init__(self, library):
        self.library = library
        self.dirty = library.dirty

    def owners(self):
        return list(self.library.nodes())

    def set_module_data(self, owner_id, module_id, data):
        self.library.set_module_data(owner_id, module_id, data)


@pytest.fixture
def repo():
    library = Library()
    library.add_child(library.id, Project(title="Build"))
    return FakeRepo(library)


def test_absent_format_means_version_one():
    assert data_version({}) == 1
    assert data_version({"format": 3}) == 3
    assert data_version({"format": True}) == 1  # A bool is not a version.


def test_stamping_nothing_leaves_nothing():
    """An entry that would hold only its stamp is stored as {} — which removes the file."""
    assert stamped({}, 2) == {}
    assert stamped({"note": "x"}, 2) == {"note": "x", "format": 2}


def test_a_format_must_declare_one_migration_per_version():
    with pytest.raises(ValueError, match="needs 1 migrations"):
        ModuleDataFormat("m", version=2)


def test_older_data_is_brought_forward(repo):
    child = repo.owners()[0]
    repo.set_module_data(child.id, "m", {"old": 1})
    fmt = ModuleDataFormat("m", version=2, migrations=(lambda d: {"new": d["old"]},))
    changed = migrate_module_data(repo, [fmt])
    assert changed == [child.id]
    assert child.module_data["m"] == {"new": 1, "format": 2}


def test_newer_data_is_left_alone(repo):
    """An older build must never overwrite a newer one's data — it just looks empty."""
    child = repo.owners()[0]
    repo.set_module_data(child.id, "m", {"future": True, "format": 9})
    changed = migrate_module_data(repo, [ModuleDataFormat("m", version=1)])
    assert changed == []
    assert child.module_data["m"] == {"future": True, "format": 9}


def test_a_successor_takes_over_a_retired_module(repo):
    child = repo.owners()[0]
    repo.set_module_data(child.id, "old_module", {"value": 5})
    retired = ModuleDataFormat("old_module", version=1)
    takeover = Takeover(retired=retired, convert=lambda old, existing: {"kept": old["value"]})
    fmt = ModuleDataFormat("new_module", version=1, takeovers=(takeover,))
    migrate_module_data(repo, [fmt])
    assert child.module_data["new_module"] == {"kept": 5, "format": 1}
    assert "old_module" not in child.module_data


def test_unknown_entries_survive_a_round_trip(tmp_path):
    """Data belonging to a module this build does not have must come back untouched."""
    from dplanner.core.storage.locations import init_repo
    from dplanner.domain.library_file import write_library_file
    from dplanner.domain.seed import seed_project
    from dplanner.domain.store import LibraryStore

    directory = seed_project(init_repo(tmp_path / "repo") / "build", "Build")
    path = tmp_path / "library.json"
    write_library_file(path, [directory])
    store = LibraryStore(path)
    library = store.load()
    project = library.projects[0]
    library.set_module_data(project.id, "from_the_future", {"anything": [1, 2], "format": 7})
    store.flush({(project.id, "module_data")})

    reloaded = LibraryStore(path).load()
    assert reloaded.projects[0].module_data["from_the_future"] == {
        "anything": [1, 2],
        "format": 7,
    }
