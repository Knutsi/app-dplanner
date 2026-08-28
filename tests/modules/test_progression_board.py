"""The progression board: the execution surface, and the seams it reaches others through."""

import json

import pytest

from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri


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


def test_with_nothing_done_only_the_frontier_is_ready(services, project, tab):
    assert tab.board.ready.titles() == ["A"]
    assert tab.board.upcoming.titles() == ["B", "C"]
    assert tab.board.running.titles() == []
    assert tab.board.header.percent.text() == "0%"


def test_the_board_follows_a_status_change_and_its_undo(services, project, tab):
    """Nothing is stored: a status write moves the cards, and undo moves them back."""
    a, b, _c, _d = project.steps
    set_status(services, a, "done")
    assert tab.board.ready.titles() == ["B", "C"]
    assert tab.board.upcoming.titles() == ["D"]
    assert tab.board.header.percent.text() == "25%"

    set_status(services, b, "in-progress")
    assert tab.board.running.titles() == ["B"]
    assert tab.board.ready.titles() == ["C"]

    services.undo.undo()
    assert tab.board.running.titles() == []
    assert tab.board.ready.titles() == ["B", "C"]


def test_a_blocked_step_needs_attention_and_leads_the_running_column(services, project, tab):
    a, b, _c, _d = project.steps
    set_status(services, a, "done")
    set_status(services, b, "in-progress")
    set_status(services, project.steps[2], "blocked")
    assert tab.board.running.titles() == ["C", "B"]  # Attention first.
    blocked = tab.board.running.cards()[0]
    assert "attention" in blocked.detail.text()


def test_a_ready_card_says_what_it_unblocks(services, project, tab):
    card = tab.board.ready.cards()[0]
    assert card.title.text() == "A"
    assert card.detail.text() == "Unblocks 3"


def test_the_columns_say_so_when_they_are_empty(services, tab, project):
    for step in project.steps:
        set_status(services, step, "done")
    assert tab.board.header.percent.text() == "100%"
    assert "All done" in _notes(tab.board.ready)


def _notes(column):
    from PySide6.QtWidgets import QLabel

    texts = []
    for index in range(column._rows.count()):
        item = column._rows.itemAt(index)
        widget = item.widget() if item is not None else None
        if isinstance(widget, QLabel):
            texts.append(widget.text())
    return " ".join(texts)


# -- the seams -------------------------------------------------------------------------------


def test_selecting_a_card_publishes_it_so_the_step_verbs_target_it(services, project, tab):
    tab.board.ready.cards()[0].select()

    context = services.context.current()
    assert context.selected_entities("step") == [project.steps[0].id]
    assert services.actions.spec("steps.rename").state(context).enabled


def test_double_clicking_a_card_opens_its_details(app, services, project, tab, monkeypatch):
    """The card runs the same ``steps.details`` verb every other view's double-click runs,
    against a context naming exactly its own step."""
    # A hand-built event rather than QTest.mouseDClick: QTest's press never sees a release,
    # so QApplication.mouseButtons() would stay "held" for every later test in the process.
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from dplanner.modules.step_properties.dialog import StepDetailsDialog

    shown = []
    monkeypatch.setattr(
        StepDetailsDialog, "exec", lambda self: shown.append(self.panel.current_step_id())
    )
    card = tab.board.ready.cards()[0]
    centre = QPointF(card.rect().center())
    app.sendEvent(
        card,
        QMouseEvent(
            QEvent.Type.MouseButtonDblClick,
            centre,
            QPointF(card.mapToGlobal(centre.toPoint())),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert shown == [project.steps[0].id]


def test_a_background_board_does_not_publish_its_selection(services, project, tab):
    """One selection scope; only the pane the user is in may write to it."""
    tab.on_deactivated()
    tab.board.ready.cards()[0].select()
    assert services.context.current().selected_entities("step") == []


def test_a_ready_card_offers_run_agent_wearing_the_gates_own_reason(services, project, tab):
    """The button renders the real action's state — the reason is the gate's, never a copy."""
    button = tab.board.ready.cards()[0].run_button
    assert button is not None
    assert not button.isEnabled()  # No instruction, no checkout: the gate says why.
    assert button.toolTip().startswith("Run Agent — ")


def test_a_build_without_an_agent_has_no_button_at_all(services, project):
    """Hidden means absent: agent_state=None is a build where the capability does not exist."""
    from dplanner.modules.progression.module import ProgressionActivity, ProgressionDeps

    activity = ProgressionActivity(
        ProgressionDeps(
            library=services.document,
            actions=services.actions,
            context=services.context,
            tabs=services.tabs,
        ),
        project.id,
    )
    assert all(card.run_button is None for card in activity.board.ready.cards())
    activity.close()


def test_the_tab_is_titled_for_its_project_and_follows_a_rename(services, project, tab):
    from dplanner.domain.commands import SetFieldCommand

    assert tab.title == "Discovery — Progression"
    services.undo.push(SetFieldCommand(project.id, "title", "Discovery Phase"))
    assert "Discovery Phase — Progression" in [a.title for a in services.tabs.activities()]


def test_a_deleted_project_takes_its_board_with_it(services, project, tab):
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
    assert (mirror.menu, mirror.group, mirror.palette) == ("Step", "open", False)


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
    assert "Ready to launch:" in text


def test_the_window_and_the_terminal_agree(services, project, tab, tmp_path):
    """The tab and the verb read one derivation, asserted where they meet: the titles."""
    from dplanner.domain.progression import progression as derive
    from dplanner.modules.step_status.aspect import read as status_read

    set_status(services, project.steps[0], "done")
    derived = derive(services.document, project, status_read)
    assert tab.board.ready.titles() == [row.step.title for row in derived.ready]
    assert tab.board.upcoming.titles() == [c.step.title for c in derived.upcoming]


def test_the_domain_speaks_the_status_modules_vocabulary():
    """domain/progression.py names three of the status aspect's words without importing
    it (the domain may not learn the module's schema). This is the one place both are
    importable, so it pins the copy: rename a status in the aspect and this fails instead
    of the board silently reclassifying every step."""
    from dplanner.domain import progression
    from dplanner.modules.step_status.aspect import STATUSES

    assert {progression.DONE, progression.IN_PROGRESS, progression.BLOCKED} <= set(STATUSES)
