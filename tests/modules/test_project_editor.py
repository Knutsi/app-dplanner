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
from dplanner.modules.project_editor.modes import CONNECT, IDLE, LASSO, PAN, REGION_CREATE
from dplanner.modules.project_editor.module import PANEL_ID as PROJECT_PANEL_ID
from dplanner.modules.project_editor.positions import NODE_H, NODE_W, snapped
from dplanner.modules.project_editor.renderers import (
    BADGE_INSET,
    FILL_ALPHA,
    ICON_D,
    ICON_GAP,
    LIFT,
    PAINT_MARGIN,
    medallion_end,
)
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


def send(
    app,
    tab,
    kind,
    scene_pos,
    buttons=Qt.MouseButton.LeftButton,
    modifiers=Qt.KeyboardModifier.NoModifier,
):
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
    """A double-click runs the same creation the New verbs do, so it wears the same name."""
    scene(tab).create_requested.emit(240.0, 80.0)
    assert len(project.steps) == 3
    assert project.steps[-1].module_data["project_editor"]["x"] == 240.0
    assert services.undo.undo_text() == "New Step"
    services.undo.undo()
    assert len(project.steps) == 2


# -- New, and where a new node lands -------------------------------------------------------


def answer_new_dialog(monkeypatch, title):
    """The New verbs ask for a name; hand one over rather than opening a modal.

    Patched by name rather than through the module's re-exported ``QInputDialog``, which is
    the form the region verbs' test already uses and the only one strict typing accepts.
    """
    monkeypatch.setattr(
        "dplanner.modules.project_editor.verbs.QInputDialog.getText",
        staticmethod(lambda *_a, **_k: (title, True)),
    )


def new_specs(services):
    return [
        spec
        for spec in services.actions.all_specs()
        if spec.menu == "Step" and spec.submenu == "New"
    ]


def named(services, title):
    """The New action for a kind, by the name a person reads."""
    return next(spec for spec in new_specs(services) if title in spec.label)


def test_new_is_a_submenu_of_the_kinds_a_step_can_be(services, project, tab):
    assert [spec.label for spec in new_specs(services)] == [
        "&Step…",
        "&Feature…",
        "&Milestone…",
        "&Agent Step…",
        "&Check…",
    ]
    # The plain verb keeps its id: it is bound to N and wears the toolbar's plus.
    assert new_specs(services)[0].id == "steps.new"


def test_a_facet_is_not_offered_as_a_kind(services, project, tab):
    """New offers what a node *is*, never what it carries — "New Description" is nonsense."""
    labels = " ".join(spec.label for spec in new_specs(services))
    assert "Description" not in labels and "Estimate" not in labels


def test_creating_a_kind_marks_it_in_the_same_undo_step(services, project, tab, monkeypatch):
    from dplanner.modules.feature.aspect import is_feature

    answer_new_dialog(monkeypatch, "Bulk import")
    services.actions.run(named(services, "Feature").id, services.context.current())
    created = project.steps[-1]
    assert created.title == "Bulk import" and is_feature(created) is True
    assert services.undo.undo_text() == "New Feature"
    services.undo.undo()
    assert len(project.steps) == 2


def test_a_new_milestone_arrives_with_a_generated_label(services, project, tab, monkeypatch):
    from dplanner.modules.step_milestone.aspect import read as milestone_label

    answer_new_dialog(monkeypatch, "Ship it")
    services.actions.run(named(services, "Milestone").id, services.context.current())
    assert milestone_label(project.steps[-1]) == "v1"


def test_a_new_step_lands_where_the_canvas_was_last_clicked(services, project, tab, monkeypatch):
    tab._view.note_click(QPointF(400.0, 200.0))
    answer_new_dialog(monkeypatch, "Placed")
    services.actions.run("steps.new", services.context.current())
    entry = project.steps[-1].module_data["project_editor"]
    # Centred on the click, then snapped to the grid every stored position lands on: the
    # node appears under the cursor rather than with its corner there.
    assert (entry["x"], entry["y"]) == (snapped(400.0 - NODE_W / 2), snapped(200.0 - NODE_H / 2))


