"""The status aspect: its vocabulary on disk, its CLI, and its Status submenu."""

import json
from datetime import date

import pytest

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.planning.status import (
    MERGED_ORIGIN,
    MODULE_ID,
    Status,
    Unknown,
    forget_days_for_paste,
    label,
    read_since,
    read_started,
    record_merged,
    record_started,
    stored,
    write,
)

MONDAY, TUESDAY, FRIDAY = date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 25)

# -- the aspect, with no application at all ----------------------------------------------------


def test_absence_reads_as_pending():
    assert stored(Step(title="A")) is Status.PENDING


def test_write_and_read_round_trip():
    step = Step(title="A")
    step.module_data[MODULE_ID] = write(Status.DONE, today=date(2026, 9, 21))
    assert stored(step) is Status.DONE


def test_pending_writes_nothing():
    """Absence encodes the default: setting a step back to pending removes the file."""
    assert write(Status.PENDING, today=date(2026, 9, 21)) == {}


def test_an_unknown_word_reads_as_unknown_and_stays_on_disk():
    """A newer build may know states this one does not: reading must neither crash over one
    nor guess pending, which would make the step due again — and must not touch it."""
    step = Step(title="A")
    step.module_data[MODULE_ID] = {"status": "paused", "format": 1}
    assert stored(step) == Unknown("paused")
    assert step.module_data[MODULE_ID] == {"status": "paused", "format": 1}


def test_an_entry_with_days_but_no_word_reads_as_pending():
    step = Step(title="A")
    step.module_data[MODULE_ID] = {"since": "2026-09-21", "format": 2}
    assert stored(step) is Status.PENDING


def test_a_status_remembers_the_day_it_changed_and_the_day_work_began():
    step = Step(title="A")
    step.module_data[MODULE_ID] = write(Status.IN_PROGRESS, today=MONDAY)
    assert (read_since(step), read_started(step)) == (MONDAY, MONDAY)
    # Said again, nothing moved: the day it changed stands.
    step.module_data[MODULE_ID] = write(
        Status.IN_PROGRESS, today=TUESDAY, previous=step.module_data[MODULE_ID]
    )
    assert read_since(step) == MONDAY
    step.module_data[MODULE_ID] = write(
        Status.DONE, today=FRIDAY, previous=step.module_data[MODULE_ID]
    )
    assert (stored(step), read_since(step), read_started(step)) == (Status.DONE, FRIDAY, MONDAY)


def test_a_reopened_step_keeps_the_day_it_first_began():
    """Pending keeps the days — an entry with no status, which reads as pending — so work
    picked up again knows when it first started."""
    step = Step(title="A")
    step.module_data[MODULE_ID] = write(Status.IN_PROGRESS, today=MONDAY)
    step.module_data[MODULE_ID] = write(
        Status.PENDING, today=TUESDAY, previous=step.module_data[MODULE_ID]
    )
    assert "status" not in step.module_data[MODULE_ID] and stored(step) is Status.PENDING
    assert (read_since(step), read_started(step)) == (TUESDAY, MONDAY)
    step.module_data[MODULE_ID] = write(
        Status.IN_PROGRESS, today=FRIDAY, previous=step.module_data[MODULE_ID]
    )
    assert (read_since(step), read_started(step)) == (FRIDAY, MONDAY)


def test_a_status_written_before_the_days_were_stamped_has_none():
    """An older build's entry says nothing of its days, and nothing reads that as today."""
    step = Step(title="A")
    step.module_data[MODULE_ID] = {"status": "done", "format": 1}
    assert (stored(step), read_since(step), read_started(step)) == (Status.DONE, None, None)


def test_a_copy_keeps_the_status_and_forgets_the_days():
    done, pending = Step(title="A"), Step(title="B")
    done.module_data[MODULE_ID] = write(Status.DONE, today=FRIDAY)
    started = write(Status.IN_PROGRESS, today=MONDAY)
    pending.module_data[MODULE_ID] = write(Status.PENDING, today=TUESDAY, previous=started)
    forget_days_for_paste(None, [done, pending], {})  # type: ignore[arg-type]
    assert stored(done) is Status.DONE and read_since(done) is None
    assert MODULE_ID not in pending.module_data


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
    assert stored(step) is Status.IN_PROGRESS


