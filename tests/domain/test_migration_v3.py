"""Format 3: the project's code repository becomes the first code row of its locations."""

import json

from dplanner.core.formats import FORMAT_KEY
from dplanner.core.storage.locations import init_repo
from dplanner.domain.library_file import write_library_file
from dplanner.domain.locations import Location
from dplanner.domain.migrations import FORMAT
from dplanner.domain.store import PROJECT_META, LibraryStore


def _project(tmp_path, meta):
    repo = init_repo(tmp_path / "plans")
    directory = repo / "search"
    directory.mkdir()
    (directory / PROJECT_META).write_text(json.dumps(meta) + "\n")
    path = tmp_path / "library.json"
    write_library_file(path, [directory])
    return directory, LibraryStore(path)


def test_a_format_two_repository_becomes_the_first_code_row(tmp_path):
    directory, store = _project(
        tmp_path,
        {
            "id": "p1",
            "title": "Search",
            "repository": "git@github.com:acme/widget.git",
            FORMAT_KEY: 2,
        },
    )
    project = store.load().projects[0]
    assert project.locations == (Location("l1", "code", "git@github.com:acme/widget.git"),)
    written = json.loads((directory / PROJECT_META).read_text())
    assert written[FORMAT_KEY] == FORMAT.current_version == 3
    assert "repository" not in written
    assert written["locations"] == [
        {"id": "l1", "role": "code", "repository": "git@github.com:acme/widget.git"}
    ]


def test_a_format_two_project_with_no_repository_gets_no_row(tmp_path):
    directory, store = _project(tmp_path, {"id": "p1", "title": "Search", FORMAT_KEY: 2})
    project = store.load().projects[0]
    assert project.locations == ()
    assert "locations" not in json.loads((directory / PROJECT_META).read_text())


def test_a_format_three_project_reads_its_table_as_written(tmp_path):
    rows = [
        {"id": "l1", "role": "code", "repository": "https://github.com/acme/widget"},
        {"id": "l2", "role": "specs", "repository": "https://github.com/acme/specs", "path": "p"},
    ]
    _directory, store = _project(tmp_path, {"id": "p1", "locations": rows, FORMAT_KEY: 3})
    project = store.load().projects[0]
    assert [row.role for row in project.locations] == ["code", "specs"]
    assert project.locations[1].path == "p"
