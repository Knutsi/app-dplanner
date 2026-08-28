"""A project open in a tab: the canvas, the panels it steers, and the gestures between them.

The canvas is exercised through the scene's signals rather than through synthetic mouse
events: what matters is that a gesture becomes the right command on the undo stack, and a
QTest.mousePress would test Qt rather than this module.

The detail panels are the window's, not the tab's, so they are reached through the window —
which is the point: however many projects are open, there is one of each.
"""

import pytest
from PySide6.QtCore import QEvent, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter
from PySide6.QtWidgets import QGraphicsView

from dplanner.domain.commands import (
    AddNodeCommand,
    RemoveNodeCommand,
    SetEdgesCommand,
    SetFieldCommand,
)
from dplanner.domain.model import Project, Step
from dplanner.framework.context import SCOPE_SELECTION
from dplanner.modules.project_editor.modes import CONNECT, IDLE, PAN
from dplanner.modules.project_editor.module import PANEL_ID as PROJECT_PANEL_ID
from dplanner.modules.project_editor.positions import NODE_H, NODE_W
from dplanner.modules.project_editor.renderers import FILL_ALPHA
from dplanner.modules.project_editor.selection import EDGE_KIND, EdgeRef
from dplanner.modules.step_properties.module import PANEL_ID as STEP_PANEL_ID
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, DEFAULT, LIGHT


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


def step_panel(services):
    return services.window.dock.widget_for(STEP_PANEL_ID)


def project_panel(services):
    return services.window.dock.widget_for(PROJECT_PANEL_ID)


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


