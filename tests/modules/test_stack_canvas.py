"""A stack on the canvas: its frame and "+", moving it, linking to it, and its verbs.

Driven the way a mouse drives it — real events on the viewport, through the helpers in
``test_project_editor`` — because every gesture here is a press whose meaning depends on what
is under it, and a signal-level test cannot tell a frame from the card over it.
"""

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from tests.modules.test_project_editor import (
    body_of,
    click,
    drag,
    labels,
    offered,
    placement_of,
    press_key,
    scene,
    send,
    silence_details,
    view,
)

from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.framework.context import (
    SCOPE_ACTIVITY,
    SCOPE_SELECTION,
    Context,
    ContextNode,
    selection_uri,
)
from dplanner.modules.project_editor.positions import GRID, centred_on, read_stack, write_member
from dplanner.modules.project_editor.stacks import FRAME_PAD, MEMBER_GAP, read_stacks, stack_of
from dplanner.theme.cards import DIM_OPACITY

TITLES = ("Plan", "Parse head", "Parse body", "Parse tail", "Ship", "Loose")


@pytest.fixture
def plan(services, make_project):
    """Plan → [Parse head, Parse body, Parse tail] → Ship, the three in the middle stacked,
    and a loose step beside — nobody having placed any of it."""
    library = services.document
    project = make_project("Importer")
    steps = []
    for title in TITLES:
        step = Step(title=title)
        AddNodeCommand(project.id, step).redo(library)
        steps.append(step)
    for waiter, source in zip(steps[1:5], steps[:4], strict=True):
        SetEdgesCommand(waiter.id, "requires", [source.id]).redo(library)
    for member in steps[1:4]:
        SetModuleDataCommand(member.id, "project_editor", write_member("s1")).redo(library)
    return project


@pytest.fixture
def tab(services, plan):
    return services.tabs.open("project", plan.id)


def ids(plan):
    return [step.id for step in plan.steps]


def frame_of(tab):
    (frame,) = scene(tab)._frames.values()
    return frame


def pad(tab):
    """A point on the frame's pad, left of its column: the stack, and no card."""
    rect = frame_of(tab).frame_scene_rect()
    return QPointF(rect.left() + FRAME_PAD / 2, rect.center().y())


def plus(tab):
    return frame_of(tab).add.scenePos()


def requires(services, step_id):
    return services.document.step(step_id).edges.get("requires", [])


def picked(tab):
    return list(scene(tab).selection().steps)


def undo_text(services):
    return services.undo.undo_text()


# -- drawing -----------------------------------------------------------------------------------


def test_the_frame_stands_round_the_column_and_the_chain_runs_down_its_middle(tab, plan):
    _plan, head, body, tail, ship, _loose = ids(plan)
    frame = frame_of(tab).frame_scene_rect()
    column = body_of(tab, head).united(body_of(tab, tail))
    assert frame == column.adjusted(-FRAME_PAD, -FRAME_PAD, FRAME_PAD, FRAME_PAD)

    # The chain's own links are arrows still — drawn short and straight, card to card.
    link = scene(tab)._edges[next(r for r in scene(tab)._edges if r.waiter == body)]
    path = link.path()
    start, end = path.pointAtPercent(0.0), path.pointAtPercent(1.0)
    assert start.x() == end.x() == frame.center().x()
    assert (start.y(), end.y()) == (body_of(tab, head).bottom(), body_of(tab, body).top())

    # The way in arrives at the first card's side, and the way out leaves the last card's,
    # as into and out of any card; the "+" sits in the frame's bottom edge.
    into = next(e for r, e in scene(tab)._edges.items() if r.waiter == head)
    first = body_of(tab, head)
    assert into.path().pointAtPercent(1.0) == QPointF(first.left(), first.center().y())
    out = next(e for r, e in scene(tab)._edges.items() if r.waiter == ship)
    last = body_of(tab, tail)
    assert out.path().pointAtPercent(0.0) == QPointF(last.right(), last.center().y())
    assert plus(tab) == QPointF(frame.center().x(), frame.bottom())


def test_only_the_last_card_of_a_stack_has_a_handle(tab, plan):
    _plan, head, body, tail, *_rest = ids(plan)
    nodes = scene(tab)._nodes
    assert [nodes[s].has_handle() for s in (head, body, tail)] == [False, False, True]
    assert not nodes[head].is_over_handle(nodes[head].handle_scene_pos())


