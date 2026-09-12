"""The spotlight: a picked step lights its arrows, and Alt fades everything they miss.

Two halves of one derivation. The lighting is always on — an arrow hanging off the selection
is what says *this is what that card is connected to* — and the fading is the look, switched
on for good by ``canvas.spotlight`` or lent for as long as Alt is held.
"""

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent, QKeyEvent

from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand
from dplanner.domain.model import Step
from dplanner.modules.project_editor.selection import EdgeRef, Neighbourhood, neighbourhood
from dplanner.theme.cards import DIM_OPACITY

# -- the derivation, with no canvas ------------------------------------------------------------


def refs(*pairs):
    return [EdgeRef(waiter=waiter, kind="requires", source=source) for waiter, source in pairs]


def test_nothing_picked_has_no_neighbourhood():
    """Which is what keeps a spotlight over an empty selection from dimming everything to
    say nothing at all."""
    assert neighbourhood(refs(("b", "a")), []) == Neighbourhood()


def test_the_neighbourhood_is_the_arrows_that_touch_the_selection_and_both_their_ends():
    edges = refs(("b", "a"), ("c", "b"), ("d", "c"))
    near = neighbourhood(edges, ["b"])
    assert near.edges == {edges[0], edges[1]}
    assert near.steps == {"a", "b", "c"}  # The picked step is its own neighbour.


def test_a_step_with_no_links_is_its_own_whole_neighbourhood():
    assert neighbourhood(refs(("b", "a")), ["lonely"]) == Neighbourhood(steps=frozenset({"lonely"}))


def test_every_kind_of_arrow_counts_and_the_direction_does_not():
    """The canvas draws both kinds, so both connect a card to what it is beside."""
    related = EdgeRef(waiter="b", kind="relates", source="a")
    assert neighbourhood([related], ["a"]).edges == {related}
    assert neighbourhood([related], ["b"]).edges == {related}


# -- on the canvas -------------------------------------------------------------------------------


@pytest.fixture
def project(services, make_project):
    project = make_project("Discovery")
    for title in ("Read the spec", "Draft the model", "Ship it", "Something else"):
        AddNodeCommand(project.id, Step(title=title)).redo(services.document)
    first, second, third, _apart = project.steps
    services.undo.push(SetEdgesCommand(second.id, "requires", [first.id]))
    services.undo.push(SetEdgesCommand(third.id, "requires", [second.id]))
    return project


@pytest.fixture
def tab(services, project):
    return services.tabs.open("project", project.id)


def edge(tab, waiter, source):
    return tab._scene._edges[EdgeRef(waiter=waiter.id, kind="requires", source=source.id)]


def node(tab, step):
    return tab._scene._nodes[step.id]


def send_key(tab, kind, key, modifiers=Qt.KeyboardModifier.NoModifier):
    tab._view.event(QKeyEvent(kind, key, modifiers))


def test_a_picked_step_lights_the_arrows_that_touch_it(services, project, tab):
    first, second, third, _apart = project.steps
    assert not edge(tab, second, first)._lit

    tab._scene.select_step(second.id)
    assert edge(tab, second, first)._lit and edge(tab, third, second)._lit

    tab._scene.select_step(first.id)
    assert edge(tab, second, first)._lit
    assert not edge(tab, third, second)._lit  # Two steps away is not connected.

    tab._scene.select_step(None)
    assert not edge(tab, second, first)._lit


def test_lighting_alone_fades_nothing(services, project, tab):
    """The arrows say what is connected; hiding the rest of the graph is a separate act."""
    tab._scene.select_step(project.steps[0].id)
    assert all(node(tab, step).opacity() == 1.0 for step in project.steps)


def test_the_spotlight_fades_every_step_the_selection_does_not_reach(services, project, tab):
    first, second, third, apart = project.steps
    services.actions.run("canvas.spotlight", services.context.current())
    tab._scene.select_step(second.id)

    assert node(tab, second).opacity() == 1.0
    assert node(tab, first).opacity() == 1.0 and node(tab, third).opacity() == 1.0
    assert node(tab, apart).opacity() == DIM_OPACITY
    assert edge(tab, second, first).opacity() == 1.0

    tab._scene.select_step(first.id)
    assert node(tab, third).opacity() == DIM_OPACITY
    assert edge(tab, third, second).opacity() == DIM_OPACITY


def test_the_spotlight_with_nothing_picked_dims_nothing(services, project, tab):
    services.actions.run("canvas.spotlight", services.context.current())
    assert all(node(tab, step).opacity() == 1.0 for step in project.steps)

    tab._scene.select_step(project.steps[0].id)
    tab._scene.select_step(None)
    assert all(node(tab, step).opacity() == 1.0 for step in project.steps)


def test_relinking_the_graph_lights_it_again_under_the_selection(services, project, tab):
    """The neighbourhood is derived every sync, so an edge added by anybody — a menu, a CLI
    run this window adopted — is lit the moment it is drawn."""
    first, _second, _third, apart = project.steps
    services.actions.run("canvas.spotlight", services.context.current())
    tab._scene.select_step(first.id)
    assert node(tab, apart).opacity() == DIM_OPACITY

    services.undo.push(SetEdgesCommand(apart.id, "requires", [first.id]))
    assert node(tab, apart).opacity() == 1.0
    assert edge(tab, apart, first)._lit


def test_holding_alt_spotlights_for_a_moment(services, project, tab):
    first, _second, _third, apart = project.steps
    tab._scene.select_step(first.id)

    send_key(tab, QEvent.Type.KeyPress, Qt.Key.Key_Alt)
    assert node(tab, apart).opacity() == DIM_OPACITY

    send_key(tab, QEvent.Type.KeyRelease, Qt.Key.Key_Alt)
    assert node(tab, apart).opacity() == 1.0


def test_losing_the_keyboard_ends_a_held_spotlight(services, project, tab):
    """Alt+Tab is Alt held and then taken away: the release is delivered elsewhere, and the
    canvas would still be spotlit when the user came back."""
    first, _second, _third, apart = project.steps
    tab._scene.select_step(first.id)
    send_key(tab, QEvent.Type.KeyPress, Qt.Key.Key_Alt)

    tab._view.event(QFocusEvent(QEvent.Type.FocusOut))
    assert node(tab, apart).opacity() == 1.0


def test_letting_alt_go_leaves_the_preference_alone(services, project, tab):
    """The key lends the look; it does not set it — and the menu entry never flickers."""
    from dplanner.modules.project_editor.module import LOOK_KEY, MODULE_ID

    first, _second, _third, apart = project.steps
    services.actions.run("canvas.spotlight", services.context.current())
    tab._scene.select_step(first.id)

    send_key(tab, QEvent.Type.KeyPress, Qt.Key.Key_Alt)
    send_key(tab, QEvent.Type.KeyRelease, Qt.Key.Key_Alt)
    assert node(tab, apart).opacity() == DIM_OPACITY
    assert services.actions.spec("canvas.spotlight").state(services.context.current()).checked

    from dplanner.framework.user_config import get_global
    from dplanner.modules.project_editor.look import Look

    assert Look.from_json(get_global(MODULE_ID, LOOK_KEY)).spotlight is True


def test_the_spotlight_is_remembered_and_every_canvas_wears_it(
    services, project, tab, make_project
):
    other = services.tabs.open("project", make_project("Later").id)
    assert not tab._scene._spotlight and not other._scene._spotlight

    services.actions.run("canvas.spotlight", services.context.current())
    assert tab._scene._spotlight and other._scene._spotlight

    later = services.tabs.open("project", make_project("Later still").id)
    assert later._scene._spotlight  # A tab opened afterwards wears it too.
