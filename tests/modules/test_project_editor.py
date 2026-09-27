"""A project open in a tab: the canvas, the panels it steers, and the gestures between them.

The canvas is exercised through the scene's signals rather than through synthetic mouse
events: what matters is that a gesture becomes the right command on the undo stack, and a
QTest.mousePress would test Qt rather than this module.

The detail panels are the window's, not the tab's, so they are reached through the window —
which is the point: however many projects are open, there is one of each.
"""

from dataclasses import replace
from datetime import date

import pytest
from PySide6.QtCore import QEvent, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QKeyEvent, QMouseEvent, QPainter

from dplanner.domain.commands import (
    AddNodeCommand,
    RemoveNodeCommand,
    SetEdgesCommand,
    SetFieldCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION
from dplanner.modules.project_editor.modes import (
    CONNECT,
    CONTRACT_HORIZONTAL,
    CONTRACT_VERTICAL,
    DIVIDE_HORIZONTAL,
    DIVIDE_VERTICAL,
    IDLE,
    LASSO,
    PAN,
    REDIRECT_FROM,
    REDIRECT_TO,
)
from dplanner.modules.project_editor.positions import GRID, NODE_H, NODE_W, snapped, write_member
from dplanner.modules.project_editor.renderers import (
    BADGE_INSET,
    ICON_D,
    ICON_GAP,
    LEFT_INSET,
    PAINT_MARGIN,
    medallion_end,
)
from dplanner.modules.project_editor.selection import EDGE_KIND, EdgeRef
from dplanner.theme import apply_theme
from dplanner.theme.cards import FILL_ALPHA, LIFT
from dplanner.theme.themes import DARK, LIGHT


@pytest.fixture
def project(services, make_project):
    library = services.document
    project = make_project("Discovery")
    for title in ("Read the spec", "Draft the model"):
        AddNodeCommand(project.id, Step(title=title)).redo(library)
    return project


@pytest.fixture
def tab(services, project):
    return services.tabs.open("project", project.id)


def published_steps(services):
    """The step ids the active pane published — what every panel and verb reads."""
    return services.context.current().selected_entities("step")


def scene(tab):
    return tab._scene


def view(tab):
    return tab._view


def chain(services, project):
    """A three-step chain, first → second → third, for the cases two steps cannot express."""
    third = Step(title="Ship it")
    services.undo.push(AddNodeCommand(project.id, third))
    first, second = project.steps[0], project.steps[1]
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    services.undo.push(SetEdgesCommand(third.id, "requires", [second.id]))
    return first, second, third


# -- driving the canvas the way a mouse does ---------------------------------------------------
#
# These send real mouse events to the view rather than emitting the scene's signals. The
# difference is not pedantry: every gesture below was once covered by a signal-level test, and
# the link drop was broken the whole time because the bug was in the gesture, not the handler.
# They go to the *view* because that is where the mode stack reads them, and where a real
# mouse arrives — the scene only ever sees what no mode claimed.


RIGHT = Qt.MouseButton.RightButton


def send(
    app,
    tab,
    kind,
    scene_pos,
    buttons=Qt.MouseButton.LeftButton,
    modifiers=Qt.KeyboardModifier.NoModifier,
    button=Qt.MouseButton.LeftButton,
):
    viewport = view(tab).viewport()
    local = QPointF(view(tab).mapFromScene(scene_pos))
    # The global position has to be real: QGraphicsScene picks the item under the *screen*
    # point, so a placeholder here makes every press land on empty canvas.
    event = QMouseEvent(
        kind,
        local,
        QPointF(viewport.mapToGlobal(local.toPoint())),
        button,
        buttons,
        modifiers,
    )
    app.sendEvent(viewport, event)


def press_key(app, tab, key, modifiers=Qt.KeyboardModifier.NoModifier):
    _send_key(app, tab, QEvent.Type.KeyPress, key, modifiers)


def release_key(app, tab, key, modifiers=Qt.KeyboardModifier.NoModifier):
    _send_key(app, tab, QEvent.Type.KeyRelease, key, modifiers)


def _send_key(app, tab, kind, key, modifiers):
    # Straight to the widget rather than through QApplication.sendEvent: Qt routes key events
    # only to the window the platform considers active, and earlier tests leave their windows
    # open, so which one that is depends on what ran before. The mouse helpers above go the
    # whole way; what matters here is GraphView's own dispatch, and this reaches it.
    event = QKeyEvent(kind, key, modifiers)
    view(tab).event(event)


def centre_of(node):
    return node.scenePos() + QPointF(90, 28)


def click(app, tab, scene_pos):
    send(app, tab, QEvent.Type.MouseButtonPress, scene_pos)
    send(app, tab, QEvent.Type.MouseButtonRelease, scene_pos, Qt.MouseButton.NoButton)


def drag(app, tab, start, end):
    """Press at ``start``, move to ``end``, release there."""
    send(app, tab, QEvent.Type.MouseButtonPress, start)
    send(app, tab, QEvent.Type.MouseMove, end)
    send(app, tab, QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.NoButton)


# -- the canvas ------------------------------------------------------------------------------


def test_the_graph_shows_a_node_per_step(services, project, tab):
    assert set(scene(tab)._nodes) == {step.id for step in project.steps}


def test_a_new_step_appears_without_disturbing_the_others(services, project, tab):
    before = scene(tab)._nodes[project.steps[0].id]
    services.undo.push(AddNodeCommand(project.id, Step(title="Ship it")))
    assert len(scene(tab)._nodes) == 3
    # Node items are reconciled, never rebuilt: one under the mouse must keep its identity.
    assert scene(tab)._nodes[project.steps[0].id] is before


def test_a_steps_github_refs_decorate_its_node(services, project, tab):
    """A PR wears a pill, a branch a glyph — supplied through the composition root, so this
    exercises the wiring, not just the seam."""
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.github.aspect import MODULE_ID, GithubRefs, write

    step = project.steps[0]
    refs = GithubRefs(branch="feat/login", pr_number=12, pr_state="merged")
    services.undo.push(SetModuleDataCommand(step.id, MODULE_ID, write(refs)))
    accent = scene(tab)._nodes[step.id]._accent
    assert accent.pill_text == "PR #12"
    assert accent.pill_tone == "good"
    assert accent.branch is True

    services.undo.push(SetModuleDataCommand(step.id, MODULE_ID, {}))
    assert scene(tab)._nodes[step.id]._accent.pill_text == ""


def test_a_branch_alone_is_a_glyph_not_a_pill(services, project, tab):
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.github.aspect import MODULE_ID, GithubRefs, write

    step = project.steps[0]
    services.undo.push(SetModuleDataCommand(step.id, MODULE_ID, write(GithubRefs(branch="b"))))
    accent = scene(tab)._nodes[step.id]._accent
    assert accent.pill_text == "" and accent.branch is True


def test_an_edge_is_drawn_for_a_link(services, project, tab):
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    assert len(scene(tab)._edges) == 1


def test_selecting_a_node_publishes_the_step(services, project, tab):
    """Publishing *is* how every panel and verb learns: the canvas never reaches for one."""
    step = project.steps[0]
    scene(tab).select_step(step.id)
    uris = [node.uri for node in services.context.current().scope(SCOPE_SELECTION)]
    assert uris == [f"app://selection/step/{step.id}"]


def test_only_the_pane_the_user_is_in_publishes(services, project, tab, make_project):
    """Two projects side by side is two canvases, and the window still has exactly one
    selection — the active pane's, which is what lets every panel and verb read one."""
    other = make_project("Build")
    AddNodeCommand(other.id, Step(title="Ship it")).redo(services.document)
    second = services.tabs.open("project", other.id)
    services.tabs.move_current_right()
    assert services.tabs.group_count() == 2

    scene(second).select_step(other.steps[0].id)
    assert published_steps(services) == [other.steps[0].id]

    # The user moves to the other pane. Its activation republishes what it has selected.
    second.on_deactivated()
    tab.on_activated()
    scene(tab).select_step(project.steps[0].id)
    assert published_steps(services) == [project.steps[0].id]

    # And a background pane re-syncing its canvas does not speak over it.
    scene(second).select_step(None)
    assert published_steps(services) == [project.steps[0].id]


# -- the gestures themselves ---------------------------------------------------------------


def test_dragging_from_a_handle_onto_another_node_links_them(app, services, project, tab):
    """The whole point of the canvas. Dragging from A means "A, then B", so B waits on A."""
    first, second = project.steps
    canvas = scene(tab)
    drag(app, tab, canvas._nodes[first.id].handle_scene_pos(), centre_of(canvas._nodes[second.id]))

    assert services.document.step(second.id).edges.get("requires") == [first.id]
    assert len(canvas._edges) == 1


def test_a_drag_that_would_close_a_cycle_creates_nothing(app, services, project, tab):
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    canvas = scene(tab)
    drag(app, tab, canvas._nodes[second.id].handle_scene_pos(), centre_of(canvas._nodes[first.id]))

    assert "requires" not in services.document.step(first.id).edges


def test_dragging_a_node_stores_its_position(app, services, project, tab):
    step = project.steps[0]
    canvas = scene(tab)
    node = canvas._nodes[step.id]
    start = centre_of(node)
    send(app, tab, QEvent.Type.MouseButtonPress, start)
    node.setPos(node.pos() + QPointF(64, 32))
    send(app, tab, QEvent.Type.MouseButtonRelease, start, Qt.MouseButton.NoButton)

    assert services.document.step(step.id).module_data["project_editor"]["x"] == 104.0
    assert services.undo.undo_text() == "Move Step"


def test_double_clicking_empty_space_creates_a_step_there(app, services, project, tab, monkeypatch):
    opened = silence_details(monkeypatch)
    send(app, tab, QEvent.Type.MouseButtonDblClick, QPointF(700, 500))

    assert len(project.steps) == 3
    # And the details dialog opens on it, the name ready to be typed over.
    assert [dialog.panel.current_step_id() for dialog in opened] == [project.steps[-1].id]
    # Centred on the click: 700 - NODE_W / 2, snapped to the grid.
    assert project.steps[-1].module_data["project_editor"]["x"] == 592.0


def test_double_clicking_a_step_opens_its_details(app, services, project, tab, monkeypatch):
    """On a node the gesture selects it and runs the same ``steps.details`` verb every
    other view's double-click runs — and creates nothing."""
    from dplanner.modules.step_properties.dialog import StepDetailsDialog

    shown = []
    monkeypatch.setattr(
        StepDetailsDialog, "exec", lambda self: shown.append(self.panel.current_step_id())
    )
    step = project.steps[0]
    send(app, tab, QEvent.Type.MouseButtonDblClick, centre_of(scene(tab)._nodes[step.id]))

    assert shown == [step.id]
    assert len(project.steps) == 2


# -- gestures become commands -----------------------------------------------------------------


def test_a_drag_is_one_undoable_move(services, project, tab):
    step = project.steps[0]
    scene(tab).nodes_moved.emit([(step.id, 200.0, 120.0)])

    assert services.document.step(step.id).module_data["project_editor"]["x"] == 200.0
    assert services.undo.undo_text() == "Move Step"
    services.undo.undo()
    assert "project_editor" not in services.document.step(step.id).module_data


def test_moving_two_nodes_is_one_undo_step(services, project, tab):
    first, second = project.steps
    scene(tab).nodes_moved.emit([(first.id, 8.0, 8.0), (second.id, 16.0, 16.0)])
    assert services.undo.undo_text() == "Move Steps"
    services.undo.undo()
    assert "project_editor" not in services.document.step(first.id).module_data
    assert "project_editor" not in services.document.step(second.id).module_data


def test_a_drop_runs_the_same_verb_the_menu_does(services, project, tab):
    """The drop is not a special case: it runs `steps.link` against a context naming both
    ends — and leaves the selection as it found it, so the next Connect starts where the
    user was."""
    first, second = project.steps
    tab.select_step(first.id)
    scene(tab).link_requested.emit((first.id,), second.id)

    assert services.document.step(second.id).edges["requires"] == [first.id]
    assert services.context.current().selected_entities("step") == [first.id]
    assert scene(tab).selection().steps == (first.id,)


def test_a_refused_drop_says_why_instead_of_doing_nothing(services, project, tab):
    first, _second, third = chain(services, project)
    # third already waits on first through second; linking first onto third closes the loop.
    scene(tab).link_requested.emit((third.id,), first.id)

    assert "requires" not in services.document.step(first.id).edges
    assert "cycle" in services.window.statusBar().currentMessage()


def test_a_drop_onto_an_already_linked_node_says_so(services, project, tab):
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    scene(tab).link_requested.emit((first.id,), second.id)
    assert services.window.statusBar().currentMessage() == "Already linked"


def test_a_step_whose_list_holds_a_ghost_can_still_be_linked_and_unlinked(
    app, services, project, tab
):
    """The 2026-09-08 fault: a bare removal — what a merge or an outside edit leaves — put a
    ghost id in the waiter's list, and every later write of that list failed "no such step":
    Connect from the canvas, then Unlink on a picked arrow. The model carries what is there."""
    first, second, _third = chain(services, project)
    spare = Step(title="Spare")
    services.undo.push(AddNodeCommand(project.id, spare))
    services.undo.push(RemoveNodeCommand(first.id))
    assert services.document.step(second.id).edges["requires"] == [first.id]

    scene(tab).link_requested.emit((spare.id,), second.id)
    assert services.document.step(second.id).edges["requires"] == [first.id, spare.id]

    edge_item(tab, second, spare).setSelected(True)
    press_key(app, tab, Qt.Key.Key_Delete)
    assert services.document.step(second.id).edges["requires"] == [first.id]


def test_the_selection_keeps_the_order_it_was_made_in(services, project, tab):
    """`Context.selected_entities` promises the selecting view's order, and a two-step verb
    is the reason that promise matters."""
    first, second = project.steps
    scene(tab).select_steps([second.id, first.id])
    assert services.context.current().selected_entities("step") == [second.id, first.id]


def test_creating_on_the_canvas_is_one_undo_step(services, project, tab, monkeypatch):
    """A double-click runs the same creation New does, so it wears the same name — and
    opens the same details dialog, on the step it made."""
    opened = silence_details(monkeypatch)
    scene(tab).create_requested.emit(240.0, 80.0)
    assert len(project.steps) == 3
    assert project.steps[-1].module_data["project_editor"]["x"] == 240.0
    assert services.undo.undo_text() == "New Step"
    assert [dialog.panel.current_step_id() for dialog in opened] == [project.steps[-1].id]
    services.undo.undo()
    assert len(project.steps) == 2


# -- New, and where a new node lands -------------------------------------------------------


def silence_details(monkeypatch):
    """New opens the details dialog on the step it made; collect those instead of
    blocking on a modal. Returns the list the dialogs land in."""
    from dplanner.modules.step_properties.dialog import StepDetailsDialog

    opened = []
    monkeypatch.setattr(StepDetailsDialog, "exec", lambda self: opened.append(self))
    return opened


def test_new_is_one_verb_and_it_opens_the_details_dialog(services, project, tab, monkeypatch):
    """No submenu of kinds and no prompt: a step is born "New step" and the dialog opens
    on it with the name selected, where the aspect bar says what it is."""
    assert not any(spec.submenu == "New" for spec in services.actions.all_specs())
    opened = silence_details(monkeypatch)
    tab._view.note_click(QPointF(400.0, 200.0))  # Placed, so the gesture is one composite.
    services.actions.run("steps.new", services.context.current())
    created = project.steps[-1]
    assert created.title == "New step"
    assert services.undo.undo_text() == "New Step"
    (dialog,) = opened
    assert dialog.panel.current_step_id() == created.id
    assert dialog.name_edit().selectedText() == "New step"
    services.undo.undo()
    assert len(project.steps) == 2


def test_a_new_step_lands_where_the_canvas_was_last_clicked(services, project, tab, monkeypatch):
    tab._view.note_click(QPointF(400.0, 200.0))
    silence_details(monkeypatch)
    services.actions.run("steps.new", services.context.current())
    entry = project.steps[-1].module_data["project_editor"]
    # Centred on the click, then snapped to the grid (Snap to Grid is on by default): the
    # node appears under the cursor rather than with its corner there.
    assert (entry["x"], entry["y"]) == (
        snapped(400.0 - NODE_W / 2, GRID),
        snapped(200.0 - NODE_H / 2, GRID),
    )


def test_a_right_click_counts_as_the_click_new_places_at(services, project, tab, monkeypatch):
    """The menu's own New lands where the menu was raised, not where the mouse last was."""
    tab._view.note_click(QPointF(0.0, 0.0))
    offered(tab, QPointF(560.0, 320.0))
    silence_details(monkeypatch)
    services.actions.run("steps.new", services.context.current())
    entry = project.steps[-1].module_data["project_editor"]
    assert (entry["x"], entry["y"]) == (
        snapped(560.0 - NODE_W / 2, GRID),
        snapped(320.0 - NODE_H / 2, GRID),
    )


def test_a_canvas_nobody_clicked_leaves_the_node_to_the_ambient_layout(
    services, project, tab, monkeypatch
):
    silence_details(monkeypatch)
    services.actions.run("steps.new", services.context.current())
    assert "project_editor" not in project.steps[-1].module_data


def test_a_new_step_is_selected_the_moment_it_exists(services, project, tab, monkeypatch):
    """New leaves you on what you just made: the details dialog it opens is already on it,
    so naming a step and describing it are one gesture rather than two."""
    silence_details(monkeypatch)
    services.actions.run("steps.new", services.context.current())
    created = project.steps[-1]
    assert list(scene(tab).selection().steps) == [created.id]
    assert published_steps(services) == [created.id]


def test_two_new_steps_in_a_row_do_not_land_on_one_another(services, project, tab, monkeypatch):
    """The remembered point steps one row on after it is used, so pressing New twice leaves
    two nodes where a stale point would have hidden one under the other."""
    from dplanner.modules.project_editor.sorts import V_GAP

    tab._view.note_click(QPointF(400.0, 200.0))
    silence_details(monkeypatch)
    services.actions.run("steps.new", services.context.current())
    services.actions.run("steps.new", services.context.current())

    first, second = (step.module_data["project_editor"] for step in project.steps[-2:])
    assert (second["x"], second["y"]) == (first["x"], snapped(first["y"] + NODE_H + V_GAP, GRID))


def test_a_double_click_moves_the_point_on_too(app, services, project, tab, monkeypatch):
    """It pointed at a spot in the same sense a right-click did, so New after it lands
    below what the double-click made rather than on top of it."""
    tab._view.note_click(QPointF(400.0, 200.0))  # The press a double-click begins with.
    silence_details(monkeypatch)
    scene(tab).create_requested.emit(400.0, 200.0)
    services.actions.run("steps.new", services.context.current())
    made, after = (step.module_data["project_editor"] for step in project.steps[-2:])
    assert after["y"] > made["y"]


def test_deleting_the_selected_step_clears_the_selection(app, services, project, tab):
    step = project.steps[0]
    scene(tab).select_step(step.id)
    press_key(app, tab, Qt.Key.Key_Delete)

    assert published_steps(services) == []
    assert len(project.steps) == 1


# -- the tab's title ----------------------------------------------------------------------------


def test_a_rename_reaches_the_tab_title(services, project, tab):
    services.undo.push(SetFieldCommand(project.id, "title", "Discovery Phase"))
    assert [a.title for a in services.tabs.activities()] == ["Discovery Phase"]


# -- the rule that keeps opening a tab free -----------------------------------------------------


def test_opening_a_tab_writes_nothing(services, project, tab):
    """Automatic layout is never persisted. If it were, merely opening a project would
    dirty the workspace, and every step an agent created through the CLI would grow a
    position file the next time a window happened to open."""
    services.autosave.flush_now()
    assert not services.autosave.has_pending()
    for step in project.steps:
        assert "project_editor" not in step.module_data


# -- the link verbs, with no canvas in sight ----------------------------------------------------
#
# The property that made this an action rather than a private signal: it is a pure function of
# a Context, so it can be evaluated without a widget and offered by the palette.


def context_of(services, *step_ids):
    from dplanner.framework.context import ContextNode, selection_uri

    services.context.set_scope(
        SCOPE_SELECTION, tuple(ContextNode(selection_uri("step", s)) for s in step_ids)
    )
    return services.context.current()


def state(services, action_id, context):
    return services.actions.spec(action_id).state(context)


def test_link_wants_at_least_two_steps(services, project, tab):
    first, second = project.steps
    assert not state(services, "steps.link", context_of(services)).enabled
    assert not state(services, "steps.link", context_of(services, first.id)).enabled
    assert state(services, "steps.link", context_of(services, first.id, second.id)).enabled


def test_link_makes_the_last_step_wait_on_every_other_in_one_undo(services, project, tab):
    first, second = project.steps
    third = Step(title="Ship it")
    services.undo.push(AddNodeCommand(project.id, third))
    services.undo.push(SetEdgesCommand(third.id, "requires", [second.id]))

    services.actions.run("steps.link", context_of(services, first.id, second.id, third.id))
    assert services.document.step(third.id).edges["requires"] == [second.id, first.id]
    services.undo.undo()
    assert services.document.step(third.id).edges["requires"] == [second.id]


def test_a_fan_in_that_would_close_a_cycle_refuses_the_lot(services, project, tab):
    first, _second, third = chain(services, project)
    spare = Step(title="Spare")
    services.undo.push(AddNodeCommand(project.id, spare))
    # first waits on spare fine, but on third it closes the loop.
    found = state(services, "steps.link", context_of(services, spare.id, third.id, first.id))
    assert not found.enabled and found.label is not None and "cycle" in found.label


def test_link_greys_itself_and_says_why(services, project, tab):
    """A greyed menu entry that does not say why is a puzzle; the reason rides on the label."""
    first, _second, third = chain(services, project)
    found = state(services, "steps.link", context_of(services, third.id, first.id))
    assert found.visible and not found.enabled
    assert found.label is not None and "cycle" in found.label


def test_link_runs_from_a_context_alone(services, project, tab):
    first, second = project.steps
    services.actions.run("steps.link", context_of(services, first.id, second.id))
    assert services.document.step(second.id).edges["requires"] == [first.id]
    services.undo.undo()
    assert "requires" not in services.document.step(second.id).edges


def test_unlink_offers_itself_only_for_a_linked_pair(services, project, tab):
    first, second = project.steps
    # Disabled rather than hidden: it is a toolbar button, and a row that reflows as the
    # selection changes cannot be read. `build_menu` renders it greyed, like the menu bar.
    assert not state(services, "steps.unlink", context_of(services, first.id, second.id)).enabled

    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    # Either way round: the pair is linked, however the user happened to select it.
    assert state(services, "steps.unlink", context_of(services, first.id, second.id)).enabled
    assert state(services, "steps.unlink", context_of(services, second.id, first.id)).enabled
    # And Link stands down, so the two never both offer themselves.
    assert not state(services, "steps.link", context_of(services, first.id, second.id)).visible


def test_remove_link_wants_picked_arrows_and_unlink_the_pair(services, project, tab):
    """Two verbs, filed by where the link was picked: an arrow on the canvas, or its two
    steps anywhere — in the order table, say, with no arrow in sight."""
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    pair = context_of(services, first.id, second.id)
    assert state(services, "steps.unlink", pair).enabled
    removal = state(services, "links.remove", pair)
    assert not removal.enabled and removal.label == "Remove &Link — pick links first"

    edge_item(tab, second, first).setSelected(True)
    picked = services.context.current()
    assert state(services, "links.remove", picked).enabled
    assert not state(services, "steps.unlink", picked).enabled
    services.actions.run("links.remove", picked)
    assert "requires" not in services.document.step(second.id).edges


def test_unlink_removes_the_edge(services, project, tab):
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    services.actions.run("steps.unlink", context_of(services, first.id, second.id))
    assert "requires" not in services.document.step(second.id).edges


# -- one selection scope, several panes ----------------------------------------------------------


def test_a_background_pane_does_not_publish_its_selection(services, project, tab):
    """There is one selection scope and there can be several panes on screen. A background
    one re-syncing its canvas — when a step is deleted, say — must not clobber what the pane
    the user is actually in published."""
    step = project.steps[0]
    tab.on_deactivated()

    scene(tab).select_step(step.id)
    assert services.context.current().selected_entities("step") == []

    tab.on_activated()
    assert services.context.current().selected_entities("step") == [step.id]


# -- edges are things you can pick ---------------------------------------------------------------


def edge_item(tab, waiter, source, kind="requires"):
    return scene(tab)._edges[EdgeRef(waiter=waiter.id, kind=kind, source=source.id)]


def a_point_on(edge):
    """A point the user would aim at: the middle of the drawn curve."""
    return edge.path().pointAtPercent(0.5)


def test_an_edge_can_be_clicked(app, services, project, tab):
    """A 1.4 px bezier is not a target, so the item's shape is the stroked path — clicking
    the curve within a few pixels has to count, or edges cannot be picked at all."""
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    edge = edge_item(tab, second, first)

    click(app, tab, a_point_on(edge) + QPointF(0, 4))
    assert edge.isSelected()
    assert scene(tab).selection().edges == (EdgeRef(second.id, "requires", first.id),)


def test_a_picked_edge_survives_an_unrelated_change(services, project, tab):
    """Edges used to be thrown away and rebuilt on every sync, so a selection could not
    outlive one. They are diffed by key now, for the same reason nodes always were."""
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    edge = edge_item(tab, second, first)
    edge.setSelected(True)

    services.undo.push(SetFieldCommand(first.id, "title", "Read it again"))
    assert edge_item(tab, second, first) is edge
    assert edge.isSelected()


def test_a_picked_edge_reaches_the_context(services, project, tab):
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    edge_item(tab, second, first).setSelected(True)

    picked = services.context.current().selected_entities(EDGE_KIND)
    assert picked == [EdgeRef(second.id, "requires", first.id).entity_id()]


def redirect_state(services, action_id):
    return services.actions.spec(action_id).state(services.context.current())


def test_redirect_is_available_exactly_while_links_are_picked(services, project, tab):
    """The tool's own precondition, and it says so rather than vanishing: a greyed entry is
    how somebody learns that arrows are things you can pick."""
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    for action_id in ("steps.redirect_to", "steps.redirect_from"):
        state = redirect_state(services, action_id)
        assert not state.enabled and "pick links first" in (state.label or "")

    edge_item(tab, second, first).setSelected(True)
    for action_id in ("steps.redirect_to", "steps.redirect_from"):
        assert redirect_state(services, action_id).enabled


def test_redirect_to_moves_the_picked_links_onto_the_step_clicked(app, services, project, tab):
    """The gesture the tool exists for: two steps' requirements become one step's, in one
    undo entry — and the arrows keep the far end they had."""
    first, second, third = chain(services, project)
    fourth = Step(title="Rewrite it")
    services.undo.push(AddNodeCommand(project.id, fourth))
    services.undo.push(SetEdgesCommand(third.id, "requires", [second.id, first.id]))
    for source in (first, second):
        edge_item(tab, third, source).setSelected(True)

    services.actions.run("steps.redirect_to", services.context.current())
    assert modes(tab).current().name == REDIRECT_TO
    click(app, tab, centre_of(scene(tab).node(fourth.id)))

    # A set: which order the canvas reports two picked arrows in is the scene's business.
    assert set(services.document.step(fourth.id).edges["requires"]) == {second.id, first.id}
    assert "requires" not in services.document.step(third.id).edges
    assert services.undo.undo_text() == "Redirect 2 Links"
    assert modes(tab).current().name == IDLE  # One redirect ends the mode, like one divide.

    services.undo.undo()
    assert services.document.step(third.id).edges["requires"] == [second.id, first.id]


def test_redirect_from_moves_the_other_end(app, services, project, tab):
    first, second, _third = chain(services, project)
    fourth = Step(title="Rewrite it")
    services.undo.push(AddNodeCommand(project.id, fourth))
    edge_item(tab, second, first).setSelected(True)

    press_key(app, tab, Qt.Key.Key_E, Qt.KeyboardModifier.ShiftModifier)
    assert modes(tab).current().name == REDIRECT_FROM
    click(app, tab, centre_of(scene(tab).node(fourth.id)))

    assert services.document.step(second.id).edges["requires"] == [fourth.id]


def test_a_redirect_the_model_refuses_leaves_the_link_and_the_mode(app, services, project, tab):
    """The ring under the cursor is the model's answer, and so is the click: a step the
    arrow cannot reach is not a target, and the gesture is still going."""
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    edge_item(tab, second, first).setSelected(True)

    services.actions.run("steps.redirect_to", services.context.current())
    click(app, tab, centre_of(scene(tab).node(first.id)))  # Would be a self-link.

    assert services.document.step(second.id).edges["requires"] == [first.id]
    assert modes(tab).current().name == REDIRECT_TO


def test_leaving_the_redirect_mode_changes_nothing(app, services, project, tab):
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    edge_item(tab, second, first).setSelected(True)
    before = services.undo.undo_text()

    press_key(app, tab, Qt.Key.Key_E)
    assert modes(tab).current().name == REDIRECT_TO
    press_key(app, tab, Qt.Key.Key_Escape)
    assert modes(tab).current().name == IDLE
    assert services.undo.undo_text() == before


def test_delete_removes_the_picked_edges_as_one_step(app, services, project, tab):
    """Two edges on the same waiting step are one command: two SetEdgesCommands would each
    be built from the state before either ran, and the second would put the first one back."""
    first, second, third = chain(services, project)
    services.undo.push(SetEdgesCommand(third.id, "requires", [second.id, first.id]))
    for source in (first, second):
        edge_item(tab, third, source).setSelected(True)

    press_key(app, tab, Qt.Key.Key_Delete)
    assert "requires" not in services.document.step(third.id).edges
    services.undo.undo()
    assert services.document.step(third.id).edges["requires"] == [second.id, first.id]


def test_delete_means_the_verb_the_selection_calls_for(app, services, project, tab):
    """One key, two verbs, and no branch on the canvas: the first the context allows runs."""
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))

    edge_item(tab, second, first).setSelected(True)
    press_key(app, tab, Qt.Key.Key_Delete)
    assert len(project.steps) == 2 and "requires" not in services.document.step(second.id).edges

    scene(tab).select_step(second.id)
    press_key(app, tab, Qt.Key.Key_Delete)
    assert len(project.steps) == 1


