"""A step with a playbook pass shows where it stands in a strip under its card: the words come
from the pass's records on disk (``passes.standing``), polled by the playbook module, and the
card's foot grows down to make room on the scene's motion clock — at once with Reduce Motion
on, and for a card a tab opens with. Everything runs through the application the composition
root builds; the canvas never learns what a pass is."""

from dataclasses import replace

import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPalette
from tests.modules.step_playbook.test_passes import run, settings

from dplanner.domain import ledger
from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.modules.canvas.items import GROW_S
from dplanner.modules.canvas.layouts.positions import NODE_H, NODE_W, STRIP_H
from dplanner.modules.canvas.renderers import (
    PAINT_MARGIN,
    NodeAccent,
    NodeState,
    paint_node,
)
from dplanner.modules.canvas.scene import MOTION_TICK_MS

REVIEWED = "plan-execute-review-other"


def standings(services):
    return next(m for m in services.modules if m.id == "step_playbook")._deps.standings


@pytest.fixture
def project(services, make_project):
    project = make_project("Flow")
    for title in ("Build it", "Elsewhere"):
        AddNodeCommand(project.id, Step(title=title)).redo(services.document)
    return project


@pytest.fixture
def tab(services, project):
    return services.tabs.open("project", project.id)


def write_pass(services, project, *records):
    """The records of a pass on the project's first step, the first pinning its settings."""
    step = project.steps[0]
    directory = services.repo.project_dir(project.id)
    first, *rest = records
    for record in (replace(first, settings=settings(REVIEWED).to_json()), *rest):
        ledger.write(directory, replace(record, project=project.id, step=step.id))
    standings(services).refresh()


def card(tab, project, index=0):
    return tab._scene._nodes[project.steps[index].id]


def parked():
    """A pass whose run waits on its usage: its strip shows, and nothing is at work."""
    return run("plan", end="limit", over=False)


def settle(scene, seconds=GROW_S + 0.05):
    """Run the motion clock by hand for ``seconds``, a display frame at a time."""
    for _ in range(int(seconds / 0.016) + 1):
        scene.advance_motion(0.016)


def test_a_pass_under_way_names_where_it_stands_under_the_card(services, project, tab):
    write_pass(services, project, run("plan"), run("execute", end="", over=False))
    phrase, tone, tip = card(tab, project)._accent.playbook
    assert (phrase, tone) == ("Executing", "busy")
    assert "▸ execute" in tip.splitlines()
    assert card(tab, project, 1)._accent.playbook == ("", "", "")


def test_a_live_headless_turn_rings_the_card_like_a_running_agent(services, project, tab):
    """The ring a terminal run wears, from the pass's records: while a turn is under way, and
    no longer once it parks — the strip still says where the pass stands."""
    node, scene = card(tab, project), tab._scene
    write_pass(services, project, run("plan"), run("execute", end="", over=False))
    assert node._accent.ring == "info" and node.wears_ring()
    assert scene._motion_clock.isActive()
    assert not card(tab, project, 1).wears_ring()

    write_pass(services, project, run("plan"), run("execute", end="limit", over=False))
    assert node._accent.playbook[0] and not node.wears_ring()
    settle(scene)
    assert not scene._motion_clock.isActive()


def test_the_cards_foot_grows_down_to_the_strip_and_the_body_stays(services, project, tab):
    node, scene = card(tab, project), tab._scene
    write_pass(services, project, parked())
    # It begins where it was: the strip grows, it does not jump.
    assert node.size() == (NODE_W, NODE_H) and node.growing()
    assert scene._motion_clock.isActive()
    scene.advance_motion(0.016)
    assert NODE_H < node.size()[1] < NODE_H + STRIP_H
    settle(scene)
    assert node.size() == (NODE_W, NODE_H + STRIP_H) and not node.growing()
    # What the step stores, where the arrows meet, is the body: the strip is the pass's.
    assert node.body_size() == (NODE_W, NODE_H) and node.footprint() == (NODE_W, NODE_H)
    assert node._middle_y() == NODE_H / 2
    assert not scene._motion_clock.isActive()


def test_the_strip_folds_back_when_the_pass_is_no_longer_shown(services, project, tab):
    node, scene = card(tab, project), tab._scene
    write_pass(services, project, run("plan", end="", over=False))
    settle(scene)
    directory = services.repo.project_dir(project.id)
    for record in ledger.records(directory):
        ledger.path_for(directory, record).unlink()
    standings(services).refresh()
    assert node._accent.playbook == ("", "", "") and node.growing()
    settle(scene)
    assert node.size() == (NODE_W, NODE_H)


