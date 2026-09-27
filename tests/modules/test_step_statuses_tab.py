"""Step statuses: what needs a person right now, and the seams it reaches others through."""

import json

import pytest

from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.framework.list_rows import DETAIL_ROLE


@pytest.fixture
def project(services, make_project):
    """The diamond: B and C wait on A, D waits on both — serial and parallel in one graph."""
    library = services.document
    project = make_project("Discovery")
    for title in ("A", "B", "C", "D"):
        AddNodeCommand(project.id, Step(title=title)).redo(library)
    a, b, c, d = project.steps
    for waiter, sources in ((b, [a]), (c, [a]), (d, [b, c])):
        SetEdgesCommand(waiter.id, "requires", [s.id for s in sources]).redo(library)
    return project


@pytest.fixture
def tab(services, project):
    return services.tabs.open("progression", project.id)


def set_status(services, step, status):
    services.undo.push(
        SetModuleDataCommand(step.id, "step_status", {"status": status, "format": 1})
    )


# -- what it shows ---------------------------------------------------------------------------


def listed(tab):
    """The table as a person reads it: a heading as ``# words``, a row as its title."""
    table = tab.table
    rows = []
    for row in range(table.rowCount()):
        text = table.item(row, 0).text() if table.is_heading(row) else ""
        if table.is_heading(row):
            rows.append(f"# {text}")
        else:
            rows.append(table.item(row, 1).text())
    return rows


def test_with_nothing_done_the_frontier_is_ready_and_the_rest_waits(services, project, tab):
    assert listed(tab) == ["# Ready to start", "A", "# Waiting", "B", "C", "D"]


def test_the_groups_come_closest_to_done_first_and_running_work_is_not_listed(
    services, make_project
):
    """Blocked, then the finished work a person looks at, then what can start, then what
    cannot yet. An agent at work needs nobody: in progress and done are nowhere."""
    project = make_project("Discovery")
    library = services.document
    words = {
        "Stuck": "blocked",
        "Reviewed": "ready-to-merge",
        "Finished": "ready-for-review",
        "Busy": "in-progress",
        "Over": "done",
        "Fresh": "",
    }
    for title, word in words.items():
        step = Step(title=title)
        AddNodeCommand(project.id, step).redo(library)
        if word:
            set_status(services, step, word)
    tab = services.tabs.open("progression", project.id)
    assert listed(tab) == [
        "# Blocked",
        "Stuck",
        "# Ready to merge",
        "Reviewed",
        "# Ready for review",
        "Finished",
        "# Ready to start",
        "Fresh",
    ]


def test_a_step_waiting_on_reviewed_work_waits(services, project, tab):
    """A plain requires is fulfilled by done alone: B and C stay waiting while A is under
    review or waiting on its merge, and start once it is done."""
    a = project.steps[0]
    for word in ("ready-for-review", "ready-to-merge"):
        set_status(services, a, word)
        assert "# Ready to start" not in listed(tab)
        assert listed(tab)[-4:] == ["# Waiting", "B", "C", "D"]
    set_status(services, a, "done")
    assert listed(tab) == ["# Ready to start", "B", "C", "# Waiting", "D"]


def test_the_table_follows_a_status_change_and_its_undo(services, project, tab):
    set_status(services, project.steps[0], "done")
    assert listed(tab)[:3] == ["# Ready to start", "B", "C"]
    services.undo.undo()
    assert listed(tab)[:2] == ["# Ready to start", "A"]


def test_a_row_says_its_key_and_what_finishing_it_unblocks(services, project, tab):
    from dplanner.modules.progression.view import STEP_COLUMN, UNBLOCKS_COLUMN

    row = tab.table.row_of(project.steps[0].id)
    assert tab.table.item(row, STEP_COLUMN).data(DETAIL_ROLE) == "S1"
    assert tab.table.item(row, UNBLOCKS_COLUMN).text() == "3"
    last = tab.table.row_of(project.steps[3].id)
    assert tab.table.item(last, UNBLOCKS_COLUMN).text() == ""  # Nothing waits on D.