def test_delete_on_steps_and_an_arrow_removes_everything_picked_in_one_undo(
    app, services, project, tab
):
    """The key a mixed pick is deleted with: both steps, the links into them, and the arrow
    picked beside them between two steps that stay — one entry on the stack, one Ctrl+Z."""
    first, second = project.steps
    third, fourth = Step(title="Ship it"), Step(title="Tell people")
    for step in (third, fourth):
        services.undo.push(AddNodeCommand(project.id, step))
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    services.undo.push(SetEdgesCommand(third.id, "requires", [second.id]))
    services.undo.push(SetEdgesCommand(fourth.id, "requires", [third.id]))
    scene(tab).select_steps([first.id, second.id])
    edge_item(tab, fourth, third).setSelected(True)

    press_key(app, tab, Qt.Key.Key_Delete)
    assert [step.id for step in project.steps] == [third.id, fourth.id]
    assert "requires" not in services.document.step(third.id).edges
    assert "requires" not in services.document.step(fourth.id).edges
    assert services.undo.undo_text() == "Delete 3 Items"

    services.undo.undo()  # Once: everything comes back.
    assert len(project.steps) == 4
    assert services.document.step(second.id).edges["requires"] == [first.id]
    assert services.document.step(third.id).edges["requires"] == [second.id]
    assert services.document.step(fourth.id).edges["requires"] == [third.id]


def test_deleting_a_multiple_selection_is_one_undo_step(services, project, tab):
    first, second = project.steps
    scene(tab).select_steps([first.id, second.id])
    services.actions.run("steps.delete", services.context.current())

    assert project.steps == []
    assert services.undo.undo_text() == "Delete 2 Steps"
    services.undo.undo()
    assert len(project.steps) == 2


def test_deleting_a_step_takes_the_links_into_it_along(services, project, tab):
    """No ghost id reaches disk, and the undo is still exact: the step comes back first,
    then the list that named it."""
    first, second, third = chain(services, project)
    scene(tab).select_step(second.id)
    services.actions.run("steps.delete", services.context.current())

    assert "requires" not in services.document.step(third.id).edges
    assert services.undo.undo_text() == "Delete Step"
    services.undo.undo()
    assert services.document.step(third.id).edges["requires"] == [second.id]
    assert services.document.step(second.id).edges["requires"] == [first.id]


# -- the canvas holds still ----------------------------------------------------------------------


def test_moving_a_node_does_not_pan_the_canvas(app, services, project, tab):
    """The complaint this fixed: the scene rect was recomputed from the items on every sync,
    the scroll bars re-ranged under a fixed value, and the canvas slid away under the drag."""
    step = project.steps[0]
    canvas = scene(tab)
    node = canvas._nodes[step.id]
    looking_at = view(tab).mapToScene(view(tab).viewport().rect().topLeft())

    start = centre_of(node)
    send(app, tab, QEvent.Type.MouseButtonPress, start)
    node.setPos(node.pos() + QPointF(240, 160))
    send(app, tab, QEvent.Type.MouseButtonRelease, start, Qt.MouseButton.NoButton)

    assert view(tab).mapToScene(view(tab).viewport().rect().topLeft()) == looking_at


def test_the_canvas_is_a_plane_no_graph_can_move(services, project, tab):
    """The scrollable area is a constant centred on the origin.

    Nothing about the graph may reach it — it used to be grown from the items, and every
    node that moved re-ranged the scroll bars under a fixed value, which read as the canvas
    panning away under the drag. A constant cannot do that, and it is also what lets the
    user keep panning long after the last node is behind them.
    """
    canvas = scene(tab)
    was = canvas.sceneRect()
    assert was.contains(QRectF(-50_000.0, -50_000.0, 100_000.0, 100_000.0))

    canvas.select_step(project.steps[0].id)
    services.actions.run("steps.delete", services.context.current())

    assert canvas.sceneRect() == was


def test_panning_does_not_stop_beyond_the_graph(services, project, tab):
    """The complaint this fixed: panning hit a wall a few hundred pixels past the steps."""
    canvas_view = view(tab)
    top = canvas_view.mapToScene(canvas_view.viewport().rect()).boundingRect().top()
    bar = canvas_view.verticalScrollBar()
    bar.setValue(bar.value() + 5_000)

    moved = canvas_view.mapToScene(canvas_view.viewport().rect()).boundingRect().top() - top
    # In scene units: the view frames the graph on first show, and how far it zoomed to do
    # so depends on the viewport the dock left it — the panels beside it, the sizes an
    # earlier test's window remembered — so the scroll is read through the transform.
    assert moved * canvas_view.transform().m11() == pytest.approx(5_000.0, abs=2.0)


def test_the_canvas_has_no_scroll_bars(services, project, tab):
    """A bar whose handle is a two-hundredth of its groove says nothing true; the minimap
    is what tells the user where they are. The bars still exist, so the wheel still works."""
    canvas_view = view(tab)
    policy = Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert canvas_view.horizontalScrollBarPolicy() == policy
    assert canvas_view.verticalScrollBarPolicy() == policy


# -- the canvas follows the theme ----------------------------------------------------------------


def painted_node(tab, step_id, background: str) -> QColor:
    """The colour the node's body comes out, rendered over ``background``."""
    node = scene(tab)._nodes[step_id]
    image = QImage(int(NODE_W), int(NODE_H), QImage.Format.Format_ARGB32)
    image.fill(QColor(background))
    painter = QPainter(image)
    scene(tab).render(
        painter, QRectF(image.rect()), QRectF(node.scenePos(), QSizeF(NODE_W, NODE_H))
    )
    painter.end()
    return image.pixelColor(int(NODE_W / 2), int(NODE_H * 0.75))


def test_a_title_wraps_at_a_word_and_the_overflow_elides(app):
    from PySide6.QtGui import QFont, QFontMetrics

    from dplanner.theme.cards import title_lines

    metrics = QFontMetrics(QFont())
    short = title_lines(metrics, "Ship it", 10_000.0)
    assert short == ["Ship it"]

    long_title = "Rebuild the deployment pipeline for the beta environment"
    width = metrics.horizontalAdvance("Rebuild the deployment") + 2.0
    first, second = title_lines(metrics, long_title, width)
    assert first == "Rebuild the deployment"
    assert second.startswith("pipeline")
    assert metrics.horizontalAdvance(second) <= width  # elided, never clipped


def ink_over(background: str, ink: str, alpha: int) -> QColor:
    share = alpha / 255
    base, over = QColor(background), QColor(ink)
    return QColor(
        *(
            round(getattr(base, channel)() * (1 - share) + getattr(over, channel)() * share)
            for channel in ("red", "green", "blue")
        )
    )


