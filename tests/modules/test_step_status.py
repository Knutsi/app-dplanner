"""The status aspect: its vocabulary on disk, its CLI, and its Status submenu."""

import json
from datetime import date

import pytest

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.step_status.aspect import (
    MODULE_ID,
    STATUSES,
    forget_days_for_paste,
    read,
    read_since,
    read_started,
    record_started,
    write,
)

MONDAY, TUESDAY, FRIDAY = date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 25)

# -- the aspect, with no application at all ----------------------------------------------------


def test_absence_reads_as_pending():
    assert read(Step(title="A")) == "pending"


def test_write_and_read_round_trip():
    step = Step(title="A")
    step.module_data[MODULE_ID] = write("done", today=date(2026, 9, 21))
    assert read(step) == "done"


def test_pending_writes_nothing():
    """Absence encodes the default: setting a step back to pending removes the file."""
    assert write("pending", today=date(2026, 9, 21)) == {}


def test_an_unknown_word_reads_as_pending_not_an_error():
    """A newer build may know states this one does not; reading must not crash over one."""
    step = Step(title="A")
    step.module_data[MODULE_ID] = {"status": "paused", "format": 1}
    assert read(step) == "pending"


def test_a_status_remembers_the_day_it_changed_and_the_day_work_began():
    step = Step(title="A")
    step.module_data[MODULE_ID] = write("in-progress", today=MONDAY)
    assert (read_since(step), read_started(step)) == (MONDAY, MONDAY)
    # Said again, nothing moved: the day it changed stands.
    step.module_data[MODULE_ID] = write(
        "in-progress", today=TUESDAY, previous=step.module_data[MODULE_ID]
    )
    assert read_since(step) == MONDAY
    step.module_data[MODULE_ID] = write("done", today=FRIDAY, previous=step.module_data[MODULE_ID])
    assert (read(step), read_since(step), read_started(step)) == ("done", FRIDAY, MONDAY)


def test_a_reopened_step_keeps_the_day_it_first_began():
    """Pending keeps the days — an entry with no status, which reads as pending — so work
    picked up again knows when it first started."""
    step = Step(title="A")
    step.module_data[MODULE_ID] = write("in-progress", today=MONDAY)
    step.module_data[MODULE_ID] = write(
        "pending", today=TUESDAY, previous=step.module_data[MODULE_ID]
    )
    assert "status" not in step.module_data[MODULE_ID] and read(step) == "pending"
    assert (read_since(step), read_started(step)) == (TUESDAY, MONDAY)
    step.module_data[MODULE_ID] = write(
        "in-progress", today=FRIDAY, previous=step.module_data[MODULE_ID]
    )
    assert (read_since(step), read_started(step)) == (FRIDAY, MONDAY)


def test_a_status_written_before_the_days_were_stamped_has_none():
    """An older build's entry says nothing of its days, and nothing reads that as today."""
    step = Step(title="A")
    step.module_data[MODULE_ID] = {"status": "done", "format": 1}
    assert (read(step), read_since(step), read_started(step)) == ("done", None, None)


def test_a_copy_keeps_the_status_and_forgets_the_days():
    done, pending = Step(title="A"), Step(title="B")
    done.module_data[MODULE_ID] = write("done", today=FRIDAY)
    started = write("in-progress", today=MONDAY)
    pending.module_data[MODULE_ID] = write("pending", today=TUESDAY, previous=started)
    forget_days_for_paste(None, [done, pending])  # type: ignore[arg-type]
    assert read(done) == "done" and read_since(done) is None
    assert MODULE_ID not in pending.module_data


def test_writing_an_unknown_status_is_refused():
    with pytest.raises(ValueError, match="unknown status"):
        write("paused", today=date(2026, 9, 21))


# -- the window's own claim that work started --------------------------------------------------


def _one_step():
    from dplanner.domain.model import Library, Project

    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    step = Step(title="Deploy")
    library.add_child(project.id, step)
    return library, step


def test_record_started_claims_in_progress():
    library, step = _one_step()
    assert record_started(library, step.id, date(2026, 9, 21)) is True
    assert read(step) == "in-progress"


def test_record_started_writes_nothing_twice():
    """The claim is idempotent: a second launch on a running step dirties nothing."""
    library, step = _one_step()
    record_started(library, step.id, date(2026, 9, 21))
    assert record_started(library, step.id, date(2026, 9, 21)) is False


def test_record_started_overrides_a_finished_claim():
    """Launching on a step that reads done means work resumed — there is no other honest
    reading of it, and the person who did not want that switched the launch setting off."""
    library, step = _one_step()
    step.module_data[MODULE_ID] = write("done", today=date(2026, 9, 21))
    assert record_started(library, step.id, date(2026, 9, 21)) is True
    assert read(step) == "in-progress"