def test_the_filter_shows_one_group_and_says_so_when_it_is_empty(services, project, tab):
    """One click on a segment; a single group needs no heading, since the filter says it."""
    tab.filter.button("waiting").click()
    assert tab.filter_key == "waiting"
    assert listed(tab) == ["B", "C", "D"]
    tab.filter.button("review").click()
    assert tab.table.rowCount() == 0
    assert tab.empty.isVisibleTo(tab.widget) and not tab.table.isVisibleTo(tab.widget)
    assert tab.empty.label.text() == "Nothing is ready for review."
    tab.filter.button("all").click()
    assert listed(tab)[:2] == ["# Ready to start", "A"]
    assert tab.table.isVisibleTo(tab.widget)


def test_an_empty_project_and_a_finished_one_say_so(services, make_project):
    project = make_project("Empty")
    tab = services.tabs.open("progression", project.id)
    assert tab.empty.label.text() == "No steps yet."
    step = Step(title="Only")
    AddNodeCommand(project.id, step).redo(services.document)
    set_status(services, step, "in-progress")
    assert tab.empty.label.text() == "Nothing needs you right now."


def test_the_title_counts_what_needs_a_person_and_follows_a_rename(services, project, tab):
    """Blocked, merge, review and start count; waiting does not. None needing anybody
    drops the count rather than saying nought."""
    from dplanner.domain.commands import SetFieldCommand

    assert tab.title == "Discovery — Step statuses (1)"
    assert services.tabs.tab_title(tab) == tab.title
    set_status(services, project.steps[0], "done")
    assert services.tabs.tab_title(tab) == "Discovery — Step statuses (2)"
    for step in project.steps:
        set_status(services, step, "in-progress")
    assert services.tabs.tab_title(tab) == "Discovery — Step statuses"
    services.undo.push(SetFieldCommand(project.id, "title", "Discovery Phase"))
    assert services.tabs.tab_title(tab) == "Discovery Phase — Step statuses"


# -- ticking is picking ------------------------------------------------------------------------


def _press(app, table, row, column, kind=None):
    """A left button event at a cell's centre, hand-built: QTest's press never sees a
    release, so ``QApplication.mouseButtons()`` would stay held for every later test."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    rect = table.visualRect(table.model().index(row, column))
    centre = QPointF(rect.center())
    viewport = table.viewport()
    for event_kind in (
        [kind] if kind else [QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease]
    ):
        app.sendEvent(
            viewport,
            QMouseEvent(
                event_kind,
                centre,
                QPointF(viewport.mapToGlobal(centre.toPoint())),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )


def test_a_click_on_a_box_ticks_that_row_and_the_ticks_are_published(app, services, project, tab):
    """The box is the selection's own target: a click adds its row and leaves the others,
    and what is ticked is what the Step menu and the strip act on."""
    from dplanner.modules.progression.view import CHECK_COLUMN

    tab.on_activated()
    b, c = project.steps[1], project.steps[2]
    _press(app, tab.table, tab.table.row_of(b.id), CHECK_COLUMN)
    _press(app, tab.table, tab.table.row_of(c.id), CHECK_COLUMN)
    assert tab.table.picked() == [b.id, c.id]
    assert services.context.current().selected_entities("step") == [b.id, c.id]
    _press(app, tab.table, tab.table.row_of(b.id), CHECK_COLUMN)
    assert tab.table.picked() == [c.id]


def test_a_double_click_on_a_box_is_two_ticks_and_opens_nothing(
    app, services, project, tab, monkeypatch
):
    from PySide6.QtCore import QEvent

    from dplanner.modules.progression.view import CHECK_COLUMN

    opened = []
    monkeypatch.setattr(services.actions, "run", lambda action_id, ctx: opened.append(action_id))
    row = tab.table.row_of(project.steps[0].id)
    _press(app, tab.table, row, CHECK_COLUMN)
    _press(app, tab.table, row, CHECK_COLUMN, QEvent.Type.MouseButtonDblClick)
    assert tab.table.picked() == [] and opened == []


def test_double_clicking_a_row_opens_its_details(app, services, project, tab, monkeypatch):
    """The one gesture across the application: against a context naming the row's step."""
    from PySide6.QtCore import QEvent

    from dplanner.modules.progression.view import STEP_COLUMN

    opened = []
    monkeypatch.setattr(
        services.actions,
        "run",
        lambda action_id, ctx: opened.append((action_id, ctx.selected_entities("step"))),
    )
    a = project.steps[0]
    row = tab.table.row_of(a.id)
    _press(app, tab.table, row, STEP_COLUMN)
    _press(app, tab.table, row, STEP_COLUMN, QEvent.Type.MouseButtonDblClick)
    assert opened == [("steps.details", [a.id])]


