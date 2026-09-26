"""The library file: which projects, and where this machine has their repositories."""

import json
import subprocess
from pathlib import Path

from tests.platforms import set_home

from dplanner.core.storage.locations import init_repo
from dplanner.domain.library_file import (
    LIBRARY_FORMAT,
    LibraryFile,
    read_library_file,
    write_library_file,
)


def test_a_format_one_file_reads_as_paths_without_checkouts(tmp_path):
    path = tmp_path / "library.json"
    path.write_text(json.dumps({"format": 1, "projects": [{"path": str(Path("/plans/search"))}]}))
    assert read_library_file(path) == LibraryFile([Path("/plans/search")], {})


def test_checkouts_round_trip_by_repository_and_are_absent_when_none(tmp_path):
    path = tmp_path / "library.json"
    write_library_file(
        path,
        [Path("/plans/search"), Path("/plans/billing")],
        {"github.com/acme/widget": Path("/src/widget")},
    )
    raw = json.loads(path.read_text())
    assert raw["format"] == LIBRARY_FORMAT == 4
    assert raw["projects"] == [
        {"path": str(Path("/plans/search"))},
        {"path": str(Path("/plans/billing"))},
    ]
    assert raw["checkouts"] == {"github.com/acme/widget": str(Path("/src/widget"))}
    assert read_library_file(path) == LibraryFile(
        [Path("/plans/search"), Path("/plans/billing")],
        {"github.com/acme/widget": Path("/src/widget")},
    )
    write_library_file(path, [Path("/plans/search")])
    assert "checkouts" not in json.loads(path.read_text())


def test_the_archive_round_trips_in_order_and_is_absent_when_empty(tmp_path):
    path = tmp_path / "library.json"
    archived = [Path("/plans/launch"), Path("/plans/spike")]
    write_library_file(path, [Path("/plans/search")], archived=archived)
    assert json.loads(path.read_text())["archived"] == [{"path": str(entry)} for entry in archived]
    assert read_library_file(path) == LibraryFile([Path("/plans/search")], {}, archived)
    write_library_file(path, [Path("/plans/search")])
    assert "archived" not in json.loads(path.read_text())
    assert read_library_file(path).archived == []


def test_a_bad_archive_row_is_dropped_and_the_rest_kept(tmp_path):
    path = tmp_path / "library.json"
    rows = [{"path": str(Path("/plans/launch"))}, {"path": ""}, "junk", {"path": 3}]
    path.write_text(json.dumps({"format": 4, "projects": [], "archived": rows}))
    assert read_library_file(path).archived == [Path("/plans/launch")]


def test_a_format_two_checkout_is_filed_under_its_origin(tmp_path):
    """A row's per-project checkout becomes this machine's checkout of the repository
    the folder is a clone of — its origin, or its own path when it has none."""
    widget = init_repo(tmp_path / "widget")
    subprocess.run(
        ["git", "-C", str(widget), "remote", "add", "origin", "git@github.com:Acme/Widget.git"],
        check=True,
    )
    local = init_repo(tmp_path / "local")
    path = tmp_path / "library.json"
    rows = [
        {"path": str(tmp_path / "plans" / "search"), "checkout": str(widget)},
        {"path": str(tmp_path / "plans" / "billing"), "checkout": str(local)},
    ]
    path.write_text(json.dumps({"format": 2, "projects": rows}))
    found = read_library_file(path)
    assert found.projects == [tmp_path / "plans" / "search", tmp_path / "plans" / "billing"]
    assert found.checkouts == {"github.com/acme/widget": widget, str(local.resolve()): local}


def test_a_bad_row_or_checkout_is_dropped_and_the_rest_kept(tmp_path):
    path = tmp_path / "library.json"
    rows = [{"path": str(Path("/plans/search")), "checkout": 12}, {"path": ""}, "junk"]
    checkouts = {"github.com/acme/widget": 7, "": "/x", "github.com/acme/ok": "/src/ok"}
    path.write_text(json.dumps({"format": 3, "projects": rows, "checkouts": checkouts}))
    assert read_library_file(path) == LibraryFile(
        [Path("/plans/search")], {"github.com/acme/ok": Path("/src/ok")}
    )


def test_a_tilde_is_expanded_in_both_paths(tmp_path, monkeypatch):
    set_home(monkeypatch, tmp_path)
    path = tmp_path / "library.json"
    raw = {
        "format": 3,
        "projects": [{"path": "~/plans/search"}],
        "checkouts": {"github.com/acme/widget": "~/src/widget"},
    }
    path.write_text(json.dumps(raw))
    found = read_library_file(path)
    assert found.projects == [tmp_path / "plans" / "search"]
    assert found.checkouts == {"github.com/acme/widget": tmp_path / "src" / "widget"}
