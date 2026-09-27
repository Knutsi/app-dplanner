"""Which repository is which — legacy, unset, colocated, separated — one derivation, many
readers."""

import subprocess
from pathlib import Path

import pytest
from tests.facts import code_facts, code_row

from dplanner.core.storage.locations import canonical_remote, init_repo
from dplanner.core.storage.pointer import remove_from_index
from dplanner.domain.locations import CODE, Location, Placement
from dplanner.domain.model import Project
from dplanner.domain.repositories import (
    ACCEPTED,
    COLOCATED,
    LEGACY,
    SEPARATED,
    UNSET,
    RepositoryFacts,
    repository_facts,
)
from dplanner.domain.seed import seed_project

PLAN = Path("/home/anna/plans")
WIDGET = Path("/home/anna/src/widget")


def facts(**overrides):
    base = {
        "plan_root": PLAN,
        "plan_remote": "git@github.com:acme/plans.git",
        "repository": "https://github.com/acme/widget",
        "checkout": WIDGET,
        "colocation": "",
    }
    return code_facts(**{**base, **overrides})


def test_no_repository_is_the_legacy_shape_and_warns():
    found = facts(repository="")
    assert found.state == LEGACY and found.warns and found.plan_in_code
    # Read as colocated: the plan's own repository stands in for the code.
    assert found.code_root == PLAN and found.code_remote == "git@github.com:acme/plans.git"


def test_no_repository_in_a_plan_repositorys_index_is_unset_and_read_as_nothing():
    """A project the index lists was made in a plan repository: with no code named its
    code is nowhere yet — never the plan's — and accepting colocation does not change that."""
    found = RepositoryFacts(
        plan_root=PLAN,
        plan_remote="git@github.com:acme/plans.git",
        placements=(),
        colocation="",
        indexed=True,
    )
    assert found.state == UNSET
    assert not found.plan_in_code and not found.warns
    assert found.code_root is None and found.code_remote == ""
    accepted = RepositoryFacts(PLAN, "", (), ACCEPTED, indexed=True)
    assert accepted.state == UNSET


def test_a_named_code_repository_is_read_the_same_indexed_or_not():
    listed = RepositoryFacts(PLAN, "", facts().placements, "", indexed=True)
    assert listed.state == SEPARATED and listed.code_root == WIDGET
    assert listed.code_remote == "https://github.com/acme/widget"


def test_a_separate_code_repository_does_not_warn():
    found = facts()
    assert found.state == SEPARATED and not found.warns
    assert found.plan_label == "acme/plans" and found.code_label == "acme/widget"


@pytest.mark.parametrize(
    "overrides",
    [
        {"repository": "git@github.com:Acme/Plans.git"},  # the plan's remote, spelt otherwise
        {"checkout": PLAN},  # the code is checked out at the plan root
        {"checkout": PLAN / "sub"},  # or inside it
        {"plan_root": WIDGET / "planning"},  # or the plan sits inside the code checkout
        {"plan_remote": "", "repository": str(PLAN)},  # a remote-less code repo, as its path
    ],
)
def test_the_same_repository_is_colocated_however_it_is_said(overrides):
    found = facts(**overrides)
    assert found.state == COLOCATED and found.warns


def test_an_accepted_colocation_stops_the_warning_but_not_the_state():
    found = facts(checkout=PLAN, colocation=ACCEPTED)
    assert found.state == COLOCATED and not found.warns


def test_labels_without_a_remote_fall_back_to_the_folder():
    found = facts(plan_remote="", repository="")
    assert found.plan_label == "plans" and found.code_label == ""


def test_the_facts_are_read_off_the_project_directory(tmp_path):
    repo = init_repo(tmp_path / "plans")
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:acme/plans.git"],
        check=True,
    )
    (repo / "search").mkdir()
    project = Project(title="Search", locations=code_row("https://github.com/acme/widget"))
    checkouts = {"github.com/acme/widget": tmp_path / "src" / "widget"}
    found = repository_facts(project, repo / "search", checkouts)
    assert found.plan_root == repo
    assert canonical_remote(found.plan_remote) == "github.com/acme/plans"
    assert found.checkout == tmp_path / "src" / "widget"
    assert found.repository == "https://github.com/acme/widget"


def test_the_index_decides_between_unset_and_legacy(tmp_path):
    """Seeded into a plan repository, a project is listed and reads unset; one that is its
    repository's root, or that no line names — a plan from before the index — is legacy."""
    plans = init_repo(tmp_path / "plans")
    seed_project(plans / "search", "Search")
    assert repository_facts(Project(title="Search"), plans / "search", {}).state == UNSET
    remove_from_index(plans / "search")
    assert repository_facts(Project(title="Search"), plans / "search", {}).state == LEGACY
    root = init_repo(tmp_path / "widget")
    assert repository_facts(Project(title="Widget"), root, {}).state == LEGACY
    assert not repository_facts(Project(), tmp_path / "loose", {}).indexed


def test_every_location_is_placed_and_the_primary_code_row_is_the_repository(tmp_path):
    """The older readers' `repository` and `checkout` are the first code row's; every
    other row is placed too, and a read-only one lands in its managed clone."""
    repo = init_repo(tmp_path / "plans")
    locations = (
        Location("l1", CODE.id, "https://github.com/acme/widget"),
        Location("l2", CODE.id, "https://github.com/acme/widget-ui", label="UI"),
        Location("l3", "spec", "https://github.com/acme/specs", path="products/search"),
    )
    project = Project(title="Search", locations=locations)
    checkouts = {"github.com/acme/widget-ui": tmp_path / "ui"}
    found = repository_facts(
        project, repo, checkouts, managed=lambda location: tmp_path / "cache" / location.id
    )
    assert [found.location.id for found in found.placements] == ["l1", "l2", "l3"]
    assert found.repository == "https://github.com/acme/widget" and found.checkout is None
    assert found.placement("l2") == Placement(locations[1], tmp_path / "ui")
    assert found.placement("l3") == Placement(locations[2], tmp_path / "cache" / "l3", managed=True)
    specs = found.placement("l3")
    assert specs is not None
    assert specs.directory == tmp_path / "cache" / "l3" / "products" / "search"
    assert found.state == SEPARATED
    assert found.state == SEPARATED
    assert repository_facts(project, tmp_path / "loose", {}).plan_root is None
