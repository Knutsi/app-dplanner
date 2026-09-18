"""``dplanner library …`` — membership, headless.

The same rules File ▸ New/Open Project enforces: a project directory must exist, carry a
``project.dproj``, and sit inside a git repository. No ``qapp`` fixture, like every CLI test.
"""

import json
import shutil

from dplanner.core.storage.locations import init_repo
from dplanner.domain.library_file import read_library_file
from dplanner.domain.seed import seed_project


def data(text):
    return json.loads(text)


# -- list --------------------------------------------------------------------------------------


def test_an_empty_library_says_so(cli):
    assert "The library is empty." in cli("library", "list")


def test_list_shows_available_projects_with_their_paths(cli, workspace):
    cli("project", "create", "Discovery")
    said = cli("library", "list")
    assert "Discovery" in said and str(workspace / "discovery") in said

    rows = data(cli("library", "list", "--json"))["projects"]
    assert len(rows) == 1
    assert rows[0]["title"] == "Discovery"
    assert rows[0]["path"] == str(workspace / "discovery")
    assert rows[0]["available"] is True


def test_a_project_that_cannot_open_is_a_problem_row_not_a_refusal(cli, workspace):
    cli("project", "create", "Discovery")
    shutil.rmtree(workspace / "discovery")

    said = cli("library", "list")
    assert "unavailable" in said and str(workspace / "discovery") in said

    rows = data(cli("library", "list", "--json"))["projects"]
    assert len(rows) == 1
    assert rows[0]["available"] is False and rows[0]["reason"]


# -- add ---------------------------------------------------------------------------------------


def test_add_puts_an_existing_project_into_the_library_file(cli, cli_library, tmp_path):
    repo = init_repo(tmp_path / "other")
    directory = seed_project(repo / "planning", "Gadget")

    said = cli("library", "add", str(directory))
    assert "Gadget" in said and "added" in said
    assert directory in read_library_file(cli_library).projects
    titles = [row["title"] for row in data(cli("project", "list", "--json"))["projects"]]
    assert titles == ["Gadget"]


def test_add_refuses_a_directory_that_does_not_exist(cli, tmp_path):
    assert "no such directory" in cli("library", "add", str(tmp_path / "nowhere"), expect=1)


def test_add_refuses_a_directory_that_is_not_a_project(cli, tmp_path):
    plain = init_repo(tmp_path / "plain")
    assert "not a DPlanner project" in cli("library", "add", str(plain), expect=1)


def test_add_refuses_a_project_outside_version_control(cli, tmp_path):
    directory = seed_project(tmp_path / "loose", "Loose")
    said = cli("library", "add", str(directory), expect=1)
    assert "not inside a git repository" in said and "git init" in said


def test_add_refuses_what_is_already_listed(cli, workspace):
    cli("project", "create", "Discovery")
    assert "already in the library" in cli("library", "add", str(workspace / "discovery"), expect=1)


# -- remove ------------------------------------------------------------------------------------


def test_remove_forgets_the_project_but_keeps_its_files(cli, cli_library, workspace):
    cli("project", "create", "Discovery")
    said = cli("library", "remove", "Discovery")
    assert "files stay on disk" in said

    assert read_library_file(cli_library).projects == []
    assert data(cli("project", "list", "--json"))["projects"] == []
    assert (workspace / "discovery" / "project.dproj").is_file()  # unlike `project delete`


# -- path --------------------------------------------------------------------------------------


def test_path_prints_the_library_file_this_invocation_uses(cli, cli_library):
    assert cli("library", "path").strip() == str(cli_library)
    assert data(cli("library", "path", "--json"))["path"] == str(cli_library)


# -- a plan repository: add every project it lists, and browse it first ------------------------


def test_add_over_a_plan_repository_adds_every_listed_project(cli, tmp_path):
    plans = init_repo(tmp_path / "plans")
    seed_project(plans / "search", "Search")
    seed_project(plans / "billing", "Billing")

    said = cli("library", "add", str(plans))
    assert "Added 2 projects" in said and "+ Search" in said and "+ Billing" in said
    titles = [row["title"] for row in data(cli("project", "list", "--json"))["projects"]]
    assert titles == ["Search", "Billing"]

    again = data(cli("library", "add", str(plans), "--json"))
    assert again["added"] == []
    assert [row["reason"] for row in again["skipped"]] == ["already in the library"] * 2


def test_add_skips_a_project_already_here_from_another_clone_by_its_id(cli, tmp_path):
    import shutil

    plans = init_repo(tmp_path / "plans")
    directory = seed_project(plans / "search", "Search")
    cli("library", "add", str(directory))
    clone = tmp_path / "clone"
    shutil.copytree(plans, clone)
    said = data(cli("library", "add", str(clone), "--json"))
    assert said["added"] == [] and said["skipped"][0]["reason"] == "already in the library"


def test_browse_lists_projects_with_activity_and_library_state(cli, tmp_path):
    import subprocess

    plans = init_repo(tmp_path / "plans")
    directory = seed_project(plans / "search", "Search")
    seed_project(plans / "billing", "Billing")
    git = ["git", "-C", str(plans)]
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run(
        [*git, "-c", "user.name=Anna", "-c", "user.email=a@example.com", "commit", "-qm", "plans"],
        check=True,
    )
    cli("library", "add", str(directory))

    rows = data(cli("library", "browse", str(plans / "billing"), "--json"))["projects"]
    assert [(r["title"], r["in_library"], r["last_author"], r["commits"]) for r in rows] == [
        ("Search", True, "Anna", 1),
        ("Billing", False, "Anna", 1),
    ]
    text = cli("library", "browse", str(plans))
    assert "Search" in text and "[in library]" in text and "Anna, just now" in text
    assert "not inside a git repository" in cli("library", "browse", str(tmp_path), expect=1)
