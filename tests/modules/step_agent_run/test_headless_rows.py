"""Headless runs in the Agents browser: a row beside the shells, *Follow* and *Open Session*
opening the default terminal on the very verbs a person types, greyed with the reason the verb
would refuse with — in the browser, the Step menu and Tools ▸ Agent List alike."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from tests.modules.step_agent_run.test_agent_run_tracking import module, select

from dplanner.domain import ledger, questions
from dplanner.domain.ledger import LedgerRecord, Turn
from dplanner.domain.model import now_stamp
from dplanner.modules.agent_supervisor.follow import follow_argv
from dplanner.modules.agent_supervisor.takeover import RUNNING, open_session_argv
from dplanner.modules.step_agent_run import module as run_module
from dplanner.modules.step_agent_run.browser_dialog import HeadlessRow


def headless_run(services, step, *turns: Turn, **fields) -> LedgerRecord:
    """A headless run of the step, written into its project's ledger as a launch writes it."""
    runs = module(services)
    record = LedgerRecord(
        run=ledger.new_run_id(datetime.now(UTC)),
        project=services.document.project_of(step.id).id,
        step=step.id,
        harness="claude",
        launched=now_stamp(),
        machine=ledger.machine_id(),
        session="S-1",
        mode=ledger.HEADLESS,
        stage="execute",
        attempt=1,
        callsign="kettle-two",
        **fields,
    ).with_turns(turns)
    ledger.write(runs._deps.project_dir(step.id), record)
    return record


RUNNING_TURN = Turn(n=1, prompt="launch", started=now_stamp())


@pytest.fixture
def opened(services, monkeypatch):
    """The module with its terminal recorded instead of opened."""
    runs = module(services)
    calls: list[tuple[object, ...]] = []

    def open_terminal(*opened: object) -> str:
        calls.append(opened)
        return ""

    runs._deps = replace(runs._deps, open_terminal=open_terminal)
    return runs, calls


def test_a_headless_run_is_a_row_beside_the_shells(services, step, tmp_path, opened):
    runs, _calls = opened
    record = headless_run(services, step, RUNNING_TURN)
    runs.track(step.id, str(tmp_path / "shell"), str(tmp_path / "exit"))
    runs._open_browser()
    browser = runs._browser
    row = browser.headless_row(record.run)
    assert isinstance(row, HeadlessRow)
    assert row.title.text() == "Deploy · Execute"
    words = row.status.words()
    assert words.startswith("Running · kettle-two · Claude Code · ") and words.endswith(" ago")
    assert row.status.tone() == "busy"
    assert len(browser.rows()) == 1  # The terminal's row, beside it.
    assert browser.status.words() == "2 running"
    assert runs._button.text() == "2 agents running"


def test_a_pass_runs_row_leads_with_the_cards_phrase(services, step, opened):
    runs, _calls = opened
    record = headless_run(services, step, RUNNING_TURN, pass_="P")
    runs._deps = replace(runs._deps, pass_phrase=lambda _step: "Review 1/2")
    runs._open_browser()
    assert runs._browser.headless_row(record.run).status.words().startswith("Review 1/2 · ")


def test_follow_opens_a_terminal_on_the_verb(services, step, opened):
    runs, calls = opened
    record = headless_run(services, step, RUNNING_TURN)
    runs._open_browser()
    row = runs._browser.headless_row(record.run)
    assert row.follow_button.isEnabled()

    row.follow_button.click()

    ((directory, title, argv, project),) = calls
    project_dir = runs._deps.project_dir(step.id)
    assert argv == follow_argv(runs._deps.library_path, project_dir, record.run)
    assert directory == project_dir and title == "Follow Deploy"
    assert project == services.document.project_of(step.id).id


def test_open_session_is_greyed_while_a_turn_runs(services, step, opened):
    runs, calls = opened
    record = headless_run(services, step, RUNNING_TURN)
    runs._open_browser()
    row = runs._browser.headless_row(record.run)
    assert not row.open_button.isEnabled()
    assert row.open_button.toolTip() == f"Open Session — {RUNNING}"
    select(services, step)
    state = services.actions.spec("agent.open_session").state(services.context.current())
    assert not state.enabled and state.label == f"Open Agent Session — {RUNNING}"
    assert services.actions.spec("agent.follow").state(services.context.current()).enabled
    assert calls == []


@pytest.mark.parametrize("agreed", [True, False])
def test_open_session_on_a_parked_run_asks_first(services, step, opened, monkeypatch, agreed: bool):
    runs, calls = opened
    asked = questions.asked("p", step.id, now_stamp(), [questions.one("Keep both?")])
    parked = replace(RUNNING_TURN, ended=now_stamp(), end="asked", question=asked.id)
    record = headless_run(services, step, parked)
    questions.write(runs._deps.project_dir(step.id), replace(asked, run=record.run))
    asks: list[str] = []

    def confirm(_parent: object, _title: str, question: str, verb: str) -> bool:
        asks.append(question)
        return agreed

    monkeypatch.setattr(run_module, "confirm", confirm)
    runs._open_browser()
    row = runs._browser.headless_row(record.run)
    assert row.status.words().startswith("Waits for you · a decision")

    row.open_button.click()

    assert len(asks) == 1 and "taken over by you" in asks[0]
    project_dir = runs._deps.project_dir(step.id)
    expected = open_session_argv(runs._deps.library_path, project_dir, record.run)
    assert [call[2] for call in calls] == ([expected] if agreed else [])


def test_an_ended_run_opens_without_asking(services, step, opened, monkeypatch):
    _runs, calls = opened
    done = replace(RUNNING_TURN, ended=now_stamp(), end="done")
    record = headless_run(services, step, done, ended=now_stamp())
    monkeypatch.setattr(run_module, "confirm", lambda *_a, **_k: pytest.fail("asked"))
    select(services, step)
    services.actions.run("agent.open_session", services.context.current())
    assert [call[2][-3] for call in calls] == [record.run]


def test_the_step_menu_says_when_a_step_has_no_headless_run(services, step):
    select(services, step)
    state = services.actions.spec("agent.follow").state(services.context.current())
    assert not state.enabled and state.label == "Follow Agent Run — no headless run on this step"


def test_clear_ended_takes_the_ended_headless_runs_off_the_list(services, step, opened):
    runs, _calls = opened
    done = replace(RUNNING_TURN, ended=now_stamp(), end="done")
    record = headless_run(services, step, done, ended=now_stamp())
    runs._open_browser()
    browser = runs._browser
    assert browser.headless_row(record.run) is None  # Ended: kept off screen until asked for.
    browser.show_ended.setChecked(True)
    assert browser.headless_row(record.run) is not None
    browser.clear_button.click()
    assert browser.headless_row(record.run) is None


def test_tools_agent_list_follows_the_live_headless_runs(services, step, opened):
    runs, calls = opened
    record = headless_run(services, step, RUNNING_TURN)
    runs.check()  # The tick that reads the ledger.
    entry = services.window.dynamic_menubar.data_menu("agent_run.list").actions()[0]
    assert entry.text() == "Follow “Deploy”" and entry.isEnabled()
    entry.trigger()
    assert [call[2][-3] for call in calls] == [record.run]
