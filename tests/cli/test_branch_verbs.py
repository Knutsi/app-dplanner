"""``dplanner branch …``, ``cut …`` and ``land …`` — a stretch of the plan on a feature
branch, from the terminal.

No ``qapp`` fixture: the aspects and their verbs are Qt-free by rule.
"""

import json

import pytest

from dplanner.domain.store import LibraryStore
from dplanner.modules.branches.aspect import CUT_ID, LAND_ID, branch_of, cut_of


def data(text):
    return json.loads(text)


def reload(library_path):
    return LibraryStore(library_path).load()


def by_title(library, title):
    return next(
        step for project in library.projects for step in project.steps if step.title == title
    )


@pytest.fixture
def cli(cli):
    """Menu on main, then Card fanning out to Edit and Canvas and back into Drag, then
    Release after Drag and Home — the exploration's plan, before anything is on a branch.
    Titled in words: a title like "S17" would read as the key of step 17."""
    cli("project", "create", "Widget")
    cli("step", "add", "widget", "Menu")
    cli("step", "add", "widget", "Home", "--after", "Menu")
    cli("step", "add", "widget", "Card", "--after", "Menu")
    cli("step", "add", "widget", "Edit", "--after", "Card")
    cli("step", "add", "widget", "Canvas", "--after", "Card")
    cli("step", "add", "widget", "Drag", "--after", "Edit", "--after", "Canvas")
    cli("step", "add", "widget", "Release", "--after", "Drag", "--after", "Home")
    return cli


def requires(library, title):
    return sorted(s.title for s in library.requires(by_title(library, title).id))


def test_put_brackets_the_steps_and_moves_the_outside_links_onto_the_ends(cli, cli_library):
    said = data(
        cli(
            "branch",
            "put",
            "Card",
            "Edit",
            "Canvas",
            "Drag",
            "--branch",
            "feature/stacks",
            "--json",
        )
    )
    library = reload(cli_library)
    cut, land = library.step(said["cut"]), library.step(said["land"])
    assert branch_of(cut) == "feature/stacks" and cut_of(land) == cut.id
    assert requires(library, cut.title) == ["Menu"]
    assert requires(library, "Card") == [cut.title]
    assert requires(library, "Edit") == ["Card"]
    assert requires(library, land.title) == ["Drag"]
    assert requires(library, "Release") == ["Home", land.title]
    # Dressed as the window makes them: nobody works the cut, an agent lands it.
    assert cut.module_data["estimation"]["off"] is True
    assert land.module_data["step_agent_instruction"]
    shown = data(cli("branch", "show", "widget", "--json"))
    (branch,) = shown["branches"]
    assert branch["branch"] == "feature/stacks" and len(branch["steps"]) == 4


def test_remove_takes_the_whole_bracket_away_and_closes_the_links(cli, cli_library):
    cli("branch", "put", "Card", "Edit", "Canvas", "Drag", "--branch", "feature/stacks")
    said = cli("branch", "remove", "Edit")
    assert "feature/stacks is gone" in said
    library = reload(cli_library)
    assert not any(
        CUT_ID in s.module_data or LAND_ID in s.module_data for s in library.projects[0].steps
    )
    assert requires(library, "Card") == ["Menu"]
    assert requires(library, "Release") == ["Drag", "Home"]


def test_put_refuses_a_pick_with_a_step_left_between(cli):
    said = cli("branch", "put", "Card", "Drag", "--branch", "feature/x", expect=1)
    assert "comes between them" in said


def test_put_refuses_a_name_git_would_refuse(cli):
    said = cli("branch", "put", "Card", "--branch", "feature x", expect=1)
    assert "not a branch name git accepts" in said


def test_a_landing_set_by_hand_finds_the_one_open_cut_upstream(cli, cli_library):
    cli("step", "add", "widget", "Cut", "--after", "Menu")
    cli("cut", "set", "Cut", "--branch", "feature/by-hand")
    cli("step", "add", "widget", "Land", "--after", "Cut")
    said = cli("land", "set", "Land")
    assert "lands feature/by-hand" in said
    library = reload(cli_library)
    assert cut_of(by_title(library, "Land")) == by_title(library, "Cut").id


def test_a_landing_with_no_cut_upstream_is_refused(cli):
    said = cli("land", "set", "Drag", expect=1)
    assert "no open branch cut is upstream" in said


def test_a_member_agent_is_briefed_onto_the_branch(cli, tmp_path):
    cli("branch", "put", "Card", "Edit", "Canvas", "Drag", "--branch", "feature/stacks")
    cli("agent", "on", "Edit")
    brief = tmp_path / "brief.md"
    brief.write_text("Edit a stack.", encoding="utf-8")
    cli("describe", "set", "Edit", "--file", str(brief))
    prompt = data(cli("agent", "prompt", "Edit", "--json"))
    assert prompt["base"] == "feature/stacks"
    assert "gh pr create --base feature/stacks" in prompt["prompt"]


def test_lint_names_main_work_linked_into_the_middle(cli):
    cli("branch", "put", "Card", "Edit", "Canvas", "Drag", "--branch", "feature/stacks")
    cli("step", "link", "Edit", "Home")
    found = data(cli("project", "lint", "widget", "--json", expect=1))
    checks = {row["check"] for row in found["findings"]}
    assert "branch.late-entry" in checks


def test_a_cut_takes_no_status(cli):
    said = data(cli("branch", "put", "Card", "--branch", "feature/one", "--json"))
    said = cli("status", "set", said["cut"], "done", expect=1)
    assert "is a branch cut: a branch cut has no status" in said
