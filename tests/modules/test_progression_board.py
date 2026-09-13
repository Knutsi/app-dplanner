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


def test_reading_the_board_back_never_wraps_a_layout_item(monkeypatch, services, project, tab):
    """A QLayoutItem wrapper is a double delete waiting for a gc pass (CLAUDE.md's crash
    notes): the column keeps its own list of what it laid out and reads that, never the
    layout — including across a rebuild, which is what ``clear()`` used ``takeAt`` for."""
    from PySide6.QtWidgets import QLayout

    def refuse(_layout, _index):
        raise AssertionError("itemAt() hands out a QLayoutItem wrapper; read the list instead")

    monkeypatch.setattr(QLayout, "itemAt", refuse)
    monkeypatch.setattr(QLayout, "takeAt", refuse)
    a, _b, _c, _d = project.steps
    set_status(services, a, "done")
    assert tab.board.ready.titles() == ["B", "C"]
    assert tab.board.ready.cards()[0].title.text() == "B"


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


def test_ticking_ready_cards_counts_them_on_the_run_button_and_publishes_them(
    services, project, tab
):
    """The Ready lane's button renders the real action's state over the ticked steps —
    the reason is the gate's, never a copy — and its dropdown is the Step menu's own Run
    Agent child, which acts on the ticked steps because opening it publishes them."""
    board = tab.board
    button = board.run_button
    assert button is not None and button.text() == "Run Agents" and not button.isEnabled()
    assert button.toolTip().startswith("Tick the ready steps")
    cards = board.ready.cards()
    assert all(card.check_box is not None for card in cards)

    cards[0].check_box.setChecked(True)
    assert button.text() == "Run 1 Agent"
    assert not button.isEnabled()  # No instruction, no checkout: the gate says why.
    assert button.toolTip().startswith("Run Agent — ")
    assert board.ticked() == [cards[0].step_id]

    menu = board.run_menu()
    assert menu is not None
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert labels[-1] == "&Manage Agent Profiles…" and len(labels) > 1
    assert services.context.current().selected_entities("step") == [cards[0].step_id]

    cards[0].check_box.setChecked(False)
    assert button.text() == "Run Agents" and board.ticked() == []


@pytest.fixture
def ready_agents(services, make_project):
    """A finished step and five agent steps waiting on it: five cards in the Ready lane,
    each briefed enough to launch. What a board looks like the morning a milestone lands."""
    project = make_project("Discovery")
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
    """Every QMessageBox, recorded instead of blocking — the seam test_agent_run.py uses."""
    from PySide6.QtWidgets import QMessageBox

    shown: list[str] = []

    def record(box: QMessageBox) -> int:
        shown.append(box.text())
        return 0

    monkeypatch.setattr(QMessageBox, "exec", record)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: None)
    return shown


def test_the_ticked_ready_steps_launch_in_one_gesture_and_nothing_is_asked(
    services, ready_agents, monkeypatch
):
    """Three ticks, one press, three peers — and no confirmation, which is not an omission.

    The gate asks before launching a step whose prerequisites are not done; a step is in
    this lane precisely because they are. The lane's rule and the gate's question are the
    same question, so a launch from here can only ever be a quiet one — and a box that
    never appears in the place a person launches from is worth a test saying so.
    """
    from dplanner.modules.step_agent_instruction import launcher
    from dplanner.modules.step_agent_run.aspect import launched

    tab = services.tabs.open("progression", ready_agents.id)
    board = tab.board
    prepared = []

    def resolve(_template, files, _workdir):
        prepared.append(files)
        return ["fake-term"]

    monkeypatch.setattr(launcher, "spawn", lambda cmd, cwd, **_kw: None)
    monkeypatch.setattr(launcher, "resolve_command", resolve)
    boxes = _boxes(monkeypatch)

    cards = board.ready.cards()[:3]
    for card in cards:
        card.check_box.setChecked(True)
    assert board.run_button.text() == "Run 3 Agents"
    assert board.run_button.isEnabled(), board.run_button.toolTip()

    menu = board.run_menu()
    default_profile = next(entry for entry in menu.actions() if not entry.isSeparator())
    default_profile.trigger()

    assert len(prepared) == 3
    assert len({files.directory for files in prepared}) == 3
    assert boxes == []
    assert all(launched(services.document.step(card.step_id)) for card in cards)


