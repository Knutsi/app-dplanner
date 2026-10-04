"""Setting a status is one workflow: what it refuses, what it writes, what it ends — and
that the window's Status verbs and ``dplanner status set`` reach the same outcome."""

import json
from datetime import date

import pytest

from dplanner.domain.commands import AddNodeCommand, SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.workflow import Actor, AgentRun, Daemon, EndClaim, Person, PlanView
from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri
from dplanner.modules.step_status.workflows import STOPPED, Kept, StatusWorkflow, perform
from dplanner.planning import agent, wait
from dplanner.planning.schedule import Wait
from dplanner.planning.status import MODULE_ID, Status, stored

MONDAY = date(2026, 9, 21)
ACTORS: list[Actor] = [Person(), AgentRun(), Daemon()]

# -- the workflow, with no application at all --------------------------------------------------


def _keep_reason(view: PlanView, step: Step, reason: str, today: date):
    return "N1", SetModuleDataCommand(step.id, "notes_probe", {"reason": reason})


WORKFLOW = StatusWorkflow(keep_reason=_keep_reason)


@pytest.fixture
def library():
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    for title in ("Read the spec", "Build the modal", "Hold a day"):
        library.add_child(project.id, Step(title=title))
    library.set_module_data(
        _step(library, "Build the modal").id, agent.MODULE_ID, agent.write_state(True)
    )
    library.set_module_data(
        _step(library, "Hold a day").id, wait.MODULE_ID, wait.write(Wait(days=1.0))
    )
    return library


def _step(library, title):
    return next(n for n in library.nodes() if isinstance(n, Step) and n.title == title)


def test_a_library_is_a_plan_view(library):
    view: PlanView = library  # mypy holds this; a mutator on `view` would not type-check.
    assert view.project_of(_step(library, "Read the spec").id).title == "Discovery"


@pytest.mark.parametrize("actor", ACTORS, ids=lambda a: type(a).__name__)
@pytest.mark.parametrize("status", list(Status), ids=lambda s: s.value)
def test_a_plain_step_takes_any_status_from_anyone(library, status, actor):
    step = _step(library, "Read the spec")
    change, _kept = WORKFLOW.set_status(library, step, status, actor=actor, today=MONDAY)
    assert change.follow_ups == (
        (EndClaim(library.project_of(step.id).id, step.id),) if status in STOPPED else ()
    )
    if change.command is not None:
        change.command.redo(library)
    assert stored(step) is status


@pytest.mark.parametrize("actor", ACTORS, ids=lambda a: type(a).__name__)
@pytest.mark.parametrize("status", list(Status), ids=lambda s: s.value)
def test_a_wait_takes_only_pending_whoever_asks(library, status, actor):
    wait = _step(library, "Hold a day")
    why = WORKFLOW.refusal([wait], status, actor)
    assert bool(why) is (status is not Status.PENDING)
    if why:
        assert "a wait has no status" in why
        with pytest.raises(ValueError, match="a wait has no status"):
            WORKFLOW.set_status(library, wait, status, actor=actor, today=MONDAY)


@pytest.mark.parametrize("actor", ACTORS, ids=lambda a: type(a).__name__)
def test_only_an_agent_run_is_held_at_review(library, actor):
    """The director rule as a typed branch: a person and a daemon finish an agent step; an
    agent's own run stops at ready-for-review."""
    step = _step(library, "Build the modal")
    why = WORKFLOW.refusal([step], Status.DONE, actor)
    assert bool(why) is isinstance(actor, AgentRun)
    assert not why or ("ready-for-review" in why and "--because" in why)


def test_under_review_an_agent_may_finish_it(library):
    step = _step(library, "Build the modal")
    change, _kept = WORKFLOW.set_status(
        library, step, Status.READY_FOR_REVIEW, actor=AgentRun(), today=MONDAY
    )
    assert change.command is not None
    change.command.redo(library)
    assert WORKFLOW.refusal([step], Status.DONE, AgentRun()) == ""


