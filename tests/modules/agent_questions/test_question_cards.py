"""The question cards on top of the Control Centre: one card per open question, oldest first,
answered by the person at the window through the same inbox ``question answer`` uses.

Questions are real files in each project's directory, written as the supervisor and
``question ask`` write them; the cards find them by polling, so a test calls ``poll()`` (or
``refresh()``) where the timer would have.
"""

from datetime import UTC, datetime, timedelta

import pytest
from PySide6.QtWidgets import QWidget

from dplanner.domain import questions
from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.modules.agent_questions.module import AgentQuestionsDeps
from dplanner.modules.agent_questions.panel import QuestionCards
from dplanner.modules.agent_supervisor import limits
from dplanner.modules.status_board.activity import CONTROL_CENTRE_KIND, ControlCentreActivity

STAMP = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)


def add_step(services, project, title):
    step = Step(title=title)
    AddNodeCommand(project.id, step).redo(services.document)
    return step


def ask(services, project, step, text="Which store?", *, minutes=0, options=(), **fields):
    """A question on disk, asked ``minutes`` after the first, in AskUserQuestion's shape."""
    question = questions.asked(
        project.id,
        step.id,
        (STAMP + timedelta(minutes=minutes)).isoformat(),
        [questions.one(text, "", options)],
        by={"callsign": "Kettle Nine", "harness": "claude"},
        **fields,
    )
    questions.write(services.repo.project_dir(project.id), question)
    return question


def rewrite(services, project, question):
    questions.write(services.repo.project_dir(project.id), question)


def board(services) -> ControlCentreActivity:
    tab = services.tabs.open(CONTROL_CENTRE_KIND)
    assert isinstance(tab, ControlCentreActivity) and tab.questions is not None
    return tab


def ids(cards: QuestionCards) -> list[str]:
    return [card.facts.question.id for card in cards.cards()]


@pytest.fixture
def alpha(services, make_project):
    project = make_project("Alpha")
    return project, add_step(services, project, "Pick a cache")


class Recorder:
    def __init__(self) -> None:
        self.answers: list[tuple[str, str]] = []
        self.retries: list[str] = []
        self.revealed: list[str] = []
        self.said: list[str] = []
        self.refuse = ""

    def answer(self, _directory, question_id: str, given: str) -> str:
        if self.refuse:
            raise ValueError(self.refuse)
        self.answers.append((question_id, given))
        return "answered"

    def retry_now(self, _directory, run: str) -> str:
        self.retries.append(run)
        return "retried"

    def show_status(self, text: str, msecs: int = 0) -> None:
        self.said.append(text)

    def add_status_widget(self, widget: QWidget) -> None:
        raise AssertionError("the cards put nothing in the status bar")


@pytest.fixture
def faked(services):
    """Cards over the window's library with every effect recorded instead of done."""
    recorder = Recorder()
    host = QWidget()
    cards = QuestionCards(
        AgentQuestionsDeps(
            library=services.document,
            status=recorder,
            project_dir=services.repo.project_dir,
            answer=recorder.answer,
            retry_now=recorder.retry_now,
            reveal=recorder.revealed.append,
            key_of=lambda _step: "S1",
        ),
        host,
    )
    yield cards, recorder
    cards.close()
    host.deleteLater()


def test_open_and_escalated_questions_are_cards_oldest_first(services, alpha) -> None:
    project, step = alpha
    tab = board(services)
    rows = tab._needing
    assert tab.title == (f"Control Centre ({rows})" if rows else "Control Centre")
    later = ask(services, project, step, "Second?", minutes=5)
    first = ask(services, project, step, "First?")
    passed = ask(services, project, step, "Passed on?", minutes=9)
    rewrite(services, project, questions.escalated(passed, {"kind": "coordinator"}, "", ""))
    for minutes, settle in ((10, "answer"), (11, "withdraw")):
        gone = ask(services, project, step, f"{settle}?", minutes=minutes)
        if settle == "answer":
            gone = questions.answered(gone, {f"{settle}?": "yes"}, {"kind": "person"}, "")
        else:
            gone = questions.withdrawn(gone, "the run ended", "")
        rewrite(services, project, gone)

    tab.questions.refresh()

    assert ids(tab.questions) == [first.id, later.id, passed.id]
    assert tab.title == f"Control Centre ({rows + 3})"
    assert tab.questions.widget.isVisibleTo(tab.widget)


def test_the_lane_hides_with_no_question(services, alpha) -> None:
    tab = board(services)
    assert tab.questions.count == 0
    assert not tab.questions.widget.isVisibleTo(tab.widget)


def test_a_new_question_appears_on_the_next_poll(services, alpha) -> None:
    project, step = alpha
    tab = board(services)
    ask(services, project, step)
    tab.questions.poll()
    assert tab.questions.count == 1


