"""Whose turn in a conversation is due: the side with the turn, whose agent has gone, once.

No window: ``due_turns`` is a plain function over the ledger, handed what an agent step is,
whether a run stands on a step and what a step's status reads — the seams the composition
root wires.
"""

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.modules.step_review.aspect import (
    MODULE_ID,
    due_turns,
    last,
    opened,
    said,
    turn_launched,
)
from dplanner.planning.status import Status, Unknown, held


def conversation():
    """A review R of the work W, both agent steps."""
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    work, review = Step(title="W"), Step(title="R")
    library.add_child(project.id, work)
    library.add_child(project.id, review)
    return library, project, work, review


def write(library, review, entry):
    SetModuleDataCommand(review.id, MODULE_ID, entry).redo(library)


def _stored(word):
    """A word on disk as the status reader reads it: one this build does not know is unknown."""
    try:
        return Status(word)
    except ValueError:
        return Unknown(word)


def due(library, project, running=(), statuses=None):
    return [
        found.step.title
        for found in due_turns(
            library,
            project,
            is_agent=lambda _step: True,
            running=lambda step: step.title in running,
            status_for=lambda step: held(_stored((statuses or {}).get(step.title, "in-progress"))),
        )
    ]


def test_the_party_is_due_once_findings_are_posted_and_its_agent_has_gone():
    library, project, work, review = conversation()
    write(library, review, opened(review, work.id, "2026-09-27T10:00:00+00:00"))
    assert due(library, project, running={"R"}) == []  # The asker is writing its findings.
    write(library, review, said(review, work.id, findings="…", posted="2026-09-27T10:05:00+00:00"))
    assert due(library, project, running={"R"}) == ["W"]
    assert due(library, project, running={"R", "W"}) == []  # Its agent is still there.


def test_a_turn_launched_for_is_not_due_again():
    library, project, work, review = conversation()
    write(library, review, opened(review, work.id, "2026-09-27T10:00:00+00:00"))
    write(library, review, said(review, work.id, findings="…", posted="2026-09-27T10:05:00+00:00"))
    write(library, review, turn_launched(review, work.id))
    held = last(review, work.id)
    assert held is not None and held.party_turn_launched == "2026-09-27T10:05:00+00:00"
    assert due(library, project, running={"R"}) == []


def test_the_asker_is_due_after_the_reply_and_again_after_the_next_one():
    library, project, work, review = conversation()
    write(library, review, opened(review, work.id, "2026-09-27T10:00:00+00:00"))
    write(library, review, said(review, work.id, findings="…", posted="2026-09-27T10:05:00+00:00"))
    write(library, review, said(review, work.id, reply="…", replied="2026-09-27T10:20:00+00:00"))
    assert due(library, project, running={"W"}) == ["R"]
    write(library, review, turn_launched(review, work.id))
    assert due(library, project, running={"W"}) == []
    # The relaunched review asks again, and the answer is a new turn of its own.
    write(library, review, opened(review, work.id, "2026-09-27T10:30:00+00:00"))
    write(library, review, said(review, work.id, findings="…", posted="2026-09-27T10:35:00+00:00"))
    write(library, review, said(review, work.id, reply="…", replied="2026-09-27T10:50:00+00:00"))
    assert due(library, project, running={"W"}) == ["R"]


def test_an_ended_conversation_and_a_side_a_person_settled_are_never_due():
    library, project, work, review = conversation()
    write(library, review, opened(review, work.id, "2026-09-27T10:00:00+00:00"))
    write(library, review, said(review, work.id, findings="…", posted="2026-09-27T10:05:00+00:00"))
    assert due(library, project, statuses={"W": "done"}) == []
    assert due(library, project, statuses={"W": "blocked"}) == []
    assert due(library, project, statuses={"W": "unknown"}) == []  # A newer build's word.
    write(library, review, said(review, work.id, approved="2026-09-27T10:10:00+00:00"))
    assert due(library, project) == []


def test_a_conversation_not_opened_yet_is_nobodys_turn_here():
    """A review starts because its subject reached review, which ``progression.due`` says."""
    library, project, _work, _review = conversation()
    assert due(library, project) == []