def send(app, tab, kind, scene_pos, buttons=Qt.MouseButton.LeftButton):
    viewport = view(tab).viewport()
    local = QPointF(view(tab).mapFromScene(scene_pos))
    # The global position has to be real: QGraphicsScene picks the item under the *screen*
    # point, so a placeholder here makes every press land on empty canvas.
    event = QMouseEvent(
        kind,
        local,
        QPointF(viewport.mapToGlobal(local.toPoint())),
        Qt.MouseButton.LeftButton,
        buttons,
        Qt.KeyboardModifier.NoModifier,
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


def test_selecting_a_node_publishes_the_step_and_shows_it(services, project, tab):
    """Publishing *is* how the panel learns: the canvas never reaches for it."""
    step = project.steps[0]
    scene(tab).select_step(step.id)
    uris = [node.uri for node in services.context.current().scope(SCOPE_SELECTION)]
    assert uris == [f"app://selection/step/{step.id}"]
    assert step_panel(services).current_step_id() == step.id


def test_deselecting_returns_the_area_to_the_project_form(services, project, tab):
    dock = services.window.dock
    scene(tab).select_step(project.steps[0].id)
    assert dock.is_panel_showing(STEP_PANEL_ID)
    scene(tab).select_step(None)
    assert not dock.is_panel_showing(STEP_PANEL_ID)
    assert dock.is_panel_showing(PROJECT_PANEL_ID)
    assert project_panel(services).current_project_id() == project.id


def test_two_panes_share_one_detail_panel(services, project, tab):
    """The reason the panel is the window's. Two projects side by side is two canvases and
    one editor — and the editor shows whichever pane the user is in, because only that pane
    may publish a selection."""
    other = Project(title="Build")
    AddNodeCommand(services.document.id, other).redo(services.document)
    AddNodeCommand(other.id, Step(title="Ship it")).redo(services.document)
    second = services.tabs.open("project", other.id)
    services.tabs.move_current_right()
    assert services.tabs.group_count() == 2

    scene(second).select_step(other.steps[0].id)
    assert step_panel(services).current_step_id() == other.steps[0].id

    # The user moves to the other pane. Its activation republishes what it has selected.
    second.on_deactivated()
    tab.on_activated()
    scene(tab).select_step(project.steps[0].id)
    assert step_panel(services).current_step_id() == project.steps[0].id

    # And a background pane re-syncing its canvas does not take the panel with it.
    scene(second).select_step(None)
    assert step_panel(services).current_step_id() == project.steps[0].id


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


def test_double_clicking_empty_space_creates_a_step_there(app, services, project, tab):
    send(app, tab, QEvent.Type.MouseButtonDblClick, QPointF(700, 500))

    assert len(project.steps) == 3
    # Centred on the click: 700 - NODE_W / 2, snapped to the grid.
    assert project.steps[-1].module_data["project_editor"]["x"] == 592.0


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
    """The drop is not a special case: it selects both ends and runs `steps.link`."""
    first, second = project.steps
    scene(tab).link_requested.emit(first.id, second.id)

    assert services.document.step(second.id).edges["requires"] == [first.id]
    assert services.context.current().selected_entities("step") == [first.id, second.id]


def test_a_refused_drop_says_why_instead_of_doing_nothing(services, project, tab):
    first, _second, third = chain(services, project)
    # third already waits on first through second; linking first onto third closes the loop.
    scene(tab).link_requested.emit(third.id, first.id)

    assert "requires" not in services.document.step(first.id).edges
    assert "cycle" in services.window.statusBar().currentMessage()


def test_a_drop_onto_an_already_linked_node_says_so(services, project, tab):
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    scene(tab).link_requested.emit(first.id, second.id)
    assert services.window.statusBar().currentMessage() == "Already linked"


def test_the_selection_keeps_the_order_it_was_made_in(services, project, tab):
    """`Context.selected_entities` promises the selecting view's order, and a two-step verb
    is the reason that promise matters."""
    first, second = project.steps
    scene(tab).select_steps([second.id, first.id])
    assert services.context.current().selected_entities("step") == [second.id, first.id]


def test_creating_on_the_canvas_is_one_undo_step(services, project, tab):
    scene(tab).create_requested.emit(240.0, 80.0)
    assert len(project.steps) == 3
    assert project.steps[-1].module_data["project_editor"]["x"] == 240.0
    assert services.undo.undo_text() == "Add Step"
    services.undo.undo()
    assert len(project.steps) == 2


def test_deleting_the_shown_step_leaves_the_panel_empty(app, services, project, tab, monkeypatch):
    from dplanner.modules.project_editor import verbs

    monkeypatch.setattr(verbs, "confirm", lambda *_args: True)
    step = project.steps[0]
    scene(tab).select_step(step.id)
    press_key(app, tab, Qt.Key.Key_Delete)

    assert step_panel(services).current_step_id() is None
    assert len(project.steps) == 1


# -- the project form ---------------------------------------------------------------------------


def test_the_project_form_edits_the_project(services, project, tab):
    panel = project_panel(services)
    assert panel.current_project_id() == project.id
    panel.summary_edit.setText("Replace the index")
    panel.summary_edit.editingFinished.emit()
    assert project.summary == "Replace the index"
    services.undo.undo()
    assert project.summary == ""


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


def test_link_wants_exactly_two_steps(services, project, tab):
    first, second = project.steps
    assert not state(services, "steps.link", context_of(services)).enabled
    assert not state(services, "steps.link", context_of(services, first.id)).enabled
    assert state(services, "steps.link", context_of(services, first.id, second.id)).enabled


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


def test_delete_means_the_verb_the_selection_calls_for(app, services, project, tab, monkeypatch):
    """One key, two verbs, and no branch on the canvas: the first the context allows runs."""
    from dplanner.modules.project_editor import verbs

    monkeypatch.setattr(verbs, "confirm", lambda *_args: True)
    first, second = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))

    edge_item(tab, second, first).setSelected(True)
    press_key(app, tab, Qt.Key.Key_Delete)
    assert len(project.steps) == 2 and "requires" not in services.document.step(second.id).edges

    scene(tab).select_step(second.id)
    press_key(app, tab, Qt.Key.Key_Delete)
    assert len(project.steps) == 1


def test_deleting_a_multiple_selection_is_one_undo_step(services, project, tab, monkeypatch):
    from dplanner.modules.project_editor import verbs

    monkeypatch.setattr(verbs, "confirm", lambda *_args: True)
    first, second = project.steps
    scene(tab).select_steps([first.id, second.id])
    services.actions.run("steps.delete", services.context.current())

    assert project.steps == []
    assert services.undo.undo_text() == "Delete 2 Steps"
    services.undo.undo()
    assert len(project.steps) == 2


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


def test_the_canvas_is_a_plane_no_graph_can_move(services, project, tab, monkeypatch):
    """The scrollable area is a constant centred on the origin.

    Nothing about the graph may reach it — it used to be grown from the items, and every
    node that moved re-ranged the scroll bars under a fixed value, which read as the canvas
    panning away under the drag. A constant cannot do that, and it is also what lets the
    user keep panning long after the last node is behind them.
    """
    from dplanner.modules.project_editor import verbs

    monkeypatch.setattr(verbs, "confirm", lambda *_args: True)
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
    assert moved == pytest.approx(5_000.0, abs=2.0)


