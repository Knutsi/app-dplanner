"""A project's locations: the table, its rows' validation, and where each is placed."""

from pathlib import Path

import pytest

from dplanner.domain.locations import (
    CODE,
    Location,
    LocationRole,
    Placement,
    duplicates,
    find_location,
    matching,
    next_id,
    normalise_path,
    place,
    primary_code,
    problem,
    read_locations,
    replaced,
    roles_by_id,
    without,
    write_locations,
)

WIDGET = "https://github.com/acme/widget"
SPEC = LocationRole("spec", "Spec", "Where the specs come from.", writes=False)
REPORTING = LocationRole(
    "reporting", "Reporting", "Where the reports go.", writes=True, default_path="reports"
)
ROLES = roles_by_id([CODE, SPEC, REPORTING])


def test_rows_round_trip_and_absence_encodes_the_default():
    rows = (
        Location("l1", "code", WIDGET),
        Location("l2", "spec", "git@github.com:acme/specs.git", path="products/search", ref="v2"),
        Location("l3", "code", "https://github.com/acme/ui", label="UI"),
    )
    written = write_locations(rows)
    assert written[0] == {"id": "l1", "role": "code", "repository": WIDGET}
    assert set(written[1]) == {"id", "role", "repository", "path", "ref"}
    assert written[2]["label"] == "UI"
    assert read_locations(written) == rows


def test_reading_is_tolerant_and_deals_ids_where_none_are_written():
    raw = [
        {"role": "code", "repository": WIDGET},
        "junk",
        {"role": "reporting"},  # No repository: skipped.
        {"id": "l1", "role": "wiki", "repository": WIDGET, "path": "./notes/"},
        {"id": "l1", "role": "reporting", "repository": WIDGET},  # A duplicate id: dealt anew.
    ]
    found = read_locations(raw)
    assert [(row.id, row.role) for row in found] == [
        ("l2", "code"),
        ("l1", "wiki"),
        ("l3", "reporting"),
    ]
    assert found[1].path == "notes"  # An unknown role is kept as it is; its path normalised.
    assert read_locations(None) == () and read_locations({"role": "code"}) == ()


def test_the_next_id_is_past_every_dealt_one():
    assert next_id(()) == "l1"
    assert next_id((Location("l7", "code", WIDGET), Location("x", "code", WIDGET))) == "l8"


@pytest.mark.parametrize(
    ("location", "words"),
    [
        (Location("l1", "code", ""), "names no repository"),
        (Location("l1", "code", "-x"), "not a repository address"),
        (Location("l1", "code", WIDGET, path="../out"), "leaves its repository"),
        (Location("l1", "code", WIDGET, path="/etc"), "leaves its repository"),
        (Location("l1", "code", WIDGET, path="C:/x"), "leaves its repository"),
        (Location("l1", "code", WIDGET, ref="-r"), "not a git ref"),
        (Location("l1", "code", WIDGET, ref="a..b"), "not a git ref"),
        (Location("l1", "code", WIDGET, ref="v1.lock"), "not a git ref"),
    ],
)
def test_a_row_that_cannot_stand_says_why(location, words):
    assert words in problem(location)


def test_a_row_that_stands_has_no_problem():
    assert problem(Location("l1", "code", WIDGET, path="docs/search", ref="main")) == ""


def test_a_position_is_normalised_to_one_spelling():
    assert normalise_path("./docs/search/") == "docs/search"
    assert normalise_path("docs\\search") == "docs/search"
    assert normalise_path(" . ") == "" and normalise_path("") == ""


def test_rows_are_named_by_id_or_by_role_and_label():
    rows = (
        Location("l1", "code", WIDGET),
        Location("l2", "code", "https://github.com/acme/ui", label="UI"),
        Location("l3", "reporting", WIDGET, path="reports"),
    )
    assert matching(rows, "l2") == (rows[1],)
    assert matching(rows, "code") == rows[:2]
    assert matching(rows, "Code:ui") == (rows[1],)
    assert find_location(rows, "reporting") == rows[2]
    with pytest.raises(LookupError, match="names several"):
        find_location(rows, "code")
    with pytest.raises(LookupError, match="no location 'l9'"):
        find_location(rows, "l9")
    assert primary_code(rows) == rows[0] and primary_code(rows[2:]) is None


def test_replacing_and_removing_keep_the_order():
    rows = (Location("l1", "code", WIDGET), Location("l2", "reporting", WIDGET))
    changed = Location("l1", "code", "https://github.com/acme/other")
    assert replaced(rows, changed) == (changed, rows[1])
    added = Location("l3", "spec", WIDGET)
    assert replaced(rows, added) == (*rows, added)
    assert without(rows, "l1") == (rows[1],)