def test_a_reason_is_kept_in_the_same_command(library):
    step = _step(library, "Build the modal")
    change, kept = WORKFLOW.set_status(
        library, step, Status.DONE, actor=AgentRun(), today=MONDAY, because="docs only"
    )
    assert kept == Kept("N1", added=True) and change.command is not None
    change.command.redo(library)
    assert stored(step) is Status.DONE
    assert step.module_data["notes_probe"] == {"reason": "docs only"}
    change.command.undo(library)  # One undo gesture takes both back.
    assert stored(step) is Status.PENDING and "notes_probe" not in step.module_data


def test_a_reason_goes_with_done_only(library):
    assert "--because" in WORKFLOW.refusal(
        [_step(library, "Read the spec")], Status.BLOCKED, Person(), because="why not"
    )


def test_a_repeated_status_changes_nothing_but_still_ends_the_claim(library):
    step = _step(library, "Read the spec")
    first, _kept = WORKFLOW.set_status(
        library, step, Status.READY_FOR_REVIEW, actor=Person(), today=MONDAY
    )
    assert first.command is not None
    first.command.redo(library)
    again, _kept = WORKFLOW.set_status(
        library, step, Status.READY_FOR_REVIEW, actor=Person(), today=MONDAY
    )
    assert again.command is None and again.follow_ups == first.follow_ups
    assert perform(again.follow_ups, lambda claim: True).ended == first.follow_ups


# -- both surfaces, one outcome ----------------------------------------------------------------


@pytest.mark.parametrize("status", list(Status), ids=lambda s: s.value)
def test_the_window_and_the_cli_reach_the_same_outcome(
    services, make_project, cli, workspace, clock, at_work_board, status
):
    """The same step, the same day, an agent at work on it: the director's verb in the
    window and a person's `status set` write the same entry and end the claim alike."""
    services.clock.pin(MONDAY)
    clock.pin(MONDAY)

    project = make_project("Window")
    step = Step(title="Read the spec")
    AddNodeCommand(project.id, step).redo(services.document)
    at_work_board.start(project.id, step.id, "in the window's plan")
    services.actions.run(
        f"status.{status.value}",
        Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step.id)),)}),
    )

    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Read the spec")
    cli("agent-work", "start", "in the terminal's plan", "--step", "S1", "--project", "Discovery")
    cli("status", "set", "Read the spec", status.value, "--project", "Discovery")

    status_file = (
        workspace / "discovery" / "steps" / "read-the-spec" / "modules" / f"{MODULE_ID}.json"
    )
    written = json.loads(status_file.read_text()) if status_file.exists() else {}
    assert dict(step.module_data.get(MODULE_ID) or {}) == written
    standing = {claim.doing for claim in at_work_board.claims()}
    expected = set() if status in STOPPED else {"in the window's plan", "in the terminal's plan"}
    assert standing == expected


def test_the_window_s_done_is_one_undo_step_and_leaves_the_claim_ended(
    services, make_project, at_work_board
):
    """The claim is an external fact: undoing the director's done brings the status back,
    never the agent's banner."""
    services.clock.pin(MONDAY)
    project = make_project("Window")
    step = Step(title="Read the spec")
    AddNodeCommand(project.id, step).redo(services.document)
    at_work_board.start(project.id, step.id, "Building")
    context = Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step.id)),)})
    services.actions.run("status.done", context)
    assert stored(step) is Status.DONE and at_work_board.claims() == []
    services.undo.undo()
    assert stored(step) is Status.PENDING and at_work_board.claims() == []


# -- the failure boundaries: a claim is released only once the change is accepted ---------------


def _window_steps(services, make_project, at_work_board, titles):
    project = make_project("Window")
    steps = []
    for title in titles:
        step = Step(title=title)
        AddNodeCommand(project.id, step).redo(services.document)
        at_work_board.start(project.id, step.id, title)
        steps.append(step)
    context = Context(
        {SCOPE_SELECTION: tuple(ContextNode(selection_uri("step", s.id)) for s in steps)}
    )
    return steps, context


