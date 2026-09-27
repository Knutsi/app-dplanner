"""The window saying agents are at work, and what that changes about being interrupted.

The feature exists because a developer editing a plan an agent is rewriting gets asked a
question in the middle of their sentence. So these test the halves of the fix: the window
says who else is writing — in one band however many agents there are, with the dialog
behind it saying each in full — and while it is saying so the collision waits to be picked
up rather than being thrown.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from PySide6.QtWidgets import QToolButton

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


def in_order(board, *claims):
    """Stamp ``(project, step)`` claims as begun a second apart, in the order given. A stamp
    carries whole seconds, and claims begun within one are listed by step id — a uuid."""
    for index, (project, step) in enumerate(claims):
        path = board._path(project, step)
        stored = json.loads(path.read_text(encoding="utf-8"))
        stored["started"] = (datetime.now(UTC) - timedelta(seconds=len(claims) - index)).isoformat()
        path.write_text(json.dumps(stored), encoding="utf-8")


def steps(services, project, *titles):
    made = [Step(title=title) for title in titles]
    for step in made:
        services.undo.push(AddNodeCommand(project.id, step))
    return made


def test_several_agents_are_one_band_that_counts_them(session, services, project, at_work_board):
    """Four stacked bands were four things to read past. One band says *that* agents are
    writing and which steps they are on, and fills with everything they counted together."""
    first, second = steps(services, project, "Build the modal", "Draft the model")
    at_work_board.start(project.id, doing="Shaping")
    at_work_board.start(project.id, step=first.id, doing="Building", of=6)
    at_work_board.set(project.id, step=first.id, done=3)
    at_work_board.start(project.id, step=second.id, doing="Drafting", of=10)
    at_work_board.set(project.id, step=second.id, done=9)
    in_order(at_work_board, (project.id, ""), (project.id, first.id), (project.id, second.id))
    module(session).refresh()
    (notice,) = notices(session)
    assert notice.words == "3 agents are at work on Discovery · S1, S2"
    assert notice.tone == "warn" and notice.busy
    assert notice.fraction == pytest.approx(12 / 16)


def test_a_silent_agent_is_not_said_at_all(session, project, at_work_board):
    """Half an hour without a word and the claim lapses: a band nobody believes is worse
    than none, and the agent's next verb brings it back (``domain/at_work.py``)."""
    at_work_board.start(project.id, doing="Cutting the graph")
    module(session).refresh()
    backdate(at_work_board, project.id, FRESH_MINUTES + 10)
    module(session).refresh()
    assert notices(session) == []
    assert not session.services.window.notices.isVisible()


def test_clearing_takes_every_claim_and_the_banner_away(session, services, project, at_work_board):
    (step,) = steps(services, project, "Build the modal")
    at_work_board.start(project.id, doing="Shaping")
    at_work_board.start(project.id, step=step.id, doing="Building")
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


# -- the dialog behind the band -------------------------------------------------------------------


def opened(session):
    """Click the band, as a person would, and hand back the dialog it opened."""
    (notice,) = notices(session)
    notice.open()
    dialog = module(session).dialog()
    assert dialog is not None and dialog.isVisible()
    return dialog


@pytest.fixture
def dialog_disposed(session):
    yield
    dialog = module(session).dialog()
    if dialog is not None:
        dialog.hide()


def test_a_click_on_the_band_lists_every_agent_and_what_it_is_doing(
    session, services, project, at_work_board, dialog_disposed
):
    (step,) = steps(services, project, "Build the modal")
    at_work_board.start(project.id, doing="Shaping")
    at_work_board.start(project.id, step=step.id, doing="Building", of=4)
    at_work_board.set(project.id, step=step.id, done=1)
    module(session).refresh()
    rows = opened(session).rows()
    assert [row.title.text() for row in rows] == ["Discovery", "S1 Build the modal"]
    assert rows[0].status.words() == "Shaping · heard just now"
    assert rows[1].status.words() == "Building · 1 of 4 · heard just now"
    # A count fills the row's bar; a claim with none gets the line and no promise.
    assert rows[1].bar.isVisibleTo(rows[1]) and rows[1].bar.value() == 25
    assert not rows[0].bar.isVisibleTo(rows[0])
    # The plan as a whole has no step to select.
    assert rows[1].reveal_button.isVisibleTo(rows[1])
    assert not rows[0].reveal_button.isVisibleTo(rows[0])


def test_a_row_across_projects_names_its_project(
    session, services, project, make_project, at_work_board, dialog_disposed
):
    other = make_project("Billing")
    (step,) = steps(services, project, "Build the modal")
    at_work_board.start(project.id, step=step.id, doing="Building")
    at_work_board.start(other.id, doing="Invoicing")
    in_order(at_work_board, (project.id, step.id), (other.id, ""))
    module(session).refresh()
    assert notices(session)[0].words == "2 agents are at work on Discovery · S1; Billing"
    titles = [row.title.text() for row in opened(session).rows()]
    assert titles == ["Discovery · S1 Build the modal", "Billing"]


def test_a_row_clears_its_own_claim_and_leaves_the_rest(
    session, services, project, at_work_board, dialog_disposed
):
    """The one way to drop a dead agent's claim without clearing the live ones beside it."""
    (step,) = steps(services, project, "Build the modal")
    at_work_board.start(project.id, doing="Shaping")
    at_work_board.start(project.id, step=step.id, doing="Building")
    module(session).refresh()
    dialog = opened(session)
    dismiss = dialog.rows()[1].findChild(QToolButton, "WellRowDismiss")
    dismiss.click()
    assert [claim.doing for claim in at_work_board.claims()] == ["Shaping"]
    assert [row.title.text() for row in dialog.rows()] == ["Discovery"]
    assert notices(session)[0].words.startswith("An agent is at work on Discovery — Shaping")


def test_reveal_selects_the_step_the_agent_is_on(
    session, services, project, at_work_board, dialog_disposed
):
    (step,) = steps(services, project, "Build the modal")
    at_work_board.start(project.id, step=step.id, doing="Building")
    module(session).refresh()
    opened(session).rows()[0].reveal_button.click()
    graph = next(
        a for a in services.tabs.activities() if a.uri.startswith("app://activity/project")
    )
    assert graph._scene.selected_step() == step.id


def test_clear_all_empties_the_dialog_and_takes_the_band_away(
    session, project, at_work_board, dialog_disposed
):
    at_work_board.start(project.id, doing="Shaping")
    module(session).refresh()
    dialog = opened(session)
    dialog.clear_button.click()
    assert at_work_board.claims() == []
    assert notices(session) == []
    assert dialog.rows() == []
    assert dialog.empty.label.text() == "No agent is at work."
    assert not dialog.clear_button.isEnabled()
