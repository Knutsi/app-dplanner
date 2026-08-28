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
    assert directory in read_library_file(cli_library)
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

    assert read_library_file(cli_library) == []
    assert data(cli("project", "list", "--json"))["projects"] == []
    assert (workspace / "discovery" / "project.dproj").is_file()  # unlike `project delete`


# -- path --------------------------------------------------------------------------------------


def test_path_prints_the_library_file_this_invocation_uses(cli, cli_library):
    assert cli("library", "path").strip() == str(cli_library)
    assert data(cli("library", "path", "--json"))["path"] == str(cli_library)
