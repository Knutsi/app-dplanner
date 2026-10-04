"""Setting a status is one workflow: what it refuses, what it writes, what it ends — and
that the window's Status verbs and ``dplanner status set`` reach the same outcome."""

import json
from datetime import date

import pytest

from dplanner.domain.commands import AddNodeCommand, SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.workflow import Actor, AgentRun, Daemon, EndClaim, Person, PlanView
from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri
from dplanner.modules.step_status.workflows import STOPPED, StatusWorkflow, perform
from dplanner.planning.status import MODULE_ID, Status, stored

MONDAY = date(2026, 9, 21)
ACTORS: list[Actor] = [Person(), AgentRun(), Daemon()]

# -- the workflow, with no application at all --------------------------------------------------


def _keep_reason(view: PlanView, step: Step, reason: str, today: date):
    return "N1", SetModuleDataCommand(step.id, "notes_probe", {"reason": reason})


WORKFLOW = StatusWorkflow(
    works_nobody=lambda step: "a wait" if step.title == "Hold a day" else "",
    is_agent=lambda step: step.title == "Build the modal",
    keep_reason=_keep_reason,
)


@pytest.fixture
def library():
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    for title in ("Read the spec", "Build the modal", "Hold a day"):
        library.add_child(project.id, Step(title=title))
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
    change = WORKFLOW.set_status(library, step, status, actor=actor, today=MONDAY)
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
    change = WORKFLOW.set_status(
        library, step, Status.READY_FOR_REVIEW, actor=AgentRun(), today=MONDAY
    )
    assert change.command is not None
    change.command.redo(library)
    assert WORKFLOW.refusal([step], Status.DONE, AgentRun()) == ""


def test_a_reason_is_kept_in_the_same_command(library):
    step = _step(library, "Build the modal")
    change = WORKFLOW.set_status(
        library, step, Status.DONE, actor=AgentRun(), today=MONDAY, because="docs only"
    )
    assert change.command is not None
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
    first = WORKFLOW.set_status(
        library, step, Status.READY_FOR_REVIEW, actor=Person(), today=MONDAY
    )
    assert first.command is not None
    first.command.redo(library)
    again = WORKFLOW.set_status(
        library, step, Status.READY_FOR_REVIEW, actor=Person(), today=MONDAY
    )
    assert again.command is None and again.follow_ups == first.follow_ups
    ended: list[EndClaim] = []

    def end_claim(claim: EndClaim) -> bool:
        ended.append(claim)
        return True

    assert perform(again, end_claim)
    assert ended == list(first.follow_ups)


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
