"""The project verbs that say which code a plan is about, and move a plan out of it."""

import json
import subprocess

from dplanner.core.storage.locations import init_repo
from dplanner.core.storage.pointer import read_index


def data(text):
    return json.loads(text)


def _origin(repo, url):
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", url], check=True)


def _identity(repo):
    git = ["git", "-C", str(repo)]
    subprocess.run([*git, "config", "user.email", "t@example.com"], check=True)
    subprocess.run([*git, "config", "user.name", "t"], check=True)


def test_create_in_a_plan_repository_with_a_code_repository(cli, tmp_path):
    plans = init_repo(tmp_path / "plans")
    said = cli(
        "project",
        "create",
        "Search rewrite",
        "--in",
        str(plans),
        "--code",
        "https://github.com/acme/widget",
        "--checkout",
        str(tmp_path / "widget"),
    )
    assert "Created" in said and "Code: acme/widget" in said
    row = data(cli("project", "show", "Search rewrite", "--json"))
    assert row["dir"] == str(plans / "search-rewrite")
    assert row["repository"] == "https://github.com/acme/widget"
    assert row["checkout"] == str((tmp_path / "widget").resolve())
    assert row["state"] == "separated" and row["plan_root"] == str(plans)
    assert read_index(plans) == ["search-rewrite"]


def test_create_needs_exactly_one_place(cli, tmp_path):
    said = cli(
        "project", "create", "X", "--dir", str(tmp_path / "a"), "--in", str(tmp_path), expect=1
    )
    assert "exactly one" in said
    assert "exactly one" in cli("project", "create", "X", "--in", "", expect=1)


def test_create_warns_when_the_code_repository_is_the_plans(cli, workspace):
    _origin(workspace, "https://github.com/acme/widget.git")
    said = cli("project", "create", "Discovery", "--code", "git@github.com:acme/widget.git")
    assert "inside the code it plans" in said
    assert data(cli("project", "show", "Discovery", "--json"))["state"] == "colocated"


def test_show_prints_both_repositories_and_the_way_out(cli, workspace):
    cli("project", "create", "Discovery")
    said = cli("project", "show", "Discovery")
    assert "plan: widget" in said and "code: not set" in said and "project move" in said
    row = data(cli("project", "show", "Discovery", "--json"))
    assert row["state"] == "legacy" and row["plan_root"] == str(workspace)


def test_a_location_is_added_checked_out_changed_and_removed(cli, tmp_path):
    cli("project", "create", "Discovery")
    said = cli(
        "location",
        "add",
        "Discovery",
        "--role",
        "code",
        "--repository",
        "https://github.com/acme/widget",
        "--checkout",
        str(tmp_path / "widget"),
    )
    assert "Added to Discovery" in said and "l1  Code: acme/widget" in said
    row = data(cli("project", "show", "Discovery", "--json"))
    assert row["repository"] == "https://github.com/acme/widget"
    assert row["checkout"] == str((tmp_path / "widget").resolve())
    assert row["locations"][0]["id"] == "l1" and row["locations"][0]["role"] == "code"

    # A second row of a role that allows several, named by its label from then on.
    cli(
        "location",
        "add",
        "Discovery",
        "--role",
        "code",
        "--repository",
        "git@github.com:acme/ui.git",
        "--label",
        "UI",
    )
    said = cli("location", "list", "Discovery")
    assert "l2  Code — UI: acme/ui — not checked out on this machine" in said
    said = cli("location", "set", "Discovery", "code:ui", "--path", "./apps/web/", "--ref", "main")
    assert "acme/ui at apps/web @main" in said
    assert "nothing to change" in cli("location", "set", "Discovery", "l2", expect=1)
    assert "names several" in cli(
        "location", "checkout", "Discovery", "code", str(tmp_path), expect=1
    )

    cli("location", "checkout", "Discovery", "l1", "--forget")
    assert data(cli("project", "show", "Discovery", "--json"))["checkout"] == ""
    cli("location", "remove", "Discovery", "l2")
    rows = data(cli("location", "list", "Discovery", "--json"))["locations"]
    assert [row["id"] for row in rows] == ["l1"]
    assert "no location 'l9'" in cli("location", "remove", "Discovery", "l9", expect=1)


def test_a_location_that_cannot_stand_is_refused_and_the_roles_are_listed(cli):
    cli("project", "create", "Discovery", "--code", "https://github.com/acme/widget")
    said = cli("location", "add", "Discovery", "--role", "code", "--path", "../out", expect=1)
    assert "leaves its repository" in said
    said = cli("location", "add", "Discovery", "--role", "code", "--repository=-x", expect=1)
    assert "not a repository address" in said
    # With no repository named, a row is about the project's code.
    said = cli("location", "add", "Discovery", "--role", "code", "--label", "again")
    assert "acme/widget" in said
    assert "code" in cli("location", "roles") and "worked in" in cli("location", "roles")


def test_set_records_the_acceptance(cli):
    cli("project", "create", "Discovery")
    cli("project", "set", "Discovery", "--accept-colocation")
    assert data(cli("project", "show", "Discovery", "--json"))["colocation"] == "accepted"
    cli("project", "set", "Discovery", "--warn-colocation")
    assert data(cli("project", "show", "Discovery", "--json"))["colocation"] == ""
    assert "nothing to set" in cli("project", "set", "Discovery", expect=1)


def test_move_takes_the_plan_into_a_plan_repository(cli, workspace, tmp_path):
    _origin(workspace, "https://github.com/acme/widget.git")
    _identity(workspace)
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Deploy")
    subprocess.run(["git", "-C", str(workspace), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(workspace), "commit", "-qm", "plan"], check=True)
    plans = init_repo(tmp_path / "plans")
    _identity(plans)

    said = cli("project", "move", "Discovery", "--into", str(plans))

    assert "Moved the plan of 'Discovery'" in said
    assert "committed in the repository it left and the plan repository" in said
    row = data(cli("project", "show", "Discovery", "--json"))
    assert row["dir"] == str(plans / "discovery") and row["state"] == "separated"
    assert row["checkout"] == str(workspace.resolve())
    assert not (workspace / "discovery").exists() and read_index(plans) == ["discovery"]
    assert "Deploy" in cli("step", "list", "Discovery")


def test_move_refuses_into_the_code_repository_and_needs_one_target(cli, workspace):
    _origin(workspace, "https://github.com/acme/widget.git")
    cli("project", "create", "Discovery")
    said = cli("project", "move", "Discovery", "--to", str(workspace / "plans" / "d"), expect=1)
    assert "code repository" in said
    assert "exactly one" in cli("project", "move", "Discovery", expect=1)


def test_delete_drops_the_index_line(cli, workspace):
    cli("project", "create", "Discovery")
    cli("project", "create", "Billing")
    assert read_index(workspace) == ["discovery", "billing"]
    cli("project", "delete", "Discovery")
    assert read_index(workspace) == ["billing"]