def test_a_broken_stack_draws_its_gap(services, tab, plan):
    _plan, head, body, *_rest = ids(plan)
    services.document.set_edges(body, "requires", [], rules=False)  # Another writer's edit.
    assert frame_of(tab).stack.gaps == ((head, body),)


def test_the_spotlight_fades_a_frame_none_of_whose_cards_is_lit(services, tab, plan):
    *_rest, loose = ids(plan)
    scene(tab).set_spotlight(True)
    scene(tab).select_step(loose)
    assert frame_of(tab).opacity() == DIM_OPACITY
    scene(tab).select_step(ids(plan)[2])
    assert frame_of(tab).opacity() == 1.0


# -- moving ------------------------------------------------------------------------------------


def test_dragging_the_frame_moves_the_stack_as_one_undo(app, services, tab, plan):
    _plan, head, body, tail, *_rest = ids(plan)
    was = {s: body_of(tab, s).topLeft() for s in (head, body, tail)}
    drag(app, tab, pad(tab), pad(tab) + QPointF(160.0, 80.0))

    assert undo_text(services) == "Move Stack"
    for step_id in (head, body, tail):
        assert body_of(tab, step_id).topLeft() == was[step_id] + QPointF(160.0, 80.0)
    seat = placement_of(services, head)
    assert (seat["x"], seat["y"]) == (was[head].x() + 160.0, was[head].y() + 80.0)
    assert "x" not in placement_of(services, body)

    services.undo.undo()
    assert {s: body_of(tab, s).topLeft() for s in (head, body, tail)} == was


def test_a_drag_on_any_card_in_a_stack_moves_the_whole_stack(app, services, tab, plan):
    _plan, head, body, tail, *_rest = ids(plan)
    was = body_of(tab, head).topLeft()
    grip = body_of(tab, body).center()
    drag(app, tab, grip, grip + QPointF(80.0, 0.0))
    assert undo_text(services) == "Move Stack"
    assert body_of(tab, head).topLeft() == was + QPointF(80.0, 0.0)
    assert body_of(tab, tail).left() == was.x() + 80.0


def test_a_click_on_a_card_picks_it_and_a_click_on_the_frame_picks_the_stack(app, tab, plan):
    _plan, head, body, tail, *_rest = ids(plan)
    click(app, tab, body_of(tab, body).center())
    assert picked(tab) == [body]
    click(app, tab, pad(tab))
    assert picked(tab) == [head, body, tail]


def test_escape_mid_drag_puts_the_stack_back(app, services, tab, plan):
    head = ids(plan)[1]
    was = body_of(tab, head).topLeft()
    depth = services.undo.undo_text()
    send(app, tab, QEvent.Type.MouseButtonPress, pad(tab))
    send(app, tab, QEvent.Type.MouseMove, pad(tab) + QPointF(120.0, 0.0))
    assert body_of(tab, head).topLeft() == was + QPointF(120.0, 0.0)
    press_key(app, tab, Qt.Key.Key_Escape)
    assert body_of(tab, head).topLeft() == was
    assert services.undo.undo_text() == depth


def test_a_pick_with_a_stack_in_it_moves_the_stack_whole_beside_a_loose_card(
    app, services, tab, plan
):
    first, head, body, *_rest = ids(plan)
    scene(tab).select_steps([first, body])
    was = {s: body_of(tab, s).topLeft() for s in (first, head)}
    grip = body_of(tab, first).center()
    drag(app, tab, grip, grip + QPointF(0.0, 160.0))
    assert undo_text(services) == "Move Steps"
    for step_id in (first, head):
        assert body_of(tab, step_id).topLeft() == was[step_id] + QPointF(0.0, 160.0)


