"""The playbook model and the aspect naming a step's playbook: the nine presets, the stage ids
a run names, and which playbook a step resolves to — its own, a landing's, the project's, or
none. No ``qapp``: all of it is Qt-free by rule."""

import pytest

from dplanner.domain.headless import StageKind
from dplanner.domain.model import Project, Step
from dplanner.modules.step_playbook.aspect import (
    MODULE_ID,
    Choice,
    Defaults,
    inherited,
    read,
    read_project,
    resolve,
    summary,
    write,
    write_project,
)
from dplanner.modules.step_playbook.presets import (
    LANDING_DEFAULT,
    PRESETS,
    Playbook,
    Stage,
    StageRole,
    preset,
)
from dplanner.planning.branches import LAND_ID


def playbook(playbook_id: str) -> Playbook:
    found = preset(playbook_id)
    assert found is not None
    return found


def test_the_nine_presets_are_the_designs_list_in_its_order():
    assert [(p.id, p.stage_words()) for p in PRESETS] == [
        ("execute", "execute"),
        ("plan-execute-coordinator", "plan, execute, coordinator"),
        ("plan-execute-person", "plan, execute, person"),
        ("plan-execute-progress", "plan, execute, progress"),
        ("plan-execute-review-self", "plan, execute, review (same agent)"),
        ("plan-execute-review-other", "plan, execute, review (other agent)"),
        ("plan-person-execute", "plan, person, execute"),
        ("review-only", "review (other agent), person"),
        ("spike", "plan, person"),
    ]
    assert LANDING_DEFAULT is playbook("review-only")
    assert preset("plan-execute-review") is None


def test_a_stage_id_is_its_role_numbered_when_the_role_repeats():
    twice = Playbook(
        "t",
        "T",
        1,
        (
            Stage(StageRole.EXECUTE),
            Stage(StageRole.REVIEW, "same"),
            Stage(StageRole.REVIEW, "other"),
        ),
        "",
    )
    assert twice.stage_ids() == ("execute", "review", "review-2")
    assert playbook("plan-person-execute").stage_ids() == ("plan", "person", "execute")


def test_only_the_agent_roles_map_onto_a_headless_turn_and_only_judges_are_gates():
    assert {role: role.agent_stage for role in StageRole} == {
        StageRole.PLAN: StageKind.PLAN,
        StageRole.EXECUTE: StageKind.EXECUTE,
        StageRole.REVIEW: StageKind.REVIEW,
        StageRole.PERSON: None,
        StageRole.COORDINATOR: None,
        StageRole.PROGRESS: None,
    }
    assert {role for role in StageRole if role.is_gate} == {
        StageRole.REVIEW,
        StageRole.PERSON,
        StageRole.COORDINATOR,
    }
    assert not playbook("execute").has_gate() and not playbook("plan-execute-progress").has_gate()
    assert playbook("review-only").reviews_with_other()
    assert not playbook("plan-execute-review-self").reviews_with_other()


def test_the_entry_names_a_preset_and_only_the_overrides_that_differ():
    step = Step(title="Build it")
    assert read(step) is None and summary(step) == "" and write(None) == {}
    step.module_data[MODULE_ID] = write(Choice(playbook("spike")))
    assert step.module_data[MODULE_ID] == {"playbook": "spike", "format": 1}
    choice = Choice(playbook("plan-execute-review-other"), rounds=3, reviewer="codex")
    step.module_data[MODULE_ID] = write(choice)
    rounds = step.module_data[MODULE_ID]["rounds"]
    assert rounds == 3.0 and isinstance(rounds, float)  # a number written is a float
    assert read(step) == choice
    assert summary(step) == "Plan → execute ⇄ review (other agent) · 3 rounds · reviewer codex"


@pytest.mark.parametrize(
    "entry",
    [
        {"playbook": "no-such-preset"},
        {"playbook": 7},
        {"rounds": 3.0},
    ],
)
def test_an_entry_naming_no_preset_this_build_knows_reads_as_the_default(entry):
    step = Step(title="Build it")
    step.module_data[MODULE_ID] = entry
    assert read(step) is None


@pytest.mark.parametrize("rounds", [0, 6, 2.5, True, "3"])
def test_a_round_cap_out_of_range_reads_as_the_default(rounds):
    step = Step(title="Build it")
    step.module_data[MODULE_ID] = {"playbook": "spike", "rounds": rounds}
    assert read(step) == Choice(playbook("spike"))


def test_the_project_entry_names_only_what_differs_from_its_defaults():
    project = Project(title="Discovery")
    assert read_project(project) == Defaults(None, LANDING_DEFAULT)
    assert write_project(Defaults()) == {}
    entry = write_project(Defaults(default=playbook("execute"), landing=playbook("spike")))
    assert entry == {"default": "execute", "landing": "spike", "format": 1}
    project.module_data[MODULE_ID] = entry
    assert read_project(project) == Defaults(playbook("execute"), playbook("spike"))


def test_a_step_runs_its_own_then_a_landings_then_the_projects_then_none():
    project = Project(title="Discovery")
    work = Step(title="Build it")
    land = Step(title="Land it")
    land.module_data[LAND_ID] = {"cut": "a-cut-id", "format": 1}
    assert resolve(work, project) == inherited(work, project)
    assert (resolve(work, project).playbook, resolve(work, project).source) == (None, "none")
    assert (resolve(land, project).playbook, resolve(land, project).source) == (
        LANDING_DEFAULT,
        "landing",
    )
    project.module_data[MODULE_ID] = write_project(
        Defaults(default=playbook("execute"), landing=playbook("plan-execute-person"))
    )
    assert resolve(work, project).playbook == playbook("execute")
    assert resolve(work, project).source == "project"
    assert resolve(land, project).playbook == playbook("plan-execute-person")
    work.module_data[MODULE_ID] = write(Choice(playbook("spike")))
    assert resolve(work, project).playbook == playbook("spike")
    assert resolve(work, project).source == "step"
    assert inherited(work, project).playbook == playbook("execute")
