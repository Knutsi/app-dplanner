"""The question cards: one card per open question in the library, on a lane a host puts
where a person looks — the Control Centre, on top of its board.

A card says who asks (callsign and harness — or, for a playbook's own gate, whose judgement it
waits for), about which step, what kind of question it is,
the question, and the ways to answer it: a button per choice, a line in a person's own words,
*Retry now* for a run that is held or blocked, *Follow* for a run's question — the run's
turns in a terminal, read-only — and *Go to Step*. Nothing on it is
decoration: DESIGN.md's *Cards*, a ``#ToolCard`` well on a ``#CardLane``, and no accent.

**The cards outlive a refresh.** Questions are written by other processes — a supervisor, an
agent's ``question ask``, a git pull — and nothing watches the directory, so the lane polls
each project's ``questions.fingerprint`` and re-reads only what changed. It then reconciles
by question id, building only what is new and dropping only what has gone, because a
rebuild would take a half-typed answer with it.

Oldest first: the question that has waited longest is the one on top. Only open and
escalated questions are cards; an answered one waits in its file for its run's machine, and
the answer's own words — the ``said`` of :func:`inbox.answer` — tell the person so.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain import questions
from dplanner.domain.model import NodeId
from dplanner.domain.questions import Question
from dplanner.domain.short_titles import UNTITLED
from dplanner.framework.cards import CARD_PADDING, STACK_SPACING, card_rule
from dplanner.framework.signalling import StatusLine
from dplanner.framework.widgets import caption, note, quiet
from dplanner.modules.agent_questions.dialog import QuestionBodyDialog
from dplanner.modules.agent_supervisor import limits
from dplanner.modules.agent_supervisor.supervisor import RETRYABLE
from dplanner.theme.cards import title_font
from dplanner.theme.tokens import FIELD_GAP, ROW_LINE_GAP

if TYPE_CHECKING:  # module.py imports this file, so the Deps arrive as a forward name.
    from dplanner.modules.agent_questions.module import AgentQuestionsDeps

POLL_MS = 2000
SHOWN = (questions.OPEN, questions.ESCALATED)
KIND_WORDS = {
    questions.DECISION: "Decision",
    questions.PLAN_APPROVAL: "Plan approval",
    questions.PERMISSION: "Permission",
    questions.BLOCKED: "Blocked",
    questions.LIMIT: "Usage hold",
}
# Who a playbook's gate waits for, by the kind of stage it stands for: a gate is asked by the
# engine, not an agent, and the person reading the card must see whether it is theirs.
GATE_WORDS = {
    questions.PERSON: "Waits for you",
    "progress": "Waits for you",
    questions.COORDINATOR: "Waits for the coordinator — or you, when none drives the run",
}
# The most height the lane takes: about two cards, so the host's surface keeps the page.
LANE_HEIGHT_CAP = 320


@dataclass(frozen=True)
class CardFacts:
    """Everything a card shows, so a card is rebuilt exactly when one of them changed."""

    question: Question
    agent: str  # "Kettle Sixteen · Claude Code"
    where: str  # "Alpha · S14 Questions on top of the Control Centre"
    has_step: bool
    resets: str  # The reset in the reader's clock, now; "" for none known.


class QuestionCard(QFrame):
    """One question: who asks and about what over the rule, the ways to answer under it."""

    def __init__(
        self,
        facts: CardFacts,
        *,
        answer: Callable[[Question, str], None],
        retry: Callable[[Question], None],
        reveal: Callable[[Question], None],
        show_body: Callable[[Question], None],
        follow: Callable[[Question], None] = lambda _question: None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.facts = facts
        question = facts.question
        self.setObjectName("ToolCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        layout.setSpacing(FIELD_GAP)

        # Who asks, and about what — with the way to the step at the right.
        head = QHBoxLayout()
        layout.addLayout(head)  # Before it is filled: a parentless layout leaks its items.
        head.setSpacing(FIELD_GAP)
        names = QVBoxLayout()
        head.addLayout(names, 1)
        names.setSpacing(ROW_LINE_GAP)
        kind = KIND_WORDS.get(question.kind, question.kind.capitalize())
        self.kind = caption(f"{kind} · {facts.where}", self)
        self.kind.setWordWrap(True)
        names.addWidget(self.kind)
        self.agent = QLabel(facts.agent, self)
        self.agent.setFont(title_font(self.agent.font()))
        self.agent.setWordWrap(True)
        names.addWidget(self.agent)
        # What to look at sits up here beside who asks; what to answer with, under the rule.
        self.show_body: QPushButton | None = None
        if question.body.strip():
            words = "Show Plan…" if question.kind == questions.PLAN_APPROVAL else "Show Details…"
            self.show_body = quiet(QPushButton(words, self))
            self.show_body.clicked.connect(lambda: show_body(question))
            head.addWidget(self.show_body, 0, Qt.AlignmentFlag.AlignTop)
        # A run's question: what the run did up to it, watched in a terminal.
        self.follow: QPushButton | None = None
        if question.run:
            self.follow = quiet(QPushButton("Follow", self))
            self.follow.setToolTip("Watch the run's turns in a terminal — read-only")
            self.follow.clicked.connect(lambda: follow(question))
            head.addWidget(self.follow, 0, Qt.AlignmentFlag.AlignTop)
        self.go = quiet(QPushButton("Go to Step", self))
        self.go.setEnabled(facts.has_step)
        self.go.setToolTip(
            "Select the step in its project's graph"
            if facts.has_step
            else "The step is no longer in the library"
        )
        self.go.clicked.connect(lambda: reveal(question))
        head.addWidget(self.go, 0, Qt.AlignmentFlag.AlignTop)

        # The question itself.
        self.text = QLabel(self._text(facts), self)
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.text)
        if question.state == questions.ESCALATED:
            why = str(question.escalated.get("why", "")).strip()
            layout.addWidget(note(f"Passed to you by the coordinator{': ' + why if why else '.'}"))

        layout.addWidget(card_rule(self))

        # The ways to answer, on one line: the choices, Retry now, then a person's own words.
        choices = QHBoxLayout()
        layout.addLayout(choices)
        choices.setSpacing(FIELD_GAP)
        self.options: list[QPushButton] = []
        for label, said in _options(question):
            button = quiet(QPushButton(label, self))
            button.setToolTip(said)
            button.clicked.connect(lambda _checked=False, given=label: answer(question, given))
            choices.addWidget(button)
            self.options.append(button)
        self.retry: QPushButton | None = None
        if question.kind in RETRYABLE and question.run:
            self.retry = quiet(QPushButton("Retry Now", self))
            self.retry.setToolTip("Resume the run now, without waiting")
            self.retry.clicked.connect(lambda: retry(question))
            choices.addWidget(self.retry)

        self.field: QLineEdit | None = None
        self.send: QPushButton | None = None
        if question.kind == questions.LIMIT:  # A held run waits for its account, not words.
            choices.addStretch(1)
        else:
            self.field = QLineEdit(self)
            self.field.setPlaceholderText(
                "Or answer in your own words…" if self.options else "Answer in your own words…"
            )
            choices.addWidget(self.field, 1)
            self.send = quiet(QPushButton("Answer", self))
            self.send.setEnabled(False)
            choices.addWidget(self.send)
            field, send = self.field, self.send

            def submit() -> None:
                if field.text().strip():
                    answer(question, field.text().strip())

            field.textChanged.connect(lambda text: send.setEnabled(bool(text.strip())))
            field.returnPressed.connect(submit)
            send.clicked.connect(submit)

        self.status = StatusLine(self)
        layout.addWidget(self.status)
        if len(question.questions) != 1:
            for button in self.options:
                button.setEnabled(False)
            if self.field is not None and self.send is not None:
                self.field.setEnabled(False)
                self.send.setEnabled(False)
            self.status.say(
                f"It asks {len(question.questions)} questions at once; the window answers one",
                "warn",
            )

    @staticmethod
    def _text(facts: CardFacts) -> str:
        question = facts.question
        if question.kind != questions.LIMIT:
            return question.text or "(The question has no words.)"
        # Worded here rather than read from the record: the time it was parked with is
        # stale by the next day, and the card is read now.
        if facts.resets:
            return f"The account ran out of usage. The run resumes by itself at {facts.resets}."
        return "The account ran out of usage, and when it resets is unknown."

    def typed(self) -> str:
        return self.field.text() if self.field is not None else ""

    def set_typed(self, text: str) -> None:
        if self.field is not None and text:
            self.field.setText(text)

    def refuse(self, reason: str) -> None:
        self.status.say(reason, "error")


def _gate_words(question: Question) -> str:
    """Who a question nobody's agent asked waits for: a playbook gate's judge, by its stage."""
    if question.purpose == "round-cap":
        return "The gate's rounds ran out — somebody decides"
    if question.pass_:
        return GATE_WORDS.get(questions.gate_role(question), "The playbook asks")
    return "An agent"


def _options(question: Question) -> list[tuple[str, str]]:
    """The choices the question offers, but Retry now, which is its own button."""
    if len(question.questions) != 1:
        return []
    offered = question.questions[0].get("options", [])
    found = [
        (str(option.get("label", "")), str(option.get("description", "")))
        for option in offered
        if isinstance(option, dict)
    ]
    return [(label, said) for label, said in found if label and label != questions.RETRY_NOW]


class _Lane(QScrollArea):
    """The scroller the cards sit in: as tall as the cards, up to a cap, past which they
    scroll and the host's own surface keeps the rest of the page."""

    def __init__(self, lane: QWidget, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.setWidget(lane)
        self._lane = lane

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        # At the width the cards have: wrapped words are taller in the narrower guess
        # sizeHint makes, and the lane would ask for a hole under its last card.
        hint, lane, width = super().sizeHint(), self._lane, self.viewport().width()
        fits = lane.hasHeightForWidth() and width > 0
        height = lane.heightForWidth(width) if fits else lane.sizeHint().height()
        return QSize(hint.width(), min(height, LANE_HEIGHT_CAP))


class QuestionCards:
    """The lane of cards over the library's projects, or the ones :meth:`show_projects`
    names. ``widget`` is hidden while there is no card: a host's page has nothing on top
    then."""

    def __init__(self, deps: "AgentQuestionsDeps", parent: QWidget | None = None) -> None:
        self._deps = deps
        self._open: dict[NodeId, list[Question]] = {}
        self._stamps: dict[NodeId, object] = {}
        self._cards: dict[str, QuestionCard] = {}
        self._only: set[NodeId] = set()
        self._changed: Callable[[], None] = lambda: None

        self.lane = QWidget()
        self.lane.setObjectName("CardLane")
        self._lane = QVBoxLayout(self.lane)
        self._lane.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        self._lane.setSpacing(STACK_SPACING)
        self._lane.addStretch(1)
        self.widget: QScrollArea = _Lane(self.lane, parent)

        self._poll = QTimer(self.widget)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self.poll)
        self._poll.start()
        self.refresh()

    # -- what a host asks ----------------------------------------------------------------------

    @property
    def count(self) -> int:
        return len(self._cards)

    def cards(self) -> list[QuestionCard]:
        """The cards, top to bottom."""
        return list(self._cards.values())

    def set_changed(self, changed: Callable[[], None]) -> None:
        """Called whenever the number of cards changes."""
        self._changed = changed

    def show_projects(self, project_ids: Sequence[NodeId]) -> None:
        """Only these projects' questions; none named is every project's."""
        self._only = set(project_ids)
        self._reconcile()

    def refresh(self) -> None:
        """Read what changed and say it again — the library may have renamed a step."""
        self._read()
        self._reconcile()

    def poll(self) -> None:
        if self._read():
            self._reconcile()

    def close(self) -> None:
        self._poll.stop()

    # -- internals -----------------------------------------------------------------------------

    def _read(self) -> bool:
        """Re-read each project whose inbox changed on disk; whether any did."""
        changed = False
        here: set[NodeId] = set()
        for project in self._deps.library.projects:
            directory = self._deps.project_dir(project.id)
            if directory is None:
                continue
            here.add(project.id)
            stamp = questions.fingerprint(directory)
            if self._stamps.get(project.id) == stamp:
                continue
            self._stamps[project.id] = stamp
            self._open[project.id] = [q for q in questions.records(directory) if q.state in SHOWN]
            changed = True
        for gone in set(self._open) - here:
            del self._open[gone]
            self._stamps.pop(gone, None)
            changed = True
        return changed

    def _reconcile(self) -> None:
        before = self.count
        found = [
            question
            for project_id, asked in self._open.items()
            if not self._only or project_id in self._only
            for question in asked
        ]
        wanted = [self._facts(q) for q in sorted(found, key=lambda q: (q.asked, q.id))]
        ids = {facts.question.id for facts in wanted}
        for question_id in [i for i in self._cards if i not in ids]:
            self._drop(self._cards.pop(question_id))
        # Kept cards are already in order among themselves, so inserting each new one at
        # its place keeps the whole lane in order.
        kept: dict[str, QuestionCard] = {}
        for place, facts in enumerate(wanted):
            card = self._cards.get(facts.question.id)
            if card is not None and card.facts == facts:
                kept[facts.question.id] = card
                continue
            typed = card.typed() if card is not None else ""
            if card is not None:
                self._drop(card)
            card = QuestionCard(
                facts,
                answer=self._answer,
                retry=self._retry,
                reveal=self._reveal,
                show_body=self._show_body,
                follow=self._follow,
                parent=self.lane,
            )
            card.set_typed(typed)
            self._lane.insertWidget(place, card)
            kept[facts.question.id] = card
        self._cards = kept
        self.widget.setVisible(bool(kept))
        self.widget.updateGeometry()
        if self.count != before:
            self._changed()

    def _drop(self, card: QuestionCard) -> None:
        self._lane.removeWidget(card)
        card.hide()
        card.deleteLater()

    def _facts(self, question: Question) -> CardFacts:
        deps, library = self._deps, self._deps.library
        callsign = question.by.get("callsign", "")
        harness = question.by.get("harness", "")
        label = next((h.label for h in deps.harnesses if h.id == harness), harness)
        agent = " · ".join(part for part in (callsign, label) if part) or _gate_words(question)
        has_step = library.has(question.step)
        if has_step:
            step = library.step(question.step)
            key = deps.key_of(step)
            step_words = f"{key} {step.title or 'Untitled step'}".strip()
        else:
            step_words = "a step no longer in the library"
        where = step_words
        if len(library.projects) > 1 and library.has(question.project):
            where = f"{library.project(question.project).title or UNTITLED} · {step_words}"
        moment = limits.parse(question.resets)
        return CardFacts(
            question=question,
            agent=agent,
            where=where,
            has_step=has_step,
            resets=limits.clock(moment) if moment is not None else "",
        )

    def _act(self, question: Question, act: Callable[[Path], str]) -> None:
        card = self._cards.get(question.id)
        directory = self._deps.project_dir(question.project)
        try:
            if directory is None:
                raise LookupError("its project is no longer in the library")
            said = act(directory)
        except (LookupError, ValueError) as refused:
            if card is not None:
                card.refuse(str(refused))
            return
        self._deps.status.show_status(said)
        self.refresh()

    def _answer(self, question: Question, given: str) -> None:
        self._act(question, lambda directory: self._deps.answer(directory, question.id, given))

    def _retry(self, question: Question) -> None:
        self._act(question, lambda directory: self._deps.retry_now(directory, question.run))

    def _follow(self, question: Question) -> None:
        self._act(question, lambda directory: self._deps.follow(directory, question.run))

    def _reveal(self, question: Question) -> None:
        if self._deps.library.has(question.step):
            self._deps.reveal(question.step)

    def _show_body(self, question: Question) -> None:
        words = "Plan" if question.kind == questions.PLAN_APPROVAL else "Details"
        dialog = QuestionBodyDialog(
            f"{words} · {question.short}", question.body, self.widget.window()
        )
        dialog.exec()
        dialog.deleteLater()