def test_a_right_click_counts_as_the_click_new_places_at(services, project, tab, monkeypatch):
    """The menu's own New lands where the menu was raised, not where the mouse last was."""
    from dplanner.modules.project_editor import module as editor

    class _Unshown:
        """The handler ends in a modal exec(); the test wants everything up to it."""

        def exec(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(editor, "build_menu", lambda *a, **k: _Unshown())
    tab._view.note_click(QPointF(0.0, 0.0))
    tab._on_context_menu(tab._view.mapFromScene(QPointF(560.0, 320.0)))
    answer_new_dialog(monkeypatch, "From the menu")
    services.actions.run("steps.new", services.context.current())
    entry = project.steps[-1].module_data["project_editor"]
    assert (entry["x"], entry["y"]) == (snapped(560.0 - NODE_W / 2), snapped(320.0 - NODE_H / 2))


def test_a_canvas_nobody_clicked_leaves_the_node_to_the_ambient_layout(
    services, project, tab, monkeypatch
):
    answer_new_dialog(monkeypatch, "Unplaced")
    services.actions.run("steps.new", services.context.current())
    assert "project_editor" not in project.steps[-1].module_data


def test_a_new_step_is_selected_the_moment_it_exists(services, project, tab, monkeypatch):
    """New leaves you on what you just made: the panel beside the canvas is already showing
    it, so naming a step and describing it are one gesture rather than two."""
    answer_new_dialog(monkeypatch, "Placed")
    services.actions.run("steps.new", services.context.current())
    created = project.steps[-1]
    assert list(scene(tab).selection().steps) == [created.id]
    assert step_panel(services).current_step_id() == created.id


def test_two_new_steps_in_a_row_do_not_land_on_one_another(services, project, tab, monkeypatch):
    """The remembered point steps one row on after it is used, so pressing New twice leaves
    two nodes where a stale point would have hidden one under the other."""
    from dplanner.modules.project_editor.sorts import V_GAP

    tab._view.note_click(QPointF(400.0, 200.0))
    answer_new_dialog(monkeypatch, "First")
    services.actions.run("steps.new", services.context.current())
    answer_new_dialog(monkeypatch, "Second")
    services.actions.run("steps.new", services.context.current())

    first, second = (step.module_data["project_editor"] for step in project.steps[-2:])
    assert (second["x"], second["y"]) == (first["x"], snapped(first["y"] + NODE_H + V_GAP))


def test_a_double_click_moves_the_point_on_too(app, services, project, tab, monkeypatch):
    """It pointed at a spot in the same sense a right-click did, so New after it lands
    below what the double-click made rather than on top of it."""
    tab._view.note_click(QPointF(400.0, 200.0))  # The press a double-click begins with.
    scene(tab).create_requested.emit(400.0, 200.0)
    answer_new_dialog(monkeypatch, "After the double-click")
    services.actions.run("steps.new", services.context.current())
    made, after = (step.module_data["project_editor"] for step in project.steps[-2:])
    assert after["y"] > made["y"]


def test_deleting_the_shown_step_leaves_the_panel_empty(app, services, project, tab):
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


def test_deleting_a_multiple_selection_is_one_undo_step(services, project, tab):
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


# -- a selected node is a card off the table -----------------------------------------------


def painted_under(tab, step_id, background: str) -> QColor:
    """The ground just below a node's seat: empty canvas, or the shadow of a lifted node."""
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
    return image.pixelColor(int(margin + NODE_W / 2), int(margin + NODE_H + 3))


@pytest.mark.parametrize("theme", (DARK, LIGHT), ids=lambda t: t.name)
def test_selecting_a_node_deepens_the_fill_it_already_had(themed, services, project, tab, theme):
    """The shading is a *gain* on the node's own fill rather than a colour of its own, which
    is what lets a picked milestone stay purple while it is picked.

    The exactness is the second assertion in disguise: the body can only come out at the
    gained alpha over the ground if **nothing else is painted under it**. A node's fill is
    translucent, so shadow rings left beneath would darken it and a picked step would read
    as a hole rather than as a card off the table — which is what the first cut did.
    """
    from dplanner.modules.project_editor.renderers import SELECTED_FILL_GAIN

    apply_theme(themed, theme)
    step = project.steps[0]
    scene(tab).select_step(step.id)
    body = painted_node(tab, step.id, theme.bg_base)
    wanted = ink_over(theme.bg_base, theme.text_primary, round(FILL_ALPHA * SELECTED_FILL_GAIN))

    assert abs(body.red() - wanted.red()) <= 2
    assert abs(body.green() - wanted.green()) <= 2
    assert abs(body.blue() - wanted.blue()) <= 2


def test_a_selected_node_casts_a_shadow_on_the_ground_it_left(services, project, tab):
    """The lift reads because the seat darkens under it. Rendered over white, where a
    low-alpha black actually says something."""
    step = project.steps[0]
    assert painted_under(tab, step.id, "white") == QColor("white")
    scene(tab).select_step(step.id)
    assert painted_under(tab, step.id, "white").lightness() < QColor("white").lightness()


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
    from dplanner.modules.project_editor.renderers import (
        LIFT,
        SHADOW_DROP,
        SHADOW_SPREAD,
    )

    node = scene(tab)._nodes[project.steps[0].id]
    plain = node.boundingRect()
    node.setSelected(True)
    assert node.boundingRect() == plain
    assert plain.bottom() >= NODE_H + SHADOW_DROP + SHADOW_SPREAD
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


def test_the_new_button_drops_the_kinds_down(services, project, tab):
    """The arrow renders Step \u25b8 New itself — not a copy of it — so the kinds are declared
    once, in the composition root, and the toolbar cannot come to offer a different list."""
    menu = tab._toolbar.dropdown("steps.new")
    assert menu is not None
    assert [action.text() for action in menu.actions()] == [
        "&Step\u2026",
        "&Feature\u2026",
        "&Milestone\u2026",
        "&Agent Step\u2026",
        "&Check\u2026",
    ]
    # Each wears the medallion its node will wear, so the list reads at a glance.
    assert all(not action.icon().isNull() for action in menu.actions())


def test_an_entry_in_that_dropdown_runs_the_verb(services, project, tab, monkeypatch):
    from dplanner.modules.feature.aspect import is_feature

    answer_new_dialog(monkeypatch, "Bulk import")
    menu = tab._toolbar.dropdown("steps.new")
    assert menu is not None
    menu.actions()[1].trigger()
    assert is_feature(project.steps[-1]) is True


def test_only_the_new_button_carries_an_arrow(services, project, tab):
    """A dropdown is for a verb that has kinds behind it; the rest of the row is one click."""
    assert toolbar_button(tab, "steps.new").menu() is not None
    assert toolbar_button(tab, "steps.delete").menu() is None


def test_closing_the_tab_lets_its_toolbars_go(services, project, tab):
    """A toolbar subscribes to the context, and unlike the menu bar it does not outlive
    its tab. A leaked subscription would restate a dead widget on every selection change."""
    before = len(services.context.changed._slots)
    tab.close()
    assert len(services.context.changed._slots) < before


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
    tab.set_mode(REGION_CREATE, True)
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


def test_the_delete_key_reaches_a_selected_region(app, services, project, tab):
    region = add_region(services, project, 400.0, 300.0, 200.0, 120.0)
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


def test_marks_are_off_until_asked_and_then_colour_the_bare_sockets(services, project, tab):
    from dplanner.modules.project_editor.renderers import END_MARK, START_MARK

    first, second, _third = chain(services, project)
    assert not close_to(painted_at(tab, first.id, 0.0, NODE_H / 2), START_MARK)

    services.actions.run("canvas.mark_starts", services.context.current())
    services.actions.run("canvas.mark_ends", services.context.current())
    assert close_to(painted_at(tab, first.id, 0.0, NODE_H / 2), START_MARK)
    # Something follows the first step, so its right socket is not an end.
    assert not close_to(painted_at(tab, first.id, NODE_W, NODE_H / 2), END_MARK)
    assert not close_to(painted_at(tab, second.id, 0.0, NODE_H / 2), START_MARK)
    assert close_to(painted_at(tab, _third.id, NODE_W, NODE_H / 2), END_MARK)


def test_an_orphan_wears_a_red_ring_only_while_the_mark_is_on(services, project, tab):
    from dplanner.modules.project_editor.renderers import RING_GAP

    lonely = Step(title="Alone")
    services.undo.push(AddNodeCommand(project.id, lonely))
    ring = lambda: painted_at(tab, lonely.id, -RING_GAP, NODE_H / 2)  # noqa: E731
    assert ring().red() <= ring().green() + 20

    services.actions.run("canvas.mark_orphans", services.context.current())
    assert ring().red() > ring().green() + 40

    first = project.steps[0]
    services.undo.push(SetEdgesCommand(lonely.id, "relates", [first.id]))  # Any link will do.
    assert ring().red() <= ring().green() + 20


def test_a_mark_is_remembered_and_every_canvas_wears_it(services, project, tab, make_project):
    from dplanner.framework.user_config import get_global
    from dplanner.modules.project_editor.marks import Marks
    from dplanner.modules.project_editor.module import MARKS_KEY, MODULE_ID

    button = toolbar_button(tab, "canvas.mark_ends")
    assert not button.isChecked()
    services.actions.run("canvas.mark_ends", services.context.current())
    assert button.isChecked()
    assert Marks.from_json(get_global(MODULE_ID, MARKS_KEY)) == Marks(ends=True)

    other = services.tabs.open("project", make_project("Later").id)
    assert other._scene._marks == Marks(ends=True)
    assert scene(tab)._marks == Marks(ends=True)

    services.actions.run("canvas.mark_ends", services.context.current())
    assert not button.isChecked()
    assert other._scene._marks == Marks()


def test_a_mark_reaches_out_no_further_than_the_item_paints():
    from dplanner.modules.project_editor.renderers import MARK_R, RING_GAP, RING_W

    assert MARK_R + 1.0 <= PAINT_MARGIN
    assert RING_GAP + RING_W + 1.0 <= PAINT_MARGIN


# -- the node's top edge, which two decorations share -------------------------------------------


def test_the_medallion_row_leaves_the_badge_less_room_the_more_it_holds():
    """The row and the badge start from opposite ends of the same 220 px edge.

    A step wearing every aspect and carrying a milestone label used to paint one over the
    other; the badge asks how far the row reached instead of assuming it may claim a fixed
    share. The row's advance already includes the trailing gap, which is why one term covers
    both the medallions and the space after them.
    """
    assert medallion_end(()) == BADGE_INSET
    assert medallion_end(("tag",)) == BADGE_INSET + ICON_D + ICON_GAP
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
    assert min(p["x"] for p in placed) == snapped(900.0 - NODE_W / 2)
    assert min(p["y"] for p in placed) == snapped(700.0 - NODE_H / 2)
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
        "D&uplicate Step",
        "&Delete Step",
        "|",
        "Select &All Steps",
    ]