def test_the_ticks_survive_a_rebuild_by_step(services, project, tab):
    """An accepted review is still ticked in its new group."""
    a = project.steps[0]
    set_status(services, a, "ready-for-review")
    tab.table.toggle_row(tab.table.row_of(a.id))
    set_status(services, a, "ready-to-merge")
    assert listed(tab)[:2] == ["# Ready to merge", "A"]
    assert tab.table.picked() == [a.id]


def test_a_background_tab_does_not_publish_its_selection(services, project, tab):
    """One selection scope; only the pane the user is in may write to it."""
    tab.on_deactivated()
    tab.table.toggle_row(tab.table.row_of(project.steps[0].id))
    assert services.context.current().selected_entities("step") == []


# -- the strip acts on the ticked rows -------------------------------------------------------


def test_the_strip_seats_run_agent_and_the_status_verbs_greyed_until_a_row_is_ticked(
    services, project, tab
):
    tab.on_activated()
    for action_id in ("agent.run", "status.ready-to-merge", "status.done"):
        button = tab.controls.button_for(action_id)
        assert button is not None and not button.isEnabled(), action_id
    # The verb the tab leads with wears its words; the status verbs are glyphs.
    assert tab.controls.button_for("agent.run").text() == "Run Agents"


def test_accepting_reviews_moves_them_to_merge_and_done_takes_them_away(services, project, tab):
    """Ready to Merge and Done are the Step ▸ Status verbs themselves, run over every
    ticked row as one undo step."""
    tab.on_activated()
    a, b = project.steps[0], project.steps[1]
    set_status(services, a, "done")
    set_status(services, b, "ready-for-review")
    c = project.steps[2]
    set_status(services, c, "ready-for-review")
    for step in (b, c):
        tab.table.toggle_row(tab.table.row_of(step.id))
    merge = tab.controls.button_for("status.ready-to-merge")
    assert merge.isEnabled() and not merge.isChecked()
    merge.click()
    assert listed(tab)[:3] == ["# Ready to merge", "B", "C"]
    assert tab.table.picked() == [b.id, c.id]
    assert merge.isChecked()  # Every ticked row stands there now.
    tab.controls.button_for("status.done").click()
    assert listed(tab) == ["# Ready to start", "D"]
    services.undo.undo()
    assert listed(tab)[:3] == ["# Ready to merge", "B", "C"]  # Both, in one step.


def test_ticking_ready_rows_offers_run_agent_with_the_gates_reason(services, project, tab):
    """The strip renders the real action's state over the ticked rows — the reason is the
    gate's, never a copy — and its arrow drops the Step menu's own Run Agent child."""
    tab.on_activated()
    tab.table.toggle_row(tab.table.row_of(project.steps[0].id))
    button = tab.controls.button_for("agent.run")
    assert not button.isEnabled()  # No instruction, no checkout: the gate says why.
    assert "Run Agent — " in button.toolTip()
    menu = tab.controls.menu_for("agent.run")
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert labels[-1] == "&Manage Agent Profiles…" and len(labels) > 1


