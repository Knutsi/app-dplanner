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
        "--repository",
        "https://github.com/acme/widget",
        "--checkout",
        str(tmp_path / "widget"),
    )
    assert "Created" in said and "code: acme/widget" in said
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
    said = cli("project", "create", "Discovery", "--repository", "git@github.com:acme/widget.git")
    assert "inside the code it plans" in said
    assert data(cli("project", "show", "Discovery", "--json"))["state"] == "colocated"


def test_show_prints_both_repositories_and_the_way_out(cli, workspace):
    cli("project", "create", "Discovery")
    said = cli("project", "show", "Discovery")
    assert "plan: widget" in said and "code: not set" in said and "project move" in said
    assert "checkout: not on this machine" in said
    row = data(cli("project", "show", "Discovery", "--json"))
    assert row["state"] == "legacy" and row["plan_root"] == str(workspace)


def test_set_records_the_repository_the_checkout_and_the_acceptance(cli, tmp_path):
    cli("project", "create", "Discovery")
    cli(
        "project",
        "set",
        "Discovery",
        "--repository",
        "https://github.com/acme/widget",
        "--checkout",
        str(tmp_path / "widget"),
    )
    row = data(cli("project", "show", "Discovery", "--json"))
    assert row["repository"] == "https://github.com/acme/widget"
    assert row["checkout"] == str((tmp_path / "widget").resolve())

    cli("project", "set", "Discovery", "--forget-checkout", "--accept-colocation")
    row = data(cli("project", "show", "Discovery", "--json"))
    assert row["checkout"] == "" and row["colocation"] == "accepted"

    cli("project", "set", "Discovery", "--warn-colocation")
    assert data(cli("project", "show", "Discovery", "--json"))["colocation"] == ""
    assert "nothing to set" in cli("project", "set", "Discovery", expect=1)


def test_set_says_when_a_checkout_is_not_the_projects_code(cli, tmp_path):
    cli("project", "create", "Discovery", "--repository", "https://github.com/acme/widget")
    other = init_repo(tmp_path / "other")
    _origin(other, "https://github.com/acme/other.git")
    said = cli("project", "set", "Discovery", "--checkout", str(other))
    assert "not the project's code repository" in said


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
