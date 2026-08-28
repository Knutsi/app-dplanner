"""Canvas accents: status bars, badges, glyphs and chips — through the neutral seam.

The canvas never learns what "done", a release or an agent run is; the composition root
translates the aspects into a :class:`NodeAccent`, and these tests drive the real wiring
end to end.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand, SetModuleDataCommand
from dplanner.domain.model import Project, Step
from dplanner.modules.project_editor.renderers import NodeAccent
from dplanner.modules.step_agent_run import aspect as agent_run
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


def test_a_done_step_is_muted_with_a_green_body(services, project, tab):
    step = project.steps[0]
    services.undo.push(SetModuleDataCommand(step.id, status.MODULE_ID, status.write("done")))
    accent = node(tab, step)._accent
    assert accent.muted is True
    assert accent.body_tone == "good"
    assert accent.bar_tone == ""  # The body wears the green; a bar would say it twice.


def test_a_shipped_release_reads_finished(services, project, tab):
    """Done outranks the release purple on the body; the tag still says what it was."""
    step = project.steps[1]
    services.undo.push(SetModuleDataCommand(step.id, release.MODULE_ID, release.write("MVP")))
    services.undo.push(SetModuleDataCommand(step.id, status.MODULE_ID, status.write("done")))
    accent = node(tab, step)._accent
    assert accent.body_tone == "good"
    assert "tag" in accent.icons and accent.badge == "MVP"


def test_a_release_is_a_highlighted_node_with_a_tag(services, project, tab):
    step = project.steps[1]
    services.undo.push(SetModuleDataCommand(step.id, release.MODULE_ID, release.write("MVP")))
    accent = node(tab, step)._accent
    assert accent.badge == "MVP"
    assert accent.body_tone == "highlight"
    assert "tag" in accent.icons
    # The badge already wears the label, so the subtitle must not repeat it.
    assert "release" not in node(tab, step)._subtitle


def test_an_estimate_is_the_steps_stat_not_subtitle_text(services, project, tab):
    step = project.steps[0]
    services.undo.push(
        SetModuleDataCommand(step.id, "estimation", {"days": 3.0, "format": 1})
    )
    accent = node(tab, step)._accent
    assert accent.stat_text == "3d"
    assert accent.stat_strong is False
    assert "3d" not in node(tab, step)._subtitle


def test_a_release_stat_is_the_accumulated_days_and_date(services, project, tab):
    """The release's number is the schedule's answer at its row — days and landing date."""
    first, second = project.steps
    for step, days in ((first, 2.0), (second, 3.0)):
        services.undo.push(SetModuleDataCommand(step.id, "estimation", {"days": days}))
    services.undo.push(SetModuleDataCommand(second.id, release.MODULE_ID, release.write("MVP")))
    accent = node(tab, second)._accent
    assert accent.stat_strong is True
    assert accent.stat_text.startswith("5d · ")
    assert any(char.isdigit() for char in accent.stat_text.split("·")[1])


def test_in_progress_gets_a_busy_bar_and_leaves_the_subtitle(services, project, tab):
    """The bar wears the status now, so the subtitle must not say it again."""
    step = project.steps[0]
    services.undo.push(
        SetModuleDataCommand(step.id, status.MODULE_ID, status.write("in-progress"))
    )
    accent = node(tab, step)._accent
    assert accent.bar_tone == "busy"
    assert accent.muted is False
    assert "in progress" not in node(tab, step)._subtitle


def test_blocked_gets_a_bad_bar(services, project, tab):
    step = project.steps[0]
    services.undo.push(SetModuleDataCommand(step.id, status.MODULE_ID, status.write("blocked")))
    assert node(tab, step)._accent.bar_tone == "bad"


def test_an_instructed_step_wears_the_spark_medallion(services, project, tab):
    step = project.steps[0]
    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    assert "spark" in node(tab, step)._accent.icons
    assert "instructed" not in node(tab, step)._subtitle


@pytest.mark.parametrize(
    ("state", "chip_text", "chip_tone"),
    [
        ("launched", "launched", "info"),
        ("working", "working", "info"),
        ("plan-for-review", "plan ready", "attention"),
        ("pending-approval", "needs approval", "attention"),
    ],
)
def test_agent_run_states_become_chips(services, project, tab, state, chip_text, chip_tone):
    step = project.steps[0]
    services.undo.push(
        SetModuleDataCommand(step.id, agent_run.MODULE_ID, agent_run.write(state))
    )
    accent = node(tab, step)._accent
    assert (accent.chip_text, accent.chip_tone) == (chip_text, chip_tone)


def test_clearing_the_status_unmutes(services, project, tab):
    step = project.steps[0]
    services.undo.push(SetModuleDataCommand(step.id, status.MODULE_ID, status.write("done")))
    services.undo.undo()
    assert node(tab, step)._accent.muted is False