def test_a_cli_run_that_writes_nothing_releases_nothing(cli, at_work_board, monkeypatch):
    """The claim is an effect owed to a *written* run: a flush that refuses leaves the
    status unwritten and the claim standing, and the run never says it was done."""
    from dplanner.domain.store import LibraryStore, StaleWorkspaceError

    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Read the spec")
    cli("agent-work", "start", "Building", "--step", "S1", "--project", "Discovery")

    def refuse(self, marks):
        raise StaleWorkspaceError("somebody else wrote here")

    monkeypatch.setattr(LibraryStore, "flush", refuse)
    said = cli("status", "set", "S1", "done", "--project", "Discovery", expect=1)
    monkeypatch.undo()
    assert "nothing was written" in said and "no agent at work" not in said
    assert "pending" in cli("status", "show", "S1", "--project", "Discovery")
    assert [claim.doing for claim in at_work_board.claims()] == ["Building"]


def test_a_cli_claim_that_cannot_be_ended_is_said_and_the_status_stands(
    cli, at_work_board, monkeypatch
):
    cli("project", "create", "Discovery")
    cli("step", "add", "Discovery", "Read the spec")
    cli("agent-work", "start", "Building", "--step", "S1", "--project", "Discovery")

    def locked(project, step=""):
        raise PermissionError("the claim file is locked")

    monkeypatch.setattr(at_work_board, "end", locked)
    said = cli("status", "set", "S1", "done", "--project", "Discovery", expect=1)
    monkeypatch.undo()
    assert "done is written" in said and "the claim file is locked" in said
    assert "done" in cli("status", "show", "S1", "--project", "Discovery")


def test_a_window_selection_that_fails_part_way_moves_no_step_and_ends_no_claim(
    services, make_project, at_work_board, monkeypatch
):
    """One composite for the selection: a refusal on the second step takes the first back,
    leaves no undo entry, and ends no claim."""
    steps, context = _window_steps(services, make_project, at_work_board, ["One", "Two"])
    library = services.document
    real = type(library).set_module_data

    def refuse_two(self, owner_id, module_id, data, *args, **kwargs):
        if owner_id == steps[1].id and module_id == MODULE_ID:
            raise ValueError("another writer changed it")
        return real(self, owner_id, module_id, data, *args, **kwargs)

    monkeypatch.setattr(type(library), "set_module_data", refuse_two)
    with pytest.raises(ValueError, match="another writer"):
        services.actions.run("status.done", context)
    monkeypatch.undo()
    assert [stored(step) for step in steps] == [Status.PENDING, Status.PENDING]
    assert not services.undo.can_undo()
    assert {claim.doing for claim in at_work_board.claims()} == {"One", "Two"}


def test_a_claim_that_cannot_be_ended_leaves_the_others_ended_and_says_so(
    services, make_project, at_work_board, monkeypatch
):
    """A failed release mid-selection: every status is set, every other claim is ended, and
    the one that stands is on a notice with a retry — nothing rolled back for an effect."""
    from dplanner.modules.step_status.module import NOTICE_ID

    steps, context = _window_steps(services, make_project, at_work_board, ["One", "Two", "Three"])
    real = at_work_board.end

    def locked_two(project, step=""):
        if step == steps[1].id:
            raise PermissionError("the claim file is locked")
        return real(project, step)

    monkeypatch.setattr(at_work_board, "end", locked_two)
    services.actions.run("status.done", context)
    assert [stored(step) for step in steps] == [Status.DONE] * 3
    assert [claim.doing for claim in at_work_board.claims()] == ["Two"]
    (notice,) = [n for n in services.window.notices.notices() if n.id == NOTICE_ID]
    assert "the claim file is locked" in notice.words and notice.act is not None

    monkeypatch.undo()
    notice.act()  # The retry takes the same idempotent path, and the notice goes.
    assert at_work_board.claims() == []
    assert NOTICE_ID not in [n.id for n in services.window.notices.notices()]


def test_a_refused_review_approval_is_a_refusal_not_a_traceback(cli, monkeypatch):
    """An agent approving a source that was never put up for review is held at review like
    any agent's done — said as one line, with nothing written."""
    cli("project", "create", "Widget")
    cli("step", "add", "widget", "Build the parser", "--agent")
    cli("step", "add", "widget", "Review the parser", "--after", "S1", "--agent", "--review")
    cli("status", "set", "S1", "in-progress")
    monkeypatch.setenv("CLAUDECODE", "1")
    said = cli("review", "approve", "R2", expect=1)
    assert "ready-for-review" in said and "Traceback" not in said
    assert "in-progress" in cli("status", "show", "S1")
    assert "pending" in cli("status", "show", "R2")