def test_a_stacked_card_grows_right_and_down_and_its_column_makes_room(app, services, tab, plan):
    _plan, head, body, *_rest = ids(plan)
    card = body_of(tab, head)
    node = scene(tab)._nodes[head]
    assert node.edge_at(QPointF(card.left() + 2.0, card.center().y())) == ""
    assert node.edge_at(QPointF(card.center().x(), card.top() + 2.0)) == ""
    grip = QPointF(card.center().x(), card.bottom() - 2.0)
    assert node.edge_at(grip) == "bottom"

    below = body_of(tab, body).top()
    send(app, tab, QEvent.Type.MouseButtonPress, grip)
    send(app, tab, QEvent.Type.MouseMove, grip + QPointF(0.0, 40.0))
    # The column re-lays under the grown card as it grows, a member's gap below it.
    grown = body_of(tab, body).top()
    assert grown > below
    assert MEMBER_GAP <= grown - body_of(tab, head).bottom() < MEMBER_GAP + GRID
    send(
        app, tab, QEvent.Type.MouseButtonRelease, grip + QPointF(0.0, 40.0), Qt.MouseButton.NoButton
    )
    assert undo_text(services) == "Resize Step"
    assert body_of(tab, body).top() == grown


def test_a_double_click_on_the_frame_makes_no_step(app, tab, plan, monkeypatch):
    opened = silence_details(monkeypatch)
    count = len(plan.steps)
    send(app, tab, QEvent.Type.MouseButtonDblClick, pad(tab))
    assert len(plan.steps) == count and opened == []


# -- linking -----------------------------------------------------------------------------------


def test_a_link_dropped_anywhere_on_a_stack_waits_through_its_first_card(app, services, tab, plan):
    _plan, head, body, *_rest, loose = ids(plan)
    handle = scene(tab)._nodes[loose].handle_scene_pos()
    drag(app, tab, handle, body_of(tab, body).center())
    assert loose in requires(services, head)
    assert loose not in requires(services, body)

    services.undo.undo()
    drag(app, tab, scene(tab)._nodes[loose].handle_scene_pos(), pad(tab))
    assert loose in requires(services, head)


def test_connect_from_a_picked_stack_links_from_its_last_card(app, services, tab, plan):
    *_rest, tail, _ship, loose = ids(plan)
    click(app, tab, pad(tab))
    services.actions.run("steps.connect", services.context.current())
    click(app, tab, body_of(tab, loose).center())
    assert requires(services, loose) == [tail]


# -- the "+" and the verbs ---------------------------------------------------------------------


def test_the_plus_adds_a_step_below_the_last_and_opens_its_details(
    app, services, tab, plan, monkeypatch
):
    opened = silence_details(monkeypatch)
    _plan, head, body, tail, ship, _loose = ids(plan)
    click(app, tab, plus(tab))

    (stack,) = read_stacks(plan.steps)
    added = stack.members[-1]
    assert stack.members[:3] == (head, body, tail)
    assert requires(services, added) == [tail]
    assert requires(services, ship) == [added]
    assert [dialog.panel.current_step_id() for dialog in opened] == [added]
    services.undo.undo()
    assert read_stacks(plan.steps)[0].members == (head, body, tail)
    assert requires(services, ship) == [tail]


def test_new_stack_lands_where_the_canvas_was_clicked_and_opens_its_details(
    services, tab, plan, monkeypatch
):
    opened = silence_details(monkeypatch)
    view(tab).note_click(QPointF(1600.0, 400.0))
    services.actions.run("stacks.new", services.context.current())
    born = plan.steps[-1]
    assert read_stack(born)
    seat = placement_of(services, born.id)
    assert (seat["x"], seat["y"]) == tab._snapped(*centred_on(1600.0, 400.0))
    assert undo_text(services) == "New Stack"
    assert [dialog.panel.current_step_id() for dialog in opened] == [born.id]


def test_new_stack_with_no_click_lands_where_nothing_is(services, tab, plan, monkeypatch):
    silence_details(monkeypatch)
    services.actions.run("stacks.new", services.context.current())
    frames = [frame.frame_scene_rect() for frame in scene(tab)._frames.values()]
    born = scene(tab)._frames[read_stack(plan.steps[-1])].frame_scene_rect()
    for node in scene(tab)._nodes.values():
        if node.step_id != plan.steps[-1].id:
            assert not born.intersects(node.body_scene_rect())
    assert all(not born.intersects(other) for other in frames if other != born)


def run_on(services, tab, action_id, *step_ids):
    """Run a verb on these steps, as a menu over that pick would."""
    context = Context(
        {
            SCOPE_ACTIVITY: tab.activity_nodes(),
            SCOPE_SELECTION: tuple(ContextNode(selection_uri("step", s)) for s in step_ids),
        }
    )
    state = services.actions.spec(action_id).state(context)
    if state.enabled:
        services.actions.run(action_id, context)
    return state