def test_a_role_named_twice_is_a_duplicate_only_when_it_says_a_project_names_it_once():
    rows = (
        Location("l1", "code", WIDGET),
        Location("l2", "code", WIDGET, label="again"),
        Location("l3", "reporting", WIDGET),
        Location("l4", "reporting", WIDGET, path="other"),
        Location("l5", "wiki", WIDGET),
        Location("l6", "wiki", WIDGET),
    )
    assert duplicates(rows, ROLES) == ("reporting",)


def test_a_row_names_itself_by_its_role_and_label():
    assert Location("l1", "code", WIDGET).name(ROLES) == "Code"
    assert Location("l1", "code", WIDGET, label="UI").name(ROLES) == "Code — UI"
    assert Location("l1", "wiki", WIDGET).name(ROLES) == "wiki"
    assert (
        Location("l1", "code", "git@github.com:Acme/Widget.git").repository_label == "Acme/Widget"
    )


# -- where a location is on this machine ----------------------------------------------------------


def test_a_recorded_checkout_places_the_row_however_the_repository_is_spelt(tmp_path):
    row = Location("l1", "code", "git@github.com:Acme/Widget.git", path="apps/web")
    found = place(
        row,
        checkouts={"github.com/acme/widget": tmp_path / "widget"},
        plan_root=None,
        plan_remote="",
    )
    assert found == Placement(row, tmp_path / "widget")
    assert found.directory == tmp_path / "widget" / "apps" / "web" and found.here


def test_the_plan_repository_places_a_row_that_names_it(tmp_path):
    row = Location("l1", "reporting", "https://github.com/acme/plans", path="reports")
    found = place(
        row, checkouts={}, plan_root=tmp_path / "plans", plan_remote="git@github.com:acme/plans.git"
    )
    assert found.root == tmp_path / "plans" and not found.managed


def test_a_remote_less_repository_is_placed_at_its_own_path_when_it_is_here(tmp_path):
    (tmp_path / "local").mkdir()
    here = Location("l1", "code", str(tmp_path / "local"))
    gone = Location("l2", "code", str(tmp_path / "gone"))
    assert place(here, checkouts={}, plan_root=None, plan_remote="").root == tmp_path / "local"
    assert place(gone, checkouts={}, plan_root=None, plan_remote="").root is None


def test_a_read_only_row_lands_in_its_managed_clone_and_a_writing_one_never_does(tmp_path):
    specs = Location("l1", "spec", "https://github.com/acme/specs", path="products")
    reports = Location("l2", "reporting", "https://github.com/acme/specs", path="reports")

    def managed(location: Location) -> Path | None:
        return tmp_path / "cache" / location.id if not ROLES[location.role].writes else None

    found = place(specs, checkouts={}, plan_root=None, plan_remote="", managed=managed)
    assert found == Placement(specs, tmp_path / "cache" / "l1", managed=True)
    assert found.directory == tmp_path / "cache" / "l1" / "products" and not found.here
    unplaced = place(reports, checkouts={}, plan_root=None, plan_remote="", managed=managed)
    assert unplaced.root is None
    # A checkout this machine has wins over the managed clone.
    found = place(
        specs,
        checkouts={"github.com/acme/specs": tmp_path / "specs"},
        plan_root=None,
        plan_remote="",
        managed=managed,
    )
    assert found == Placement(specs, tmp_path / "specs")


def test_a_folder_on_this_computer_is_read_as_a_location(tmp_path):
    """The shortest way to name a location: a folder of a checkout says which repository
    (its origin, or its own path when it has none) and which position."""
    import subprocess

    from dplanner.core.storage.locations import init_repo
    from dplanner.domain.locations import LocatedFolder, located_folder

    repo = init_repo(tmp_path / "specs")
    (repo / "products" / "search").mkdir(parents=True)
    assert located_folder(repo / "products" / "search") == LocatedFolder(
        str(repo.resolve()), repo, "products/search"
    )
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", WIDGET], check=True)
    assert located_folder(repo / "products") == LocatedFolder(WIDGET, repo, "products")
    assert located_folder(repo) == LocatedFolder(WIDGET, repo, "")
    (tmp_path / "loose").mkdir()
    assert located_folder(tmp_path / "loose") is None


def test_a_checkout_the_application_keeps_is_placed_as_here_and_says_so(tmp_path):
    """A kept clone is a working checkout — an agent may open a shell there — told apart
    from the person's own only in the wording, and only when the reader says where kept
    clones live."""
    from dplanner.core.storage.kept import kept_dir

    row = Location("l1", "code", WIDGET)
    kept = kept_dir(tmp_path / "config", WIDGET)
    checkouts = {row.canonical: kept}
    found = place(
        row, checkouts=checkouts, plan_root=None, plan_remote="", kept_root=tmp_path / "config"
    )
    assert found == Placement(row, kept, kept=True) and found.here and not found.managed
    assert not place(row, checkouts=checkouts, plan_root=None, plan_remote="").kept
    own = {row.canonical: tmp_path / "Code" / "widget"}
    assert not place(
        row, checkouts=own, plan_root=None, plan_remote="", kept_root=tmp_path / "config"
    ).kept