@pytest.fixture
def ready_agents(services, make_project):
    """A finished step and five agent steps waiting on it: five rows ready to start,
    each briefed enough to launch. What the tab looks like the morning a milestone lands."""
    project = make_project("Discovery", legacy=True)
    done = Step(title="Groundwork")
    AddNodeCommand(project.id, done).redo(services.document)
    set_status(services, done, "done")
    for title in ("One", "Two", "Three", "Four", "Five"):
        step = Step(title=title)
        AddNodeCommand(project.id, step).redo(services.document)
        SetEdgesCommand(step.id, "requires", [done.id]).redo(services.document)
        services.document.set_text(step.id, "step_agent_instruction", f"Ship {title}.")
    return project


def _boxes(monkeypatch):
    """Every Run Anyway dialog, recorded instead of blocking — the seam test_agent_run.py
    uses."""
    from PySide6.QtWidgets import QDialog

    from dplanner.modules.step_agent_instruction.run_dialog import RunAnywayDialog

    shown: list[str] = []

    def record(dialog: RunAnywayDialog) -> int:
        shown.append(dialog.lead.text())
        return int(QDialog.DialogCode.Rejected)

    monkeypatch.setattr(RunAnywayDialog, "exec", record)
    return shown


def test_the_ticked_ready_steps_launch_in_one_gesture_and_nothing_is_asked(
    services, ready_agents, monkeypatch
):
    """Three ticks, one press, three peers — and no confirmation, which is not an omission.

    The gate asks before launching a step whose prerequisites are not done; a step is
    ready to start precisely because they are. The group's rule and the gate's question
    are the same question, so a launch from here can only ever be a quiet one — and a box
    that never appears in the place a person launches from is worth a test saying so.
    """
    from dplanner.modules.step_agent_instruction import launcher
    from dplanner.modules.step_agent_run.aspect import launched

    tab = services.tabs.open("progression", ready_agents.id)
    tab.on_activated()
    prepared = []

    def resolve(_template, files, _workdir):
        prepared.append(files)
        return ["fake-term"]

    monkeypatch.setattr(launcher, "spawn", lambda cmd, cwd, **_kw: None)
    monkeypatch.setattr(launcher, "resolve_command", resolve)
    boxes = _boxes(monkeypatch)

    chosen = [step.id for step in ready_agents.steps[1:4]]
    for step_id in chosen:
        tab.table.toggle_row(tab.table.row_of(step_id))
    button = tab.controls.button_for("agent.run")
    assert button.isEnabled(), button.toolTip()
    assert button.defaultAction().text() == "Run 3 Agents…"

    menu = tab.controls.menu_for("agent.run")
    default_profile = next(entry for entry in menu.actions() if not entry.isSeparator())
    default_profile.trigger()

    assert len(prepared) == 3
    assert len({files.directory for files in prepared}) == 3
    assert boxes == []
    assert all(launched(services.document.step(step_id)) for step_id in chosen)


def test_more_ticks_than_the_limit_grey_run_agent_with_the_count_as_the_reason(
    services, ready_agents
):
    """Past *Settings ▸ Agent profiles*' limit the count itself refuses, before any step is
    asked about — so the verb says the cap rather than naming one step's problem."""
    from dplanner.modules.step_agent_instruction.settings_page import DEFAULT_MAX_AGENTS

    tab = services.tabs.open("progression", ready_agents.id)
    tab.on_activated()
    ready = [step.id for step in ready_agents.steps[1:]]
    assert len(ready) == DEFAULT_MAX_AGENTS + 1
    for step_id in ready:
        tab.table.toggle_row(tab.table.row_of(step_id))
    button = tab.controls.button_for("agent.run")
    assert not button.isEnabled()
    assert button.defaultAction().text() == (
        f"Run {len(ready)} Agents — at most {DEFAULT_MAX_AGENTS} at a time "
        "(Settings ▸ Agent profiles)"
    )
    tab.table.toggle_row(tab.table.row_of(ready[0]))  # One fewer is the whole remedy.
    assert button.isEnabled(), button.toolTip()


