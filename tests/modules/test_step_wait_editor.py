"""The wait step in the window: the Wait template, the Type toggle and the block on its
Details tab — one undoable write each, of the entry ``dplanner wait set`` writes."""

from datetime import date

import pytest
from PySide6.QtCore import QDate

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.domain.schedule import Wait
from dplanner.modules.estimation.aspect import enabled as estimate_on
from dplanner.modules.step_description.aspect import enabled as description_on
from dplanner.modules.step_wait.aspect import read

TODAY = date(2026, 9, 4)


@pytest.fixture
def project(services, make_project):
    services.clock.pin(TODAY)
    project = make_project("Discovery")
    AddNodeCommand(project.id, Step(title="Hardware arrives")).redo(services.document)
    return project


@pytest.fixture
def panel(step_editor, project):
    return step_editor(project.steps[0].id)


def wait_block(panel):
    labels = [panel.tab_bar.tabText(i) for i in range(panel.tab_bar.count())]
    details = panel._pages.widget(labels.index("Details"))
    return next(b for b in details._blocks if b.section.id == "step_wait.details")


def test_the_wait_template_makes_a_wait_of_a_day_with_no_estimate_or_description(
    services, project, panel
):
    step = project.steps[0]
    assert wait_block(panel).isHidden()
    panel.bar.template("Wait").trigger()
    assert read(step) == Wait(days=1.0)
    assert not estimate_on(step) and not description_on(step)
    assert panel.bar.template("Wait").isChecked()
    assert not wait_block(panel).isHidden()
    services.undo.undo()  # one undo step, as every template is
    assert read(step) is None and estimate_on(step)


def test_the_block_holds_until_a_day_or_for_working_days(services, project, panel):
    step = project.steps[0]
    panel.bar.action("wait.toggle").trigger()
    section = wait_block(panel).extension
    assert section.days_choice.isChecked() and section.days.value() == 1.0
    assert not section.until.isEnabled()
    section.days.setValue(3.0)
    assert read(step) == Wait(days=3.0)
    section.until.setDate(QDate(2026, 11, 4))
    section.until_choice.setChecked(True)
    assert read(step) == Wait(until=date(2026, 11, 4))
    assert section.until.isEnabled() and not section.days.isEnabled()
    services.undo.undo()  # a burst of edits to one entry is one step, as typing is
    wait = read(step)
    assert wait is not None and wait.until is None and section.days_choice.isChecked()


def test_a_wait_takes_no_status_no_agent_and_no_tests_and_says_why(services, project, panel):
    from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri

    step = project.steps[0]
    context = Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step.id)),)})
    assert services.actions.spec("status.done").state(context).enabled
    panel.bar.template("Wait").trigger()
    done = services.actions.spec("status.done").state(context)
    assert not done.enabled and "a wait has no status" in done.label
    for toggle, words in (("agent.toggle", "no work for an agent"), ("test.toggle", "to test")):
        state = services.actions.spec(toggle).state(context)
        assert not state.enabled and words in state.label
    run = services.actions.spec("agent.run").state(context)
    assert not run.enabled