def test_a_half_typed_answer_survives_a_poll(services, alpha) -> None:
    project, step = alpha
    tab = board(services)
    ask(services, project, step)
    tab.questions.refresh()
    (card,) = tab.questions.cards()
    assert card.field is not None
    card.field.setText("Redis, with a ")

    ask(services, project, step, "Another?", minutes=3)
    tab.questions.poll()

    first, _second = tab.questions.cards()
    assert first is card and card.field.text() == "Redis, with a "


def test_the_projects_filter_narrows_the_cards(services, alpha, make_project) -> None:
    project, step = alpha
    beta = make_project("Beta")
    elsewhere = ask(services, beta, add_step(services, beta, "Paint"))
    ask(services, project, step, minutes=1)
    tab = board(services)
    tab.questions.refresh()
    assert tab.questions.count == 2
    assert "Beta" in tab.questions.cards()[0].kind.text()

    tab.projects.set_active({beta.id})

    assert ids(tab.questions) == [elsewhere.id]


def test_a_choice_answers_as_the_person_through_the_inbox(services, alpha) -> None:
    project, step = alpha
    asked = ask(services, project, step, options=(("Redis", "fast"), ("SQLite", "simple")))
    tab = board(services)
    tab.questions.refresh()
    (card,) = tab.questions.cards()
    assert [button.text() for button in card.options] == ["Redis", "SQLite"]

    card.options[1].click()

    stored = questions.find(services.repo.project_dir(project.id), asked.id)
    assert stored is not None and stored.state == questions.ANSWERED
    assert stored.answer["answers"] == {"Which store?": "SQLite"}
    assert stored.answer["by"]["kind"] == questions.PERSON
    # It parks no run, so nothing resumes — and the person is told so.
    assert "parks no run" in services.window.statusBar().currentMessage()
    assert tab.questions.count == 0


def test_a_free_answer_goes_in_its_own_words(services, alpha, faked) -> None:
    project, step = alpha
    asked = ask(services, project, step, options=(("Redis", ""),))
    cards, recorder = faked
    cards.refresh()
    (card,) = cards.cards()
    assert card.field is not None and card.send is not None
    assert not card.send.isEnabled()

    card.field.setText("  Redis, in memory  ")
    card.field.returnPressed.emit()

    assert recorder.answers == [(asked.id, "Redis, in memory")]
    assert recorder.said == ["answered"]


def test_a_refused_answer_says_why_on_its_card(services, alpha, faked) -> None:
    project, step = alpha
    ask(services, project, step, options=(("Redis", ""),))
    cards, recorder = faked
    cards.refresh()
    (card,) = cards.cards()
    recorder.refuse = "Q-1234 is already answered (by Knut)"

    card.options[0].click()

    assert card.status.words() == recorder.refuse and card.status.tone() == "error"
    assert recorder.said == []


def test_go_to_step_reveals_the_step(services, alpha, faked) -> None:
    project, step = alpha
    ask(services, project, step)
    cards, recorder = faked
    cards.refresh()
    (card,) = cards.cards()

    card.go.click()

    assert recorder.revealed == [step.id]


def test_a_usage_hold_shows_its_reset_and_retries_now(services, alpha, faked) -> None:
    project, step = alpha
    reset = datetime.now(UTC) + timedelta(hours=2)
    ask(
        services,
        project,
        step,
        "",
        kind=questions.LIMIT,
        options=((questions.RETRY_NOW, "Resume the run now"),),
        run="run-1",
        resets=reset.isoformat(),
    )
    cards, recorder = faked
    cards.refresh()
    (card,) = cards.cards()
    assert "Usage hold" in card.kind.text()
    assert limits.clock(reset) in card.text.text()
    # Retry now is its own button, never a second choice beside it; a hold takes no words.
    assert card.options == [] and card.field is None and card.retry is not None

    card.retry.click()

    assert recorder.retries == ["run-1"]


def test_a_decision_offers_no_retry(services, alpha, faked) -> None:
    project, step = alpha
    ask(services, project, step, run="run-1")
    cards, _recorder = faked
    cards.refresh()
    (card,) = cards.cards()
    assert card.retry is None


def test_a_question_asking_several_at_once_is_greyed_with_why(services, alpha, faked) -> None:
    project, step = alpha
    question = questions.asked(
        project.id,
        step.id,
        STAMP.isoformat(),
        [questions.one("One?", "", (("A", ""),)), questions.one("Two?")],
    )
    rewrite(services, project, question)
    cards, _recorder = faked
    cards.refresh()
    (card,) = cards.cards()
    assert card.options == [] and card.field is not None and not card.field.isEnabled()
    assert "2 questions at once" in card.status.words()


def test_a_plan_to_approve_is_shown_behind_its_own_button(services, alpha, faked) -> None:
    project, step = alpha
    ask(services, project, step, kind=questions.PLAN_APPROVAL, body="## Plan\n\n1. Do it.")
    ask(services, project, step, "Plain?", minutes=1)
    cards, _recorder = faked
    cards.refresh()
    plan, plain = cards.cards()
    assert plan.show_body is not None and plan.show_body.text() == "Show Plan…"
    assert plain.show_body is None