def test_a_build_without_the_verbs_seats_none(services, project):
    """Hidden means absent: a build the root names no verbs for has a strip of the filter."""
    from dplanner.modules.progression.module import ProgressionActivity, ProgressionDeps

    activity = ProgressionActivity(
        ProgressionDeps(
            library=services.document,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
            debounce=services.debounce,
        ),
        project.id,
    )
    assert activity.controls.button_for("agent.run") is None
    activity.close()
    # Built bare, so no tab host will delete the page: a top-level widget left to the
    # boundary collector dies inside it, which is how a worker segfaulted on this test.
    activity.widget.deleteLater()


def test_a_deleted_project_takes_its_tab_with_it(services, project, tab):
    from dplanner.domain.commands import RemoveNodeCommand

    services.undo.push(RemoveNodeCommand(project.id))
    assert services.tabs.activities() == []


def test_the_action_opens_it_for_the_focused_project(services, project):
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )
    services.actions.run("progression.open", services.context.current())
    assert [a.uri for a in services.tabs.activities()] == [
        f"app://activity/progression/{project.id}"
    ]


def test_the_step_menu_mirror_opens_the_same_tab(services, project):
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )
    services.actions.run("progression.open_step", services.context.current())
    assert [a.uri for a in services.tabs.activities()] == [
        f"app://activity/progression/{project.id}"
    ]

    mirror = services.actions.spec("progression.open_step")
    assert (mirror.menu, mirror.group, mirror.palette) == ("Step", "surfaces", False)


# -- the CLI, with no window at all ----------------------------------------------------------


def test_the_cli_gives_the_same_answer(cli):
    """No `qapp` fixture: what an agent asks is derived on the spot and cannot be stale."""
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "A")
    cli("step", "add", "Discovery", "B", "--after", "A")
    cli("step", "add", "Discovery", "C", "--after", "B")
    cli("status", "set", "A", "done")

    found = json.loads(cli("progression", "show", "Discovery", "--json"))
    assert found["percent"] == pytest.approx(100 / 3)
    assert [s["title"] for s in found["ready"]] == ["B"]
    assert [s["title"] for s in found["upcoming"]] == ["C"]
    assert found["counts"]["done"] == 1

    text = cli("progression", "show", "Discovery")
    assert text.splitlines()[0] == "33% done — 1 of 3 steps"
    assert "Ready to start:" in text

    cli("status", "set", "B", "ready-for-review")
    found = json.loads(cli("progression", "show", "Discovery", "--json"))
    assert [s["title"] for s in found["review"]] == ["B"] and found["counts"]["review"] == 1
    assert found["ready"] == [] and [s["title"] for s in found["upcoming"]] == ["C"]
    assert "Ready for review:\n  B  (unblocks 1)" in cli("progression", "show", "Discovery")
    cli("status", "set", "B", "ready-to-merge")
    found = json.loads(cli("progression", "show", "Discovery", "--json"))
    assert [s["title"] for s in found["merge"]] == ["B"] and found["counts"]["merge"] == 1


def test_the_window_and_the_terminal_agree(services, project, tab):
    """The tab and the verb read one derivation, asserted where they meet: the steps."""
    from dplanner.domain.progression import progression as derive
    from dplanner.modules.step_status.aspect import read as status_read

    set_status(services, project.steps[0], "done")
    derived = derive(services.document, project, status_read)
    expected = [
        *(step.id for step in derived.ready),
        *(coming.step.id for coming in derived.upcoming),
        *(step.id for step in derived.waiting),
    ]
    assert tab.table.steps() == expected
