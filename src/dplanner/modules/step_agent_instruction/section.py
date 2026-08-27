"""The Agent tab: the instruction, with the trigger right under it.

The button is not a second implementation of anything — it evaluates and runs the same
``agent.run`` :class:`ActionSpec` the menus do, so the two can never disagree about when a
run is possible, and the state's reason label becomes the disabled button's tooltip.
"""

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout

from dplanner.framework.action_registry import ActionState
from dplanner.framework.prose_section import ProseSection
from dplanner.framework.text_binding import TextField
from dplanner.framework.undo import UndoService


class AgentSection(ProseSection):
    """The instruction editor, plus Run Agent — enabled exactly when the action is."""

    def __init__(
        self,
        field_for: Callable[[str], TextField[Any] | None],
        undo: UndoService[Any],
        placeholder: str,
        run_state: Callable[[], ActionState],
        run: Callable[[], None],
    ) -> None:
        super().__init__(field_for, undo, placeholder)
        self._run_state = run_state

        self.run_button = QPushButton("Run Agent…", self)
        self.run_button.setObjectName("AgentRunButton")
        self.run_button.clicked.connect(lambda: run())

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.run_button)
        layout = self.layout()
        assert isinstance(layout, QVBoxLayout)  # ProseSection's own layout.
        layout.setSpacing(6)  # DESIGN.md: the button belongs with its editor — within-block.
        layout.addLayout(row)

        # Typing the first instruction is what arms the button, so it follows the editor.
        self.edit.textChanged.connect(self._refresh_run)

    def show_target(self, target_id: str | None) -> None:
        super().show_target(target_id)
        self._refresh_run()

    def _refresh_run(self) -> None:
        state = self._run_state()
        self.run_button.setEnabled(state.enabled)
        self.run_button.setToolTip(
            state.label or "Open a terminal with the agent briefed on this step"
        )
