"""The Playbook block on a step's Details tab: which playbook, its round cap and reviewer.

The same entry ``dplanner playbook set`` writes. Its first row is *Default*, naming what the
step inherits — the project's landing default on a landing, else its default, else Run Agent
— and choosing it removes the entry. The overrides belong to a choice of the step's own, so
they are revealed only by one that can use them: *Rounds* under a playbook with a gate,
*Reviewer* under one another agent reviews in, and neither under *Default*. A field with
nothing to apply to is hidden rather than greyed — it is not a verb waiting on a reason, and
a step with no playbook of its own reads as one line.
"""

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QSpinBox, QVBoxLayout

from dplanner.domain.model import Library, Step
from dplanner.framework.module_data_section import ModuleDataSection
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import block, captioned
from dplanner.modules.step_playbook.aspect import MODULE_ID, Choice, inherited, read, write
from dplanner.modules.step_playbook.presets import MAX_ROUNDS, PRESETS, ROUNDS, preset
from dplanner.theme.tokens import FIELD_GAP

ROUNDS_HINT = (
    "How many verdicts each gate may give before it escalates to somebody — "
    "changes on the last round is never a silent extra round."
)
REVIEWER_HINT = "The agent CLI that reviews the work when the playbook asks another agent."


class PlaybookSection(ModuleDataSection):
    """A preset, or the default; and the two overrides a choice of its own may carry."""

    def __init__(
        self, library: Library, undo: UndoService[Library], harness_ids: tuple[str, ...]
    ) -> None:
        super().__init__(library, undo, module_id=MODULE_ID, undo_label="Set Playbook")
        self.playbook = QComboBox(self)
        self.playbook.addItem("Default", None)
        add_presets(self.playbook)
        self.rounds = QSpinBox(self)
        self.rounds.setRange(0, MAX_ROUNDS)
        self.rounds.setSpecialValueText(f"Default ({ROUNDS})")
        self.rounds.setKeyboardTracking(False)
        self.reviewer = QComboBox(self)
        self.reviewer.addItem("Default — another vendor", None)
        for harness_id in harness_ids:
            self.reviewer.addItem(harness_id, harness_id)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(FIELD_GAP)
        layout.addWidget(self.playbook)  # The block's own caption names it.
        self._rounds_caption = captioned("Rounds", self, ROUNDS_HINT)
        block(layout, self._rounds_caption, self.rounds)
        self._reviewer_caption = captioned("Reviewer", self, REVIEWER_HINT)
        block(layout, self._reviewer_caption, self.reviewer)
        self.playbook.activated.connect(lambda _index: self._on_playbook())
        self.rounds.valueChanged.connect(lambda _rounds: self.commit())
        self.reviewer.activated.connect(lambda _index: self.commit())

    # -- ModuleDataSection -----------------------------------------------------------------------

    def load_step(self, step: Step | None) -> None:
        choice = read(step) if step is not None else None
        self.playbook.setItemText(0, self._default_words(step))
        self.playbook.setCurrentIndex(
            self.playbook.findData(choice.playbook.id) if choice is not None else 0
        )
        self.rounds.setValue(choice.rounds if choice is not None and choice.rounds else 0)
        reviewer = choice.reviewer if choice is not None else None
        self.reviewer.setCurrentIndex(max(0, self.reviewer.findData(reviewer)))
        self._show_overrides()

    def entry(self, step: Step) -> dict[str, Any]:
        playbook = preset(self.playbook.currentData() or "")
        if playbook is None:
            return write(None)
        return write(
            Choice(
                playbook,
                rounds=(self.rounds.value() or None) if playbook.has_gate() else None,
                reviewer=self.reviewer.currentData() if playbook.reviews_with_other() else None,
            )
        )

    # -- input -----------------------------------------------------------------------------------

    def _on_playbook(self) -> None:
        self._show_overrides()
        self.commit()

    def _show_overrides(self) -> None:
        playbook = preset(self.playbook.currentData() or "")
        rounds = playbook is not None and playbook.has_gate()
        reviewer = playbook is not None and playbook.reviews_with_other()
        for widget in (self._rounds_caption, self.rounds):
            widget.setVisible(rounds)
        for widget in (self._reviewer_caption, self.reviewer):
            widget.setVisible(reviewer)

    def _default_words(self, step: Step | None) -> str:
        if step is None:
            return "Default"
        playbook = inherited(step, self._library.project_of(step.id)).playbook
        return f"Default — {playbook.name if playbook is not None else 'Run Agent'}"


def add_presets(combo: QComboBox, *, but: str | None = None) -> None:
    """Every preset as a row of ``combo`` — named, its stages in the tooltip — but one."""
    for playbook in PRESETS:
        if playbook.id != but:
            combo.addItem(playbook.name, playbook.id)
            combo.setItemData(
                combo.count() - 1,
                f"{playbook.stage_words()}\n{playbook.summary}",
                Qt.ItemDataRole.ToolTipRole,
            )
