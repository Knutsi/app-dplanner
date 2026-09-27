"""The Review tab: who reviews, through which lenses, in how many rounds — and the
conversation so far.

The settings are one undoable entry, the same one ``dplanner review set`` writes. The
conversation under them is read-only: it is what the reviewer and the reviewed step said
through ``dplanner review …``, and it follows the ledger as those verbs write it, whether
they ran in this window or in a terminal beside it.
"""

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QListWidgetItem,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.agents import AgentHarness
from dplanner.domain.model import Library, NodeId, Step
from dplanner.framework.list_rows import DETAIL_ROLE, TRAILING_ROLE, RichList
from dplanner.framework.module_data_section import ModuleDataSection
from dplanner.framework.signalling import StatusLine, Tone
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import EmptyState, block, caption
from dplanner.modules.step_review.aspect import (
    DEFAULT_AGENT,
    LENSES,
    MODULE_ID,
    ReviewSettings,
    settings,
    subjects,
    write,
)
from dplanner.modules.step_review.rounds import (
    APPROVED,
    ASKER,
    ENDED_STATES,
    ESCALATED,
    POSTED,
    REPLIED,
    Message,
    last,
    messages,
    rounds,
    standing,
    with_party,
)
from dplanner.modules.step_review.rounds import MODULE_ID as ROUNDS_ID
from dplanner.theme.tokens import FIELD_GAP, PANEL_MARGIN, SECTION_GAP

MOST_ROUNDS = 10
NO_ROUNDS = "No rounds yet"