def test_the_canvas_has_no_scroll_bars(services, project, tab):
    """A bar whose handle is a two-hundredth of its groove says nothing true; the minimap
    is what tells the user where they are. The bars still exist, so the wheel still works."""
    canvas_view = view(tab)
    policy = Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert canvas_view.horizontalScrollBarPolicy() == policy
    assert canvas_view.verticalScrollBarPolicy() == policy


# -- the canvas follows the theme ----------------------------------------------------------------


@pytest.fixture
def themed(app):
    """A theme is applied application-wide, so put the default back for whatever runs next."""
    yield app
    apply_theme(app, DEFAULT)


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

    from dplanner.modules.project_editor.renderers import title_lines

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


def test_the_minimap_goes_off_screen_without_a_graph(app, services, project, tab, monkeypatch):
    """An empty box is worse than no box — DESIGN.md's rule for a panel, one surface down."""
    from dplanner.modules.project_editor import verbs

    monkeypatch.setattr(verbs, "confirm", lambda *_args: True)
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
    assert view(tab).dragMode() == QGraphicsView.DragMode.ScrollHandDrag

    release_key(app, tab, Qt.Key.Key_Space)
    assert modes(tab).current().name == IDLE
    assert view(tab).dragMode() == QGraphicsView.DragMode.RubberBandDrag


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


def test_closing_the_tab_lets_its_toolbars_go(services, project, tab):
    """A toolbar subscribes to the context, and unlike the menu bar it does not outlive
    its tab. A leaked subscription would restate a dead widget on every selection change."""
    before = len(services.context.changed._slots)
    tab.close()
    assert len(services.context.changed._slots) < before


# -- selecting everything ----------------------------------------------------------------------