def rendered_node(tab, step_id) -> QImage:
    node = scene(tab)._nodes[step_id]
    image = QImage(int(NODE_W), int(NODE_H), QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    scene(tab).render(
        painter, QRectF(image.rect()), QRectF(node.scenePos(), QSizeF(NODE_W, NODE_H))
    )
    painter.end()
    return image


@pytest.mark.parametrize("theme", (DARK, LIGHT), ids=lambda t: t.name)
def test_a_decorated_node_actually_paints_its_pill(themed, services, project, tab, theme):
    """Not a pixel-perfect check — just that the pill and glyph reach the canvas in both
    themes rather than erroring or painting nothing."""
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.github.aspect import MODULE_ID, GithubRefs, write

    apply_theme(themed, theme)
    step = project.steps[0]
    plain = rendered_node(tab, step.id)
    refs = GithubRefs(branch="feat/login", pr_number=12, pr_state="merged")
    services.undo.push(SetModuleDataCommand(step.id, MODULE_ID, write(refs)))
    assert rendered_node(tab, step.id) != plain


@pytest.mark.parametrize("theme", (DARK, LIGHT), ids=lambda t: t.name)
def test_a_node_is_painted_in_the_theme_that_is_current(themed, services, project, tab, theme):
    """Switching the theme repaints the graph.

    ``QStyleOptionGraphicsItem.palette`` is filled once, when the scene is created, and never
    refreshed — so every node kept the ink of whatever theme the tab was opened in, and a
    light theme drew the whole graph in the dark theme's near-white and lost it.
    """
    apply_theme(themed, theme)
    body = painted_node(tab, project.steps[0].id, theme.bg_base)
    wanted = ink_over(theme.bg_base, theme.text_primary, FILL_ALPHA)

    assert abs(body.red() - wanted.red()) <= 2
    assert abs(body.green() - wanted.green()) <= 2
    assert abs(body.blue() - wanted.blue()) <= 2


# -- a selected node is a card off the table -----------------------------------------------


def painted_under(tab, step_id, background: str) -> QColor:
    """The ground just below a node's seat: empty canvas, or the shadow of a lifted node.

    Sampled at the left end, before ``LEFT_INSET``: the problem squiggle hangs in the same
    band and runs from there to the right edge, and a red arc is not what this is asking
    about.
    """
    node = scene(tab)._nodes[step_id]
    margin = 12
    width, height = int(NODE_W + 2 * margin), int(NODE_H + 2 * margin)
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(background))
    painter = QPainter(image)
    scene(tab).render(
        painter,
        QRectF(image.rect()),
        QRectF(node.scenePos() - QPointF(margin, margin), QSizeF(width, height)),
    )
    painter.end()
    return image.pixelColor(int(margin + 2), int(margin + NODE_H + 3))


@pytest.mark.parametrize("theme", (DARK, LIGHT), ids=lambda t: t.name)
def test_selecting_a_node_deepens_the_fill_it_already_had(themed, services, project, tab, theme):
    """The shading is a *gain* on the node's own fill rather than a colour of its own, which
    is what lets a picked milestone stay purple while it is picked.

    The exactness is the second assertion in disguise: the body can only come out at the
    gained alpha over the ground if **nothing else is painted under it**. A node's fill is
    translucent, so shadow rings left beneath would darken it and a picked step would read
    as a hole rather than as a card off the table — which is what the first cut did.
    """
    from dplanner.theme.cards import SELECTED_FILL_GAIN

    apply_theme(themed, theme)
    step = project.steps[0]
    scene(tab).select_step(step.id)
    body = painted_node(tab, step.id, theme.bg_base)
    wanted = ink_over(theme.bg_base, theme.text_primary, round(FILL_ALPHA * SELECTED_FILL_GAIN))

    assert abs(body.red() - wanted.red()) <= 2
    assert abs(body.green() - wanted.green()) <= 2
    assert abs(body.blue() - wanted.blue()) <= 2


def test_every_card_rests_on_a_shadow_and_a_selected_one_casts_a_deeper_one(services, project, tab):
    """A card on the table darkens the ground just under it; the lift reads because the
    picked card's seat darkens more. Rendered over white, where a low-alpha black actually
    says something.

    Over a *linked* step: the orphan ring is on by default and falls in the same few pixels
    under the body, which is the shadow's own ground.
    """
    step, other = project.steps[:2]
    services.undo.push(SetEdgesCommand(other.id, "requires", [step.id]))
    resting = painted_under(tab, step.id, "white").lightness()
    assert resting < QColor("white").lightness()
    scene(tab).select_step(step.id)
    assert painted_under(tab, step.id, "white").lightness() < resting


def test_a_lifted_node_sits_over_its_neighbours(services, project, tab):
    """Nodes share one Z, where the stacking order is whichever sync added last — so the
    selected one has to claim the top or its shadow would fall behind the node next to it."""
    first, second = (scene(tab)._nodes[step.id] for step in project.steps[:2])
    assert first.zValue() == second.zValue()
    scene(tab).select_step(project.steps[0].id)
    assert first.zValue() > second.zValue()
    scene(tab).select_step(project.steps[1].id)
    assert second.zValue() > first.zValue()


def test_the_bounding_rect_covers_everything_a_node_paints(services, project, tab):
    """Constant, selected or not: a rect that grew on selection would invalidate the wrong
    region and leave the shadow behind when the selection moved on."""
    from dplanner.theme.cards import LIFT, LIFTED_SHADOW

    node = scene(tab)._nodes[project.steps[0].id]
    plain = node.boundingRect()
    node.setSelected(True)
    assert node.boundingRect() == plain
    assert plain.bottom() >= NODE_H + LIFTED_SHADOW.drop + LIFTED_SHADOW.spread
    assert plain.top() <= -LIFT


# -- the minimap -----------------------------------------------------------------------------------


def minimap(tab):
    return view(tab).minimap


def settle(app):
    """The map is fed from ``QGraphicsScene.changed``, which the scene emits on the turn of
    the event loop that precedes its views repainting — so the map and the canvas always
    agree, and a test that changes the graph has to let that turn happen."""
    app.processEvents()


def test_the_minimap_draws_every_node(app, services, project, tab):
    settle(app)
    assert not minimap(tab).isHidden()
    assert len(minimap(tab)._nodes) == len(project.steps)


def test_the_minimap_goes_off_screen_without_a_graph(app, services, project, tab):
    """An empty box is worse than no box — DESIGN.md's rule for a panel, one surface down."""
    scene(tab).select_steps([step.id for step in project.steps])
    services.actions.run("steps.delete", services.context.current())
    settle(app)

    assert minimap(tab).isHidden()


def test_clicking_the_minimap_looks_there(app, services, project, tab):
    """The map is how you get back to the graph after panning away from it."""
    canvas_view = view(tab)
    settle(app)
    bar = canvas_view.verticalScrollBar()
    bar.setValue(bar.value() + 5_000)
    away = canvas_view.mapToScene(canvas_view.viewport().rect()).boundingRect().center()

    map_widget = minimap(tab)
    local = QPointF(map_widget.width() / 2, 12.0)  # Near the top of the map: back up there.
    app.sendEvent(
        map_widget,
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            local,
            QPointF(map_widget.mapToGlobal(local.toPoint())),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )

    back = canvas_view.mapToScene(canvas_view.viewport().rect()).boundingRect().center()
    assert back.y() < away.y()


# -- modes -----------------------------------------------------------------------------------------


def modes(tab):
    return view(tab).modes


def test_the_base_mode_never_pops(services, project, tab):
    assert modes(tab).current().name == IDLE
    assert not modes(tab).pop()
    assert modes(tab).current().name == IDLE


def test_space_pans_while_it_is_held(app, services, project, tab):
    press_key(app, tab, Qt.Key.Key_Space)
    assert modes(tab).current().name == PAN
    assert view(tab).viewport().cursor().shape() == Qt.CursorShape.OpenHandCursor

    release_key(app, tab, Qt.Key.Key_Space)
    assert modes(tab).current().name == IDLE
    assert view(tab).viewport().cursor().shape() == Qt.CursorShape.ArrowCursor


def test_a_press_on_a_card_pans_while_space_is_held(app, services, project, tab):
    """A hand holding Space is panning, wherever it lands — Qt's own hand drag gave a press
    on a card to the card, which moved instead of the plane."""
    step = project.steps[0]
    node = scene(tab)._nodes[step.id]
    seat = node.pos()
    canvas_view = view(tab)
    bars = canvas_view.horizontalScrollBar(), canvas_view.verticalScrollBar()
    was = (bars[0].value(), bars[1].value())
    press_key(app, tab, Qt.Key.Key_Space)

    start = centre_of(node)
    send(app, tab, QEvent.Type.MouseButtonPress, start)
    assert canvas_view.viewport().cursor().shape() == Qt.CursorShape.ClosedHandCursor
    send(app, tab, QEvent.Type.MouseMove, start + QPointF(-120.0, -80.0))
    send(
        app,
        tab,
        QEvent.Type.MouseButtonRelease,
        start + QPointF(-120.0, -80.0),
        Qt.MouseButton.NoButton,
    )

    assert node.pos() == seat
    assert services.undo.undo_text() != "Move Step"
    assert (bars[0].value(), bars[1].value()) == (was[0] + 120, was[1] + 80)
    assert canvas_view.viewport().cursor().shape() == Qt.CursorShape.OpenHandCursor
    release_key(app, tab, Qt.Key.Key_Space)
    assert modes(tab).current().name == IDLE