class ReviewSection(ModuleDataSection):
    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        *,
        key_of: Callable[[Step], str],
        harnesses: Sequence[AgentHarness],
        default_profile: Callable[[], str],
    ) -> None:
        super().__init__(library, undo, module_id=MODULE_ID, undo_label="Set Review")
        self._key_of = key_of
        self._harnesses = harnesses
        self._default_profile = default_profile

        self.agent = QComboBox(self)
        self.agent.activated.connect(lambda _index: self.commit())
        self.lenses = {lens.id: QCheckBox(lens.label, self) for lens in LENSES}
        for lens in LENSES:
            self.lenses[lens.id].setToolTip(lens.asks)
        for box in self.lenses.values():
            box.toggled.connect(lambda _on: self.commit())
        self.skills = QLineEdit(self)
        self.skills.setPlaceholderText("Skills of your own, comma-separated (optional)")
        self.skills.editingFinished.connect(self.commit)
        self.max_rounds = QSpinBox(self)
        self.max_rounds.setRange(1, MOST_ROUNDS)
        self.max_rounds.setSuffix(" rounds")
        self.max_rounds.setKeyboardTracking(False)
        self.max_rounds.valueChanged.connect(lambda _rounds: self.commit())
        self.standing = StatusLine(self)
        self.conversation = RichList(self)
        self.empty = EmptyState(NO_ROUNDS, self, stands_in_for=self.conversation)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(SECTION_GAP)
        block(layout, caption("Agent", self), self.agent)
        boxes = QWidget(self)
        row = QHBoxLayout(boxes)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SECTION_GAP)
        for box in self.lenses.values():
            row.addWidget(box)
        row.addStretch(1)
        block(layout, caption("Lenses", self), boxes, self.skills)
        cap = QWidget(self)
        cap_row = QHBoxLayout(cap)
        cap_row.setContentsMargins(0, 0, 0, 0)
        cap_row.setSpacing(FIELD_GAP)
        cap_row.addWidget(self.max_rounds)
        cap_row.addStretch(1)
        block(layout, caption("Round cap", self), cap)
        talk = block(layout, caption("Conversation", self), self.standing)
        talk.addWidget(self.conversation, 1)
        talk.addWidget(self.empty, 1)
        layout.setStretchFactor(talk, 1)

        self._unsubscribes = [
            library.module_data_changed.connect(self._on_rounds),
            library.edges_changed.connect(lambda step_id, _origin: self._on_edges(step_id)),
        ]

    def dispose(self) -> None:
        super().dispose()
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    # -- ModuleDataSection -----------------------------------------------------------------------

    def load_step(self, step: Step | None) -> None:
        chosen = settings(step) if step is not None else ReviewSettings()
        self._fill_agents(chosen.agent)
        for lens, box in self.lenses.items():
            box.setChecked(lens in chosen.lenses)
        self.skills.setText(", ".join(lens for lens in chosen.lenses if lens not in self.lenses))
        self.max_rounds.setValue(chosen.max_rounds)
        self._show_conversation(step)

    def entry(self, step: Step) -> dict[str, Any]:
        named = [lens for lens, box in self.lenses.items() if box.isChecked()]
        own = [skill.strip() for skill in self.skills.text().split(",") if skill.strip()]
        return write(
            ReviewSettings(
                agent=str(self.agent.currentData() or DEFAULT_AGENT),
                lenses=tuple(dict.fromkeys([*named, *own])),
                max_rounds=self.max_rounds.value(),
            )
        )

    # -- what the tests read ---------------------------------------------------------------------

    def agents(self) -> list[tuple[str, str]]:
        """The agent choices as offered: the words, and the id each writes."""
        return [
            (self.agent.itemText(index), str(self.agent.itemData(index)))
            for index in range(self.agent.count())
        ]

    def rows(self) -> list[tuple[str, str]]:
        """The conversation as listed: each message's heading and the line under it."""
        return [
            (
                self.conversation.item(index).text(),
                str(self.conversation.item(index).data(DETAIL_ROLE)),
            )
            for index in range(self.conversation.count())
        ]

    # -- internals -------------------------------------------------------------------------------

    def _fill_agents(self, agent: str) -> None:
        """The default profile first, named, then every agent CLI this build can launch —
        and a choice this build does not know, kept so showing the tab never loses it."""
        self.agent.clear()
        self.agent.addItem(f"Default profile — {self._default_profile()}", DEFAULT_AGENT)
        for harness in self._harnesses:
            self.agent.addItem(harness.label, harness.id)
        if self.agent.findData(agent) < 0:
            self.agent.addItem(f"{agent} (not in this build)", agent)
        self.agent.setCurrentIndex(self.agent.findData(agent))

    def _show_conversation(self, step: Step | None) -> None:
        self.conversation.clear()
        if step is None:
            self.standing.clear()
            self.empty.say(NO_ROUNDS)
            return
        text, tone = self._standing(step)
        self.standing.say(text, tone)
        held = rounds(step)
        for said in messages(held):
            self.conversation.addItem(self._row(step, said))
        self.empty.say("" if held else NO_ROUNDS)

    def _standing(self, step: Step) -> tuple[str, Tone]:
        reviewed = subjects(self._library, step)
        if not reviewed:
            return "Reviews nothing yet — link it after the step it reviews", "warn"
        if len(reviewed) > 1:
            keys = ", ".join(self._ref(each) for each in reviewed)
            return f"Reviews {keys} at once — a review takes one step", "warn"
        (subject,) = reviewed
        held = last(step, subject.id)
        text = standing(held, self._ref(step), self._ref(subject))
        cap = settings(step).max_rounds
        if held is None or held.state not in ENDED_STATES:
            text += f" — {len(with_party(step, subject.id))} of {cap} rounds"
        text = text[0].upper() + text[1:]
        if held is not None and held.state == APPROVED:
            return text, "ok"
        if held is not None and held.state == ESCALATED:
            return text, "warn"
        return text, "info"

    def _row(self, step: Step, said: Message) -> QListWidgetItem:
        party = (
            self._library.step(said.round.party) if self._library.has(said.round.party) else None
        )
        sender = self._ref(step) if said.sender == ASKER else self._ref(party) if party else "?"
        heading = {
            POSTED: f"{sender}'s findings",
            REPLIED: f"{sender}'s reply",
            ESCALATED: "Handed to a person",
            APPROVED: "Approved",
        }[said.kind]
        item = QListWidgetItem(f"Round {said.round.number} · {heading}")
        first = said.text.strip().splitlines()[0] if said.text.strip() else ""
        item.setData(DETAIL_ROLE, first)
        item.setData(TRAILING_ROLE, _when(said.at))
        item.setToolTip(said.text.strip())
        return item

    def _ref(self, step: Step) -> str:
        return self._key_of(step) or f"“{step.title}”"

    def _on_rounds(self, node_id: NodeId, module_id: str, _origin: object) -> None:
        if module_id == ROUNDS_ID and node_id == self._step_id:
            self._show_conversation(self.step())

    def _on_edges(self, step_id: NodeId) -> None:
        if step_id == self._step_id:
            self._show_conversation(self.step())


def _when(stamp: str) -> str:
    """``27 Sep 14:02`` where this machine is — or the stamp as written, when unreadable."""
    try:
        return datetime.fromisoformat(stamp).astimezone().strftime("%d %b %H:%M")
    except ValueError:
        return stamp