def test_record_started_on_a_step_that_is_gone_answers_false():
    library, _step = _one_step()
    assert record_started(library, "nobody", date(2026, 9, 21)) is False


# -- the CLI -----------------------------------------------------------------------------------


@pytest.fixture
def cli(cli):
    """The shared CLI over a seeded project — the conftest fixture, pre-populated."""
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Read the spec")
    return cli


def test_set_show_and_clear(cli, workspace, clock):
    clock.pin(MONDAY)
    cli("status", "set", "Read the spec", "done")
    assert json.loads(cli("status", "show", "Read the spec", "--json"))["status"] == "done"
    status_file = (
        workspace / "discovery" / "steps" / "read-the-spec" / "modules" / "step_status.json"
    )
    assert json.loads(status_file.read_text()) == {
        "status": "done",
        "since": "2026-09-21",
        "format": 2,
    }
    clock.pin(TUESDAY)
    cli("status", "clear", "Read the spec")
    assert "pending" in cli("status", "show", "Read the spec")
    assert json.loads(status_file.read_text()) == {"since": "2026-09-22", "format": 2}


def test_a_step_that_was_never_anything_has_no_file(cli, workspace):
    cli("status", "set", "Read the spec", "pending")
    step_dir = workspace / "discovery" / "steps" / "read-the-spec"
    assert not (step_dir / "modules" / "step_status.json").exists()


def test_a_status_said_from_the_terminal_is_a_day_on_record(cli, workspace, clock):
    """An agent reports with `status set`, and nobody opens a window to record it: the verb
    writes the day's row itself, counting the status it changed — once."""
    cli("step", "add", "Discovery", "Draft the model", "--days", "2")
    clock.pin(MONDAY)
    cli("status", "set", "Draft the model", "in-progress")
    history = workspace / "discovery" / "modules" / "progress_history.json"
    (row,) = json.loads(history.read_text())["days"]
    assert row["day"] == "2026-09-21" and row["stretches"][0]["changed"] == 1
    cli("status", "set", "Draft the model", "in-progress")  # nothing moved
    assert len(json.loads(history.read_text())["days"]) == 1


def test_a_word_outside_the_vocabulary_is_refused_by_the_parser(cli):
    """Argparse refuses it before the verb runs — the vocabulary is in the usage line."""
    with pytest.raises(SystemExit):
        cli("status", "set", "Read the spec", "paused")


def test_list_groups_by_status_in_working_order(cli):
    cli("step", "add", "Discovery", "Draft the model", "--after", "Read the spec")
    cli("status", "set", "Read the spec", "done")
    listing = json.loads(cli("status", "list", "Discovery", "--json"))["statuses"]
    assert [row["title"] for row in listing["done"]] == ["Read the spec"]
    assert [row["title"] for row in listing["pending"]] == ["Draft the model"]
    text = cli("status", "list", "Discovery")
    assert "done (1):" in text and "pending (1):" in text


# -- the Status submenu ------------------------------------------------------------------------


@pytest.fixture
def step(services, make_project):
    project = make_project("Discovery")
    step = Step(title="Read the spec")
    AddNodeCommand(project.id, step).redo(services.document)
    return step


def select(services, step):
    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("step", step.id)),))


def test_the_actions_exist_one_per_state(services):
    ids = {spec.id for spec in services.actions.all_specs()}
    assert {f"status.{status}" for status in STATUSES} <= ids


def test_the_current_state_is_checked(services, step):
    select(services, step)
    context = services.context.current()
    assert services.actions.spec("status.pending").state(context).checked is True
    assert services.actions.spec("status.done").state(context).checked is False


def test_running_the_action_sets_the_status_undoably(services, step):
    services.clock.pin(MONDAY)
    select(services, step)
    services.actions.run("status.in-progress", services.context.current())
    services.undo.break_coalescing()  # two statuses in a row would merge into one step
    services.clock.pin(TUESDAY)
    services.actions.run("status.done", services.context.current())
    assert (read(step), read_since(step), read_started(step)) == ("done", TUESDAY, MONDAY)
    services.undo.undo()  # the days come back with the status
    assert (read(step), read_since(step), read_started(step)) == ("in-progress", MONDAY, MONDAY)


def test_with_no_step_selected_the_actions_are_disabled(services):
    services.context.set_scope(SCOPE_SELECTION, ())
    state = services.actions.spec("status.done").state(services.context.current())
    assert not state.enabled
