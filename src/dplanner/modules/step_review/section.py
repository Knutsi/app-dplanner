"""The Review tab: who reviews, through which lenses, in how many rounds — and the
conversation so far.

The settings are one undoable entry, the same one ``dplanner review set`` writes. The
conversation under them is read-only: it is what the reviewer and the reviewed step said
through ``dplanner review …``, and it follows the ledger as those verbs write it, whether
they ran in this window or in a terminal beside it. The list is the quick look; a message
is read in full in the conversation dialog, opened from here on it or on the newest.
"""

from collections.abc import Callable, Sequence
from typing import Any

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.agents import AgentHarness
from dplanner.domain.model import Library, NodeId, Step
from dplanner.framework.list_rows import DETAIL_ROLE, RichList
from dplanner.framework.module_data_section import ModuleDataSection
from dplanner.framework.signalling import StatusLine
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import EmptyState, block, caption, ink_of, quiet
from dplanner.modules.step_review.aspect import (
    DEFAULT_AGENT,
    LENSES,
    MODULE_ID,
    ReviewSettings,
    settings,
    write,
)
from dplanner.modules.step_review.conversation import (
    KEY_ROLE,
    NO_ROUNDS,
    message_rows,
    open_conversation,
    reink,
    where_it_stands,
)
from dplanner.modules.step_review.rounds import MODULE_ID as ROUNDS_ID
from dplanner.theme.tokens import FIELD_GAP, PANEL_MARGIN, SECTION_GAP

MOST_ROUNDS = 10
OPEN_CONVERSATION = "Open Conversation…"


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
        self.conversation_button = quiet(QPushButton(OPEN_CONVERSATION, self))
        self.conversation_button.clicked.connect(lambda: self._open(None))
        self.conversation = RichList(self)
        self.conversation.itemActivated.connect(lambda item: self._open(str(item.data(KEY_ROLE))))
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
        where = QWidget(self)
        where_row = QHBoxLayout(where)
        where_row.setContentsMargins(0, 0, 0, 0)
        where_row.setSpacing(FIELD_GAP)
        where_row.addWidget(self.standing, 1)
        where_row.addWidget(self.conversation_button)
        talk = block(layout, caption("Conversation", self), where)
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
            self.conversation_button.setEnabled(False)
            self.empty.say(NO_ROUNDS)
            return
        self.standing.say(*where_it_stands(self._library, step, self._key_of))
        rows = message_rows(self._library, step, self._key_of, ink_of(self.conversation))
        for item in rows:
            self.conversation.addItem(item)
        self.conversation_button.setEnabled(bool(rows))
        self.empty.say("" if rows else NO_ROUNDS)

    def _open(self, at: str | None) -> None:
        if self._step_id is not None:
            open_conversation(self._library, self._step_id, self._key_of, self.window(), at=at)

    def _on_rounds(self, node_id: NodeId, module_id: str, _origin: object) -> None:
        if module_id == ROUNDS_ID and node_id == self._step_id:
            self._show_conversation(self.step())

    def _on_edges(self, step_id: NodeId) -> None:
        if step_id == self._step_id:
            self._show_conversation(self.step())

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.PaletteChange:
            reink(self.conversation)
        super().changeEvent(event)
