"""Canvas accents: status bars, badges, glyphs and chips — through the neutral seam.

The canvas never learns what "done", a milestone or an agent run is; the composition root
translates the aspects into a :class:`NodeAccent`, and these tests drive the real wiring
end to end.
"""

from datetime import date

import pytest

from dplanner.domain.commands import AddNodeCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.modules.feature import aspect as feature
from dplanner.modules.project_editor.renderers import NodeAccent
from dplanner.modules.step_agent_run import aspect as agent_run
from dplanner.modules.step_milestone import aspect as milestone
from dplanner.modules.step_status import aspect as status


@pytest.fixture
def project(services, make_project):
    library = services.document
    project = make_project("Discovery")
    for title in ("Read the spec", "Ship the beta"):
        AddNodeCommand(project.id, Step(title=title)).redo(library)
    return project


@pytest.fixture
def tab(services, project):
    return services.tabs.open("project", project.id)


def node(tab, step):
    return tab._scene._nodes[step.id]


def test_a_plain_step_has_no_accent_beyond_its_key(project, tab):
    # Flagged, because a bare step is exactly what lint has things to say about — no
    # description, no estimate. Everything else about it is the default.
    assert node(tab, project.steps[0])._accent == NodeAccent(key_text="S1", flagged=True)


def test_the_key_letter_follows_the_kind_and_the_number_stays(services, project, tab):
    """The spine reads the step's key: the number the project dealt, behind a letter for
    what the step is now — a milestone outranks a feature, a check ranks below both."""
    from dplanner.modules.step_check import aspect as check

    step = project.steps[1]
    assert node(tab, step)._accent.key_text == "S2"
    services.undo.push(SetModuleDataCommand(step.id, check.MODULE_ID, check.write(True)))
    assert node(tab, step)._accent.key_text == "C2"
    services.undo.push(SetModuleDataCommand(step.id, feature.MODULE_ID, feature.write()))
    assert node(tab, step)._accent.key_text == "F2"
    services.undo.push(SetModuleDataCommand(step.id, milestone.MODULE_ID, milestone.write("MVP")))
    assert node(tab, step)._accent.key_text == "M2"


def test_a_done_step_is_muted_with_a_green_body(services, project, tab):
    step = project.steps[0]
    services.undo.push(
        SetModuleDataCommand(
            step.id, status.MODULE_ID, status.write("done", today=date(2026, 9, 21))
        )
    )
    accent = node(tab, step)._accent
    assert accent.muted is True
    assert accent.body_tone == "good"
    assert accent.spine_tone == "good"  # The spine says where the step stands, always.


def test_a_shipped_milestone_reads_finished(services, project, tab):
    """Done outranks the milestone purple on the body; the tag still says what it was."""
    step = project.steps[1]
    services.undo.push(SetModuleDataCommand(step.id, milestone.MODULE_ID, milestone.write("MVP")))
    services.undo.push(
        SetModuleDataCommand(
            step.id, status.MODULE_ID, status.write("done", today=date(2026, 9, 21))
        )
    )
    accent = node(tab, step)._accent
    assert accent.body_tone == "good"
    assert "tag" in accent.icons and accent.badge == "MVP"


def test_a_release_is_a_highlighted_node_with_a_tag(services, project, tab):
    step = project.steps[1]
    services.undo.push(SetModuleDataCommand(step.id, milestone.MODULE_ID, milestone.write("MVP")))
    accent = node(tab, step)._accent
    assert accent.badge == "MVP"
    assert accent.body_tone == "highlight"
    assert "tag" in accent.icons


def test_a_feature_is_a_teal_node_with_a_layer_medallion(services, project, tab):
    step = project.steps[0]
    services.undo.push(SetModuleDataCommand(step.id, feature.MODULE_ID, feature.write()))
    accent = node(tab, step)._accent
    assert accent.body_tone == "feature"
    assert "layers" in accent.icons


def test_a_milestone_outranks_a_feature_on_the_body(services, project, tab):
    """The coarser claim wins the colour; the finer one keeps its medallion."""
    step = project.steps[1]
    services.undo.push(SetModuleDataCommand(step.id, feature.MODULE_ID, feature.write()))
    services.undo.push(SetModuleDataCommand(step.id, milestone.MODULE_ID, milestone.write("MVP")))
    accent = node(tab, step)._accent
    assert accent.body_tone == "highlight"
    assert accent.icons == ("tag", "layers")


def test_a_done_feature_reads_finished(services, project, tab):
    step = project.steps[0]
    services.undo.push(SetModuleDataCommand(step.id, feature.MODULE_ID, feature.write()))
    services.undo.push(
        SetModuleDataCommand(
            step.id, status.MODULE_ID, status.write("done", today=date(2026, 9, 21))
        )
    )
    accent = node(tab, step)._accent
    assert accent.body_tone == "good" and accent.muted is True


def test_an_estimate_is_the_steps_stat(services, project, tab):
    step = project.steps[0]
    services.undo.push(SetModuleDataCommand(step.id, "estimation", {"days": 3.0, "format": 1}))
    accent = node(tab, step)._accent
    assert accent.stat_text == "3d"
    assert accent.stat_strong is False


