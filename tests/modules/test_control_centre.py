"""The Control Centre: what needs a person in every project, as one board.

Every project's Step statuses merged — ranked by what finishing a step frees, ties going
library order — with each row naming its project, a *Projects* filter on the strip, and the
strip's verbs acting on ticks from several projects at once.
"""

from datetime import date
from pathlib import Path

import pytest

from dplanner.domain.commands import (
    AddNodeCommand,
    RemoveNodeCommand,
    SetEdgesCommand,
    SetFieldCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import Step
from dplanner.framework.context import activity_uri
from dplanner.modules.progression.module import (
    CONTROL_CENTRE_KIND,
    ControlCentreActivity,
)
from dplanner.modules.progression.view import PROJECT_COLUMN, STEP_COLUMN


def add(services, project, title, *after):
    step = Step(title=title)
    AddNodeCommand(project.id, step).redo(services.document)
    if after:
        SetEdgesCommand(step.id, "requires", [s.id for s in after]).redo(services.document)
    return step


@pytest.fixture
def projects(services, make_project):
    """Alpha: finishing *Map the API* frees one, *Write the docs* none. Beta: finishing
    *Order parts* frees two, *Paint* none."""
    alpha, beta = make_project("Alpha"), make_project("Beta")
    mapped = add(services, alpha, "Map the API")
    add(services, alpha, "Write the docs")
    add(services, alpha, "Wire the API", mapped)
    ordered = add(services, beta, "Order parts")
    add(services, beta, "Paint")
    add(services, beta, "Assemble", ordered)
    add(services, beta, "Test the rig", ordered)
    return alpha, beta


def tick(tab, step):
    row = tab.table.row_of(step.id)
    assert row is not None
    tab.table.toggle_row(row)


def board(services) -> ControlCentreActivity:
    activity = services.tabs.open(CONTROL_CENTRE_KIND)
    assert isinstance(activity, ControlCentreActivity)
    return activity


def listed(tab, column=STEP_COLUMN):
    """The table as a person reads it: a heading as ``# words``, a row as ``column``."""
    table = tab.table
    return [
        f"# {table.item(row, 0).text()}"
        if table.is_heading(row)
        else table.item(row, column).text()
        for row in range(table.rowCount())
    ]


READY = ["Order parts", "Map the API", "Write the docs", "Paint"]
WAITING = ["Wire the API", "Assemble", "Test the rig"]


def test_every_project_is_one_board_and_each_row_names_its_own(services, projects):
    """Ranked across projects by what finishing frees; *Write the docs* before *Paint*,
    both freeing nothing, because Alpha comes first in the library."""
    tab = board(services)
    assert listed(tab) == ["# Ready to start", *READY, "# Waiting", *WAITING]
    assert not tab.table.isColumnHidden(PROJECT_COLUMN)
    assert listed(tab, PROJECT_COLUMN)[1:5] == ["Beta", "Alpha", "Alpha", "Beta"]


def test_it_is_one_tab_for_the_library_opened_from_go(services, projects):
    services.actions.run("progression.control_centre", services.context.current())
    tab = board(services)
    assert tab.uri == activity_uri(CONTROL_CENTRE_KIND)
    assert services.tabs.open(CONTROL_CENTRE_KIND, "anything") is tab
    assert services.tabs.tab_title(tab) == "Control Centre (4)"  # Four ready to start.


def test_it_is_the_index_row_after_home(services, projects):
    """A folder of its own, as Home is: a click glances at it, activation keeps it."""
    from tests.index_helpers import click, folder

    from dplanner.framework.builder import INDEX_PANEL_ID

    panel = services.window.dock.widget_for(INDEX_PANEL_ID)
    row = panel.tree.topLevelItem(1)
    assert row is folder(panel, CONTROL_CENTRE_KIND) and row.text(0) == "Control Centre"
    assert row.childCount() == 0
    click(panel, row)
    tab = services.tabs.current_activity()
    assert tab is not None and tab.uri == activity_uri(CONTROL_CENTRE_KIND)
    assert services.tabs.is_preview(tab)
    panel.tree.itemActivated.emit(row, 0)
    assert not services.tabs.is_preview(tab)
    assert panel.context_menu(row) is None


def test_the_projects_filter_narrows_the_board_and_its_face_names_the_pick(services, projects):
    alpha, _beta = projects
    tab = board(services)
    assert [a.text() for a in tab.projects.menu.actions()] == ["Alpha", "Beta"]
    tab.projects.set_active({alpha.id})
    assert listed(tab) == [
        "# Ready to start",
        "Map the API",
        "Write the docs",
        "# Waiting",
        "Wire the API",
    ]
    assert tab.projects.face.text() == "Alpha"
    # The count in the title is the board's, not the filter's: what needs you anywhere.
    assert services.tabs.tab_title(tab) == "Control Centre (4)"
    tab.projects.clear()
    assert listed(tab)[1:5] == READY


def test_the_filter_follows_the_library_as_projects_arrive_are_renamed_and_leave(
    services, projects, make_project
):
    _alpha, beta = projects
    tab = board(services)
    tab.projects.set_active({beta.id})
    services.undo.push(SetFieldCommand(beta.id, "title", "Beta Two"))
    assert tab.projects.face.text() == "Beta Two"
    assert listed(tab, PROJECT_COLUMN)[1] == "Beta Two"

    make_project("Gamma")
    shown = [a.text() for a in tab.projects.menu.actions() if a.isVisible()]
    assert shown == ["Alpha", "Beta Two", "Gamma"]

    services.undo.push(RemoveNodeCommand(beta.id))
    assert [a.text() for a in tab.projects.menu.actions() if a.isVisible()] == ["Alpha", "Gamma"]
    assert tab.projects.active() == []  # A pick nobody can see is hiding rows for no reason.
    assert "Order parts" not in listed(tab)


def test_one_project_needs_neither_the_filter_nor_the_column(services, make_project):
    only = make_project("Alpha")
    add(services, only, "Map the API")
    tab = board(services)
    assert not tab.controls.is_shown(tab.projects)
    assert tab.table.isColumnHidden(PROJECT_COLUMN)


def test_a_change_in_any_project_reaches_the_board(services, projects):
    _alpha, beta = projects
    tab = board(services)
    paint = next(step for step in beta.steps if step.title == "Paint")
    services.undo.push(SetFieldCommand(paint.id, "title", "Paint the rig"))
    assert "Paint the rig" in listed(tab)
    services.undo.push(
        SetModuleDataCommand(paint.id, "step_status", {"status": "done", "format": 1})
    )
    assert services.tabs.tab_title(tab) == "Control Centre (3)"


def test_a_step_behind_a_dated_wait_joins_the_board_on_its_day(services, projects):
    from dplanner.modules.step_wait.aspect import MODULE_ID as WAIT_ID
    from dplanner.modules.step_wait.aspect import write as write_wait
    from dplanner.planning.schedule import Wait

    _alpha, beta = projects
    services.clock.pin(date(2026, 9, 18))
    wait = add(services, beta, "Parts arrive")
    SetModuleDataCommand(wait.id, WAIT_ID, write_wait(Wait(until=date(2026, 9, 21)))).redo(
        services.document
    )
    add(services, beta, "Unpack", wait)
    tab = board(services)
    ready = listed(tab)[: listed(tab).index("# Waiting")]
    assert "Unpack" not in ready
    services.clock.pin(date(2026, 9, 21))
    ready = listed(tab)[: listed(tab).index("# Waiting")]
    assert "Unpack" in ready


def test_show_in_order_from_a_row_opens_that_row_s_project(services, projects):
    """The board names no project, so the verbs about one read the picked step's own."""
    from dplanner.modules.step_order.module import ORDER_KIND

    _alpha, beta = projects
    tab = board(services)
    tab.on_activated()
    tick(tab, beta.steps[0])
    assert services.actions.spec("order.open_step").state(services.context.current()).enabled
    services.actions.run("order.open_step", services.context.current())
    current = services.tabs.current_activity()
    assert current is not None and current.uri == activity_uri(ORDER_KIND, beta.id)


def test_the_tab_comes_back_with_the_session(session, services, projects):
    board(services)
    services.autosave.flush_now()
    assert session.reload()
    uris = [activity.uri for activity in session.services.tabs.activities()]
    assert activity_uri(CONTROL_CENTRE_KIND) in uris


def test_ticked_ready_steps_in_two_projects_launch_in_one_gesture(
    services, make_project, library_repo, tmp_path, monkeypatch
):
    """One press, one agent per ticked step, each shell in its own project's checkout —
    and no confirmation, since a step is ready precisely because nothing it waits on is
    left."""
    from dplanner.core.storage.locations import init_repo
    from dplanner.domain.seed import seed_project
    from dplanner.modules.step_agent_instruction import launcher
    from dplanner.modules.step_agent_run.aspect import launched

    alpha = make_project("Alpha", legacy=True)
    second_repo = init_repo(tmp_path / "second")
    satellite = services.repo.attach(seed_project(second_repo, "Satellite"))
    services.document.add_child(services.document.id, satellite)
    chosen = [add(services, alpha, "Map the API"), add(services, satellite, "Wire the antenna")]
    for step in chosen:
        services.document.set_text(step.id, "step_agent_instruction", f"Ship {step.title}.")

    shells: list[Path] = []
    monkeypatch.setattr(launcher, "spawn", lambda _cmd, cwd, **_kw: shells.append(cwd))
    monkeypatch.setattr(launcher, "resolve_command", lambda *_a, **_k: ["fake-term"])

    tab = board(services)
    tab.on_activated()
    for step in chosen:
        tick(tab, step)
    button = tab.controls.button_for("agent.run")
    assert button is not None and button.isEnabled(), button and button.toolTip()
    assert button.defaultAction().text() == "Run 2 Agents…"
    button.defaultAction().trigger()
    assert shells == [library_repo, second_repo]
    assert all(launched(services.document.step(step.id)) for step in chosen)
