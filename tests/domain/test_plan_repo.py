"""A plan repository's projects: the index when it has one, a shallow scan when it does not."""

import json

from dplanner.core.storage.locations import init_repo
from dplanner.core.storage.pointer import POINTER_FILE, WORKTREES_DIR
from dplanner.domain.plan_repo import list_projects
from dplanner.domain.seed import seed_project
from dplanner.domain.store import PROJECT_META


def test_the_index_orders_the_projects_and_reports_dangling_lines(tmp_path):
    root = init_repo(tmp_path / "plans")
    seed_project(root / "search", "Search rewrite")
    seed_project(root / "teams" / "billing", "Billing")
    (root / POINTER_FILE).write_text("teams/billing\nsearch\ngone\n")

    found = list_projects(root)
    assert [project.title for project in found.projects] == ["Billing", "Search rewrite"]
    assert [project.relative for project in found.projects] == ["teams/billing", "search"]
    assert all(project.indexed for project in found.projects)
    assert found.dangling == ("gone",)
    assert found.projects[0].project_id and found.projects[0].steps == 0


def test_without_an_index_a_shallow_scan_finds_the_projects(tmp_path):
    root = init_repo(tmp_path / "plans")
    for relative, title in (
        ("search", "Search"),
        ("a/b/deep", "Deep"),  # Three levels down: found.
        ("a/b/c/deeper", "Deeper"),  # Four: somebody else's directory.
        (f"{WORKTREES_DIR}/s1-run/search", "Copy"),  # A branch's copy is not a second plan.
    ):
        seed_project(root / relative, title)
        (root / POINTER_FILE).unlink()  # Seeding indexes; this test is about having none.

    found = list_projects(root)
    assert sorted(project.title for project in found.projects) == ["Deep", "Search"]
    assert not any(project.indexed for project in found.projects)
    assert found.dangling == ()


def test_a_repository_that_is_one_project_lists_itself(tmp_path):
    root = init_repo(tmp_path / "solo")
    seed_project(root, "Solo")
    found = list_projects(root)
    assert [project.relative for project in found.projects] == ["."]
    assert found.projects[0].title == "Solo"


def test_steps_are_counted_from_the_project_file_and_a_torn_one_still_lists(tmp_path):
    root = init_repo(tmp_path / "plans")
    (root / "search").mkdir()
    meta = {"id": "abc", "title": "Search", "children": ["a", "b"]}
    (root / "search" / PROJECT_META).write_text(json.dumps(meta))
    (root / "torn").mkdir()
    (root / "torn" / PROJECT_META).write_text("{")
    (root / POINTER_FILE).write_text("search\ntorn\n")

    found = list_projects(root)
    assert [(p.title, p.steps, p.project_id) for p in found.projects] == [
        ("Search", 2, "abc"),
        ("torn", 0, ""),
    ]
