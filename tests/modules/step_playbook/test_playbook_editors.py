"""The playbook in the window: the block on a step's Details tab and the Playbooks tab of
*Project ▸ Settings…* — one undoable write each, of the entries ``dplanner playbook set``
writes."""

import pytest

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri
from dplanner.modules.step_playbook.aspect import MODULE_ID, Choice, read, read_project
from dplanner.modules.step_playbook.presets import LANDING_DEFAULT, preset
from dplanner.modules.step_playbook.project_section import ProjectPlaybookSection
from dplanner.planning.wait import MODULE_ID as WAIT_ID
from dplanner.planning.wait import Wait
from dplanner.planning.wait import write as wait_write


@pytest.fixture
def project(services, make_project):
    project = make_project("Discovery")
    AddNodeCommand(project.id, Step(title="Build it")).redo(services.document)
    return project


def playbook(playbook_id):
    found = preset(playbook_id)
    assert found is not None
    return found


def playbook_block(panel):
    labels = [panel.tab_bar.tabText(i) for i in range(panel.tab_bar.count())]
    details = panel._pages.widget(labels.index("Details"))
    return next(b for b in details._blocks if b.section.id == "step_playbook.details")


def pick(combo, data):
    index = combo.findData(data)
    assert index >= 0, data
    combo.setCurrentIndex(index)
    combo.activated.emit(index)


def test_the_block_writes_a_preset_and_default_takes_it_away(services, project, step_editor):
    step = project.steps[0]
    section = playbook_block(step_editor(step.id)).extension
    assert section.playbook.currentIndex() == 0
    assert section.playbook.itemText(0) == "Default — Run Agent"
    assert not section.rounds.isEnabled() and not section.reviewer.isEnabled()

    pick(section.playbook, "plan-execute-review-other")
    assert read(step) == Choice(playbook("plan-execute-review-other"))
    assert section.rounds.isEnabled() and section.reviewer.isEnabled()
    section.rounds.setValue(3)
    pick(section.reviewer, "codex")
    assert read(step) == Choice(playbook("plan-execute-review-other"), rounds=3, reviewer="codex")

    pick(section.playbook, "execute")  # no gate, no review: the overrides have nothing to cap
    assert step.module_data[MODULE_ID] == {"playbook": "execute", "format": 1}
    assert not section.rounds.isEnabled() and not section.reviewer.isEnabled()

    section.playbook.setCurrentIndex(0)
    section.playbook.activated.emit(0)
    assert not step.module_data.get(MODULE_ID)


def test_a_pick_undoes_back_to_the_default(services, project, step_editor):
    step = project.steps[0]
    section = playbook_block(step_editor(step.id)).extension
    pick(section.playbook, "spike")
    assert read(step) == Choice(playbook("spike"))
    services.undo.undo()
    assert read(step) is None and section.playbook.currentIndex() == 0


def test_default_names_what_the_step_inherits(services, project, step_editor):
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.step_playbook.aspect import Defaults, write_project

    services.undo.push(
        SetModuleDataCommand(
            project.id, MODULE_ID, write_project(Defaults(default=preset("spike")))
        )
    )
    section = playbook_block(step_editor(project.steps[0].id)).extension
    assert section.playbook.itemText(0) == "Default — Spike"


def test_a_wait_has_no_playbook_block(services, project, step_editor):
    step = project.steps[0]
    services.document.set_module_data(step.id, WAIT_ID, wait_write(Wait(days=1.0)))
    assert playbook_block(step_editor(step.id)).isHidden()


def settings_for(services, project):
    """*Project ▸ Settings…* on ``project``, the application's way: the module's one dialog."""
    module = next(m for m in services.modules if m.id == "projects")
    on = Context({SCOPE_SELECTION: (ContextNode(selection_uri("project", project.id)),)})
    services.actions.run("projects.settings", on)
    return module._dialog


def test_the_project_tab_sets_both_defaults_as_one_undo_each(services, project):
    dialog = settings_for(services, project)
    tab = next(e for e in dialog.extensions if isinstance(e, ProjectPlaybookSection))
    assert tab.default.currentIndex() == 0 and tab.landing.currentData() == LANDING_DEFAULT.id

    pick(tab.default, "plan-execute-person")
    assert read_project(project).default == preset("plan-execute-person")
    pick(tab.landing, "spike")
    assert project.module_data[MODULE_ID] == {
        "default": "plan-execute-person",
        "landing": "spike",
        "format": 1,
    }
    services.undo.undo()
    assert read_project(project).landing == LANDING_DEFAULT
    assert tab.landing.currentData() == LANDING_DEFAULT.id
    dialog.hide()
