"""Auto-progress in the window: the checkable verb among the arrow's, the doubled line on
the canvas, and the Step statuses tab reading the one derivation.

Three agent steps feed a fourth, C, which collects them. Everything here runs through the
application the composition root builds, so the wiring is what is under test as much as
the module.
"""

import pytest

from dplanner.domain.commands import (
    AddNodeCommand,
    SetEdgesCommand,
    SetModuleDataCommand,
    redirect_edges_command,
)
from dplanner.domain.model import SOURCE, Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.auto_progress import aspect
from dplanner.modules.canvas.renderers import EdgeAccent
from dplanner.modules.canvas.selection import EdgeRef
from dplanner.modules.step_agent_run import aspect as agent_run
from dplanner.planning import agent
from dplanner.planning.status import Status

TOGGLE = "links.auto_progress"


@pytest.fixture
def project(services, make_project):
    """A1, A2 and A3, agent steps, all required by C — an agent step too — and P, a plain
    step C does not wait on."""
    library = services.document
    project = make_project("Discovery")
    for title in ("A1", "A2", "A3", "C", "P"):
        step = Step(title=title)
        AddNodeCommand(project.id, step).redo(library)
        if title != "P":
            SetModuleDataCommand(step.id, agent.MODULE_ID, agent.write_state(True)).redo(library)
    c = by_title(project, "C")
    sources = [by_title(project, title).id for title in ("A1", "A2", "A3")]
    SetEdgesCommand(c.id, "requires", sources).redo(library)
    return project


@pytest.fixture
def tab(services, project):
    return services.tabs.open("project", project.id)


def by_title(project, title):
    return next(step for step in project.steps if step.title == title)


def edge_item(tab, waiter, source, kind="requires"):
    return tab._scene._edges[EdgeRef(waiter=waiter.id, kind=kind, source=source.id)]


def picking(services, *edges):
    """A context whose selection is these arrows — what the canvas publishes for a pick."""
    services.context.set_scope(
        SCOPE_SELECTION,
        tuple(ContextNode(selection_uri("edge", edge.entity_id())) for edge in edges),
    )
    return services.context.current()


def arrows(project, *sources, waiter="C"):
    c = by_title(project, waiter)
    return [EdgeRef(c.id, "requires", by_title(project, s).id) for s in sources]


def state(services, context):
    return services.actions.spec(TOGGLE).state(context)


# -- the verb -------------------------------------------------------------------------------


def test_the_toggle_is_greyed_with_its_reason(services, project, tab):
    assert state(services, picking(services)).label == "&Auto-progress — pick links first"

    p, c = by_title(project, "P"), by_title(project, "C")
    SetEdgesCommand(p.id, "relates", [c.id]).redo(services.document)
    relates = picking(services, EdgeRef(p.id, "relates", c.id), *arrows(project, "A1"))
    said = state(services, relates)
    assert not said.enabled and said.label == "&Auto-progress — only a requires link can"

    SetEdgesCommand(p.id, "requires", [by_title(project, "A1").id]).redo(services.document)
    plain_waiter = picking(services, *arrows(project, "A1", waiter="P"))
    said = state(services, plain_waiter)
    assert not said.enabled and said.label == "&Auto-progress — S5 is not an agent step"


def test_three_picked_links_toggle_as_one_undo(services, project, tab):
    c = by_title(project, "C")
    picked = picking(services, *arrows(project, "A1", "A2", "A3"))
    assert state(services, picked).checked is False

    services.actions.run(TOGGLE, picked)
    assert len(aspect.sources(services.document, c)) == 3
    assert state(services, picked).checked is True

    services.undo.undo()
    assert aspect.sources(services.document, c) == []
    services.undo.redo()
    services.actions.run(TOGGLE, picked)  # All on: the toggle turns them all off.
    assert aspect.sources(services.document, c) == []


def test_a_partly_flagged_pick_turns_all_of_it_on(services, project, tab):
    c = by_title(project, "C")
    services.actions.run(TOGGLE, picking(services, *arrows(project, "A1")))
    picked = picking(services, *arrows(project, "A1", "A2"))
    assert state(services, picked).checked is False
    services.actions.run(TOGGLE, picked)
    assert [s.title for s in aspect.sources(services.document, c)] == ["A1", "A2"]


