"""The window saying an agent is at work, and what that changes about being interrupted.

The feature exists because a developer editing a plan an agent is rewriting gets asked a
question in the middle of their sentence. So these test the two halves of the fix: the
window says who else is writing, and while it is saying so the collision waits to be picked
up rather than being thrown.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from dplanner.domain.at_work import FRESH_MINUTES
from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step


def module(session):
    return next(m for m in session.services.modules if m.id == "agent_at_work")


def notices(session):
    return session.services.window.notices.notices()


def words(session):
    return [notice.words for notice in notices(session)]


def backdate(board, project, minutes, step=""):
    path = board._path(project, step)
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["seen"] = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()
    path.write_text(json.dumps(stored), encoding="utf-8")


@pytest.fixture
def project(services, make_project):
    return make_project("Discovery")


def test_a_window_with_nobody_working_says_nothing(session, project):
    module(session).refresh()
    assert notices(session) == []
    assert not session.services.window.notices.isVisible()


def test_an_agent_at_work_is_said_over_the_content(session, project, at_work_board):
    at_work_board.start(project.id, doing="Cutting the graph", of=12)
    module(session).refresh()
    (notice,) = notices(session)
    assert notice.words.startswith("An agent is at work on Discovery — Cutting the graph")
    # Warn, not busy: the band is not this window's work running, it is a caution about
    # somebody else's — so it is amber, and the arc beside it is what says *running*.
    assert notice.tone == "warn" and notice.busy
    assert session.services.window.notices.isVisible()


def test_a_declared_count_fills_the_band_and_an_undeclared_one_fills_none(
    session, project, at_work_board
):
    """A meter is for work whose end is known, and an agent that counted its own steps has
    said so; one that offered no count gets the arc and no promise."""
    at_work_board.start(project.id, doing="Cutting", of=20)
    at_work_board.set(project.id, done=5)
    module(session).refresh()
    assert notices(session)[0].fraction == pytest.approx(0.25)

    at_work_board.set(project.id, of=0)
    module(session).refresh()
    assert notices(session)[0].fraction < 0


def test_a_claim_on_a_step_names_the_step_by_its_key(session, services, project, at_work_board):
    step = Step(title="Build the modal")
    services.undo.push(AddNodeCommand(project.id, step))
    at_work_board.start(project.id, step=step.id, doing="Building")
    module(session).refresh()
    assert "on Discovery · S1 — Building" in words(session)[0]


def test_two_agents_on_one_plan_are_two_notices(session, services, project, at_work_board):
    step = Step(title="Build the modal")
    services.undo.push(AddNodeCommand(project.id, step))
    at_work_board.start(project.id, doing="Shaping")
    at_work_board.start(project.id, step=step.id, doing="Building")
    module(session).refresh()
    assert len(notices(session)) == 2


def test_a_quiet_agent_changes_its_words_rather_than_vanishing(session, project, at_work_board):
    """Nothing in the window can see the agent's process, so the banner never claims it
    ended: it says how long ago it was heard and waits to be cleared."""
    at_work_board.start(project.id, doing="Cutting the graph")
    backdate(at_work_board, project.id, FRESH_MINUTES + 10)
    module(session).refresh()
    (notice,) = notices(session)
    assert notice.words.startswith("An agent was at work on Discovery")
    assert f"last heard {FRESH_MINUTES + 10} minutes ago" in notice.words
    assert notice.tone == "info" and not notice.busy


def test_clearing_takes_the_claim_and_the_banner_away(session, project, at_work_board):
    at_work_board.start(project.id, doing="Cutting the graph")
    module(session).refresh()
    (notice,) = notices(session)
    notice.act()
    assert at_work_board.claims() == []
    assert notices(session) == []


def test_the_agent_ending_takes_the_banner_away(session, project, at_work_board):
    at_work_board.start(project.id, doing="Cutting the graph")
    module(session).refresh()
    at_work_board.end(project.id)
    module(session).refresh()
    assert notices(session) == []


def test_a_claim_on_a_project_this_library_does_not_have_still_says_something(
    session, project, at_work_board
):
    """Another window's agent is still an agent running on this machine; the banner names
    what it can and never crashes over what it cannot."""
    at_work_board.start("a-project-from-another-library", doing="Elsewhere")
    module(session).refresh()
    assert words(session) == ["An agent is at work — Elsewhere · heard just now"]


def test_the_window_makes_no_claim_of_its_own(session, project, at_work_board):
    """The board belongs to the other writer. A window that could say "an agent is working"
    would be the one lie this cannot survive, so the only write it has is the clear."""
    module(session).refresh()
    assert at_work_board.claims() == []