def test_the_wheel_scrolls_and_ctrl_wheel_zooms(app, services, project, tab):
    """The hidden scroll bars are still scroll bars: the bare wheel moves the plane, and
    Ctrl turns the same wheel into the canvas's own zoom."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QWheelEvent

    canvas_view = view(tab)
    viewport = canvas_view.viewport()

    def wheel(units, modifiers=Qt.KeyboardModifier.NoModifier):
        at = QPointF(viewport.rect().center())
        app.sendEvent(
            viewport,
            QWheelEvent(
                at,
                QPointF(viewport.mapToGlobal(at.toPoint())),
                QPoint(),
                QPoint(0, units),
                Qt.MouseButton.NoButton,
                modifiers,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            ),
        )

    zoom, scrolled = canvas_view._zoom, canvas_view.verticalScrollBar().value()
    wheel(-120)
    assert canvas_view._zoom == zoom
    assert canvas_view.verticalScrollBar().value() > scrolled
    wheel(120, Qt.KeyboardModifier.ControlModifier)
    assert canvas_view._zoom > zoom


def test_with_space_held_the_keys_page_the_plane(app, services, project, tab):
    """The arrows and hjkl move the view a third of the viewport, a tenth with Shift — and
    while the hand is on the plane they stop selecting steps."""
    from dplanner.modules.project_editor.modes import PAN_NUDGE, PAN_PAGE

    canvas_view = view(tab)
    across, down = canvas_view.horizontalScrollBar(), canvas_view.verticalScrollBar()
    scene(tab).select_step(project.steps[0].id)  # Opens the step panel, which narrows the view.
    press_key(app, tab, Qt.Key.Key_Space)
    width, height = canvas_view.viewport().width(), canvas_view.viewport().height()

    x, y = across.value(), down.value()
    press_key(app, tab, Qt.Key.Key_Right)
    assert across.value() == x + round(width * PAN_PAGE)
    press_key(app, tab, Qt.Key.Key_H, Qt.KeyboardModifier.ShiftModifier)
    assert across.value() == x + round(width * PAN_PAGE) - round(width * PAN_NUDGE)
    press_key(app, tab, Qt.Key.Key_J)
    assert down.value() == y + round(height * PAN_PAGE)
    press_key(app, tab, Qt.Key.Key_Up, Qt.KeyboardModifier.ShiftModifier)
    assert down.value() == y + round(height * PAN_PAGE) - round(height * PAN_NUDGE)
    assert scene(tab).selection().steps == (project.steps[0].id,)  # hjkl did not select.

    release_key(app, tab, Qt.Key.Key_Space)
    assert modes(tab).current().name == IDLE


def test_connect_mode_shows_every_handle_and_pan_hides_them(app, services, project, tab):
    """The mode's look is pushed to every node; the stack's answer wins over enter/exit."""
    canvas = scene(tab)
    first = project.steps[0]
    assert canvas._nodes[first.id]._hints.handles == "hover"

    services.actions.run("steps.connect", services.context.current())
    assert all(item._hints.handles == "always" for item in canvas._nodes.values())

    # Space stacks Pan over Connect; popping back must restore Connect's hints.
    press_key(app, tab, Qt.Key.Key_Space)
    assert canvas._nodes[first.id]._hints.handles == "hidden"
    release_key(app, tab, Qt.Key.Key_Space)
    assert canvas._nodes[first.id]._hints.handles == "always"

    press_key(app, tab, Qt.Key.Key_Escape)
    assert canvas._nodes[first.id]._hints.handles == "hover"


def test_connect_mode_links_two_clicks_and_then_lets_go(app, services, project, tab):
    """One finished link ends the mode — pressing the button again is how you make another."""
    first, second = project.steps
    canvas = scene(tab)
    services.actions.run("steps.connect", services.context.current())
    assert modes(tab).current().name == CONNECT

    click(app, tab, centre_of(canvas._nodes[first.id]))
    click(app, tab, centre_of(canvas._nodes[second.id]))

    assert services.document.step(second.id).edges["requires"] == [first.id]
    assert modes(tab).current().name == IDLE


def test_connect_with_several_selected_links_them_all_to_the_step_clicked(
    app, services, project, tab
):
    """The selection is the sources, not a stale pick: the click is the step that waits on
    every one of them, in one undo step."""
    first, second = project.steps
    third = Step(title="Ship it")
    services.undo.push(AddNodeCommand(project.id, third))
    canvas = scene(tab)
    canvas.select_steps([first.id, second.id])
    press_key(app, tab, Qt.Key.Key_C)
    assert modes(tab).current().name == CONNECT

    click(app, tab, centre_of(canvas._nodes[third.id]))

    assert services.document.step(third.id).edges["requires"] == [first.id, second.id]
    assert modes(tab).current().name == IDLE
    services.undo.undo()
    assert "requires" not in services.document.step(third.id).edges


def test_selecting_several_steps_announces_the_selection_once(services, project, tab):
    """Qt reports a re-selection item by item; the scene announces the gesture."""
    first, second = project.steps
    heard = []
    scene(tab).selection_changed.connect(lambda selection: heard.append(selection.steps))
    scene(tab).select_steps([first.id, second.id])
    assert heard == [(first.id, second.id)]


def _announcements(services, monkeypatch):
    """How often the window heard the context, and how often the dock relaid itself."""
    from dplanner.framework.panels import PanelDock

    announced: list[int] = []
    relaid: list[int] = []
    services.context.changed.connect(lambda _context: announced.append(1))
    original = PanelDock._refresh

    def counted(self):
        relaid.append(1)
        original(self)

    monkeypatch.setattr(PanelDock, "_refresh", counted)
    return announced, relaid


def test_a_connect_announces_the_context_once_and_the_selection_stands(
    app, services, project, tab, monkeypatch
):
    """The gesture publishes the selection more than once on its way — the source pick, the
    mode leaving, the push — and the window hears one announcement over the final state:
    the selection it started with, so the step panel never steps aside for a selection
    that was empty for a microsecond. The window's regime, not the suite's: coalescing
    only shows with the debounce service deferred."""
    first, second = project.steps
    tab.select_step(first.id)
    announced, relaid = _announcements(services, monkeypatch)
    services.debounce.set_immediate(False)

    services.actions.run("steps.connect", services.context.current())
    click(app, tab, centre_of(scene(tab)._nodes[first.id]))
    click(app, tab, centre_of(scene(tab)._nodes[second.id]))
    assert announced == []  # Pending, not run.
    services.debounce.flush_all()

    assert services.document.step(second.id).edges["requires"] == [first.id]
    assert len(announced) == 1 and relaid == []
    assert scene(tab).selection().steps == (first.id,)
    assert published_steps(services) == [first.id]


def test_a_paste_announces_the_context_once_and_the_selection_stands(
    services, project, tab, monkeypatch
):
    first, _second = project.steps
    tab.select_step(first.id)
    services.actions.run("steps.copy", services.context.current())
    announced, relaid = _announcements(services, monkeypatch)
    services.debounce.set_immediate(False)

    services.actions.run("steps.paste", services.context.current())
    services.debounce.flush_all()

    (copy,) = [step for step in project.steps if step.id not in (first.id, _second.id)]
    assert len(announced) == 1 and relaid == []
    assert scene(tab).selection().steps == (copy.id,)
    assert published_steps(services) == [copy.id]


def test_escape_clears_the_pending_step_before_it_leaves(app, services, project, tab):
    """Two stages, because backing out of half a link and backing out of the mode are two
    different intentions and Escape is the only key for either."""
    first, _second = project.steps
    services.actions.run("steps.connect", services.context.current())
    click(app, tab, centre_of(scene(tab)._nodes[first.id]))

    press_key(app, tab, Qt.Key.Key_Escape)
    assert modes(tab).current().name == CONNECT
    press_key(app, tab, Qt.Key.Key_Escape)
    assert modes(tab).current().name == IDLE


def test_connect_from_the_keyboard_alone(app, services, project, tab):
    """Pick a step, press c, walk to the next one, press Enter — no mouse anywhere.

    Two unplaced steps stack in one column, so the next one along is *down* from here."""
    first, second = project.steps
    scene(tab).select_step(first.id)
    press_key(app, tab, Qt.Key.Key_C)
    assert modes(tab).current().name == CONNECT

    press_key(app, tab, Qt.Key.Key_J)
    assert scene(tab).selected_step() == second.id
    press_key(app, tab, Qt.Key.Key_Return)

    assert services.document.step(second.id).edges["requires"] == [first.id]
    assert modes(tab).current().name == IDLE


def test_the_mode_is_in_the_context(services, project, tab):
    """Which is the whole reason the Connect button can check itself: its state stays a pure
    function of the context, with no canvas in it."""
    assert not state(services, "steps.connect", services.context.current()).checked
    services.actions.run("steps.connect", services.context.current())
    assert state(services, "steps.connect", services.context.current()).checked


def test_leaving_the_pane_leaves_its_modes(services, project, tab):
    services.actions.run("steps.connect", services.context.current())
    tab.on_deactivated()
    assert modes(tab).current().name == IDLE


# -- moving about, with no canvas in sight ---------------------------------------------------------


def test_movement_verbs_read_the_positions_the_model_holds(services, project, tab):
    """`layout.positions()` already answers where every node is, so which step is to the
    right is a pure function — these are testable from a constructed context."""
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))

    assert state(services, "steps.go_right", context_of(services, first.id)).enabled
    assert not state(services, "steps.go_right", context_of(services, second.id)).enabled
    assert state(services, "steps.go_left", context_of(services, second.id)).enabled

    services.actions.run("steps.go_right", context_of(services, first.id))
    assert scene(tab).selected_step() == second.id


def test_the_arrows_say_the_same_thing_as_hjkl(app, services, project, tab):
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    scene(tab).select_step(first.id)

    press_key(app, tab, Qt.Key.Key_Right)
    assert scene(tab).selected_step() == second.id
    press_key(app, tab, Qt.Key.Key_H)
    assert scene(tab).selected_step() == first.id


# -- the toolbar -----------------------------------------------------------------------------------


def toolbar_button(tab, action_id):
    found = tab._toolbar.button(action_id)
    assert found is not None, f"{action_id} is not on the toolbar"
    return found


def test_the_toolbar_greys_rather_than_reflows(services, project, tab):
    """A row of buttons that appear and vanish as the selection changes cannot be read, so
    these verbs are disabled rather than hidden — which is why `_on_a_step` changed."""
    button = toolbar_button(tab, "steps.delete")
    assert button.isVisible() or not button.isEnabled()
    assert not button.isEnabled()

    scene(tab).select_step(project.steps[0].id)
    assert button.isEnabled()


def test_the_connect_button_checks_itself_with_the_mode(services, project, tab):
    button = toolbar_button(tab, "steps.connect")
    assert not button.isChecked()

    services.actions.run("steps.connect", services.context.current())
    assert button.isChecked()

    services.actions.run("steps.connect", services.context.current())
    assert not button.isChecked()


def test_the_toolbar_carries_verbs_from_other_modules(services, project, tab):
    """The registry is the only thing between them: undo comes from the app shell and the
    order table from step_order, and this module imports neither."""
    assert toolbar_button(tab, "appshell.undo") is not None
    assert toolbar_button(tab, "order.open").isEnabled()

    services.actions.run("order.open", services.context.current())
    assert any(a.uri.startswith("app://activity/order") for a in services.tabs.activities())


def test_new_carries_no_arrow(services, project, tab):
    """New is one click: the kinds are chosen in the details dialog it opens, not from a
    dropdown of their own."""
    assert toolbar_button(tab, "steps.new").menu() is None
    assert toolbar_button(tab, "steps.delete").menu() is None


def dropdown(tab, action_id):
    popup = tab._toolbar.menu_for(action_id)
    assert popup is not None, f"{action_id} carries no arrow"
    return {
        action.text().replace("&", "") for action in popup.actions() if not action.isSeparator()
    }


def test_a_family_of_verbs_is_one_button_and_its_arrow(services, project, tab):
    """Sort, Divide and Redirect are each several verbs and one seat on the strip. The
    arrow renders the child menu out of the action table rather than a copy of it, so a
    sort added to the menus appears here having touched nothing."""
    services.actions.run("steps.select_all", services.context.current())
    assert dropdown(tab, "canvas.sort_flow") >= {"Layered Flow", "Spine", "Radial"}
    assert dropdown(tab, "canvas.divide_vertical") == {
        "Vertical",
        "Horizontal",
        "Contract Vertically",
        "Contract Horizontally",
    }
    # Taking room back is Divide's family, under a rule of its own.
    assert any(
        action.isSeparator() for action in tab._toolbar.menu_for("canvas.divide_vertical").actions()
    )


def test_the_redirect_button_drops_both_ends(services, project, tab):
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    edge_item(tab, second, first).setSelected(True)
    assert dropdown(tab, "steps.redirect_to") == {"To Step", "From Step"}


def bands(tab):
    """Each band of the strip, as its name and the verbs seated in it."""
    from dplanner.framework.toolbar import _Group

    return [
        (group.caption.text() if group.caption is not None else "", [a.text() for a in group.verbs])
        for group in tab._toolbar.tools.findChildren(_Group)
    ]


def test_the_layout_picker_sits_in_the_arrange_band(services, project, tab):
    """It names the arrangement the canvas is showing, which is Arrange's business — and a
    lone worded button past the end of a row of named bands reads as something that fell
    off. It is a *widget* among the verbs, so it hides when there is no room rather than
    folding into the … menu, the way a filter does."""
    from dplanner.framework.toolbar import _Group

    picker = tab._layout_button
    band = picker.parentWidget()
    while band is not None and not isinstance(band, _Group):
        band = band.parentWidget()
    assert band is not None and band.caption is not None
    assert band.caption.text() == "Arrange"
    # A widget is not a verb: it never enters the … menu.
    assert picker not in [action.parent() for action in tab._toolbar.tools.verbs()]


def test_the_strip_is_named_bands_of_glyphs(services, project, tab):
    """Nineteen glyphs in a row are nineteen riddles; six named bands are a tool palette.
    Where you are looking leads it — a graph is a place before it is a thing to edit."""
    named = [name for name, _verbs in bands(tab)]
    assert named == ["Problems", "Go", "Step", "Link", "Arrange", "History", "Options"]
    seated = {verb for _name, verbs in bands(tab) for verb in verbs}
    assert {"Find Step…", "New Step", "Undo", "Look"} <= seated


def test_every_verb_on_the_strip_is_a_glyph_with_its_words_in_the_tooltip(services, project, tab):
    """A row of words is a sentence the eye rereads every time. The words are not lost —
    they lead the tooltip, and they are what the … menu lists."""
    for action_id in ("steps.new", "steps.lasso", "canvas.mark_starts", "steps.find"):
        assert services.actions.spec(action_id).icon is not None, action_id
    button = toolbar_button(tab, "steps.new")
    assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    assert not button.icon().isNull()
    assert button.toolTip().startswith("New Step")


def test_a_verb_is_filed_by_where_its_subject_is_picked(services):
    """View is the window; Graph is the canvas. A verb about picked *steps* is Step's, one
    about a point, the plane or a picked *arrow* is Graph's — and a step verb with no canvas
    in it is what the order table's right-click renders, so nothing canvas-only is left on
    Step to be greyed there."""
    specs = services.actions.all_specs()
    where = {spec.id: (spec.menu, spec.group, spec.submenu) for spec in specs}
    assert where["canvas.sort_flow"] == ("Graph", "arrange", "Sort")
    assert where["canvas.divide_vertical"] == ("Graph", "arrange", "Divide")
    assert where["canvas.contract_vertical"] == ("Graph", "contract", "Divide")
    assert where["canvas.snap"] == ("Graph", "look", None)
    assert where["steps.new"] == ("Graph", "new", None)
    assert where["steps.paste_graph"] == ("Graph", "new", None)
    assert where["steps.paste"] == ("Edit", "clipboard", None)
    assert where["steps.lasso"] == ("Graph", "select", None)
    assert where["steps.go_left"] == ("Graph", "select", "Select Nearest")
    assert where["canvas.select_only_steps"] == ("Graph", "narrow", None)
    assert where["links.remove"] == ("Graph", "links", None)
    assert where["steps.redirect_to"] == ("Graph", "links", "Redirect")
    assert where["steps.link"] == ("Step", "link", None)
    assert where["steps.unlink"] == ("Step", "link", None)
    assert where["steps.reveal"] == ("Step", "surfaces", "Show in")
    assert where["estimate.open"] == ("Go", "survey", None)
    strays = [
        spec.id
        for spec in services.actions.all_specs()
        if spec.id.startswith("canvas.") and spec.menu != "Graph"
    ]
    assert strays == []


def test_closing_the_tab_lets_its_toolbars_go(services, project, tab):
    """A toolbar subscribes to the context, and unlike the menu bar it does not outlive
    its tab. A leaked subscription would restate a dead widget on every selection change."""
    before = len(services.context.changed._slots)
    tab.close()
    assert len(services.context.changed._slots) < before


# -- finding a step, and landing on it ----------------------------------------------------------


def editor_module(services):
    from dplanner.modules.project_editor.module import ProjectEditorModule

    return next(m for m in services.modules if isinstance(m, ProjectEditorModule))


def picked_rows(picker):
    return [picker.list.item(i).text() for i in range(picker.list.count())]


def test_find_opens_on_the_landmarks_and_searches_every_step(services, project, tab):
    """A plan of three hundred steps has a dozen a person navigates by. They are what the
    picker opens on; everything is in play from the first keystroke."""
    from dplanner.modules.step_milestone.aspect import MODULE_ID as MILESTONE_ID
    from dplanner.modules.step_milestone.aspect import write as milestone_write

    first, second = project.steps
    services.undo.push(SetModuleDataCommand(first.id, MILESTONE_ID, milestone_write("Ship it")))
    picker = editor_module(services).find_picker()
    assert picker is not None
    assert picked_rows(picker) == [first.title]  # The milestone alone, before anything typed.

    picker._refilter(second.title[:5])
    assert second.title in picked_rows(picker)
    picker.deleteLater()


def test_a_step_is_found_by_its_key_as_well_as_its_name(services, project, tab):
    """S7 and "build the modal" are two ways of naming one step; the graph answers to both."""
    step = project.steps[0]
    picker = editor_module(services).find_picker()
    assert picker is not None
    picker._refilter(f"S{step.number}")
    assert picked_rows(picker) == [step.title]
    picker.deleteLater()


def test_finding_a_step_puts_the_canvas_on_it(services, project, tab):
    """Selecting a step a screen away selects something nobody can see — which is what
    Reveal in Graph did until this landed, and what Find must never do."""
    from dplanner.modules.project_editor.positions import MODULE_ID as POSITION_KEY
    from dplanner.modules.project_editor.positions import write_position

    far = project.steps[1]
    services.undo.push(SetModuleDataCommand(far.id, POSITION_KEY, write_position(4000.0, 3000.0)))
    tab._sync_soon.flush()
    before = tab._view._looking_at().center()

    services.actions.run("steps.reveal", context_of(services, far.id))
    after = tab._view._looking_at().center()
    assert after != before
    node = scene(tab).node(far.id)
    # Per axis, not as one length: centerOn aims at an integer scroll position, so a
    # viewport with an odd extent lands half a scene pixel off in that axis — under a pixel
    # each way is as centred as it gets, and how wide the panel area happens to be is not
    # this test's subject.
    residue = after - node.body_scene_rect().center()
    assert abs(residue.x()) < 1.0 and abs(residue.y()) < 1.0


def test_revealing_a_step_opens_its_canvas_on_it(app, services, project):
    """From the Control Centre the canvas is usually not open yet. A new canvas frames the
    whole graph a turn after it is first shown, and that frame used to land after the
    reveal had centred — so Show in ▸ Graph opened on the middle of the plan instead."""
    from dplanner.modules.project_editor.positions import MODULE_ID as POSITION_KEY
    from dplanner.modules.project_editor.positions import write_position

    far = project.steps[1]
    services.undo.push(SetModuleDataCommand(far.id, POSITION_KEY, write_position(4000.0, 3000.0)))

    services.actions.run("steps.reveal", context_of(services, far.id))
    app.processEvents()  # The canvas's first look is deferred to the turn after its show.

    tab = next(a for a in services.tabs.activities() if a.uri.startswith("app://activity/project"))
    residue = tab._view._looking_at().center() - scene(tab).node(far.id).body_scene_rect().center()
    assert abs(residue.x()) < 1.0 and abs(residue.y()) < 1.0


def test_find_is_ctrl_f_everywhere_and_slash_on_the_canvas(services):
    """Ctrl+F is what every application means by find, and a menu shortcut is how a Ctrl
    key is bound here — every text widget reclaims it, and the state gate keeps it off a
    tab with no canvas. The bare key is the canvas's own way in, beside it."""
    from PySide6.QtGui import QKeySequence

    from dplanner.framework.action_registry import key_sequences
    from dplanner.modules.project_editor.keymap import bound_actions

    spec = services.actions.spec("steps.find")
    assert (spec.menu, spec.group) == ("Graph", "select")
    assert spec.icon is not None
    assert QKeySequence(QKeySequence.StandardKey.Find) in key_sequences(spec.shortcut)
    assert bound_actions(Qt.Key.Key_Slash, Qt.KeyboardModifier.NoModifier) == ("steps.find",)


# -- the panel beside the canvas -----------------------------------------------------------------


def test_the_problems_list_stands_in_the_tab_not_in_the_window(services, project, tab):
    """Where a problem is clicked and the canvas moves to it. The window's dock does not
    offer it, so there is no second copy to keep in step."""
    assert tab._side_panel is not None
    assert "problems" not in {spec.id for spec in services.panels.panels()}


def test_the_panel_is_shut_until_it_is_asked_for_and_then_remembered(
    services, project, tab, make_project
):
    """A preference, so it outlives the tab: a canvas opened later stands as this one does."""
    frame = tab._side_panel.frame
    assert frame.isHidden()
    assert not look_of(services).side_panel

    services.actions.run("canvas.side_panel", services.context.current())
    assert not frame.isHidden() and look_of(services).side_panel
    assert tab._side_panel.button.isChecked()

    other = services.tabs.open("project", make_project("Later").id)
    assert other._side_panel is not None and not other._side_panel.frame.isHidden()

    # And the panel's own way out is the same verb, so the preference is written once.
    frame.close_button.click()
    assert frame.isHidden() and not look_of(services).side_panel


def test_the_panels_verb_is_the_graphs_own_chrome(services):
    """View is the window; Graph is the canvas — and this panel is inside the canvas's tab."""
    spec = services.actions.spec("canvas.side_panel")
    assert (spec.menu, spec.group) == ("Graph", "panels")
    # Named for what it holds, by the composition root — this module never spells it.
    assert spec.label == "Problems" and spec.icon is not None


def test_the_panel_leads_the_strip_in_a_band_of_its_own(services, project, tab):
    """What is wrong with the plan is what you want to know before you look at it — and
    the button carries the panel's own count, which is why it is a widget."""
    named = [name for name, _verbs in bands(tab)]
    assert named[0] == "Problems"
    button = tab._side_panel.button
    assert button.parent() is not None
    # A widget is not a verb: it never enters the … menu.
    assert button not in [action.parent() for action in tab._toolbar.tools.verbs()]


# -- selecting everything ----------------------------------------------------------------------


def test_select_all_selects_every_step(services, project, tab):
    """Select All is the Edit menu's, bound to the standard key there: a menu shortcut fires
    through the shortcut map before the canvas sees the key, so the canvas keymap has no
    row for it and the binding is asserted on the menu bar's own action."""
    from PySide6.QtGui import QKeySequence

    services.actions.run("steps.select_all", services.context.current())
    assert set(scene(tab).selection().steps) == {step.id for step in project.steps}
    published = services.context.current().selected_entities("step")
    assert set(published) == {step.id for step in project.steps}
    bound = services.window.dynamic_menubar.action("steps.select_all").shortcuts()
    assert QKeySequence(QKeySequence.StandardKey.SelectAll) in bound


def test_select_all_is_disabled_off_a_canvas(services):
    state = services.actions.spec("steps.select_all").state(services.context.current())
    assert not state.enabled


def test_select_all_is_disabled_on_an_empty_project(services, project, tab):
    for step in list(project.steps):
        services.undo.push(RemoveNodeCommand(step.id))
    state = services.actions.spec("steps.select_all").state(services.context.current())
    assert not state.enabled


# -- the right-click is composed by what is under it ------------------------------------------


def entries(menu):
    """A menu as it reads, mnemonics dropped: "|" for a rule, (title, entries) for a child."""
    rendered: list[object] = []
    for action in menu.actions():
        if action.isSeparator():
            rendered.append("|")
        elif action.menu() is not None:
            rendered.append((action.text().replace("&", ""), entries(action.menu())))
        else:
            rendered.append(action.text().replace("&", ""))
    return rendered


def labels(rendered):
    """Every label in a rendered menu, at any depth, child menu titles included."""
    found = []
    for entry in rendered:
        if isinstance(entry, tuple):
            found += [entry[0], *labels(entry[1])]
        elif entry != "|":
            found.append(entry)
    return found


def offered(tab, scene_pos):
    """What a right-click at a point offers — made current and built, never shown."""
    menu = tab.context_menu(view(tab).mapFromScene(scene_pos))
    rendered = entries(menu)
    menu.deleteLater()
    return rendered


def test_a_right_click_on_an_arrow_picks_it_and_offers_the_link_verbs(services, project, tab):
    """What an arrow is for, and nothing else: removed, made to auto-progress, or one of its
    ends moved."""
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    scene(tab).select_step(first.id)
    edge = edge_item(tab, second, first)

    assert offered(tab, a_point_on(edge)) == [
        "Remove Link",
        "Auto-progress — S2 is not an agent step",
        ("Redirect", ["To Step", "From Step"]),
    ]
    assert scene(tab).selection().steps == ()
    assert scene(tab).selection().edges == (edge.ref,)


def test_a_right_press_on_one_of_several_picked_arrows_keeps_them(app, services, project, tab):
    """Handed to Qt, a right press on an arrow — selectable, not movable — clears the whole
    selection before the menu is asked for, and Remove Link would take one arrow of three."""
    first, second, third = chain(services, project)
    services.undo.push(SetEdgesCommand(third.id, "requires", [second.id, first.id]))
    edges = [edge_item(tab, second, first), edge_item(tab, third, second)]
    edges.append(edge_item(tab, third, first))
    for edge in edges:
        edge.setSelected(True)

    at = a_point_on(edges[0])
    send(app, tab, QEvent.Type.MouseButtonPress, at, Qt.MouseButton.RightButton, button=RIGHT)
    send(app, tab, QEvent.Type.MouseButtonRelease, at, Qt.MouseButton.NoButton, button=RIGHT)

    assert offered(tab, at)[0] == "Remove 3 Links"
    assert len(scene(tab).selection().edges) == 3


def test_a_right_click_inside_a_pick_keeps_it(services, project, tab):
    """The menu must read the selection the user made, not collapse it to the node under
    the cursor — or "Delete 2 Steps" could never be said."""
    first, second = project.steps
    scene(tab).select_steps([first.id, second.id])

    assert "Delete 2 Steps" in offered(tab, centre_of(scene(tab).node(first.id)))
    assert scene(tab).selection().steps == (first.id, second.id)


