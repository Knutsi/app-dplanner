"""The project link: one description of a project, two ways of carrying it.

What is under test is the round trip and every refusal — a link is read on a machine that
has never seen the plan, so what it does with a broken one is as much of the contract as
what it does with a good one.
"""

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from dplanner.core.storage.locations import init_repo
from dplanner.domain.model import Project
from dplanner.domain.project_link import (
    FORMAT,
    ROOT,
    SUFFIX,
    LinkError,
    ProjectLink,
    decode,
    document,
    document_text,
    encode,
    find_clone,
    link_for,
    project_directory,
    read,
    read_document,
    read_file,
    relative_path,
)
from dplanner.domain.repositories import RepositoryFacts

PLAN_REMOTE = "https://github.com/acme/plans"
CODE_REMOTE = "https://github.com/acme/widget"


BASE_LINK = ProjectLink(
    plan_remote=PLAN_REMOTE,
    plan_path="search-rewrite",
    project_id="p-1",
    title="Search rewrite",
    summary="Replace the index",
    code_remote=CODE_REMOTE,
)


def link(**overrides):
    return replace(BASE_LINK, **overrides)


BASE_FACTS = RepositoryFacts(
    plan_root=Path("/home/anna/plans"),
    plan_remote=PLAN_REMOTE,
    repository=CODE_REMOTE,
    checkout=None,
    colocation="",
)


def facts(**overrides):
    return replace(BASE_FACTS, **overrides)


# -- making one --------------------------------------------------------------------------------


def test_a_link_carries_both_repositories_and_where_the_plan_sits_in_its_own():
    project = Project(node_id="p-1", title="Search rewrite", summary="Replace the index")
    made = link_for(project, Path("/home/anna/plans/search-rewrite"), facts())
    assert made == link()


def test_a_project_that_is_its_whole_plan_repository_carries_the_root_path():
    project = Project(node_id="p-1", title="Widget")
    made = link_for(project, Path("/home/anna/plans"), facts())
    assert made.plan_path == ROOT
    assert project_directory(Path("/tmp/clone"), made) == Path("/tmp/clone")


def test_a_plan_outside_git_cannot_be_shared():
    with pytest.raises(LinkError, match="not in a git repository"):
        link_for(Project(title="Widget"), Path("/tmp/widget"), facts(plan_root=None))


def test_a_plan_repository_with_no_remote_says_to_publish_it_first():
    with pytest.raises(LinkError, match="publish it to GitHub"):
        link_for(Project(title="Widget"), Path("/home/anna/plans/w"), facts(plan_remote=""))


def test_the_relative_path_is_posix_whatever_the_platform_spelt_it(tmp_path):
    directory = tmp_path / "team" / "search"
    directory.mkdir(parents=True)
    assert relative_path(tmp_path, directory) == "team/search"


# -- the file ----------------------------------------------------------------------------------


def test_the_file_round_trips_every_field():
    assert read_document(json.loads(document_text(link()))) == link()


def test_an_empty_field_writes_no_key():
    bare = ProjectLink(plan_remote=PLAN_REMOTE)
    assert document(bare) == {
        "dplanner": "project-link",
        "format": FORMAT,
        "plan": {"remote": PLAN_REMOTE, "path": ROOT},
    }
    assert read_document(document(bare)) == bare


def test_the_file_ends_in_one_newline_and_sorts_its_keys():
    text = document_text(link())
    assert text.endswith("}\n") and not text.endswith("\n\n")
    assert list(json.loads(text)) == sorted(json.loads(text))


def test_json_that_is_not_a_link_is_refused_by_name():
    with pytest.raises(LinkError, match="not a DPlanner project link"):
        read_document({"title": "Search rewrite"})


def test_a_link_with_no_plan_repository_is_refused():
    with pytest.raises(LinkError, match="names no plan repository"):
        read_document({"dplanner": "project-link", "format": 1, "plan": {"path": "x"}})


def test_a_newer_format_says_to_update_rather_than_guessing():
    raw = document(link()) | {"format": FORMAT + 1}
    with pytest.raises(LinkError, match="newer DPlanner"):
        read_document(raw)


def test_a_torn_file_names_itself(tmp_path):
    path = tmp_path / f"broken{SUFFIX}"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(LinkError, match=f"broken{SUFFIX}"):
        read_file(path)


# -- the one-line form -------------------------------------------------------------------------


def test_the_link_round_trips_every_field():
    assert decode(encode(link())) == link()


def test_the_link_spells_the_repositories_out_so_a_person_can_read_them():
    text = encode(link())
    assert text.startswith("dplanner://project?")
    assert f"plan={PLAN_REMOTE}" in text
    assert f"code={CODE_REMOTE}" in text


def test_a_title_with_spaces_and_an_ampersand_survives():
    made = link(title="Search & sort", summary="A: the index; B: the ranker")
    assert decode(encode(made)) == made


def test_another_scheme_is_refused():
    with pytest.raises(LinkError, match="not a dplanner://project link"):
        decode("https://github.com/acme/plans")


def test_a_newer_link_format_says_to_update():
    with pytest.raises(LinkError, match="newer DPlanner"):
        decode(f"dplanner://project?plan={PLAN_REMOTE}&format={FORMAT + 1}")


# -- however it arrived -------------------------------------------------------------------------


def test_read_takes_a_pasted_link():
    assert read(f"  {encode(link())}  ") == link()


def test_read_takes_a_file_path(tmp_path):
    path = tmp_path / link().filename
    path.write_text(document_text(link()), encoding="utf-8")
    assert read(str(path)) == link()
    assert path.name == "search-rewrite.dlink"


def test_read_takes_a_path_a_terminal_quoted(tmp_path):
    path = tmp_path / "a link.dlink"
    path.write_text(document_text(link()), encoding="utf-8")
    assert read(f'"{path}"') == link()


def test_read_says_what_to_do_when_nothing_was_given():
    with pytest.raises(LinkError, match="paste a project link"):
        read("   ")


def test_read_names_a_file_that_is_not_there(tmp_path):
    with pytest.raises(LinkError, match="no such file"):
        read(str(tmp_path / f"missing{SUFFIX}"))


def test_read_refuses_something_that_is_neither():
    with pytest.raises(LinkError, match="neither"):
        read("search-rewrite")


# -- do I already have this repository? ----------------------------------------------------------


def test_a_clone_of_the_same_remote_is_found_however_the_url_is_spelt(tmp_path):
    root = init_repo(tmp_path / "plans")
    subprocess.run(
        ["git", "-C", str(root), "remote", "add", "origin", "git@github.com:acme/plans.git"],
        check=True,
    )
    other = init_repo(tmp_path / "elsewhere")
    assert find_clone([other, root], PLAN_REMOTE) == root


def test_no_clone_of_it_is_no_answer(tmp_path):
    assert find_clone([init_repo(tmp_path / "plans")], PLAN_REMOTE) is None


def test_a_root_that_is_no_longer_on_disk_is_stepped_over(tmp_path):
    assert find_clone([tmp_path / "gone"], PLAN_REMOTE) is None
