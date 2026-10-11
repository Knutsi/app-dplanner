"""A branch lives in one repository — its landing's — in a project whose code is two.

The case that taught it (docs/research/2026-10-11-parallel-branches): one line of work in a
library and one in the app that uses it, each on its own feature branch, and the convention
of one name for both. No ``qapp`` fixture: the branch aspects and their verbs are Qt-free.
"""

import json

import pytest

from dplanner.domain.store import LibraryStore
from dplanner.modules.branches.plan import branch_plan
from dplanner.planning.agent import workplace
from dplanner.planning.branches import DEFAULT_START

LIB = "https://github.com/acme/lib"
APP = "https://github.com/acme/app"


def data(text):
    return json.loads(text)


def step_titled(cli_library, title):
    library = LibraryStore(cli_library).load()
    found = next(s for project in library.projects for s in project.steps if s.title == title)
    return library, found


@pytest.fixture
def cli(cli):
    """Shop's code is acme/lib (primary) and acme/app: Add then Sub in the library, Mul then
    Div in the app."""
    cli("project", "create", "Shop")
    cli("location", "add", "shop", "--role", "code", "--repository", LIB)
    cli("location", "add", "shop", "--role", "code", "--repository", APP, "--label", "App")
    cli("step", "add", "shop", "Add", "--agent")
    cli("step", "add", "shop", "Sub", "--agent", "--after", "Add")
    cli("step", "add", "shop", "Mul", "--agent")
    cli("step", "add", "shop", "Div", "--agent", "--after", "Mul")
    for title in ("Mul", "Div"):
        cli("agent", "workplace", title, "code:App")
    return cli


def test_one_branch_name_in_each_repository_and_each_landing_works_where_its_branch_is(
    cli, cli_library
):
    lib = data(cli("branch", "put", "Add", "Sub", "--branch", "feature/x", "--json"))
    app = data(cli("branch", "put", "Mul", "Div", "--branch", "feature/x", "--json"))

    library = LibraryStore(cli_library).load()
    assert workplace(library.step(lib["land"])) == ""  # The primary.
    assert workplace(library.step(app["land"])) != ""
    shown = data(cli("branch", "show", "shop", "--json"))["branches"]
    assert sorted(row["repository"] for row in shown) == ["acme/app", "acme/lib"]
    assert "in acme/app" in cli("branch", "show", "shop")
    findings = data(cli("project", "lint", "shop", "--json", expect=1))["findings"]
    assert not [f for f in findings if f["check"] in ("branch.name", "branch.repository")]


def test_one_name_twice_in_one_repository_is_refused(cli):
    cli("branch", "put", "Add", "--branch", "feature/x")
    said = cli("branch", "put", "Sub", "--branch", "feature/x", expect=1)
    assert "already called feature/x" in said


def test_a_pick_across_two_repositories_is_refused(cli):
    said = cli("branch", "put", "Add", "Mul", "--branch", "feature/y", expect=1)
    assert "work in acme/lib and acme/app" in said


def test_two_code_rows_of_one_repository_are_one_repository(cli):
    """A monorepo's UI and backend are two rows of one repository, and one branch."""
    cli("location", "add", "shop", "--role", "code", "--repository", LIB, "--path", "ui",
        "--label", "UI")  # fmt: skip
    cli("agent", "workplace", "Sub", "code:UI")
    cli("branch", "put", "Add", "Sub", "--branch", "feature/z")


def test_a_member_working_elsewhere_than_its_branch_is_refused_a_run_and_named_by_lint(
    cli, cli_library
):
    cli("branch", "put", "Add", "Sub", "--branch", "feature/x")
    cli("agent", "workplace", "Sub", "code:App")

    library, sub = step_titled(cli_library, "Sub")
    refusal = branch_plan(library, sub, "").refusal
    assert "is on feature/x, which is in acme/lib, but works in acme/app" in refusal
    findings = data(cli("project", "lint", "shop", "--json", expect=1))["findings"]
    assert [f["subject"] for f in findings if f["check"] == "branch.repository"] == [sub.id]


def test_the_first_run_inside_a_nested_branch_cuts_the_outer_one_first(cli, cli_library):
    inner = data(cli("branch", "put", "Add", "Sub", "--branch", "feature/a", "--json"))
    cli("branch", "put", inner["cut"], "Add", "Sub", inner["land"], "--branch", "feature/int")

    library, add = step_titled(cli_library, "Add")
    plan = branch_plan(library, add, "")
    assert plan.cuts == (("feature/int", DEFAULT_START), ("feature/a", "origin/feature/int"))

    cli("github", "set", "Add", "--branch", "agent/s1-add")  # Its work was carried out.
    library, add = step_titled(cli_library, "Add")
    assert branch_plan(library, add, "").cuts == ()


def test_a_landing_made_before_branches_had_a_repository_follows_its_members(cli, cli_library):
    """A landing that names no workplace — every one made before this rule — takes the
    repository its agent members agree on: they keep running, and the landing is told the
    one verb that puts it with them."""
    put = data(cli("branch", "put", "Mul", "Div", "--branch", "feature/x", "--json"))
    cli("agent", "workplace", put["land"], "primary")  # As an older build left it.

    library, div = step_titled(cli_library, "Div")
    assert branch_plan(library, div, "").refusal == ""
    land = library.step(put["land"])
    assert "lands feature/x, which is in acme/app, but works in acme/lib" in (
        branch_plan(library, land, "").refusal
    )
    findings = data(cli("project", "lint", "shop", "--json", expect=1))["findings"]
    assert [f["subject"] for f in findings if f["check"] == "branch.repository"] == [land.id]
