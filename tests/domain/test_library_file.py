"""The library file: which projects, and where this machine has their code."""

import json
from pathlib import Path

from dplanner.domain.library_file import (
    LIBRARY_FORMAT,
    LibraryEntry,
    read_library_file,
    write_library_file,
)


def test_a_format_one_file_reads_as_entries_without_checkouts(tmp_path):
    path = tmp_path / "library.json"
    path.write_text(json.dumps({"format": 1, "projects": [{"path": "/plans/search"}]}))
    assert read_library_file(path) == [LibraryEntry(Path("/plans/search"))]


def test_a_checkout_round_trips_and_is_absent_when_none(tmp_path):
    path = tmp_path / "library.json"
    write_library_file(
        path,
        [LibraryEntry(Path("/plans/search"), Path("/src/widget")), Path("/plans/billing")],
    )
    raw = json.loads(path.read_text())
    assert raw["format"] == LIBRARY_FORMAT == 2
    assert raw["projects"] == [
        {"checkout": "/src/widget", "path": "/plans/search"},
        {"path": "/plans/billing"},
    ]
    assert read_library_file(path) == [
        LibraryEntry(Path("/plans/search"), Path("/src/widget")),
        LibraryEntry(Path("/plans/billing")),
    ]


def test_a_bad_checkout_is_dropped_but_the_row_is_kept(tmp_path):
    path = tmp_path / "library.json"
    rows = [{"path": "/plans/search", "checkout": 12}, {"path": ""}, "junk"]
    path.write_text(json.dumps({"format": 2, "projects": rows}))
    assert read_library_file(path) == [LibraryEntry(Path("/plans/search"))]


def test_a_tilde_is_expanded_in_both_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "library.json"
    rows = [{"path": "~/plans/search", "checkout": "~/src/widget"}]
    path.write_text(json.dumps({"format": 2, "projects": rows}))
    [entry] = read_library_file(path)
    assert entry.path == tmp_path / "plans" / "search"
    assert entry.checkout == tmp_path / "src" / "widget"