def test_record_started_writes_nothing_twice():
    """The claim is idempotent: a second launch on a running step dirties nothing."""
    library, step = _one_step()
    record_started(library, step.id, date(2026, 9, 21))
    assert record_started(library, step.id, date(2026, 9, 21)) is False


def test_record_merged_finishes_only_a_step_waiting_on_its_merge():
    """A merged PR finishes a step ready to merge, with the merge's own origin — and says
    nothing about a step nobody has accepted, which keeps its status."""
    library, step = _one_step()
    origins = []
    library.module_data_changed.connect(lambda _node, _module, origin: origins.append(origin))
    step.module_data[MODULE_ID] = write(Status.READY_FOR_REVIEW, today=MONDAY)
    assert record_merged(library, step.id, TUESDAY) is False
    assert stored(step) is Status.READY_FOR_REVIEW

    step.module_data[MODULE_ID] = write(Status.READY_TO_MERGE, today=MONDAY)
    assert record_merged(library, step.id, TUESDAY) is True
    assert stored(step) is Status.DONE
    assert origins == [MERGED_ORIGIN]
    assert record_merged(library, step.id, TUESDAY) is False  # Done already: nothing twice.


def test_record_started_overrides_a_finished_claim():
    """Launching on a step that reads done means work resumed — there is no other honest
    reading of it, and the person who did not want that switched the launch setting off."""
    library, step = _one_step()
    step.module_data[MODULE_ID] = write(Status.DONE, today=date(2026, 9, 21))
    assert record_started(library, step.id, date(2026, 9, 21)) is True
    assert stored(step) is Status.IN_PROGRESS


def test_record_started_on_a_step_that_is_gone_answers_false():
    library, _step = _one_step()
    assert record_started(library, "nobody", date(2026, 9, 21)) is False


def test_review_and_merge_sit_between_in_progress_and_done():
    assert tuple(status.value for status in Status) == (
        "pending",
        "in-progress",
        "ready-for-review",
        "ready-to-merge",
        "done",
        "blocked",
    )


def test_any_worked_status_stamps_started_the_first_time():
    """A step an agent was never claimed on still began the day it came back for review;
    done straight from pending says nothing of when it began."""
    for worked in (Status.IN_PROGRESS, Status.READY_FOR_REVIEW, Status.READY_TO_MERGE):
        entry = write(worked, today=MONDAY)
        assert entry["started"] == MONDAY.isoformat(), worked
        later = write(Status.DONE, today=FRIDAY, previous=entry)
        assert later["started"] == MONDAY.isoformat() and later["since"] == FRIDAY.isoformat()
    assert "started" not in write(Status.DONE, today=MONDAY)


def test_the_menu_words_keep_the_small_words_small():
    assert [label(status) for status in Status] == [
        "Pending",
        "In Progress",
        "Ready for Review",
        "Ready to Merge",
        "Done",
        "Blocked",
    ]


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


# -- an agent's done waits for review ----------------------------------------------------------


@pytest.fixture
def agent_step(cli):
    cli("step", "add", "Discovery", "Build the modal", "--agent")
    return "Build the modal"


def _decisions(cli):
    notes = json.loads(cli("note", "list", "Discovery", "--label", "decision", "--json"))
    return notes if isinstance(notes, list) else notes["notes"]


def test_inside_an_agents_shell_done_on_an_agent_step_is_refused(cli, agent_step, monkeypatch):
    """The spec's rule: agents set Ready for review instead of done. The refusal names the
    word to use and the way out, and nothing is written."""
    monkeypatch.setenv("CLAUDECODE", "1")
    said = cli("status", "set", agent_step, "done", expect=1)
    assert "ready-for-review" in said and "--because" in said
    assert "pending" in cli("status", "show", agent_step)


def test_from_review_an_agent_may_finish_it(cli, agent_step, monkeypatch):
    """A reviewing agent takes a reviewed step on: ready-to-merge, then done."""
    monkeypatch.setenv("CLAUDECODE", "1")
    cli("status", "set", agent_step, "ready-for-review")
    cli("status", "set", agent_step, "done")
    assert "done" in cli("status", "show", agent_step)