def test_select_all_selects_every_step(app, services, project, tab):
    press_key(app, tab, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert set(scene(tab).selection().steps) == {step.id for step in project.steps}
    published = services.context.current().selected_entities("step")
    assert set(published) == {step.id for step in project.steps}


def test_select_all_is_disabled_off_a_canvas(services):
    state = services.actions.spec("steps.select_all").state(services.context.current())
    assert not state.enabled


def test_select_all_is_disabled_on_an_empty_project(services, project, tab):
    for step in list(project.steps):
        services.undo.push(RemoveNodeCommand(step.id))
    state = services.actions.spec("steps.select_all").state(services.context.current())
    assert not state.enabled


def test_right_clicking_inside_a_multi_selection_keeps_it(services, project, tab):
    """The menu must read the selection the user made, not collapse it to the node under
    the cursor — or "Delete 2 Steps" could never be said."""
    first, second = project.steps
    scene(tab).select_steps([first.id, second.id])

    tab._select_for_menu(scene(tab).node(first.id))
    assert set(scene(tab).selection().steps) == {first.id, second.id}


def test_right_clicking_an_unselected_step_makes_it_current(services, project, tab):
    first, second = project.steps
    scene(tab).select_step(first.id)

    tab._select_for_menu(scene(tab).node(second.id))
    assert scene(tab).selection().steps == (second.id,)


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


# -- regions ------------------------------------------------------------------------------------


def add_region(services, project, x, y, w, h, title="Region"):
    from dplanner.modules.project_editor.regions import (
        new_region,
        read_regions,
        set_regions_command,
    )

    region = new_region(title, x, y, w, h)
    services.undo.push(
        set_regions_command(project, [*read_regions(project), region], "Add Region")
    )
    return region


def regions_of(services, project):
    from dplanner.modules.project_editor.regions import read_regions

    return read_regions(services.document.project(project.id))


def test_dragging_out_a_region_is_one_undo_step(app, services, project, tab):
    tab.set_region_mode(True)
    drag(app, tab, QPointF(400.0, 296.0), QPointF(720.0, 536.0))

    found = regions_of(services, project)
    assert len(found) == 1
    assert (found[0].x, found[0].y, found[0].w, found[0].h) == (400.0, 296.0, 320.0, 240.0)
    assert services.undo.undo_text() == "Add Region"
    # One region ends the mode, the way one link ends connect.
    assert view(tab).modes.current().name == IDLE
    services.undo.undo()
    assert regions_of(services, project) == []


def test_a_body_drag_carries_the_steps_whose_centres_lie_inside(app, services, project, tab):
    first, second = project.steps  # at (40, 40) and (40, 160) in the automatic layout
    region = add_region(services, project, 0.0, 0.0, 300.0, 120.0)  # first inside, second out

    drag(app, tab, QPointF(280.0, 80.0), QPointF(440.0, 240.0))  # body: off node, off strip

    found = regions_of(services, project)[0]
    assert (found.x, found.y) == (160.0, 160.0)
    from dplanner.modules.project_editor.positions import read_position

    assert read_position(services.document.step(first.id)) == (200.0, 200.0)
    assert read_position(services.document.step(second.id)) is None
    assert services.undo.undo_text() == "Move Region"

    services.undo.undo()  # One step back restores the frame and the carried step together.
    assert (regions_of(services, project)[0].x, regions_of(services, project)[0].y) == (
        region.x,
        region.y,
    )
    assert "project_editor" not in services.document.step(first.id).module_data


def test_a_title_drag_moves_the_frame_alone(app, services, project, tab):
    first, _second = project.steps
    add_region(services, project, 0.0, 0.0, 300.0, 120.0)

    drag(app, tab, QPointF(260.0, 12.0), QPointF(340.0, 92.0))  # the title strip

    found = regions_of(services, project)[0]
    assert (found.x, found.y) == (80.0, 80.0)
    assert "project_editor" not in services.document.step(first.id).module_data


def test_the_corner_grip_resizes(app, services, project, tab):
    add_region(services, project, 400.0, 296.0, 200.0, 120.0)

    drag(app, tab, QPointF(592.0, 408.0), QPointF(840.0, 656.0))  # the bottom-right grip

    found = regions_of(services, project)[0]
    # The drag runs through the view's pixel grid, so allow one grid cell of rounding.
    assert abs(found.w - 440.0) <= 8.0 and abs(found.h - 360.0) <= 8.0
    assert found.w % 8 == 0 and found.h % 8 == 0
    assert (found.x, found.y) == (400.0, 296.0)
    assert services.undo.undo_text() == "Resize Region"


def test_double_clicking_the_title_renames(app, services, project, tab, monkeypatch):
    add_region(services, project, 400.0, 300.0, 200.0, 120.0)
    monkeypatch.setattr(
        "dplanner.modules.project_editor.region_verbs.QInputDialog.getText",
        lambda *_args, **_kwargs: ("Database setup", True),
    )

    send(app, tab, QEvent.Type.MouseButtonDblClick, QPointF(500.0, 312.0))

    assert regions_of(services, project)[0].title == "Database setup"
    assert services.undo.undo_text() == "Rename Region"


def test_the_delete_key_reaches_a_selected_region(app, services, project, tab, monkeypatch):
    region = add_region(services, project, 400.0, 300.0, 200.0, 120.0)
    monkeypatch.setattr(
        "dplanner.modules.project_editor.region_verbs.confirm", lambda *_args: True
    )
    scene(tab).select_region(region.id)
    press_key(app, tab, Qt.Key.Key_Delete)

    assert regions_of(services, project) == []
    assert services.undo.undo_text() == "Delete Region"


def test_a_selected_region_reaches_the_context(services, project, tab):
    region = add_region(services, project, 400.0, 300.0, 200.0, 120.0)
    scene(tab).select_region(region.id)
    uris = [node.uri for node in services.context.current().scope(SCOPE_SELECTION)]
    assert uris == [f"app://selection/region/{region.id}"]


def test_a_node_over_a_region_still_drags_as_a_node(app, services, project, tab):
    first, _second = project.steps
    add_region(services, project, 0.0, 0.0, 300.0, 120.0)
    node = scene(tab)._nodes[first.id]

    start = centre_of(node)
    send(app, tab, QEvent.Type.MouseButtonPress, start)
    node.setPos(node.pos() + QPointF(240.0, 0.0))
    send(app, tab, QEvent.Type.MouseButtonRelease, start, Qt.MouseButton.NoButton)

    assert services.undo.undo_text() == "Move Step"
    assert (regions_of(services, project)[0].x, regions_of(services, project)[0].y) == (
        0.0,
        0.0,
    )
