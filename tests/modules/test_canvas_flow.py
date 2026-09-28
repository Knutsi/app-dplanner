"""The canvas shows the flow: where work moves on its own, and where a person is next.

A link into a review wears the review's talk bubble at its middle; an auto-progress link is
doubled and nothing more; a plain link is plain. A step a person moves next — ready to
merge, or ready for review with no live agent to take it — pulses on the scene's one
motion clock. Everything runs through the application the composition root builds: the
canvas never learns what a review or a person's turn is.
"""

import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QImage, QPainter, QPalette

from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.modules.auto_progress import aspect as auto_progress
from dplanner.modules.project_editor import positions
from dplanner.modules.project_editor.items import MEDALLION_R
from dplanner.modules.project_editor.positions import NODE_H, NODE_W
from dplanner.modules.project_editor.renderers import (
    PAINT_MARGIN,
    PULSE_PERIOD,
    PULSE_REACH,
    EdgeAccent,
    NodeAccent,
    NodeState,
    paint_node,
    pulse_level,
)
from dplanner.modules.project_editor.selection import EdgeRef
from dplanner.modules.step_agent_instruction import aspect as agent
from dplanner.modules.step_review import aspect as review
from dplanner.modules.step_status import aspect as status
from dplanner.theme.cards import LIFT


@pytest.fixture
def project(services, make_project):
    """W, reviewed by R; A1 collected by C over an auto-progress link; P2 waiting on P1 over a
    plain one; and M on its own. Every step but P2 and M is an agent's."""
    library = services.document
    project = make_project("Flow")
    for title in ("W", "R", "A1", "C", "P1", "P2", "M"):
        step = Step(title=title)
        AddNodeCommand(project.id, step).redo(library)
        if title not in ("P2", "M"):
            SetModuleDataCommand(step.id, agent.MODULE_ID, agent.write_state(True)).redo(library)
    w, r, a1, c, p1, p2 = (by_title(project, t) for t in ("W", "R", "A1", "C", "P1", "P2"))
    SetModuleDataCommand(r.id, review.MODULE_ID, review.write(review.ReviewSettings())).redo(
        library
    )
    SetEdgesCommand(r.id, "requires", [w.id]).redo(library)
    SetEdgesCommand(c.id, "requires", [a1.id]).redo(library)
    SetModuleDataCommand(c.id, auto_progress.MODULE_ID, auto_progress.write([a1.id])).redo(library)
    SetEdgesCommand(p2.id, "requires", [p1.id]).redo(library)
    return project


@pytest.fixture
def tab(services, project):
    return services.tabs.open("project", project.id)


def by_title(project, title):
    return next(step for step in project.steps if step.title == title)


def arrow(tab, project, waiter, source):
    ref = EdgeRef(by_title(project, waiter).id, "requires", by_title(project, source).id)
    return tab._scene._edges[ref]


def card(tab, project, title):
    return tab._scene._nodes[by_title(project, title).id]


def set_status(services, project, title, word):
    entry = status.write(word, today=services.clock.today())
    step = by_title(project, title)
    SetModuleDataCommand(step.id, status.MODULE_ID, entry).redo(services.document)


# -- the arrows -------------------------------------------------------------------------------


def test_a_link_into_a_review_wears_the_talk_bubble_and_the_others_do_not(project, tab):
    assert arrow(tab, project, "R", "W").accent() == EdgeAccent(doubled=True, medallion="review")
    assert arrow(tab, project, "C", "A1").accent() == EdgeAccent(doubled=True)
    assert arrow(tab, project, "P2", "P1").accent() == EdgeAccent()


def test_the_bubble_sits_at_the_middle_inside_what_the_arrow_is_hit_by(project, tab):
    edge = arrow(tab, project, "R", "W")
    centre = edge.medallion_centre()
    assert centre is not None
    halfway = edge.path().pointAtPercent(0.5)  # Qt's own answer, by length.
    assert (centre - halfway).manhattanLength() < 2.0
    disc = QRectF(
        centre.x() - MEDALLION_R, centre.y() - MEDALLION_R, 2 * MEDALLION_R, 2 * MEDALLION_R
    )
    assert edge.boundingRect().contains(disc)
    shape = edge.shape()
    assert shape.contains(centre + QPointF(0.0, MEDALLION_R - 1.0))  # Past the line's grab.
    assert arrow(tab, project, "P2", "P1").medallion_centre() is None


def test_the_chevrons_keep_clear_of_the_bubble(project, tab):
    """A chevron under the bubble would show through its rim; they stop short either side
    and pass behind it."""
    edge = arrow(tab, project, "R", "W")
    centre = edge.medallion_centre()
    chevrons = edge._chevrons
    points = [
        QPointF(chevrons.elementAt(i).x, chevrons.elementAt(i).y)
        for i in range(chevrons.elementCount())
    ]
    assert points
    assert all((point - centre).manhattanLength() > MEDALLION_R for point in points)


def test_an_arrow_too_short_for_the_bubble_wears_none(services, project, tab):
    """A stack's own link runs a card's gap long: a bubble there would sit on both cards."""
    w, r = by_title(project, "W"), by_title(project, "R")
    for step in (w, r):
        entry = positions.write_member("reviewed")
        SetModuleDataCommand(step.id, positions.MODULE_ID, entry).redo(services.document)
    edge = arrow(tab, project, "R", "W")
    assert edge.accent().medallion == "review"
    assert edge.medallion_centre() is None


# -- the pulse --------------------------------------------------------------------------------


def test_a_step_waiting_on_its_merge_pulses(services, project, tab):
    assert not card(tab, project, "M")._accent.pulse
    set_status(services, project, "M", "ready-to-merge")
    assert card(tab, project, "M")._accent.pulse


def test_work_under_review_pulses_only_while_no_live_agent_takes_it(services, project, tab):
    """W's review and A1's collector are agents: their turn, so nothing pulses. P1 reaches P2
    over a plain link — a person looks next — and A1 is a person's again once its collector
    is blocked or done."""
    for title in ("W", "A1", "P1"):
        set_status(services, project, title, "ready-for-review")
    assert not card(tab, project, "W")._accent.pulse
    assert not card(tab, project, "A1")._accent.pulse
    assert card(tab, project, "P1")._accent.pulse
    for word in ("blocked", "done"):
        set_status(services, project, "C", word)
        assert card(tab, project, "A1")._accent.pulse
    set_status(services, project, "C", "in-progress")
    assert not card(tab, project, "A1")._accent.pulse


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