def test_a_right_click_outside_the_pick_makes_the_card_the_pick(services, project, tab):
    first, second = project.steps
    scene(tab).select_step(first.id)

    offered(tab, centre_of(scene(tab).node(second.id)))
    assert scene(tab).selection().steps == (second.id,)


def test_a_cards_menu_holds_only_what_is_about_the_step(services, project, tab):
    """A card gets what acts on the step itself — edit, link, where it stands, its agent,
    its details and its place in coverage — and nothing a table's Step menu adds: its type
    and tests are set in Step Details, compiling is the Docs tab's, the project's views are
    rows in the index beside the canvas, and none of the canvas's own verbs."""
    first, _second = project.steps
    # By name: a greyed entry carries its reason after one.
    found = {
        label.split(" — ")[0]
        for label in labels(offered(tab, centre_of(scene(tab).node(first.id))))
    }

    for about_the_step in (
        "Rename Step…",
        "Connect Steps",
        "Status",
        "Estimate",
        "Run Agent",
        "Step Details…",
        "Show in",
        "Coverage",
        "Spec Passage",
    ):
        assert about_the_step in found
    for elsewhere in (
        "Type",
        "Test",
        "Test Category",
        "Test Sort Key",
        "Compile with Agent",
        "Order",
        "Step Statuses",
        "Tests",
        "Test Details",
        "Estimate Steps",
        "Graph",
        "Redirect",
        "Find Step…",
        "Select Nearest",
        "Lasso Select",
        "New Step",
    ):
        assert elsewhere not in found


def test_a_table_still_renders_the_whole_step_menu(services, project, tab):
    """What a card leaves out is filed, not dropped: the menu bar and every table that
    lists steps still offer it — all but what a step *is*, which is set in Step Details."""
    from PySide6.QtWidgets import QMenu

    from dplanner.framework.action_menu import fill_menu

    step_menu = fill_menu(QMenu(), services.actions, services.context, "Step")
    found = labels(entries(step_menu))
    step_menu.deleteLater()
    for verb in ("Status", "Estimate", "Compile with Agent", "Show in", "Order", "Graph"):
        assert verb in found
    for kind in ("Type", "Test", "Test Category", "Test Sort Key"):
        assert kind not in found


def test_empty_canvas_offers_making_selecting_and_the_plan(services, project, tab, monkeypatch):
    """Nothing about a step: what to make where the click was, how to pick what is there,
    and the looks over the whole plan the index has no row for — and the click lets go of
    the pick, so nothing acts on it unseen."""
    first, _second = project.steps
    scene(tab).select_step(first.id)
    nowhere = QPointF(3000.0, 3000.0)

    rendered = offered(tab, nowhere)
    assert scene(tab).selection().steps == ()
    assert rendered[:2] == ["New Step", "Paste"]
    found = {label.split(" — ")[0] for label in labels(rendered)}
    for verb in (
        "Find Step…",
        "Lasso Select",
        "Select Nearest",
        "Select All Steps",
        "Estimate Steps",
    ):
        assert verb in found
    assert "Preview Report" in found
    for step_verb in ("Status", "Run Agent", "Rename Step…", "Delete Step", "Remove Link"):
        assert step_verb not in found
    # A row under the project in the index already opens each of these.
    for listed in ("Specs", "Assets", "Steps", "Coverage", "Tests"):
        assert listed not in found

    silence_details(monkeypatch)
    services.actions.run("steps.new", services.context.current())
    entry = project.steps[-1].module_data["project_editor"]
    assert (entry["x"], entry["y"]) == (
        snapped(3000.0 - NODE_W / 2, GRID),
        snapped(3000.0 - NODE_H / 2, GRID),
    )


def test_a_mixed_pick_leads_with_narrowing_and_offers_each_kind_below(services, project, tab):
    """Nothing is about steps and arrows at once, so the mixed pick's menu narrows it, acts
    on any of it, and keeps each kind's own verbs one level down."""
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    scene(tab).select_steps([second.id, first.id])
    edge_item(tab, second, first).setSelected(True)

    rendered = offered(tab, centre_of(scene(tab).node(first.id)))
    assert rendered[:3] == ["Select Only Steps", "Select Only Links", "|"]
    assert "Delete 3 Items" in rendered and "Copy 2 Steps" in rendered
    assert [entry[0] for entry in rendered if isinstance(entry, tuple)] == ["Step", "Links"]
    assert rendered[-1] == (
        "Links",
        [
            "Remove Link",
            "Auto-progress — S2 is not an agent step",
            ("Redirect", ["To Step", "From Step"]),
        ],
    )
    assert rendered[-3] == "|"  # Above the two children, and none between them.

    services.actions.run("canvas.select_only_steps", services.context.current())
    assert scene(tab).selection().steps == (second.id, first.id)
    assert scene(tab).selection().edges == ()


def test_only_links_lets_go_of_the_steps(services, project, tab):
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    edge = edge_item(tab, second, first)
    scene(tab).select_step(first.id)
    assert not state(services, "canvas.select_only_links", services.context.current()).enabled
    edge.setSelected(True)

    services.actions.run("canvas.select_only_links", services.context.current())
    assert scene(tab).selection().steps == ()
    assert scene(tab).selection().edges == (edge.ref,)


# -- the layout picker --------------------------------------------------------------------------


def save_layout(services, project, name):
    from dplanner.modules.project_editor.layout_verbs import set_current_layout_name
    from dplanner.modules.project_editor.named_layouts import save_layout_command, snapshot

    snap = snapshot(services.document, project)
    services.undo.push(save_layout_command(project, name, snap))
    set_current_layout_name(project.id, name)
    return snap


def popup_texts(tab):
    return [a.text() for a in tab._layout_button.build_popup().actions() if not a.isSeparator()]


def test_the_popup_lists_saved_layouts_with_the_applied_one_checked(services, project, tab):
    save_layout(services, project, "release plan")
    popup = tab._layout_button.build_popup()
    named = [a for a in popup.actions() if a.text() == "release plan"]
    assert len(named) == 1 and named[0].isChecked()
    assert "Save Layout &As…" in popup_texts(tab)


def test_the_face_wears_the_name_and_a_modified_dot_after_a_drag(services, project, tab):
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.project_editor.positions import write_position

    save_layout(services, project, "release plan")
    tab._layout_button._refresh_face()
    assert tab._layout_button.text() == "release plan"

    step = project.steps[0]
    services.undo.push(
        SetModuleDataCommand(step.id, "project_editor", write_position(800.0, 800.0))
    )
    assert tab._layout_button.text() == "• release plan"


def test_a_sort_action_is_one_undo_step(services, project, tab):
    """An explicit sort persists — through the undo stack, like any drag — and one Ctrl+Z
    takes the whole arrangement back."""
    assert tab.run_action("canvas.sort_spine")
    assert services.undo.undo_text() == "Spine Layout"
    for step in project.steps:
        assert "project_editor" in step.module_data
    services.undo.undo()
    for step in project.steps:
        assert "project_editor" not in step.module_data


def test_applying_a_layout_is_one_undo_step_that_restores_every_position(services, project, tab):
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.project_editor.named_layouts import snapshot
    from dplanner.modules.project_editor.positions import write_position

    saved = save_layout(services, project, "release plan")
    for index, step in enumerate(project.steps):
        entry = write_position(800.0 + index * 8, 800.0)
        services.undo.push(SetModuleDataCommand(step.id, "project_editor", entry))
    scattered = snapshot(services.document, project)
    assert scattered.steps != saved.steps

    popup = tab._layout_button.build_popup()
    next(a for a in popup.actions() if a.text() == "release plan").trigger()
    assert snapshot(services.document, project).steps == saved.steps
    assert services.undo.undo_text() == 'Apply Layout "release plan"'

    services.undo.undo()
    assert snapshot(services.document, project).steps == scattered.steps


# -- a project saved with regions ----------------------------------------------------------------


@pytest.fixture
def reopened(app, cli, cli_library, at_work_board):
    """A window opened over Discovery as a build with regions left it: three steps, their
    ids in order, and the running application — built the way ``main`` builds it, so the
    migration pass runs before the canvas reads anything."""
    from tests.old_canvas import plant

    from dplanner.app import new_session

    cli("project", "create", "Discovery")
    for title in ("Read the spec", "Draft the model", "Ship it"):
        cli("step", "add", "Discovery", title)
    step_ids = plant(cli_library, "Discovery")
    session = new_session(at_work=at_work_board)
    assert session.open_initial(cli_library)
    assert session.services is not None
    session.services.debounce.set_immediate(True)
    yield session.services, step_ids
    session.close()


def test_a_project_saved_with_regions_opens_on_the_canvas_without_them(reopened):
    """Regions were retired, and a plan that had them opens exactly as it was, minus the
    rectangles."""
    from tests.old_canvas import SEATS

    services, step_ids = reopened
    project = services.document.projects[0]
    tab = services.tabs.open("project", project.id)

    drawn = {type(item).__name__ for item in scene(tab).items() if item.parentItem() is None}
    assert drawn == {"StepNodeItem", "LinkPreviewItem", "OutlinePreviewItem"}
    for step_id, (x, y, size) in zip(step_ids, SEATS, strict=True):
        node = scene(tab)._nodes[step_id]
        assert (node.pos().x(), node.pos().y()) == (x, y)
        assert node.size() == (size or (NODE_W, NODE_H))
    assert "regions" not in project.module_data["project_editor"]


# -- the lasso -------------------------------------------------------------------------------------


def lasso(app, tab, points, modifiers=Qt.KeyboardModifier.NoModifier):
    """Press at the first point, drag through the rest, release at the last."""
    send(app, tab, QEvent.Type.MouseButtonPress, points[0], modifiers=modifiers)
    for point in points[1:]:
        send(app, tab, QEvent.Type.MouseMove, point, modifiers=modifiers)
    send(app, tab, QEvent.Type.MouseButtonRelease, points[-1], Qt.MouseButton.NoButton, modifiers)


def round_first_into_second(tab, first, second):
    """An outline enclosing the first card and poking ten pixels into the second."""
    one = scene(tab)._nodes[first.id].body_scene_rect()
    two = scene(tab)._nodes[second.id].body_scene_rect()
    return [
        QPointF(one.left() - 10, one.top() - 10),
        QPointF(two.left() + 10, one.top() - 10),
        QPointF(two.left() + 10, one.bottom() + 10),
        QPointF(one.left() - 10, one.bottom() + 10),
    ]


def test_a_lasso_picks_every_card_it_touches_and_then_lets_go(app, services, project, tab):
    first, second, third = chain(services, project)
    services.actions.run("steps.lasso", services.context.current())
    assert modes(tab).current().name == LASSO

    lasso(app, tab, round_first_into_second(tab, first, second))

    assert set(scene(tab).selection().steps) == {first.id, second.id}
    assert third.id not in scene(tab).selection().steps
    assert modes(tab).current().name == IDLE  # One lasso ends the mode, like one link.


def test_shift_adds_the_catch_to_the_selection(app, services, project, tab):
    first, second, third = chain(services, project)
    scene(tab).select_step(third.id)
    press_key(app, tab, Qt.Key.Key_S)
    assert modes(tab).current().name == LASSO

    lasso(
        app,
        tab,
        round_first_into_second(tab, first, second),
        modifiers=Qt.KeyboardModifier.ShiftModifier,
    )
    assert scene(tab).selection().steps == (third.id, first.id, second.id)


def test_a_lasso_that_never_moved_is_a_click_that_means_nothing(app, services, project, tab):
    first, _second = project.steps
    scene(tab).select_step(first.id)
    services.actions.run("steps.lasso", services.context.current())
    click(app, tab, QPointF(900.0, 900.0))
    assert scene(tab).selection().steps == (first.id,)
    assert modes(tab).current().name == IDLE


def test_escape_drops_a_half_drawn_lasso_before_it_leaves(app, services, project, tab):
    services.actions.run("steps.lasso", services.context.current())
    send(app, tab, QEvent.Type.MouseButtonPress, QPointF(0.0, 0.0))
    send(app, tab, QEvent.Type.MouseMove, QPointF(300.0, 300.0))
    assert scene(tab)._outline.isVisible()

    press_key(app, tab, Qt.Key.Key_Escape)
    assert modes(tab).current().name == LASSO
    assert not scene(tab)._outline.isVisible()
    press_key(app, tab, Qt.Key.Key_Escape)
    assert modes(tab).current().name == IDLE


def test_the_lasso_button_checks_itself_and_hides_the_handles(app, services, project, tab):
    button = toolbar_button(tab, "steps.lasso")
    assert not button.isChecked()
    services.actions.run("steps.lasso", services.context.current())
    assert button.isChecked()
    assert all(item._hints.handles == "hidden" for item in scene(tab)._nodes.values())
    press_key(app, tab, Qt.Key.Key_Escape)
    assert not button.isChecked()


# -- dividing --------------------------------------------------------------------------------------
#
# A cut is a line across the canvas, and dragging from it pushes every card on the side dragged
# towards, so a crowded graph gets room in the middle. Driven with real mouse events, like the
# lasso: the gesture is where the bugs live.


def gap_between(tab, near, far):
    """A point in the empty column between two cards, well clear of both."""
    one, two = body_of(tab, near.id), body_of(tab, far.id)
    return QPointF((one.right() + two.left()) / 2, one.bottom() + 200.0)


def seats_of(tab, *steps):
    return {step.id: body_of(tab, step.id).topLeft() for step in steps}


def stored_x(services, step_id):
    return placement_of(services, step_id)["x"]


def test_a_vertical_divide_pushes_the_side_dragged_towards(app, services, project, tab):
    first, second, third = chain(services, project)
    seats = seats_of(tab, first, second, third)
    services.actions.run("canvas.divide_vertical", services.context.current())
    assert modes(tab).current().name == DIVIDE_VERTICAL

    cut = gap_between(tab, first, second)
    drag(app, tab, cut, cut + QPointF(120.0, 0.0))

    assert stored_x(services, second.id) == seats[second.id].x() + 120.0
    assert stored_x(services, third.id) == seats[third.id].x() + 120.0
    assert "project_editor" not in services.document.step(first.id).module_data  # Untouched.
    assert services.undo.undo_text() == "Divide Graph"
    assert modes(tab).current().name == IDLE  # One divide ends the mode, like one lasso.

    services.undo.undo()  # One step back takes the whole side with it.
    assert seats_of(tab, first, second, third) == seats


def test_dragging_back_past_the_cut_flips_the_side(app, services, project, tab):
    first, second, third = chain(services, project)
    seats = seats_of(tab, first, second, third)
    press_key(app, tab, Qt.Key.Key_D)
    assert modes(tab).current().name == DIVIDE_VERTICAL

    cut = gap_between(tab, first, second)
    send(app, tab, QEvent.Type.MouseButtonPress, cut)
    send(app, tab, QEvent.Type.MouseMove, cut + QPointF(120.0, 0.0))
    assert body_of(tab, second.id).topLeft() == seats[second.id] + QPointF(120.0, 0.0)
    assert body_of(tab, first.id).topLeft() == seats[first.id]
    send(app, tab, QEvent.Type.MouseMove, cut + QPointF(-80.0, 0.0))
    assert body_of(tab, second.id).topLeft() == seats[second.id]  # The far side came back.
    assert body_of(tab, first.id).topLeft() == seats[first.id] + QPointF(-80.0, 0.0)
    send(
        app, tab, QEvent.Type.MouseButtonRelease, cut + QPointF(-80.0, 0.0), Qt.MouseButton.NoButton
    )

    assert stored_x(services, first.id) == seats[first.id].x() - 80.0
    assert "project_editor" not in services.document.step(second.id).module_data
    assert "project_editor" not in services.document.step(third.id).module_data


def test_a_horizontal_divide_pushes_up_or_down(app, services, project, tab):
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.project_editor.positions import write_position

    first, second = project.steps
    services.undo.push(
        SetModuleDataCommand(second.id, "project_editor", write_position(40.0, 304.0))
    )
    press_key(app, tab, Qt.Key.Key_D, Qt.KeyboardModifier.ShiftModifier)
    assert modes(tab).current().name == DIVIDE_HORIZONTAL

    cut = QPointF(900.0, 200.0)  # Between the rows, off every card.
    drag(app, tab, cut, cut + QPointF(0.0, 80.0))

    assert placement_of(services, second.id)["y"] == 384.0
    assert "project_editor" not in services.document.step(first.id).module_data
    assert services.undo.undo_text() == "Divide Graph"


def test_a_card_the_cut_crosses_goes_with_the_side_its_centre_is_on(app, services, project, tab):
    first, second, third = chain(services, project)
    body = body_of(tab, first.id)
    seats = seats_of(tab, first, second, third)
    below = body.bottom() + 200.0

    services.actions.run("canvas.divide_vertical", services.context.current())
    cut = QPointF(body.center().x() - 20.0, below)  # Through the card, left of its centre.
    drag(app, tab, cut, cut + QPointF(80.0, 0.0))
    assert stored_x(services, first.id) == seats[first.id].x() + 80.0
    services.undo.undo()

    services.actions.run("canvas.divide_vertical", services.context.current())
    cut = QPointF(body.center().x() + 20.0, below)  # Through the card, right of its centre.
    drag(app, tab, cut, cut + QPointF(80.0, 0.0))
    assert "project_editor" not in services.document.step(first.id).module_data
    assert stored_x(services, second.id) == seats[second.id].x() + 80.0


def test_escape_puts_a_half_divided_graph_back(app, services, project, tab):
    first, second, third = chain(services, project)
    seats = seats_of(tab, first, second, third)
    services.actions.run("canvas.divide_vertical", services.context.current())
    cut = gap_between(tab, first, second)
    send(app, tab, QEvent.Type.MouseButtonPress, cut)
    send(app, tab, QEvent.Type.MouseMove, cut + QPointF(120.0, 0.0))
    assert body_of(tab, third.id).topLeft() == seats[third.id] + QPointF(120.0, 0.0)

    press_key(app, tab, Qt.Key.Key_Escape)

    assert seats_of(tab, first, second, third) == seats
    assert modes(tab).current().name == IDLE
    assert services.undo.undo_text() != "Divide Graph"
    assert not scene(tab)._outline.isVisible()


def test_a_divide_that_never_moved_pushes_nothing(app, services, project, tab):
    first, second, _third = chain(services, project)
    services.actions.run("canvas.divide_vertical", services.context.current())

    click(app, tab, gap_between(tab, first, second))

    assert services.undo.undo_text() != "Divide Graph"
    assert "project_editor" not in services.document.step(second.id).module_data
    assert modes(tab).current().name == IDLE


