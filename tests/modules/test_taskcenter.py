"""The task browser over the running application's task service: rows follow the tasks and
keep their widgets across every tick, a busy line with no bar until the end is known, Cancel
asks its question first, finished rows clear, and the browser opens on its way out."""

import pytest
from PySide6.QtWidgets import QToolButton

from dplanner.framework.context import Context
from dplanner.modules.taskcenter import view
from dplanner.modules.taskcenter.module import TaskCenterModule


@pytest.fixture
def centre(services):
    module = next(m for m in services.modules if isinstance(m, TaskCenterModule))
    services.actions.run("taskcenter.show_tasks", Context({}))
    yield module
    module.browser.hide()


def test_rows_follow_the_tasks_and_keep_their_widgets(services, centre):
    tasks = services.tasks
    browser = centre.browser
    assert browser.empty.isVisibleTo(browser) and not browser.well.isVisibleTo(browser)
    assert centre.button.isHidden()

    reading = tasks.start("Reading through", keep_finished=True)
    (row,) = browser.rows()
    assert row.title.text() == "Reading through"
    assert row.status.tone() == "busy" and row.bar.isHidden()
    assert browser.status.words() == "1 running"
    assert centre.button.text() == "Reading through…"

    tasks.finish(reading)
    assert browser.rows() == [row]  # The same widget, turned to its outcome in place.
    assert row.status.tone() == "ok" and row.status.words().startswith("Done in")
    assert row.dismiss_button is not None and row.dismiss_button.isVisibleTo(row)

    saving = tasks.start("Saving")
    assert len(browser.rows()) == 2
    tasks.finish(saving)
    assert browser.rows() == [row]  # Not kept once finished.


def test_cancel_asks_its_question_first_when_the_task_has_one(services, centre, monkeypatch):
    asked: list[str] = []
    answers = [False, True]

    def ask(_parent, _title, question, **_verb):
        asked.append(question)
        return answers.pop(0)

    monkeypatch.setattr(view, "confirm", ask)
    copyedit = services.tasks.start(
        "Copyedit", cancellable=True, cancel_prompt="Stop the copyedit?"
    )
    (row,) = centre.browser.rows()
    assert row.cancel_button is not None
    row.cancel_button.click()
    assert asked == ["Stop the copyedit?"] and not copyedit.cancel_requested
    row.cancel_button.click()
    assert copyedit.cancel_requested
    assert not row.cancel_button.isEnabled() and row.cancel_button.text() == "Stopping…"

    probe = services.tasks.start("Probe", cancellable=True)
    quiet = next(found for found in centre.browser.rows() if found.task is probe)
    assert quiet.cancel_button is not None
    quiet.cancel_button.click()
    assert probe.cancel_requested and len(asked) == 2  # No question, so none was asked.
    services.tasks.finish(copyedit)
    services.tasks.finish(probe)


def test_a_known_fraction_fills_the_bar_under_the_busy_line(services, centre):
    fetching = services.tasks.start("Fetching 12 pages")
    (row,) = centre.browser.rows()
    assert row.bar.isHidden()
    services.tasks.set_progress(fetching, 0.4)
    assert not row.bar.isHidden() and row.bar.value() == 40
    assert row.status.tone() == "busy"
    services.tasks.finish(fetching)


def test_clear_finished_is_greyed_until_something_has_finished(services, centre):
    browser = centre.browser
    assert not browser.clear_button.isEnabled()
    services.tasks.finish(services.tasks.start("Writing the report", keep_finished=True))
    failing = services.tasks.start("Checking gh", keep_finished=True)
    services.tasks.finish(failing, "gh: not logged in")
    failed = next(row for row in browser.rows() if row.task is failing)
    assert failed.status.tone() == "error"
    assert failed.status.words().startswith("Failed after")
    assert browser.clear_button.isEnabled()
    browser.clear_button.click()
    assert services.tasks.finished() == [] and browser.rows() == []
    assert not browser.clear_button.isEnabled() and browser.empty.isVisibleTo(browser)


def test_the_browser_opens_on_its_way_out_never_on_a_rows_verb(services, centre, app):
    copyedit = services.tasks.start("Copyedit", cancellable=True)
    browser = centre.browser
    browser.hide()
    services.actions.run("taskcenter.show_tasks", Context({}))
    app.processEvents()
    assert not isinstance(browser.focusWidget(), QToolButton)
    services.tasks.finish(copyedit)