def test_make_stack_links_steps_that_are_not_a_line_as_one_undo(services, tab, plan):
    first, *_rest, loose = ids(plan)
    run_on(services, tab, "stacks.make", first, loose)
    made = stack_of(plan.steps, loose)
    assert made is not None and set(made.members) == {first, loose}
    assert requires(services, made.members[1]) == [made.members[0]]
    assert undo_text(services) == "Make Stack"
    services.undo.undo()
    assert not read_stack(services.document.step(loose)) and not requires(services, loose)


def test_make_stack_is_greyed_for_steps_with_one_left_out_between(services, tab, plan):
    first, *_rest, ship, _loose = ids(plan)
    state = run_on(services, tab, "stacks.make", first, ship)
    assert not state.enabled and "'Parse tail' comes between" in (state.label or "")


def test_a_pick_with_arrows_in_it_offers_make_stack_and_stacks_its_steps(tab, plan):
    """A drag across steps picks their arrows too; stacking them is still one click."""
    first, *_rest, loose = ids(plan)
    scene(tab).select_steps([first, loose])
    next(iter(scene(tab)._edges.values())).setSelected(True)
    menu = tab.context_menu(view(tab).mapFromScene(body_of(tab, first).center()))
    (make,) = [a for a in menu.actions() if a.text().replace("&", "") == "Make Stack"]
    assert make.isEnabled()
    make.trigger()
    menu.deleteLater()
    made = stack_of(plan.steps, loose)
    assert made is not None and set(made.members) == {first, loose}


def test_take_out_leaves_the_step_beside_the_stack_with_no_links(services, tab, plan):
    _plan, head, body, tail, *_rest = ids(plan)
    right = frame_of(tab).frame_scene_rect().right()
    run_on(services, tab, "stacks.take_out", body)
    step = services.document.step(body)
    assert not read_stack(step) and not requires(services, body)
    assert requires(services, tail) == [head]
    assert placement_of(services, body)["x"] > right
    assert undo_text(services) == "Take Out of Stack"


def test_dissolve_lays_the_stack_out_as_a_row(services, tab, plan):
    _plan, head, body, tail, *_rest = ids(plan)
    run_on(services, tab, "stacks.dissolve", body)
    assert not scene(tab)._frames
    assert body_of(tab, head).top() == body_of(tab, body).top() == body_of(tab, tail).top()
    assert requires(services, body) == [head]
    assert undo_text(services) == "Dissolve Stack"


def test_a_broken_stack_greys_its_edits_with_the_reason_but_still_dissolves(services, tab, plan):
    _plan, _head, body, tail, *_rest = ids(plan)
    services.document.set_edges(body, "requires", [], rules=False)
    for action_id in ("stacks.add_below", "stacks.take_out"):
        state = run_on(services, tab, action_id, tail)
        assert not state.enabled and "not one line" in (state.label or "")
    assert run_on(services, tab, "stacks.dissolve", tail).enabled


# -- menus and the strip -----------------------------------------------------------------------


def test_right_clicking_the_frame_picks_the_stack_and_leads_with_its_band(tab, plan):
    _plan, head, body, tail, *_rest = ids(plan)
    rendered = offered(tab, pad(tab))
    assert picked(tab) == [head, body, tail]
    assert rendered[:3] == ["Add Step Below", "Take Out of Stack", "Dissolve Stack"]
    assert ("Step" in labels(rendered)) and "Make Stack" not in labels(rendered)


def test_a_card_in_a_stack_offers_the_stack_child(tab, plan):
    rendered = offered(tab, body_of(tab, ids(plan)[2]).center())
    (child,) = [entry for entry in rendered if isinstance(entry, tuple) and entry[0] == "Stack"]
    offers = [label.split(" — ")[0] for label in child[1] if label != "|"]
    assert offers == ["Make Stack", "Add Step Below", "Take Out of Stack", "Dissolve Stack"]


def test_the_strip_offers_new_stack_and_make_stack(tab, plan):
    for action_id in ("stacks.new", "stacks.make"):
        assert tab._toolbar.button(action_id) is not None
