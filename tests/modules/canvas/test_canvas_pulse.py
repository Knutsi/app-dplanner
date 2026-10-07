"""The canvas shows where a person is next: a step ready for review or ready to merge pulses on
the scene's one motion clock. Everything runs through the application the composition root
builds: the canvas never learns what a person's turn is.
"""

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter, QPalette

from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.modules.canvas.layouts.positions import NODE_H, NODE_W
from dplanner.modules.canvas.renderers import (
    PAINT_MARGIN,
    PULSE_PERIOD,
    PULSE_REACH,
    NodeAccent,
    NodeState,
    paint_node,
    pulse_level,
)
from dplanner.planning import agent, status
from dplanner.theme.cards import LIFT


@pytest.fixture
def project(services, make_project):
    """P2 waiting on P1, both agents' steps, and M on its own."""
    library = services.document
    project = make_project("Flow")
    for title in ("P1", "P2", "M"):
        step = Step(title=title)
        AddNodeCommand(project.id, step).redo(library)
        if title != "M":
            SetModuleDataCommand(step.id, agent.MODULE_ID, agent.write_state(True)).redo(library)
    p1, p2 = (by_title(project, t) for t in ("P1", "P2"))
    SetEdgesCommand(p2.id, "requires", [p1.id]).redo(library)
    return project


@pytest.fixture
def tab(services, project):
    return services.tabs.open("project", project.id)


def by_title(project, title):
    return next(step for step in project.steps if step.title == title)


def card(tab, project, title):
    return tab._scene._nodes[by_title(project, title).id]


def set_status(services, project, title, word):
    entry = status.write(status.Status(word), today=services.clock.today())
    step = by_title(project, title)
    SetModuleDataCommand(step.id, status.MODULE_ID, entry).redo(services.document)


# -- the pulse --------------------------------------------------------------------------------


def test_a_step_waiting_on_its_merge_pulses(services, project, tab):
    assert not card(tab, project, "M")._accent.pulse
    set_status(services, project, "M", "ready-to-merge")
    assert card(tab, project, "M")._accent.pulse


def test_work_under_review_pulses_whoever_waits_on_it(services, project, tab):
    """Ready for review is a person's turn, an agent's step or not, and whatever waits on it."""
    set_status(services, project, "P1", "ready-for-review")
    assert card(tab, project, "P1")._accent.pulse
    set_status(services, project, "P1", "done")
    assert not card(tab, project, "P1")._accent.pulse


def test_the_motion_clock_runs_while_a_card_pulses_and_stops_when_nothing_moves(
    services, project, tab
):
    scene = tab._scene
    assert not scene._motion_clock.isActive()
    set_status(services, project, "M", "ready-to-merge")
    assert card(tab, project, "M").moves() and scene._motion_clock.isActive()
    before = card(tab, project, "M")._phase
    scene.advance_motion()
    assert card(tab, project, "M")._phase != before
    set_status(services, project, "M", "done")
    assert not scene._motion_clock.isActive()


def test_the_pulse_breathes_in_the_key_tone_within_the_card_s_margin(app):
    """Nothing at rest, the glow at the height of a breath; one breath divides the phase's
    wrap, so it never jumps; and its reach is inside PAINT_MARGIN, lifted or not."""
    assert pulse_level(0.0) == pytest.approx(0.0)
    assert pulse_level(PULSE_PERIOD / 2) == pytest.approx(1.0)
    assert pulse_level(1000.0) == pytest.approx(pulse_level(0.0))
    assert PULSE_REACH + LIFT < PAINT_MARGIN

    def glow(accent, phase):
        margin = int(PAINT_MARGIN)
        image = QImage(
            int(NODE_W) + 2 * margin, int(NODE_H) + 2 * margin, QImage.Format.Format_ARGB32
        )
        image.fill(0)
        painter = QPainter(image)
        painter.translate(margin, margin)
        state = NodeState(phase=phase, ports=(True, True))
        paint_node(painter, QPalette(), QRectF(0, 0, NODE_W, NODE_H), "T", accent, state)
        painter.end()
        return image.pixelColor(margin + int(NODE_W / 2), margin - 2)  # Just above the body.

    merging = NodeAccent(key_tone="good", pulse=True)
    assert glow(merging, 0.0).alpha() == 0
    lit = glow(merging, PULSE_PERIOD / 2)
    assert lit.alpha() > 0 and lit.green() > lit.red()  # The good green.
    assert glow(NodeAccent(key_tone="good"), PULSE_PERIOD / 2).alpha() == 0