def test_a_release_stat_is_the_accumulated_days_and_date(services, project, tab):
    """The milestone's number is the schedule's answer at its row — days and landing date."""
    first, second = project.steps
    for step, days in ((first, 2.0), (second, 3.0)):
        services.undo.push(SetModuleDataCommand(step.id, "estimation", {"days": days}))
    services.undo.push(SetModuleDataCommand(second.id, milestone.MODULE_ID, milestone.write("MVP")))
    accent = node(tab, second)._accent
    assert accent.stat_strong is True
    assert accent.stat_text.startswith("5d · ")
    assert any(char.isdigit() for char in accent.stat_text.split("·")[1])


def test_in_progress_gets_a_busy_bar(services, project, tab):
    step = project.steps[0]
    services.undo.push(
        SetModuleDataCommand(
            step.id, status.MODULE_ID, status.write("in-progress", today=date(2026, 9, 21))
        )
    )
    accent = node(tab, step)._accent
    assert accent.spine_tone == "busy"
    assert accent.muted is False


def test_blocked_gets_a_bad_bar(services, project, tab):
    step = project.steps[0]
    services.undo.push(
        SetModuleDataCommand(
            step.id, status.MODULE_ID, status.write("blocked", today=date(2026, 9, 21))
        )
    )
    assert node(tab, step)._accent.spine_tone == "bad"


def test_an_instructed_step_wears_the_spark_medallion(services, project, tab):
    step = project.steps[0]
    services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
    assert "spark" in node(tab, step)._accent.icons


def test_prose_reaches_a_card_one_settle_later_rather_than_within_the_turn(
    app, services, project, tab
):
    """A card shows no prose but whether an agent instruction exists, so a keystroke in a
    description must not buy a sync of every card — and the spark still arrives, a settle
    later. The window's regime: in the suite's immediate mode both run inline."""
    step = project.steps[0]
    services.debounce.set_immediate(False)
    try:
        services.document.set_text(step.id, "step_agent_instruction", "Ship it.")
        app.processEvents()  # The canvas's own turn goes by without a sync.
        assert "spark" not in node(tab, step)._accent.icons
        services.debounce.flush_all()
        assert "spark" in node(tab, step)._accent.icons
    finally:
        services.debounce.set_immediate(True)


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
    services.undo.push(SetModuleDataCommand(step.id, agent_run.MODULE_ID, agent_run.write(state)))
    accent = node(tab, step)._accent
    assert (accent.chip_text, accent.chip_tone) == (chip_text, chip_tone)


def test_clearing_the_status_unmutes(services, project, tab):
    step = project.steps[0]
    services.undo.push(
        SetModuleDataCommand(
            step.id, status.MODULE_ID, status.write("done", today=date(2026, 9, 21))
        )
    )
    services.undo.undo()
    assert node(tab, step)._accent.muted is False


# -- the live ring -----------------------------------------------------------------------------


def test_a_live_agent_run_wears_a_marching_ring(services, project, tab):
    """The chip says an agent is on the step; the ring moving says it is on it *now*. One
    scene clock drives every ring, and it runs only while there is one to drive."""
    scene = tab._scene
    step = project.steps[0]
    assert not scene._ring_timer.isActive()

    SetModuleDataCommand(step.id, agent_run.MODULE_ID, agent_run.write("working")).redo(
        services.document
    )
    item = node(tab, step)
    assert item.wears_ring() and scene._ring_timer.isActive()
    before = item._ring_phase
    scene.advance_rings()
    assert item._ring_phase != before
    assert node(tab, project.steps[1])._ring_phase == item._ring_phase  # One clock for all.

    SetModuleDataCommand(step.id, agent_run.MODULE_ID, {}).redo(services.document)
    assert not item.wears_ring() and not scene._ring_timer.isActive()


def test_the_ring_is_painted_outside_the_body_and_moves_with_the_phase(app):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter, QPalette

    from dplanner.modules.project_editor.positions import NODE_H, NODE_W
    from dplanner.modules.project_editor.renderers import (
        PAINT_MARGIN,
        RING_GAP,
        NodeState,
        paint_node,
    )

    def render(accent, phase=0.0):
        margin = int(PAINT_MARGIN)
        size = (int(NODE_W) + 2 * margin, int(NODE_H) + 2 * margin)
        image = QImage(*size, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        painter.translate(margin, margin)
        body = QRectF(0, 0, NODE_W, NODE_H)
        # Linked at both sockets: the orphan mark is on by default and rings the same few
        # pixels, and this is about the ring an agent run wears.
        state = NodeState(ring_phase=phase, ports=(True, True))
        paint_node(painter, QPalette(), body, "T", accent, state)
        painter.end()
        row = int(-RING_GAP) + margin
        columns = range(margin + 20, margin + int(NODE_W) - 20)
        return [image.pixelColor(x, row).alpha() for x in columns]

    assert not any(render(NodeAccent()))
    inked = render(NodeAccent(chip_text="working", chip_tone="info"))
    assert any(inked) and not all(inked)  # Dashes and gaps.
    assert render(NodeAccent(chip_text="working", chip_tone="info"), phase=2.0) != inked
    assert QRectF(0, 0, NODE_W, NODE_H).adjusted(-RING_GAP, 0, 0, 0).left() > -PAINT_MARGIN
