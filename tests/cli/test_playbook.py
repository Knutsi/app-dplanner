"""``dplanner playbook …``: the presets listed, a step's playbook shown with where it was
chosen, and a choice set — on a step, or as the project's defaults.

No ``qapp`` fixture: the aspect and its verbs are Qt-free by rule.
"""

import json

import pytest

from dplanner.domain.store import LibraryStore
from dplanner.modules.step_playbook.aspect import MODULE_ID


@pytest.fixture
def cli(cli):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Build it")
    return cli


def entry_of(cli_library, title):
    project = LibraryStore(cli_library).load().projects[0]
    if title is None:
        return project.module_data.get(MODULE_ID, {})
    step = next(step for step in project.steps if step.title == title)
    return step.module_data.get(MODULE_ID, {})


def test_list_names_every_preset_with_its_stages_and_the_projects_defaults(cli):
    rows = json.loads(cli("--project", "Discovery", "playbook", "list", "--json"))
    assert len(rows) == 9
    review_only = next(row for row in rows if row["playbook"] == "review-only")
    assert review_only["defaults"] == ["landing default"]
    assert [stage["id"] for stage in review_only["stages"]] == ["review", "person"]
    assert review_only["stages"][0]["reviewer"] == "other"
    text = cli("playbook", "list")
    assert "plan-person-execute" in text and "plan, person, execute" in text


def test_a_step_that_never_chose_has_run_agent(cli):
    shown = json.loads(cli("playbook", "show", "build-it", "--json"))
    assert shown["playbook"] is None and shown["source"] == "none"
    assert "Run Agent" in cli("playbook", "show", "build-it")


def test_set_writes_the_step_choice_and_default_takes_it_away(cli, cli_library):
    cli(
        "playbook",
        "set",
        "build-it",
        "plan-execute-review-other",
        "--rounds",
        "3",
        "--reviewer",
        "codex",
    )
    assert entry_of(cli_library, "Build it") == {
        "playbook": "plan-execute-review-other",
        "rounds": 3.0,
        "reviewer": "codex",
        "format": 1,
    }
    shown = json.loads(cli("playbook", "show", "build-it", "--json"))
    assert (shown["playbook"], shown["source"], shown["rounds"]) == (
        "plan-execute-review-other",
        "step",
        3,
    )
    assert [stage["id"] for stage in shown["stages"]] == ["plan", "execute", "review"]
    cli("playbook", "set", "build-it", "default")
    assert entry_of(cli_library, "Build it") == {}


def test_the_project_default_reaches_a_step_that_never_chose(cli, cli_library):
    cli("--project", "Discovery", "playbook", "set", "--project-default", "plan-execute-person")
    assert entry_of(cli_library, None) == {"default": "plan-execute-person", "format": 1}
    shown = json.loads(cli("playbook", "show", "build-it", "--json"))
    assert (shown["playbook"], shown["source"]) == ("plan-execute-person", "project")
    cli("--project", "Discovery", "playbook", "set", "--landing-default", "spike")
    assert entry_of(cli_library, None) == {
        "default": "plan-execute-person",
        "landing": "spike",
        "format": 1,
    }
    cli(
        "--project",
        "Discovery",
        "playbook",
        "set",
        "--project-default",
        "none",
        "--landing-default",
        "review-only",
    )
    assert entry_of(cli_library, None) == {}


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        (("build-it", "plan-execute-review"), "the presets are execute"),
        (("build-it", "spike", "--rounds", "6"), "--rounds is 1 to 5"),
        (("build-it", "default", "--rounds", "3"), "not the default"),
        (("build-it",), "name a step and a playbook"),
        (("build-it", "--project-default", "spike"), "name no step"),
    ],
)
def test_set_refuses_what_it_cannot_write(cli, argv, says):
    assert says in cli("--project", "Discovery", "playbook", "set", *argv, expect=1)