def test_a_change_from_the_model_mid_divide_leaves_the_pushed_cards_where_they_are(
    app, services, project, tab
):
    first, second, third = chain(services, project)
    seat = body_of(tab, third.id).topLeft()
    services.actions.run("canvas.divide_vertical", services.context.current())
    cut = gap_between(tab, first, second)
    send(app, tab, QEvent.Type.MouseButtonPress, cut)
    send(app, tab, QEvent.Type.MouseMove, cut + QPointF(120.0, 0.0))

    services.undo.push(SetFieldCommand(third.id, "title", "Ship it, renamed"))  # A sync.

    assert body_of(tab, third.id).topLeft() == seat + QPointF(120.0, 0.0)
    send(
        app, tab, QEvent.Type.MouseButtonRelease, cut + QPointF(120.0, 0.0), Qt.MouseButton.NoButton
    )
    assert stored_x(services, third.id) == seat.x() + 120.0


def test_the_cut_lies_under_the_cursor_from_edge_to_edge(app, services, project, tab):
    services.actions.run("canvas.divide_vertical", services.context.current())
    assert view(tab).viewport().cursor().shape() == Qt.CursorShape.SplitHCursor
    assert all(item._hints.handles == "hidden" for item in scene(tab)._nodes.values())

    send(app, tab, QEvent.Type.MouseMove, QPointF(250.0, 90.0), Qt.MouseButton.NoButton)

    outline = scene(tab)._outline
    assert outline.isVisible()
    shown = outline.path().boundingRect()
    looking_at = view(tab).mapToScene(view(tab).viewport().rect()).boundingRect()
    assert shown.width() == 0.0 and abs(shown.left() - 250.0) <= 1.0
    assert shown.top() <= looking_at.top() and shown.bottom() >= looking_at.bottom()

    press_key(app, tab, Qt.Key.Key_Escape)  # Nothing pending: Escape leaves.
    assert modes(tab).current().name == IDLE
    assert not outline.isVisible()
    assert view(tab).viewport().cursor().shape() == Qt.CursorShape.ArrowCursor


def test_the_band_beside_the_cut_is_the_room_being_made(app, services, project, tab):
    first, second, _third = chain(services, project)
    services.actions.run("canvas.divide_vertical", services.context.current())
    cut = gap_between(tab, first, second)
    send(app, tab, QEvent.Type.MouseButtonPress, cut)
    send(app, tab, QEvent.Type.MouseMove, cut + QPointF(120.0, 0.0))

    shown = scene(tab)._outline.path().boundingRect()
    assert abs(shown.left() - cut.x()) <= 1.0 and abs(shown.width() - 120.0) <= 1.0

    send(app, tab, QEvent.Type.MouseMove, cut + QPointF(-80.0, 0.0))
    shown = scene(tab)._outline.path().boundingRect()
    assert abs(shown.right() - cut.x()) <= 1.0 and abs(shown.width() - 80.0) <= 1.0
    press_key(app, tab, Qt.Key.Key_Escape)


def stack_steps(services, *steps):
    """Membership as the stack verbs write it, with no seat: the stack stands where the
    ambient layout puts it."""
    for step in steps:
        services.undo.push(SetModuleDataCommand(step.id, "project_editor", write_member("s1")))


def test_a_stack_is_drawn_as_a_column_and_moves_through_any_member(services, project, tab):
    _first, second, third = chain(services, project)
    stack_steps(services, second, third)
    top = body_of(tab, second.id).topLeft()
    assert body_of(tab, third.id).topLeft() == top + QPointF(0.0, 96.0)

    scene(tab).nodes_moved.emit([(third.id, 600.0, 400.0)])
    assert services.undo.undo_text() == "Move Step"
    head = placement_of(services, second.id)
    assert (head["x"], head["y"], head["stack"]) == (600.0, 400.0 - 96.0, "s1")
    assert "x" not in placement_of(services, third.id)
    assert body_of(tab, third.id).topLeft() == QPointF(600.0, 400.0)


def test_deleting_a_stacks_middle_step_closes_the_chain_as_one_undo(services, project, tab):
    """Delete, Cut and `step remove` are one removal, and in a stack it closes the chain
    round the gap — the window's install of the stack rule is what would refuse the bridge
    were it judged, so this also proves the removal carries it rather than judging."""
    first, second, third = chain(services, project)
    stack_steps(services, first, second, third)
    assert services.document.link_refusal(third.id, "requires", project.steps[0].id)
    scene(tab).select_step(second.id)
    services.actions.run("steps.delete", services.context.current())

    assert services.document.step(third.id).edges["requires"] == [first.id]
    assert services.undo.undo_text() == "Delete Step"
    services.undo.undo()
    assert services.document.step(third.id).edges["requires"] == [second.id]
    assert services.document.step(second.id).edges["requires"] == [first.id]


def test_a_divide_through_a_stack_carries_it_whole(app, services, project, tab):
    """A level cut through a stack: the stack goes to the side its frame's centre is on,
    whole, in the preview and on release alike."""
    first, second, third = chain(services, project)
    stack_steps(services, first, second, third)
    seats = seats_of(tab, first, second, third)
    below_second = (body_of(tab, second.id).bottom() + body_of(tab, third.id).top()) / 2
    above_second = (body_of(tab, first.id).bottom() + body_of(tab, second.id).top()) / 2

    # Below the frame's centre: the stack is on the near side, and nothing lies past the cut.
    services.actions.run("canvas.divide_horizontal", services.context.current())
    cut = QPointF(1200.0, below_second)
    send(app, tab, QEvent.Type.MouseButtonPress, cut)
    send(app, tab, QEvent.Type.MouseMove, cut + QPointF(0.0, 80.0))
    assert seats_of(tab, first, second, third) == seats
    send(
        app, tab, QEvent.Type.MouseButtonRelease, cut + QPointF(0.0, 80.0), Qt.MouseButton.NoButton
    )
    assert all("x" not in placement_of(services, s.id) for s in (first, second, third))

    # Above it: the stack lies past the cut, and all of it goes.
    services.actions.run("canvas.divide_horizontal", services.context.current())
    cut = QPointF(1200.0, above_second)
    send(app, tab, QEvent.Type.MouseButtonPress, cut)
    send(app, tab, QEvent.Type.MouseMove, cut + QPointF(0.0, 80.0))
    moved = {s: seat + QPointF(0.0, 80.0) for s, seat in seats.items()}
    assert seats_of(tab, first, second, third) == moved
    send(
        app, tab, QEvent.Type.MouseButtonRelease, cut + QPointF(0.0, 80.0), Qt.MouseButton.NoButton
    )
    assert placement_of(services, first.id)["y"] == seats[first.id].y() + 80.0
    assert "x" not in placement_of(services, second.id)
    assert services.undo.undo_text() == "Divide Graph"


def test_a_divide_entry_is_checked_only_while_its_own_mode_is_on(services, project, tab):
    services.actions.run("canvas.divide_horizontal", services.context.current())
    context = services.context.current()
    assert state(services, "canvas.divide_horizontal", context).checked
    assert not state(services, "canvas.divide_vertical", context).checked

    services.actions.run("canvas.divide_horizontal", context)  # Again: leaves, as Lasso does.
    assert modes(tab).current().name == IDLE
    assert not state(services, "canvas.divide_horizontal", services.context.current()).checked


# -- contracting -----------------------------------------------------------------------------------
#
# Divide's other half: the side behind the drag is pulled after it, and stops the sorts' gap
# short of the first card ahead of it in its row, however far the pointer goes.


def spread_out(services, project, tab):
    """The chain with the last step three pitches right of the one before it."""
    from dplanner.modules.project_editor.positions import write_position
    from dplanner.modules.project_editor.sorts import H_PITCH

    first, second, third = chain(services, project)
    near = body_of(tab, second.id)
    services.undo.push(
        SetModuleDataCommand(
            third.id, "project_editor", write_position(near.left() + 3 * H_PITCH, near.top())
        )
    )
    return (first, second, third), near


def status_line(services):
    return services.window.statusBar().currentMessage()


def test_a_vertical_contract_closes_the_hole_to_one_gap_as_one_undo(app, services, project, tab):
    from dplanner.modules.project_editor.sorts import H_GAP

    (first, second, third), near = spread_out(services, project, tab)
    seats = seats_of(tab, first, second, third)
    press_key(app, tab, Qt.Key.Key_X)
    assert modes(tab).current().name == CONTRACT_VERTICAL

    cut = QPointF(near.right() + 200.0, near.bottom() + 200.0)  # In the hole, off every card.
    send(app, tab, QEvent.Type.MouseButtonPress, cut)
    send(app, tab, QEvent.Type.MouseMove, cut + QPointF(-1000.0, 0.0))
    # Clamped live: however far the pointer went, the far side stops one gap short — the
    # travel rounded onto the grid, so a card on the grid stays on it.
    landed = body_of(tab, third.id).left()
    assert H_GAP <= landed - near.right() < H_GAP + GRID and landed % GRID == 0
    names = scene(tab)._nodes[third.id].name(), scene(tab)._nodes[second.id].name()
    assert f"{names[0]} stops one gap from {names[1]}" in status_line(services)
    send(app, tab, QEvent.Type.MouseButtonRelease, cut, Qt.MouseButton.NoButton)

    assert stored_x(services, third.id) == landed
    assert "project_editor" not in services.document.step(first.id).module_data  # Untouched.
    assert services.undo.undo_text() == "Contract Graph"
    assert modes(tab).current().name == IDLE  # One contract ends the mode, like one divide.

    services.undo.undo()  # One step back takes the whole side with it.
    assert seats_of(tab, first, second, third) == seats


def test_escape_puts_a_half_contracted_graph_back(app, services, project, tab):
    (first, second, third), near = spread_out(services, project, tab)
    seats = seats_of(tab, first, second, third)
    services.actions.run("canvas.contract_vertical", services.context.current())
    cut = QPointF(near.right() + 200.0, near.bottom() + 200.0)
    send(app, tab, QEvent.Type.MouseButtonPress, cut)
    send(app, tab, QEvent.Type.MouseMove, cut + QPointF(-160.0, 0.0))
    assert body_of(tab, third.id).topLeft() == seats[third.id] + QPointF(-160.0, 0.0)
    assert scene(tab)._outline.isVisible()  # The band closed so far.

    press_key(app, tab, Qt.Key.Key_Escape)

    assert seats_of(tab, first, second, third) == seats
    assert modes(tab).current().name == IDLE
    assert services.undo.undo_text() != "Contract Graph"
    assert not scene(tab)._outline.isVisible()


def test_a_horizontal_contract_closes_up_or_down(app, services, project, tab):
    from dplanner.modules.project_editor.positions import write_position
    from dplanner.modules.project_editor.sorts import V_PITCH

    first, second = project.steps
    top = body_of(tab, first.id)
    services.undo.push(
        SetModuleDataCommand(
            second.id, "project_editor", write_position(top.left(), top.top() + 3 * V_PITCH)
        )
    )
    press_key(app, tab, Qt.Key.Key_X, Qt.KeyboardModifier.ShiftModifier)
    assert modes(tab).current().name == CONTRACT_HORIZONTAL

    cut = QPointF(top.right() + 400.0, top.bottom() + 100.0)  # Between the rows.
    drag(app, tab, cut, cut + QPointF(0.0, -1000.0))

    assert placement_of(services, second.id)["y"] == top.top() + V_PITCH
    assert services.undo.undo_text() == "Contract Graph"


# -- isolating ------------------------------------------------------------------------------------


def test_isolate_wants_a_step_with_a_link_crossing_out(services, project, tab):
    first, second, _third = chain(services, project)
    assert not state(services, "steps.isolate", context_of(services)).enabled

    lonely = Step(title="Alone")
    services.undo.push(AddNodeCommand(project.id, lonely))
    alone = state(services, "steps.isolate", context_of(services, lonely.id))
    assert not alone.enabled and "already isolated" in (alone.label or "")

    assert state(services, "steps.isolate", context_of(services, second.id)).enabled
    both = state(services, "steps.isolate", context_of(services, first.id, second.id))
    assert both.enabled and both.label == "&Isolate 2 Steps"


def test_isolate_cuts_the_crossing_links_and_keeps_the_ones_inside(services, project, tab):
    first, second, third = chain(services, project)
    services.undo.push(SetEdgesCommand(first.id, "relates", [third.id]))

    services.actions.run("steps.isolate", context_of(services, first.id, second.id))

    document = services.document
    assert document.step(second.id).edges["requires"] == [first.id]  # Inside: kept.
    assert "requires" not in document.step(third.id).edges
    assert "relates" not in document.step(first.id).edges
    assert services.undo.undo_text() == "Isolate 2 Steps"
    services.undo.undo()
    assert document.step(third.id).edges["requires"] == [second.id]
    assert document.step(first.id).edges["relates"] == [third.id]


def test_the_isolate_button_is_on_the_strip(services, project, tab):
    assert not toolbar_button(tab, "steps.isolate").isEnabled()
    _first, second, _third = chain(services, project)
    scene(tab).select_step(second.id)
    assert toolbar_button(tab, "steps.isolate").isEnabled()


# -- marks -----------------------------------------------------------------------------------------


def painted_at(tab, step_id, dx: float, dy: float) -> QColor:
    """The colour ``(dx, dy)`` from a node's top-left corner comes out, rendered over
    white with the paint margin around it — sockets and rings sit on the edge."""
    node = scene(tab)._nodes[step_id]
    margin = int(PAINT_MARGIN)
    width, height = int(NODE_W + 2 * margin), int(NODE_H + 2 * margin)
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    scene(tab).render(
        painter,
        QRectF(image.rect()),
        QRectF(node.scenePos() - QPointF(margin, margin), QSizeF(width, height)),
    )
    painter.end()
    return image.pixelColor(int(margin + dx), int(margin + dy))


def close_to(colour: QColor, wanted: QColor) -> bool:
    return all(
        abs(getattr(colour, channel)() - getattr(wanted, channel)()) <= 3
        for channel in ("red", "green", "blue")
    )


def test_the_bare_sockets_are_coloured_from_the_start_and_switch_off(services, project, tab):
    """On by default: a socket with nothing on it is one of the two things a graph can be
    wrong about, and a preference that has to be found first helps nobody."""
    from dplanner.modules.project_editor.renderers import END_MARK, START_MARK

    first, second, third = chain(services, project)
    assert close_to(painted_at(tab, first.id, 0.0, NODE_H / 2), START_MARK)
    # Something follows the first step, so its right socket is not an end.
    assert not close_to(painted_at(tab, first.id, NODE_W, NODE_H / 2), END_MARK)
    assert not close_to(painted_at(tab, second.id, 0.0, NODE_H / 2), START_MARK)
    assert close_to(painted_at(tab, third.id, NODE_W, NODE_H / 2), END_MARK)

    services.actions.run("canvas.mark_starts", services.context.current())
    assert not close_to(painted_at(tab, first.id, 0.0, NODE_H / 2), START_MARK)
    assert close_to(painted_at(tab, third.id, NODE_W, NODE_H / 2), END_MARK)  # Its own switch.


def test_a_step_something_is_wrong_about_wears_a_squiggle(services, project, tab):
    """The editor's underline, for the one thing a canvas can say about a plan's own
    health: *look here*. What is wrong is the Problems panel's to say — the canvas only
    ever knows *that*, so one mark stands for every check there is."""
    from dplanner.modules.project_editor.renderers import PROBLEM_DROP

    flagged = lambda step: painted_at(tab, step.id, NODE_W / 2, NODE_H + PROBLEM_DROP)  # noqa: E731
    step = project.steps[0]
    # A bare step is exactly what lint has things to say about (no description, no
    # estimate), so the fixture's own steps are flagged once the reading settles.
    services.debounce.flush_all()
    tab._sync()
    assert flagged(step).red() > flagged(step).green() + 40

    # Nothing to say about it, nothing drawn: the accent is what the canvas paints from.
    node = scene(tab)._nodes[step.id]
    node.set_accent(replace(node._accent, flagged=False))
    assert flagged(step).red() <= flagged(step).green() + 20


def test_the_squiggle_starts_past_the_key_block_and_stops_inside_the_card():
    """It underlines the card's content, not its key — and stays within the body's width,
    so two cards side by side do not appear joined."""
    from dplanner.modules.project_editor.renderers import (
        LEFT_INSET,
        PROBLEM_DROP,
        problem_path,
    )

    body = QRectF(0.0, 0.0, NODE_W, NODE_H)
    path = problem_path(body)
    bounds = path.boundingRect()
    assert bounds.left() >= body.left() + LEFT_INSET - 0.01
    assert bounds.right() <= body.right()
    assert bounds.center().y() == pytest.approx(body.bottom() + PROBLEM_DROP, abs=1.0)
    # A card too narrow for one arc draws nothing rather than a stub.
    assert problem_path(QRectF(0.0, 0.0, LEFT_INSET + 1.0, NODE_H)).isEmpty()


def look_entry(tab, label):
    """One entry of the Options face's menu, read as it would be on opening.

    The menu is the action table rendered afresh every time, so an entry is never held
    across a change — the test asks again, as a person would by opening the menu again.
    """
    popup = tab._toolbar.look_menu()
    found = [a for a in popup.actions() if a.text().replace("&", "") == label]
    for entry in popup.actions():
        child = entry.menu()
        if child is not None:
            found += [a for a in child.actions() if a.text().replace("&", "") == label]
    assert found, f"{label} is not under the Options face"
    return found[0]


def test_a_mark_is_remembered_and_every_canvas_wears_it(services, project, tab, make_project):
    from dplanner.modules.project_editor.marks import Marks

    # The marks are under the strip's Options face now: six worded switches on a row of
    # glyphs was a row half words, and how the graph is *drawn* is a menu's question.
    assert look_entry(tab, "Ends").isChecked()  # On by default; off is the deliberate act.
    services.actions.run("canvas.mark_ends", services.context.current())
    assert not look_entry(tab, "Ends").isChecked()
    assert look_of(services).marks == Marks(ends=False)

    other = services.tabs.open("project", make_project("Later").id)
    assert other._scene._marks == Marks(ends=False)
    assert scene(tab)._marks == Marks(ends=False)

    services.actions.run("canvas.mark_ends", services.context.current())
    assert look_entry(tab, "Ends").isChecked()
    assert other._scene._marks == Marks()


