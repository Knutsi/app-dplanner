"""``dplanner wait …``: a step that holds what requires it, until a day or for working days —
and the schedule reading it as a wait, which no worker takes and no tally counts.

No ``qapp`` fixture: the aspect and its verbs are Qt-free by rule.
"""

import json
from datetime import date

import pytest

from dplanner.domain.model import Step
from dplanner.domain.schedule import Wait
from dplanner.domain.store import LibraryStore
from dplanner.modules.step_wait.aspect import MODULE_ID, read, summary, write

TODAY = date(2026, 9, 4)  # The Friday before the plan starts.


@pytest.fixture
def cli(cli, clock):
    """Read the spec (2d), then Hardware arrives, then Draft the model (2d), from Monday 7
    September. At the default 50% focus each 2d step is four working days."""
    clock.pin(TODAY)
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Read the spec", "--days", "2")
    cli("step", "add", "Discovery", "Hardware arrives")
    cli("step", "add", "Discovery", "Draft the model", "--days", "2")
    cli("step", "link", "hardware-arrives", "read-the-spec")
    cli("step", "link", "draft-the-model", "hardware-arrives")
    cli("schedule", "start", "Discovery", "--date", "2026-09-07")
    return cli


def landing(cli):
    data = json.loads(
        cli("schedule", "matrix", "Discovery", "--humans", "1", "--agents", "1", "--json")
    )
    (cell,) = data["calendar"]
    return cell["finish"]


def test_the_entry_is_one_of_until_or_days_and_nothing_else():
    step = Step(title="Hardware arrives")
    assert read(step) is None and summary(step) == ""
    step.module_data[MODULE_ID] = write(Wait(until=date(2026, 11, 4)))
    assert step.module_data[MODULE_ID] == {"until": "2026-11-04", "format": 1}
    assert read(step) == Wait(until=date(2026, 11, 4)) and summary(step) == "waits until 4 Nov"
    step.module_data[MODULE_ID] = write(Wait(days=3))
    days = step.module_data[MODULE_ID]["days"]
    assert days == 3.0 and isinstance(days, float)  # a number written is a float
    assert summary(step) == "waits 3 working days"
    assert write(None) == {}  # which removes the file
    for unreadable in ({"until": "someday"}, {"days": -1}, {"days": True}, {}):
        step.module_data[MODULE_ID] = unreadable
        assert read(step) is None


def test_an_until_wait_holds_what_requires_it_to_its_day(cli):
    """Draft the model starts on the day the wait names, not the Friday the spec lands."""
    assert landing(cli) == "2026-09-16"  # no wait: the next step follows at once
    cli("wait", "set", "hardware-arrives", "--until", "2026-09-21")
    assert landing(cli) == "2026-09-24"  # four working days from Monday the 21st


def test_a_days_wait_holds_what_requires_it_for_working_days(cli):
    cli("wait", "set", "hardware-arrives", "--days", "3")
    # The spec lands as Thursday ends; three working days on, the model begins Wednesday.
    assert landing(cli) == "2026-09-21"


def test_a_wait_is_no_work(cli):
    """Never unsized, and no part of the effort or the recorded tallies."""
    before = json.loads(cli("schedule", "matrix", "Discovery", "--json"))
    assert before["unestimated"] == 1  # an ordinary step with no estimate is unsized
    cli("wait", "set", "hardware-arrives", "--days", "1")
    after = json.loads(cli("schedule", "matrix", "Discovery", "--json"))
    assert after["unestimated"] == 0 and after["effort"] == before["effort"]
    shown = json.loads(cli("progress", "show", "Discovery", "--json"))
    assert shown["scopes"][0]["steps"] == 2


def test_clearing_a_wait_shelves_it_and_says_so_twice(cli, cli_library):
    cli("wait", "set", "hardware-arrives", "--days", "2")
    assert "waits 2 working days" in cli("wait", "set", "hardware-arrives", "--days", "2")
    assert "no longer a wait" in cli("wait", "clear", "hardware-arrives")
    step = next(
        step
        for step in LibraryStore(cli_library).load().projects[0].steps
        if step.title == "Hardware arrives"
    )
    assert read(step) is None
    assert "not a wait" in cli("wait", "clear", "hardware-arrives")  # already clear succeeds


def test_a_wait_names_a_day_or_a_count_and_nothing_else(cli):
    assert "--until is a date" in cli(
        "wait", "set", "hardware-arrives", "--until", "soon", expect=1
    )
    assert "0 or more" in cli("wait", "set", "hardware-arrives", "--days", "-2", expect=1)
