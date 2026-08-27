"""Canvas accents: done steps mute, releases wear a badge — through the neutral seam.

The canvas never learns what "done" or a release is; the composition root translates the
aspects into a :class:`NodeAccent`, and these tests drive the real wiring end to end.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand, SetModuleDataCommand
from dplanner.domain.model import Project, Step
from dplanner.modules.project_editor.items import NodeAccent
from dplanner.modules.step_release import aspect as release
from dplanner.modules.step_status import aspect as status


@pytest.fixture
def project(services):
    product = services.document
    project = Project(title="Discovery")
    AddNodeCommand(product.id, project).redo(product)
    for title in ("Read the spec", "Ship the beta"):
        AddNodeCommand(project.id, Step(title=title)).redo(product)
    return project


@pytest.fixture
def tab(services, project):
    return services.tabs.open("project", project.id)


def node(tab, step):
    return tab._scene._nodes[step.id]


def test_a_plain_step_has_no_accent(project, tab):
    assert node(tab, project.steps[0])._accent == NodeAccent()


def test_a_done_step_is_muted(services, project, tab):
    step = project.steps[0]
    services.undo.push(SetModuleDataCommand(step.id, status.MODULE_ID, status.write("done")))
    assert node(tab, step)._accent.muted is True


def test_a_release_wears_its_label_as_a_badge(services, project, tab):
    step = project.steps[1]
    services.undo.push(SetModuleDataCommand(step.id, release.MODULE_ID, release.write("MVP")))
    assert node(tab, step)._accent.badge == "MVP"
    # The badge already wears the label, so the subtitle must not repeat it.
    assert "release" not in node(tab, step)._subtitle


def test_in_progress_stays_words_not_paint(services, project, tab):
    """Only "done" earns a visual change; other states are the subtitle's business."""
    step = project.steps[0]
    services.undo.push(
        SetModuleDataCommand(step.id, status.MODULE_ID, status.write("in-progress"))
    )
    assert node(tab, step)._accent == NodeAccent()
    assert "in progress" in node(tab, step)._subtitle


def test_clearing_the_status_unmutes(services, project, tab):
    step = project.steps[0]
    services.undo.push(SetModuleDataCommand(step.id, status.MODULE_ID, status.write("done")))
    services.undo.undo()
    assert node(tab, step)._accent.muted is False