def test_a_mark_reaches_out_no_further_than_the_item_paints():
    from dplanner.modules.project_editor.renderers import (
        MARK_R,
        PROBLEM_DROP,
        PROBLEM_RISE,
        PROBLEM_W,
        RING_GAP,
        RING_W,
    )

    assert MARK_R + 1.0 <= PAINT_MARGIN
    assert RING_GAP + RING_W + 1.0 <= PAINT_MARGIN
    # The squiggle hangs below the body, which is the furthest anything reaches downward.
    assert PROBLEM_DROP + PROBLEM_RISE + PROBLEM_W / 2 + 1.0 <= PAINT_MARGIN


# -- the node's top edge, which two decorations share -------------------------------------------


def test_the_medallion_row_leaves_the_badge_less_room_the_more_it_holds():
    """The row and the badge start from opposite ends of the same 220 px edge.

    A step wearing every aspect and carrying a milestone label used to paint one over the
    other; the badge asks how far the row reached instead of assuming it may claim a fixed
    share. The row's advance already includes the trailing gap, which is why one term covers
    both the medallions and the space after them.
    """
    assert medallion_end(()) == LEFT_INSET
    assert medallion_end(("tag",)) == LEFT_INSET + ICON_D + ICON_GAP
    assert medallion_end(("tag", "layers")) > medallion_end(("tag",))


def test_a_bare_node_still_gives_its_badge_the_share_it_always_had():
    """With no medallions the row leaves more room than a badge may claim, so the elide
    budget is the fraction it always was — this change costs an undecorated node nothing."""
    assert NODE_W - BADGE_INSET - medallion_end(()) > NODE_W * 0.6


def test_a_medallion_stays_inside_the_item_that_paints_it():
    """Medallions straddle the top edge and rise with a selected node's lift. ``PAINT_MARGIN``
    is what ``boundingRect`` is made of, so growing ``ICON_D`` without measuring it here is
    how a selected step loses the top half of its icons."""
    assert ICON_D / 2 + 1.0 + LIFT <= PAINT_MARGIN


# -- a card is resizable -----------------------------------------------------------------------
#
# The frame is a band round the border (GRAB_IN inside, EDGE_REACH outside); a press on it
# grabs that edge, both bands at a corner grab the corner, and the body inside still drags.


def body_of(tab, step_id):
    return scene(tab)._nodes[step_id].body_scene_rect()


def placement_of(services, step_id):
    return services.document.step(step_id).module_data["project_editor"]


def test_dragging_the_right_edge_widens_the_card_as_one_undo_step(app, services, project, tab):
    step = project.steps[0]
    body = body_of(tab, step.id)  # (40, 40, 220, 76) in the automatic layout
    grip = QPointF(body.right() - 2.0, body.center().y() + 30.0)  # In the band, off the handle.

    drag(app, tab, grip, grip + QPointF(100.0, 0.0))

    entry = placement_of(services, step.id)
    assert (entry["x"], entry["y"]) == (40.0, 40.0)
    assert (entry["w"], entry["h"]) == (320.0, NODE_H)  # 358 snapped up to the 8-grid.
    assert services.undo.undo_text() == "Resize Step"
    assert view(tab).modes.current().name == IDLE
    assert scene(tab)._nodes[step.id].size() == (320.0, NODE_H)

    services.undo.undo()
    assert "project_editor" not in services.document.step(step.id).module_data
    assert scene(tab)._nodes[step.id].size() == (NODE_W, NODE_H)  # The model's echo lands.


def test_dragging_a_corner_moves_the_seat_with_the_edge(app, services, project, tab):
    """From the top-left the far corner stays put, so the card grows *and* moves — one
    command carrying both, or undo would have to know which half to take back."""
    step = project.steps[0]
    body = body_of(tab, step.id)
    grip = QPointF(body.left() - 2.0, body.top() - 2.0)

    drag(app, tab, grip, grip + QPointF(-40.0, -24.0))

    entry = placement_of(services, step.id)
    # The far corner stays at (260, 40 + NODE_H); the near one lands on the grid at (0, 16).
    assert (entry["x"], entry["y"], entry["w"], entry["h"]) == (0.0, 16.0, 260.0, NODE_H + 24.0)
    assert services.undo.undo_text() == "Resize Step"


def test_a_card_never_shrinks_below_its_minimum(app, services, project, tab):
    from dplanner.modules.project_editor.positions import MIN_NODE_H, MIN_NODE_W

    step = project.steps[0]
    body = body_of(tab, step.id)
    grip = QPointF(body.right() - 2.0, body.bottom() - 2.0)

    drag(app, tab, grip, QPointF(body.left() - 300.0, body.top() - 300.0))

    entry = placement_of(services, step.id)
    assert (entry["w"], entry["h"]) == (MIN_NODE_W, MIN_NODE_H)
    assert (entry["x"], entry["y"]) == (40.0, 40.0)  # The far corner is the limit.


def test_escape_puts_a_half_resized_card_back(app, services, project, tab):
    step = project.steps[0]
    node = scene(tab)._nodes[step.id]
    body = body_of(tab, step.id)
    grip = QPointF(body.right() - 2.0, body.center().y() + 30.0)
    send(app, tab, QEvent.Type.MouseButtonPress, grip)
    send(app, tab, QEvent.Type.MouseMove, grip + QPointF(100.0, 0.0))
    assert node.size() == (320.0, NODE_H)
    assert view(tab).modes.current().name == "node-resize"

    press_key(app, tab, Qt.Key.Key_Escape)

    assert node.size() == (NODE_W, NODE_H)
    assert view(tab).modes.current().name == IDLE
    assert "project_editor" not in services.document.step(step.id).module_data


def test_a_stored_size_reaches_the_card_and_its_anchors(services, project, tab):
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.project_editor.positions import write_position

    step = project.steps[0]
    services.undo.push(
        SetModuleDataCommand(step.id, "project_editor", write_position(40.0, 40.0, (300.0, 160.0)))
    )
    node = scene(tab)._nodes[step.id]
    assert node.size() == (300.0, 160.0)
    assert node.handle_scene_pos() == QPointF(340.0, 120.0)
    assert node.body_scene_rect() == QRectF(40.0, 40.0, 300.0, 160.0)


def test_a_move_keeps_the_size_a_card_was_given(services, project, tab):
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.project_editor.positions import read_size, write_position

    step = project.steps[0]
    services.undo.push(
        SetModuleDataCommand(step.id, "project_editor", write_position(40.0, 40.0, (300.0, 160.0)))
    )
    scene(tab).nodes_moved.emit([(step.id, 200.0, 120.0)])
    assert read_size(services.document.step(step.id)) == (300.0, 160.0)
    assert placement_of(services, step.id)["x"] == 200.0


def test_the_hit_shape_is_the_card_and_its_band_not_the_stat_line(services, project, tab):
    """A press under the card — where its estimate is written — is a press on empty
    canvas; a press a few pixels outside the border still belongs to the card, so the
    frame can be grabbed from either side of the line."""
    from dplanner.modules.project_editor.items import EDGE_REACH

    step = project.steps[0]
    body = body_of(tab, step.id)
    canvas = scene(tab)
    assert canvas.node_at(QPointF(body.center().x(), body.bottom() + EDGE_REACH + 8.0)) is None
    grabbed = canvas.node_at(QPointF(body.right() + EDGE_REACH - 1.0, body.center().y() + 30.0))
    assert grabbed is not None and grabbed.step_id == step.id


def test_the_frame_names_its_edges_and_corners(services, project, tab):
    node = scene(tab)._nodes[project.steps[0].id]
    body = node.body_scene_rect()
    assert node.edge_at(QPointF(body.left() + 2.0, body.center().y())) == "left"
    assert node.edge_at(QPointF(body.right() + 4.0, body.center().y() + 20.0)) == "right"
    assert node.edge_at(QPointF(body.center().x(), body.top() - 3.0)) == "top"
    assert node.edge_at(QPointF(body.center().x(), body.bottom() + 3.0)) == "bottom"
    assert node.edge_at(QPointF(body.left() - 1.0, body.top() - 1.0)) == "top-left"
    assert node.edge_at(QPointF(body.right() + 1.0, body.bottom() + 1.0)) == "bottom-right"
    assert node.edge_at(QPointF(body.right() + 1.0, body.top() - 1.0)) == "top-right"
    assert node.edge_at(QPointF(body.left() - 1.0, body.bottom() + 1.0)) == "bottom-left"
    assert node.edge_at(body.center()) == ""
    assert node.edge_at(QPointF(body.center().x(), body.bottom() + 40.0)) == ""


def test_the_pointer_says_where_a_card_can_be_grabbed(app, services, project, tab):
    """The resize arrows over the frame are the gesture's only announcement, so they have
    to be there — and gone again over the body, where a press drags."""
    step = project.steps[0]
    body = body_of(tab, step.id)
    viewport = view(tab).viewport()

    send(
        app,
        tab,
        QEvent.Type.MouseMove,
        QPointF(body.right() - 2.0, body.center().y() + 30.0),
        Qt.MouseButton.NoButton,
    )
    assert viewport.cursor().shape() == Qt.CursorShape.SizeHorCursor
    send(
        app,
        tab,
        QEvent.Type.MouseMove,
        QPointF(body.left() - 1.0, body.top() - 1.0),
        Qt.MouseButton.NoButton,
    )
    assert viewport.cursor().shape() == Qt.CursorShape.SizeFDiagCursor
    send(app, tab, QEvent.Type.MouseMove, body.center(), Qt.MouseButton.NoButton)
    assert viewport.cursor().shape() == Qt.CursorShape.ArrowCursor
    # The handle wins its corner of the right edge: a press there links, never resizes.
    send(
        app,
        tab,
        QEvent.Type.MouseMove,
        scene(tab)._nodes[step.id].handle_scene_pos(),
        Qt.MouseButton.NoButton,
    )
    assert viewport.cursor().shape() == Qt.CursorShape.ArrowCursor


def test_a_press_on_the_body_still_drags_the_card(app, services, project, tab):
    step = project.steps[0]
    node = scene(tab)._nodes[step.id]
    start = centre_of(node)
    send(app, tab, QEvent.Type.MouseButtonPress, start)
    assert view(tab).modes.current().name == IDLE  # Nothing claimed it; Qt has the drag.
    node.setPos(node.pos() + QPointF(64, 32))
    send(app, tab, QEvent.Type.MouseButtonRelease, start, Qt.MouseButton.NoButton)
    assert services.undo.undo_text() == "Move Step"


# -- the card's face: title, stat, shadow ---------------------------------------------------------


def test_the_title_face_is_larger_than_the_chrome(app):
    from PySide6.QtGui import QFont

    from dplanner.theme.cards import TITLE_POINTS, title_font

    base = QFont()
    base.setPointSizeF(10.0)
    assert title_font(base).pointSizeF() == 10.0 + TITLE_POINTS


def test_a_title_takes_as_many_lines_as_the_card_has_room_for(app):
    from PySide6.QtGui import QFont, QFontMetrics

    from dplanner.theme.cards import title_lines

    metrics = QFontMetrics(QFont())
    title = "Rebuild the deployment pipeline for the beta environment before the launch"
    width = metrics.horizontalAdvance("Rebuild the deployment") + 2.0
    three = title_lines(metrics, title, width, max_lines=3)
    assert (
        len(three) == 3
        and three[0] == "Rebuild the deployment"
        and three[1] == "pipeline for the beta"
    )
    assert three[2].startswith("environment")
    assert metrics.horizontalAdvance(three[2]) <= width
    one = title_lines(metrics, title, width, max_lines=1)
    assert len(one) == 1 and one[0].startswith("Rebuild the") and one[0].endswith("…")


def render_card(tab, step_id) -> QImage:
    node = scene(tab)._nodes[step_id]
    body = node.body_scene_rect()
    image = QImage(int(body.width()), int(body.height()), QImage.Format.Format_ARGB32)
    image.fill(scene(tab).palette().window().color())
    painter = QPainter(image)
    scene(tab).render(painter, QRectF(image.rect()), body)
    painter.end()
    return image


def block_colours(image: QImage) -> set[str]:
    """Every colour inside the key block, clear of the card's rounded corners."""
    from dplanner.theme.cards import KEY_BLOCK_W

    return {
        image.pixelColor(x, y).name()
        for x in range(4, int(KEY_BLOCK_W) - 3)
        for y in range(12, image.height() - 12)
    }


def inked(image: QImage, rect: QRectF, ground: QColor) -> QRectF:
    """The bounds of whatever inside ``rect`` departs from ``ground`` — where a glyph or a
    word actually landed."""
    found = [
        (x, y)
        for x in range(int(rect.left()), int(rect.right()))
        for y in range(int(rect.top()), int(rect.bottom()))
        if abs(image.pixelColor(x, y).lightness() - ground.lightness()) > 40
    ]
    if not found:
        return QRectF()
    xs, ys = [x for x, _ in found], [y for _, y in found]
    return QRectF(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)


def test_the_key_block_carries_who_works_the_step_over_its_key(project, tab):
    """The block down the left edge: the glyph lands where ``key_block_rects`` puts it, and
    under it the key, set level — its ink wider than it is tall, which a key read up a
    spine never was."""
    from dplanner.theme.cards import key_block_rects

    step = project.steps[0]
    image = render_card(tab, step.id)
    glyph, key = key_block_rects(QRectF(image.rect()), QFont())
    ground = image.pixelColor(4, 12)  # The block's own wash, above the pair.
    assert not inked(image, glyph, ground).isEmpty()
    word = inked(image, key, ground)
    assert word.width() > word.height()
    assert word.top() >= glyph.bottom()