def test_the_clock_ticks_at_the_display_rate_only_while_a_strip_grows(services, project, tab):
    scene = tab._scene
    write_pass(services, project, parked())
    assert scene._motion_clock.interval() < MOTION_TICK_MS
    settle(scene)
    assert not scene._motion_clock.isActive()


def test_reduce_motion_shows_the_strip_at_once(services, project, tab):
    services.actions.run("canvas.reduce_motion", services.context.current())
    assert tab._scene.motion_reduced
    write_pass(services, project, parked())
    assert card(tab, project).size() == (NODE_W, NODE_H + STRIP_H)
    assert not tab._scene._motion_clock.isActive()


def test_a_tab_opened_on_a_pass_shows_its_strip_without_growing(services, project):
    write_pass(services, project, run("plan", end="", over=False))
    tab = services.tabs.open("project", project.id)
    node = card(tab, project)
    assert node.size() == (NODE_W, NODE_H + STRIP_H) and not node.growing()


def test_the_stages_are_the_tooltip_over_the_strip_alone(services, project, tab):
    write_pass(services, project, run("plan", end="", over=False))
    node = card(tab, project)
    settle(tab._scene)
    on_strip = node.mapToScene(QPointF(NODE_W / 2, NODE_H + STRIP_H / 2))
    on_body = node.mapToScene(QPointF(NODE_W / 2, NODE_H / 2))
    assert node.playbook_tip_at(on_strip).startswith("Planning · ")
    assert node.playbook_tip_at(on_body) == ""


def test_the_playbook_strip_stands_under_the_branch_strip(qapp):
    """Painted order, read off the pixels: the branch's lane colour over the pass's tone."""
    lane = "#d040d0"
    accent = NodeAccent(strip="feature/x", strip_tone=lane, playbook=("Review 1/2", "busy", ""))
    image = QImage(int(NODE_W + 2 * PAINT_MARGIN), 400, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    painter = QPainter(image)
    painter.translate(PAINT_MARGIN, PAINT_MARGIN)
    card_rect = QRectF(0, 0, NODE_W, NODE_H + 2 * STRIP_H)
    paint_node(painter, QPalette(), card_rect, "T", accent, NodeState(grow=1.0))
    painter.end()
    x = int(PAINT_MARGIN + NODE_W - 6)
    branch = image.pixelColor(x, int(PAINT_MARGIN + NODE_H + STRIP_H / 2))
    pass_band = image.pixelColor(x, int(PAINT_MARGIN + NODE_H + STRIP_H * 1.5))
    assert branch.red() > branch.green() and branch.blue() > branch.green()  # The lane.
    assert pass_band.blue() > pass_band.red()  # Busy blue.


def test_a_click_on_the_strip_picks_the_card_and_opens_its_pass_in_step_details(
    qapp, services, project, tab, monkeypatch
):
    from PySide6.QtCore import QEvent
    from tests.modules.canvas.test_canvas import send

    ran: list[tuple[str, object]] = []
    monkeypatch.setattr(
        tab, "run_action", lambda action, context=None: ran.append((action, context))
    )

    write_pass(services, project, run("plan", end="", over=False))
    node = card(tab, project)
    settle(tab._scene)
    tab.widget.resize(800, 600)
    tab._view.centerOn(node)
    asked: list[str] = []
    tab._scene.playbook_opened.connect(asked.append)
    at = node.mapToScene(QPointF(NODE_W / 2, NODE_H + STRIP_H / 2 - 2))
    send(qapp, tab, QEvent.Type.MouseButtonPress, at)
    send(qapp, tab, QEvent.Type.MouseButtonRelease, at, buttons=Qt.MouseButton.NoButton)
    assert asked == [node.step_id]
    assert node.isSelected()
    qapp.processEvents()  # The dialog opens a turn later, never inside the release.
    [(action, context)] = ran
    assert action == "steps.details"
    assert context.selected_entity("step") == node.step_id
    assert context.selected_entity("playbook") == node.step_id
    # Let go off the strip, and nothing is asked for — nor does the card move.
    seat = node.pos()
    away = node.mapToScene(QPointF(NODE_W / 2, -40))
    send(qapp, tab, QEvent.Type.MouseButtonPress, at)
    send(qapp, tab, QEvent.Type.MouseMove, away)
    send(qapp, tab, QEvent.Type.MouseButtonRelease, away, buttons=Qt.MouseButton.NoButton)
    assert asked == [node.step_id]
    assert node.pos() == seat