def test_because_sets_done_and_keeps_the_reason_as_one_decision_note(cli, agent_step, monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "t1")  # Every agent CLI's shell, not only Claude's.
    said = cli("status", "set", agent_step, "done", "--because", "docs only, nothing to review")
    assert "done" in cli("status", "show", agent_step)
    (note,) = _decisions(cli)
    assert note["title"] == "Done without review"
    assert note["body"] == "docs only, nothing to review" and note["key"] == "S2"
    assert note["note"] in said


def test_because_run_twice_is_still_one_note(cli, agent_step, monkeypatch):
    """An agent re-runs a verb after a refusal; the note log's rule holds for this writer
    too — adding twice is one note."""
    monkeypatch.setenv("CLAUDECODE", "1")
    cli("status", "set", agent_step, "done", "--because", "docs only, nothing to review")
    again = cli("status", "set", agent_step, "done", "--because", "docs only, nothing to review")
    (note,) = _decisions(cli)
    assert f"already recorded as {note['note']}" in again


def test_a_person_and_a_plain_step_are_never_asked(cli, agent_step, monkeypatch):
    cli("status", "set", agent_step, "done")  # No marker: a person in their own terminal.
    monkeypatch.setenv("CLAUDECODE", "1")
    cli("status", "set", "Read the spec", "done")  # Not an agent step.
    assert _decisions(cli) == []


def test_because_goes_with_done_only(cli, agent_step):
    said = cli("status", "set", agent_step, "blocked", "--because", "why not", expect=1)
    assert "--because" in said


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
    assert {f"status.{status.value}" for status in Status} <= ids


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
    assert (stored(step), read_since(step), read_started(step)) == (Status.DONE, TUESDAY, MONDAY)
    services.undo.undo()  # the days come back with the status
    assert (stored(step), read_since(step), read_started(step)) == (
        Status.IN_PROGRESS,
        MONDAY,
        MONDAY,
    )


def test_a_status_verb_moves_every_chosen_step_as_one_undo_step(services, step, make_project):
    """A lasso on the canvas, or the ticked rows of Step statuses: all of them at once."""
    other = Step(title="Draft the model")
    AddNodeCommand(services.document.project_of(step.id).id, other).redo(services.document)
    services.context.set_scope(
        SCOPE_SELECTION,
        (ContextNode(selection_uri("step", step.id)), ContextNode(selection_uri("step", other.id))),
    )
    context = services.context.current()
    services.actions.run("status.ready-for-review", context)
    services.actions.run("status.ready-to-merge", context)
    assert stored(step) == stored(other) is Status.READY_TO_MERGE
    assert services.actions.spec("status.ready-to-merge").state(context).checked is True
    services.undo.undo()
    assert stored(step) == stored(other) is Status.READY_FOR_REVIEW


def test_checked_only_when_every_chosen_step_stands_there(services, step):
    other = Step(title="Draft the model")
    AddNodeCommand(services.document.project_of(step.id).id, other).redo(services.document)
    services.actions.run("status.done", _chosen(services, step))
    context = _chosen(services, step, other)
    assert services.actions.spec("status.done").state(context).checked is False


def test_a_wait_among_the_chosen_greys_the_verb(services, step):
    wait = Step(title="Hold a day")
    AddNodeCommand(services.document.project_of(step.id).id, wait).redo(services.document)
    from dplanner.planning.schedule import Wait
    from dplanner.planning.wait import write as write_wait

    services.document.set_module_data(wait.id, "step_wait", write_wait(Wait(days=1.0)))
    state = services.actions.spec("status.done").state(_chosen(services, step, wait))
    assert not state.enabled and "a wait has no status" in state.label


def _chosen(services, *steps):
    from dplanner.framework.context import Context

    return Context(
        {SCOPE_SELECTION: tuple(ContextNode(selection_uri("step", s.id)) for s in steps)}
    )


def test_with_no_step_selected_the_actions_are_disabled(services):
    services.context.set_scope(SCOPE_SELECTION, ())
    state = services.actions.spec("status.done").state(services.context.current())
    assert not state.enabled