def test_the_key_block_is_shaded_by_status(services, project, tab):
    """A status changes the block's wash — busy blue for in-progress, the good green for
    done — while the body keeps its own fill beside it."""
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.step_status.aspect import MODULE_ID as STATUS_ID
    from dplanner.modules.step_status.aspect import write as status
    from dplanner.theme.cards import KEY_BLOCK_W

    step = project.steps[0]
    image = render_card(tab, step.id)
    inside = image.pixelColor(int(KEY_BLOCK_W) + 8, image.height() // 2)  # Past the block.
    quiet = block_colours(image)
    assert inside.name() not in quiet  # The block is a shade of its own, even at rest.

    services.undo.push(
        SetModuleDataCommand(step.id, STATUS_ID, status("in-progress", today=date(2026, 9, 21)))
    )
    busy = block_colours(render_card(tab, step.id))
    assert busy != quiet
    busiest = max(busy, key=lambda name: QColor(name).blue() - QColor(name).red())
    assert QColor(busiest).blue() > QColor(busiest).red()  # A blue wash.

    services.undo.push(
        SetModuleDataCommand(step.id, STATUS_ID, status("done", today=date(2026, 9, 21)))
    )
    done = block_colours(render_card(tab, step.id))
    greenest = max(done, key=lambda name: QColor(name).green() - QColor(name).red())
    assert QColor(greenest).green() > QColor(greenest).red()  # A green wash.


def test_a_waits_clock_is_amber(services, project, tab):
    """A wait is nobody's work, and says so in the attention amber whatever its date — the
    one glyph in the block that is not the key's ink."""
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.domain.schedule import Wait
    from dplanner.modules.step_wait.aspect import MODULE_ID as WAIT_ID
    from dplanner.modules.step_wait.aspect import write as wait
    from dplanner.theme.cards import key_block_rects

    def amber(image: QImage) -> bool:
        glyph, _key = key_block_rects(QRectF(image.rect()), QFont())
        return any(
            (colour := image.pixelColor(x, y)).red() > colour.blue() + 60
            and colour.green() > colour.blue() + 30
            for x in range(int(glyph.left()), int(glyph.right()))
            for y in range(int(glyph.top()), int(glyph.bottom()))
        )

    step = project.steps[0]
    assert not amber(render_card(tab, step.id))  # A person, in the key's ink.
    services.undo.push(SetModuleDataCommand(step.id, WAIT_ID, wait(Wait(days=2.0))))
    assert amber(render_card(tab, step.id))


def test_the_reports_key_block_is_the_canvas_one():
    """``cli/`` may not read ``theme/``, so the report keeps a copy of the block's geometry;
    this is what keeps the copy honest."""
    from dplanner.cli.report import drawings
    from dplanner.theme import cards

    assert drawings.KEY_BLOCK_W == cards.KEY_BLOCK_W
    assert drawings.KEY_GLYPH == cards.KEY_GLYPH
    assert drawings.KEY_GAP == cards.KEY_GAP


def test_the_paper_draws_the_glyph(qapp):
    """The PDF renders the graph through QtSvg, which honours a narrower SVG than a browser:
    the glyph must come out in ink on paper, and a wait's in amber."""
    from PySide6.QtSvg import QSvgRenderer

    from dplanner.cli.report.drawings import (
        GRAPH_MARGIN,
        KEY_BLOCK_W,
        KEY_GAP,
        KEY_GLYPH,
        KEY_LINE,
        LIGHT,
        graph_svg,
    )
    from dplanner.cli.report.parts import Graph, Node
    from dplanner.theme.glyph_source import glyph_markup

    nodes = (
        Node("a", "S1", "Interview", 0, 0, 220, 76, glyph_markup=glyph_markup("person")),
        Node(
            "b",
            "W2",
            "Hold",
            0,
            120,
            220,
            76,
            glyph_markup=glyph_markup("clock"),
            glyph_tone="warn",
        ),
    )
    renderer = QSvgRenderer(graph_svg(Graph(nodes, ()), LIGHT).encode())
    size = renderer.defaultSize()
    image = QImage(size, QImage.Format.Format_ARGB32)
    image.fill(QColor(LIGHT.surface))
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    def glyph_pixels(node: Node) -> list[QColor]:
        top = node.y + (node.h - KEY_GLYPH - KEY_GAP - KEY_LINE) / 2 + GRAPH_MARGIN
        left = node.x + KEY_BLOCK_W / 2 - KEY_GLYPH / 2 + GRAPH_MARGIN
        return [
            image.pixelColor(int(left) + dx, int(top) + dy)
            for dx in range(int(KEY_GLYPH))
            for dy in range(int(KEY_GLYPH))
        ]

    assert any(colour.lightness() < 110 for colour in glyph_pixels(nodes[0]))
    assert any(
        colour.red() > colour.blue() + 60 and colour.green() > colour.blue() + 30
        for colour in glyph_pixels(nodes[1])
    )


def ink_in_corner(tab, step_id) -> int:
    """How far the card's bottom-right corner departs from its own fill, rendered over the
    theme's base: the stat's text pulls a pixel far from it, an empty corner stays flat.
    The card is rendered over the theme's own ground, since its ink is the theme's."""
    from dplanner.theme.cards import KEY_BLOCK_W, PAD_Y, PADDING

    node = scene(tab)._nodes[step_id]
    body = node.body_scene_rect()
    width, height = int(body.width()), int(body.height())
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(scene(tab).palette().window().color())
    painter = QPainter(image)
    scene(tab).render(painter, QRectF(image.rect()), body)
    painter.end()
    # The fill is sampled past the key block, whose key and wash are ink of their own.
    fill = image.pixelColor(int(KEY_BLOCK_W + PADDING) + 4, height // 2)
    line = int(PAD_Y) + 18
    return int(
        max(
            abs(image.pixelColor(x, y).lightness() - fill.lightness())
            for y in range(height - line, height - int(PAD_Y))
            for x in range(width - 70, width - int(PADDING))
        )
    )


def test_the_estimate_sits_inside_the_card_at_the_bottom_right(services, project, tab):
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.estimation.aspect import MODULE_ID as ESTIMATE_ID
    from dplanner.modules.estimation.aspect import write as estimate

    step = project.steps[0]
    assert ink_in_corner(tab, step.id) < 8  # An unestimated card has an empty corner.
    services.undo.push(SetModuleDataCommand(step.id, ESTIMATE_ID, estimate(3.0)))
    assert scene(tab)._nodes[step.id]._accent.stat_text == "3d"
    assert ink_in_corner(tab, step.id) > 60


# -- the ground: what is drawn under the graph, and whether gestures snap to it -----------------


def look_of(services):
    """The look as the per-user store has it — what the next window would wear."""
    from dplanner.framework.user_config import get_global
    from dplanner.modules.project_editor.look import Look
    from dplanner.modules.project_editor.module import LOOK_KEY, MODULE_ID

    return Look.from_json(get_global(MODULE_ID, LOOK_KEY))


def test_the_background_is_one_choice_of_several_remembered_per_user(
    services, project, tab, make_project
):
    context = services.context.current()
    assert state(services, "canvas.ground_dots", context).checked is True
    assert state(services, "canvas.ground_lines", context).checked is False

    services.actions.run("canvas.ground_lines", context)

    context = services.context.current()
    assert state(services, "canvas.ground_lines", context).checked is True
    assert state(services, "canvas.ground_dots", context).checked is False
    assert look_of(services).background == "lines"
    assert view(tab)._background == "lines"
    other = services.tabs.open("project", make_project("Later").id)
    assert other._view._background == "lines"


def test_snap_to_grid_is_a_toggle_every_canvas_follows(services, project, tab, make_project):
    context = services.context.current()
    assert state(services, "canvas.snap", context).checked is True
    assert scene(tab)._snap is True

    services.actions.run("canvas.snap", context)

    assert state(services, "canvas.snap", services.context.current()).checked is False
    assert look_of(services).snap is False
    assert scene(tab)._snap is False
    other = services.tabs.open("project", make_project("Later").id)
    assert other._scene._snap is False


def test_with_snapping_off_a_card_lands_where_it_was_left(app, services, project, tab):
    """Snapping is the gesture's: off, a drag stores whole units and nothing rounds them
    up to the grid on the way to disk."""
    services.actions.run("canvas.snap", services.context.current())
    step = project.steps[0]
    node = scene(tab)._nodes[step.id]
    start = centre_of(node)
    send(app, tab, QEvent.Type.MouseButtonPress, start)
    node.setPos(node.pos() + QPointF(37.0, 13.0))
    send(app, tab, QEvent.Type.MouseButtonRelease, start, Qt.MouseButton.NoButton)

    entry = placement_of(services, step.id)
    assert (entry["x"], entry["y"]) == (77.0, 53.0)

    body = body_of(tab, step.id)
    grip = QPointF(body.right() - 2.0, body.center().y() + 30.0)
    drag(app, tab, grip, grip + QPointF(37.0, 0.0))
    assert abs(placement_of(services, step.id)["w"] - 255.0) <= 1.0


def test_with_snapping_off_new_lands_exactly_under_the_click(services, project, tab, monkeypatch):
    services.actions.run("canvas.snap", services.context.current())
    tab._view.note_click(QPointF(403.0, 201.0))
    silence_details(monkeypatch)
    services.actions.run("steps.new", services.context.current())
    entry = project.steps[-1].module_data["project_editor"]
    assert (entry["x"], entry["y"]) == (403.0 - NODE_W / 2, 201.0 - NODE_H / 2)


def ground_pixel(tab, background: str, scene_point: QPointF) -> QColor:
    """The colour the view paints at a point of the plane under this background — through
    the viewport's own paint event, which is where ``drawBackground`` runs."""
    canvas_view = view(tab)
    canvas_view.set_background(background)
    image = canvas_view.viewport().grab().toImage()
    at = canvas_view.mapFromScene(scene_point)
    assert image.rect().contains(at), "the probe point is off the viewport"
    return QColor(image.pixelColor(at.x(), at.y()))


def a_grid_crossing_on_bare_ground(tab, pitch: float) -> QPointF:
    """A crossing of the grid that is on screen and under no card: the one nearest the
    viewport's top-left corner, or its bottom-right when a card covers that."""
    canvas_view = view(tab)
    shown = canvas_view.mapToScene(canvas_view.viewport().rect()).boundingRect()
    cards = [
        node.body_scene_rect().adjusted(-24, -24, 24, 24) for node in scene(tab)._nodes.values()
    ]
    for corner in (shown.topLeft() + QPointF(20, 20), shown.bottomRight() - QPointF(20, 20)):
        point = QPointF((corner.x() // pitch + 1) * pitch, (corner.y() // pitch + 1) * pitch)
        if not any(card.contains(point) for card in cards):
            return point
    raise AssertionError("no bare grid crossing on screen")


def test_the_grid_is_painted_on_the_ground_and_only_when_asked(app, services, project, tab):
    """A dot lands on every 32nd unit at 1:1 (the grid's pitch for that zoom): a crossing
    is a dot under Dots, and bare ground under Plain — and so is the plane between."""
    from dplanner.modules.project_editor.ground import pitch_for

    pitch = pitch_for(view(tab)._zoom)
    assert pitch == 32.0
    crossing = a_grid_crossing_on_bare_ground(tab, pitch)
    between = crossing + QPointF(pitch / 2, pitch / 2)
    bare = ground_pixel(tab, "none", crossing)
    assert ground_pixel(tab, "none", between) == bare
    assert ground_pixel(tab, "dots", crossing) != bare
    assert ground_pixel(tab, "dots", between) == bare
    assert ground_pixel(tab, "lines", crossing + QPointF(0.0, pitch / 2)) != bare  # On a line.
    assert ground_pixel(tab, "crosses", crossing) != bare


# -- the Edit menu: cut, copy, paste, duplicate --------------------------------------------------
#
# The clipboard is the process's, so these read it back through Qt; what a clip holds and how
# a paste clones it is pinned Qt-free in test_project_editor_clipboard.py.


def clipboard_steps():
    from PySide6.QtGui import QGuiApplication

    from dplanner.modules.project_editor.clipboard import MIME_TYPE, from_json

    data = QGuiApplication.clipboard().mimeData()
    if data is None or not data.hasFormat(MIME_TYPE):
        return []
    return from_json(bytes(data.data(MIME_TYPE).data()))


def linked_pair(services, project):
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    return first, second


def test_copy_puts_the_steps_on_the_clipboard_beside_their_titles(services, project, tab):
    from PySide6.QtGui import QGuiApplication

    first, second = linked_pair(services, project)
    services.actions.run("steps.copy", context_of(services, first.id, second.id))

    assert [c.title for c in clipboard_steps()] == ["Read the spec", "Draft the model"]
    assert QGuiApplication.clipboard().text() == "Read the spec\nDraft the model"
    assert not services.undo.can_undo() or services.undo.undo_text() == "Change Links"


def test_paste_is_one_undo_step_that_lands_at_the_click_and_selects_the_copies(
    services, project, tab
):
    first, second = linked_pair(services, project)
    services.actions.run("steps.copy", context_of(services, first.id, second.id))
    tab._view.note_click(QPointF(900.0, 700.0))

    services.actions.run("steps.paste", services.context.current())

    assert len(project.steps) == 4
    copy_first, copy_second = project.steps[2:]
    assert (copy_first.title, copy_second.title) == ("Read the spec", "Draft the model")
    assert services.document.step(copy_second.id).edges["requires"] == [copy_first.id]
    assert services.undo.undo_text() == "Paste 2 Steps"
    assert set(scene(tab).selection().steps) == {copy_first.id, copy_second.id}
    placed = [step.module_data["project_editor"] for step in (copy_first, copy_second)]
    assert min(p["x"] for p in placed) == snapped(900.0 - NODE_W / 2, GRID)
    assert min(p["y"] for p in placed) == snapped(700.0 - NODE_H / 2, GRID)
    services.undo.undo()
    assert [s.id for s in project.steps] == [first.id, second.id]


def test_pasting_twice_stacks_the_blocks_rather_than_hiding_one(services, project, tab):
    first, _second = project.steps
    services.actions.run("steps.copy", context_of(services, first.id))
    tab._view.note_click(QPointF(900.0, 700.0))
    services.actions.run("steps.paste", services.context.current())
    services.actions.run("steps.paste", services.context.current())
    one, two = (step.module_data["project_editor"] for step in project.steps[-2:])
    assert two["y"] > one["y"] and two["x"] == one["x"]


def test_paste_reaches_another_project_disconnected_like_any_paste(
    services, project, tab, make_project
):
    _first, second = linked_pair(services, project)
    services.actions.run("steps.copy", context_of(services, second.id))
    other = make_project("Rollout")
    services.tabs.open("project", other.id)

    services.actions.run("steps.paste", services.context.current())

    assert [s.title for s in other.steps] == ["Draft the model"]
    assert "requires" not in other.steps[0].edges
    assert len(project.steps) == 2


def test_paste_needs_a_canvas_and_steps_on_the_clipboard(services, project, tab):
    from PySide6.QtGui import QGuiApplication

    QGuiApplication.clipboard().setText("only text")
    assert not state(services, "steps.paste", services.context.current()).enabled

    services.actions.run("steps.copy", context_of(services, *[s.id for s in project.steps]))
    pasteable = state(services, "steps.paste", services.context.current())
    assert pasteable.enabled and pasteable.label == "&Paste 2 Steps"

    services.tabs.close_activity(tab)
    assert not state(services, "steps.paste", services.context.current()).enabled


def test_cut_copy_and_duplicate_act_on_the_chosen_steps_wherever_they_are(services, project):
    """No canvas open: the verbs still read the selection, the way Delete does, so a table's
    right-click menu can offer them. Only Paste needs the canvas — it is the target."""
    context = context_of(services, project.steps[0].id)
    for verb in ("steps.cut", "steps.copy", "steps.duplicate", "steps.delete_edit"):
        assert state(services, verb, context).enabled, verb
    assert not state(services, "steps.paste", context).enabled
    both = context_of(services, *[s.id for s in project.steps])
    assert state(services, "steps.cut", both).label == "Cu&t 2 Steps"
    assert state(services, "steps.copy", both).label == "&Copy 2 Steps"
    assert state(services, "steps.duplicate", both).label == "D&uplicate 2 Steps"
    assert not state(services, "steps.copy", context_of(services)).enabled


def test_duplicate_lands_one_row_below_selected_and_leaves_the_clipboard_alone(
    services, project, tab
):
    from PySide6.QtGui import QGuiApplication

    from dplanner.modules.project_editor.placement import below, positions

    QGuiApplication.clipboard().setText("untouched")
    first, second = linked_pair(services, project)
    was = positions(services.document, project)[second.id]

    services.actions.run("steps.duplicate", context_of(services, second.id))

    copy = project.steps[-1]
    assert copy.title == "Draft the model" and copy.id != second.id
    assert "requires" not in copy.edges  # The link to the original's upstream is not copied.
    assert services.document.step(second.id).edges["requires"] == [first.id]
    assert services.undo.undo_text() == "Duplicate Step"
    assert list(scene(tab).selection().steps) == [copy.id]
    entry = copy.module_data["project_editor"]
    assert (entry["x"], entry["y"]) == tuple(snapped(v) for v in below(*was))
    assert QGuiApplication.clipboard().text() == "untouched"


def test_cut_is_copy_then_delete_and_a_paste_after_it_brings_fresh_steps(services, project, tab):
    first, second = linked_pair(services, project)

    services.actions.run("steps.cut", context_of(services, first.id, second.id))

    assert project.steps == []
    assert [c.title for c in clipboard_steps()] == ["Read the spec", "Draft the model"]
    assert services.undo.undo_text() == "Cut 2 Steps"
    services.undo.undo()
    assert [s.id for s in project.steps] == [first.id, second.id]

    services.actions.run("steps.paste", services.context.current())
    assert len(project.steps) == 4
    assert {s.id for s in project.steps[2:]}.isdisjoint({first.id, second.id})


def test_cut_takes_the_links_into_the_cut_steps_along(services, project, tab):
    """Cut removes the way Delete does — the same command, so the same tidying."""
    _first, second, third = chain(services, project)
    services.actions.run("steps.cut", context_of(services, second.id))

    assert "requires" not in services.document.step(third.id).edges
    assert services.undo.undo_text() == "Cut Step"
    services.undo.undo()
    assert services.document.step(third.id).edges["requires"] == [second.id]


def test_a_copy_carries_its_attachments(services, project, tab):
    from dplanner.domain.assets import attach

    first = project.steps[0]
    name = attach(services.repo.files(first.id, "step_description"), b"\x89PNG-ish", "shot.png")
    services.document.set_text(first.id, "step_description", f"![shot]({name})")

    services.actions.run("steps.duplicate", context_of(services, first.id))

    copy = project.steps[-1]
    assert copy.module_text["step_description"] == f"![shot]({name})"
    assert services.repo.files(copy.id, "step_description").read_bytes(name) == b"\x89PNG-ish"


def test_a_copied_test_is_re_minted_and_a_copied_agent_run_is_forgotten(services, project, tab):
    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.step_agent_run.aspect import MODULE_ID as RUN_ID
    from dplanner.modules.step_agent_run.aspect import write as write_run
    from dplanner.modules.testing.aspect import Test, read, write

    first, second = project.steps
    services.undo.push(
        SetModuleDataCommand(first.id, "testing", write([Test("T100", "a"), Test("T101", "b")]))
    )
    services.undo.push(SetModuleDataCommand(second.id, "testing", write([Test("T102", "c")])))
    services.undo.push(SetModuleDataCommand(first.id, RUN_ID, write_run("working")))

    services.actions.run("steps.duplicate", context_of(services, first.id, second.id))

    copy_first, copy_second = project.steps[2:]
    assert [t.id for t in read(copy_first)] == ["T103", "T104"]
    assert [t.id for t in read(copy_second)] == ["T105"]
    assert RUN_ID not in copy_first.module_data
    assert RUN_ID in first.module_data


def test_the_edit_menu_delete_is_the_step_menu_delete_in_a_second_seat(services, project, tab):
    context = context_of(services, *[s.id for s in project.steps])
    assert state(services, "steps.delete_edit", context).label == "&Delete 2 Steps"
    assert state(services, "steps.delete", context).label == "&Delete 2 Steps"
    assert services.actions.spec("steps.delete_edit").palette is False
    services.actions.run("steps.delete_edit", context)
    assert project.steps == [] and services.undo.undo_text() == "Delete 2 Steps"


def test_the_edit_menu_reads_history_clipboard_selection(services):
    menu = next(a.menu() for a in services.window.menuBar().actions() if a.text() == "&Edit")
    rendered = []
    for action in menu.actions():
        if not action.isVisible():
            continue
        rendered.append("|" if action.isSeparator() else action.text())
    assert rendered == [
        "&Undo",
        "&Redo",
        "|",
        "Cu&t Step",
        "&Copy Step",
        "&Paste",
        "Dup&licate Step",
        "&Delete Step",
        "|",
        "Select &All Steps",
    ]


# -- the spatial verbs: one vocabulary with the canvas -------------------------------------------


def test_tidy_is_one_undo_step_and_offered_as_a_sort(services, project, tab):
    """The sixth sort persists like the five before it: one entry, one Ctrl+Z."""
    from dplanner.modules.project_editor.layout_verbs import SORT_ACTION_IDS

    assert "canvas.sort_tidy" in SORT_ACTION_IDS
    assert tab.run_action("canvas.sort_tidy")
    assert services.undo.undo_text() == "Tidy Layout"
    for step in project.steps:
        assert "project_editor" in step.module_data
    services.undo.undo()
    for step in project.steps:
        assert "project_editor" not in step.module_data


def test_layout_shift_builds_the_command_the_divide_gesture_pushes(app, services, project, tab):
    """``dplanner layout shift`` cannot reach a window's undo stack, so the claim it makes
    — one entry, the canvas's own — is proved by the command object: the gesture's seats
    are ``geometry.shift``'s, and ``divide_command`` on the stack undoes as one."""
    from dplanner.modules.project_editor.geometry import divide_command, shift
    from dplanner.modules.project_editor.placement import positions
    from dplanner.modules.project_editor.positions import node_size

    first, second, third = chain(services, project)
    # The seats the gesture saw: the scene snaps an ambient seat onto the grid as it
    # places the card, so they are the model's positions as the canvas shows them.
    before = positions(services.document, project) | {
        step_id: (seat.x(), seat.y())
        for step_id, seat in seats_of(tab, first, second, third).items()
    }
    sizes = {step.id: node_size(step) for step in project.steps}
    services.actions.run("canvas.divide_vertical", services.context.current())
    cut = gap_between(tab, first, second)
    drag(app, tab, cut, cut + QPointF(120.0, 0.0))
    assert services.undo.undo_text() == "Divide Graph"

    def seats():
        return {
            step.id: (placement_of(services, step.id)["x"], placement_of(services, step.id)["y"])
            for step in (second, third)
        }

    gestured = seats()
    moved = shift(before, sizes, "x", cut.x(), 120.0)
    assert moved == gestured
    services.undo.undo()

    services.undo.push(divide_command(project, moved))
    assert services.undo.undo_text() == "Divide Graph"
    assert seats() == gestured
    assert "project_editor" not in services.document.step(first.id).module_data
    services.undo.undo()
    assert "project_editor" not in services.document.step(second.id).module_data