def test_more_ticks_than_the_limit_grey_the_button_with_the_count_as_the_reason(
    services, ready_agents
):
    """Past *Settings ▸ Agent profiles*' limit the count itself refuses, before any step is
    asked about — so the face says the cap rather than naming one step's problem."""
    from dplanner.modules.step_agent_instruction.settings_page import DEFAULT_MAX_AGENTS

    tab = services.tabs.open("progression", ready_agents.id)
    board = tab.board
    cards = board.ready.cards()
    assert len(cards) == DEFAULT_MAX_AGENTS + 1

    for card in cards:
        card.check_box.setChecked(True)
    assert board.run_button.text() == f"Run {len(cards)} Agents"
    assert not board.run_button.isEnabled()
    assert board.run_button.toolTip() == (
        f"Run {len(cards)} Agents — at most {DEFAULT_MAX_AGENTS} at a time "
        "(Settings ▸ Agent profiles)"
    )

    cards[0].check_box.setChecked(False)  # One fewer is the whole remedy.
    assert board.run_button.isEnabled(), board.run_button.toolTip()


def _click(app, card, kind=None):
    """A left button event on the card's centre. A hand-built event rather than QTest's:
    QTest's press never sees a release, so `QApplication.mouseButtons()` would stay held
    for every later test in the process."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    centre = QPointF(card.rect().center())
    app.sendEvent(
        card,
        QMouseEvent(
            kind or QEvent.Type.MouseButtonPress,
            centre,
            QPointF(card.mapToGlobal(centre.toPoint())),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def test_clicking_a_ready_card_anywhere_ticks_it(app, services, project, tab):
    """The tick is a thirteen-pixel target and the card is the thing being chosen, so the
    whole card is the target — and clicking it again takes it back out of the run."""
    card = tab.board.ready.cards()[0]
    assert card.check_box is not None and not card.check_box.isChecked()

    _click(app, card)
    assert card.check_box.isChecked() and tab.board.ticked() == [card.step_id]
    assert services.context.current().selected_entities("step") == [card.step_id]

    _click(app, card)
    assert not card.check_box.isChecked() and tab.board.ticked() == []


def test_a_double_click_opens_the_details_and_leaves_the_run_alone(
    app, services, project, tab, monkeypatch
):
    """Opening a card is not choosing it: the press that began the double click ticked it,
    and the double click puts it back."""
    from PySide6.QtCore import QEvent

    from dplanner.modules.step_properties.dialog import StepDetailsDialog

    shown = []
    monkeypatch.setattr(
        StepDetailsDialog, "exec", lambda self: shown.append(self.panel.current_step_id())
    )
    card = tab.board.ready.cards()[0]

    _click(app, card)  # The press Qt sends first.
    _click(app, card, QEvent.Type.MouseButtonDblClick)

    assert shown == [card.step_id]
    assert not card.check_box.isChecked() and tab.board.ticked() == []


def test_a_cards_second_line_starts_where_its_title_does(app, services, project, tab):
    """The tick stands beside line one and the words are one column under it: a detail that
    began under the tick would be indented from the name it belongs to."""
    card = tab.board.ready.cards()[0]
    assert card.detail.isVisible() and card.detail.text() == "Unblocks 3"
    assert card.detail.x() == card.title.x()
    # One line tall, so its indicator sits on the title's first line however far it wraps.
    from PySide6.QtGui import QFontMetrics

    assert card.check_box.height() == QFontMetrics(card.title.font()).height()


def test_a_build_without_an_agent_has_no_button_at_all(services, project):
    """Hidden means absent: agent_state=None is a build where the capability does not exist."""
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
    assert activity.board.run_button is None
    assert all(card.check_box is None for card in activity.board.ready.cards())
    activity.close()
    # Built bare, so no tab host will delete the page: a top-level widget left to the
    # boundary collector dies inside it, which is how a worker segfaulted on this test.
    activity.widget.deleteLater()


def test_the_tab_is_titled_for_its_project_and_follows_a_rename(services, project, tab):
    from dplanner.domain.commands import SetFieldCommand

    assert tab.title == "Discovery — Ready to start"
    services.undo.push(SetFieldCommand(project.id, "title", "Discovery Phase"))
    assert "Discovery Phase — Ready to start" in [a.title for a in services.tabs.activities()]


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