def test_the_arrows_right_click_offers_it_checked(services, project, tab):
    from tests.modules.canvas.test_canvas import a_point_on, offered

    c, a1 = by_title(project, "C"), by_title(project, "A1")
    services.actions.run(TOGGLE, picking(services, *arrows(project, "A1")))
    assert offered(tab, a_point_on(edge_item(tab, c, a1))) == [
        "Remove Link",
        "Auto-progress",
        ("Redirect", ["To Step", "From Step"]),
    ]
    assert services.actions.spec(TOGGLE).state(services.context.current()).checked


# -- the canvas -----------------------------------------------------------------------------


def test_an_auto_progress_link_is_doubled_and_a_plain_one_is_not(services, project, tab):
    c, a1, a2 = (by_title(project, t) for t in ("C", "A1", "A2"))
    services.actions.run(TOGGLE, picking(services, *arrows(project, "A1")))
    assert edge_item(tab, c, a1).accent() == EdgeAccent(doubled=True)
    assert edge_item(tab, c, a2).accent() == EdgeAccent()
    services.undo.undo()
    assert edge_item(tab, c, a1).accent() == EdgeAccent()


def test_its_chevrons_flow_on_the_ring_clock_while_the_source_is_worked(services, project, tab):
    scene = tab._scene
    c, a1 = by_title(project, "C"), by_title(project, "A1")
    services.actions.run(TOGGLE, picking(services, *arrows(project, "A1")))
    edge = edge_item(tab, c, a1)
    assert not edge.flows() and not scene._motion_clock.isActive()

    SetModuleDataCommand(a1.id, agent_run.MODULE_ID, agent_run.write("working")).redo(
        services.document
    )
    assert edge.flows() and scene._motion_clock.isActive()
    before = edge._chevrons.boundingRect()
    scene.advance_motion()
    scene.advance_motion()
    assert edge._chevrons.boundingRect() != before  # The marks moved along.

    SetModuleDataCommand(a1.id, agent_run.MODULE_ID, {}).redo(services.document)
    assert not edge.flows() and not scene._motion_clock.isActive()


def test_a_redirected_link_arrives_plain(services, project, tab):
    """Read through the edge: the flag names A1, and the link now comes from P."""
    c, a1, p = (by_title(project, t) for t in ("C", "A1", "P"))
    library = services.document
    services.actions.run(TOGGLE, picking(services, *arrows(project, "A1")))
    plan = library.redirection([arrows(project, "A1")[0].as_edge()], p.id, SOURCE)
    services.undo.push(redirect_edges_command(library, plan, "Redirect"))
    assert p.id in c.edges["requires"] and a1.id not in c.edges["requires"]
    assert aspect.sources(library, c) == []
    assert edge_item(tab, c, p).accent() == EdgeAccent()
    assert aspect.read(c) == (a1.id,)  # Inert, never repaired.


# -- the derivation, as the window reads it --------------------------------------------------


def test_the_step_statuses_tab_puts_a_collector_in_ready_to_start(services, project):
    from dplanner.planning.status import write as status_write

    c = by_title(project, "C")
    services.actions.run(TOGGLE, picking(services, *arrows(project, "A1", "A2", "A3")))
    for title in ("A1", "A2", "A3"):
        step = by_title(project, title)
        entry = status_write(Status.READY_FOR_REVIEW, today=services.clock.today())
        SetModuleDataCommand(step.id, "step_status", entry).redo(services.document)
    statuses = services.tabs.open("progression", project.id)
    assert c.id in {step.id for step in statuses._found.ready}


def test_a_source_its_collector_takes_on_is_off_both_boards_ready_for_review(services, project):
    """A1 is under review and C, a live agent, collects it: C's turn, so neither board lists
    it as a person's — the same answer the canvas pulses by. P, under review with nobody to
    take it on, is a person's row on both, and A1 is not in what the tab's title counts."""
    from dplanner.modules.status_board.activity import CONTROL_CENTRE_KIND
    from dplanner.planning.status import write as status_write

    services.actions.run(TOGGLE, picking(services, *arrows(project, "A1")))
    for title in ("A1", "P"):
        entry = status_write(Status.READY_FOR_REVIEW, today=services.clock.today())
        SetModuleDataCommand(by_title(project, title).id, "step_status", entry).redo(
            services.document
        )
    statuses = services.tabs.open("progression", project.id)
    centre = services.tabs.open(CONTROL_CENTRE_KIND)
    for board in (statuses, centre):
        assert [step.title for step in board._found.review] == ["P"]
        assert [step.title for step in board._found.taken] == ["A1"]
    # P for review and A2 and A3 ready to start: three rows need a person, not four.
    assert statuses.title.endswith("Step statuses (3)")
