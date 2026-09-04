"""Debug ▸ Telemetry: the journal as a tab — newest first, narrowed by two switches, one
span in full below.

The tab polls the process's journal, the same one every other test in this worker writes
into, so each test clears it first and records exactly what it then asserts on.
"""

import pytest

from dplanner.framework.context import Context
from dplanner.modules.debug.telemetry_view import TELEMETRY_KIND, render_detail


@pytest.fixture
def journal(services):
    services.telemetry.clear()
    return services.telemetry


def rows(activity):
    tree = activity.tree
    return [
        tuple(tree.topLevelItem(row).text(column) for column in range(1, 5))
        for row in range(tree.topLevelItemCount())
    ]


def test_the_menu_opens_the_tab(services):
    services.actions.run("debug.telemetry", Context({}))
    activity = services.tabs.current_activity()
    assert activity is not None and activity.title == "Telemetry"


def test_rows_are_newest_first_with_kind_duration_and_outcome(services, journal):
    journal.record("action", "steps.new", duration_ms=3.0)
    journal.record("command", "Add Step", duration_ms=45.0)
    journal.record("cli", "step add", exit_code=1, refused="no such project")
    activity = services.tabs.open(TELEMETRY_KIND)
    activity.refresh()
    assert rows(activity) == [
        ("cli", "step add", "0.0 ms", "exit 1"),
        ("command", "Add Step", "45.0 ms", "ok"),
        ("action", "steps.new", "3.0 ms", "ok"),
    ]


def test_the_switches_narrow_to_slow_and_to_failures(services, journal):
    journal.record("action", "quick", duration_ms=1.0)
    journal.record("action", "slow", duration_ms=80.0)
    journal.failure("broken", RuntimeError("boom"))
    journal.record("stall", "MainThread", duration_ms=400.0, samples=["File x.py, in sleep"])
    activity = services.tabs.open(TELEMETRY_KIND)
    activity.slow_only.setChecked(True)
    assert [row[1] for row in rows(activity)] == ["MainThread", "slow"]
    activity.slow_only.setChecked(False)
    activity.failures_only.setChecked(True)
    assert [(row[1], row[3]) for row in rows(activity)] == [
        ("MainThread", "stalled"),
        ("broken", "failed"),
    ]


def test_selecting_a_row_shows_the_span_in_full(services, journal):
    with journal.span("action", "steps.link", steps=2):
        journal.record("slot", "OrderActivity._refresh", duration_ms=30.0)
    try:
        raise ValueError("bad link")
    except ValueError as error:
        journal.failure("uncaught: ValueError", error)
    activity = services.tabs.open(TELEMETRY_KIND)
    activity.refresh()
    activity.tree.topLevelItem(1).setSelected(True)  # The action: its child ran inside it.
    text = activity.detail.toPlainText()
    assert text.startswith("action steps.link —") and "steps: 2" in text
    assert "--- ran inside it ---" in text and "OrderActivity._refresh" in text
    activity.tree.clearSelection()
    activity.tree.topLevelItem(0).setSelected(True)  # The failure: its traceback.
    text = activity.detail.toPlainText()
    assert "ValueError: bad link" in text and "Traceback" in text


def test_a_stall_renders_its_samples_and_what_it_interrupted(journal):
    span = journal.record(
        "stall",
        "MainThread",
        duration_ms=1200.0,
        during=["action steps.delete"],
        samples=['  File "x.py", line 3, in sleep'],
    )
    text = render_detail(span, journal.recent())
    assert "1.20 s — stalled" in text
    assert "during: ['action steps.delete']" in text
    assert "--- stack sample 1 ---" in text and "in sleep" in text


def test_the_selection_survives_a_refresh(services, journal):
    journal.record("action", "first", duration_ms=1.0)
    activity = services.tabs.open(TELEMETRY_KIND)
    activity.refresh()
    activity.tree.topLevelItem(0).setSelected(True)
    journal.record("action", "second", duration_ms=1.0)
    activity.refresh()
    assert [item.text(2) for item in activity.tree.selectedItems()] == ["first"]
