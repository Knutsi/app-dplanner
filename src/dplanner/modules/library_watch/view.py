"""What the window shows when an outside change collides with an unsaved edit: the modal
that asks, and the status-bar button that keeps the question reachable after *Later*."""

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QToolButton, QWidget

from dplanner.framework.dialog import DialogFrame
from dplanner.framework.widgets import note

MIN_WIDTH = 520  # A changed entry is named by its path, and a path wants the room.

AGENT, THEIRS, MINE, LATER = "agent", "theirs", "mine", "later"

EXPLANATION = (
    "These entries changed outside DPlanner while this window had its own unsaved edit to"
    " them. Nothing has been written over anybody's work yet, and this window will not"
    " save until they are settled."
)
AGENT_TIP = (
    "Open a terminal with the configured agent briefed on both versions; this window"
    " takes the outside version meanwhile, and the agent writes the merge back."
)


class ConflictDialog(DialogFrame):
    """Four ways out: hand both versions to the agent, take theirs, keep ours, or later.

    On the frame: the agent is the primary — the flow's next step — and when this build
    cannot run one it is refused with the reason in the footer's status slot, its name
    kept; *Take Theirs* and *Keep Mine* are quiet secondaries; *Later* is Escape's.
    """

    def __init__(self, rows: Sequence[str], agent_refusal: str, parent: QWidget | None) -> None:
        super().__init__("Changed Here and Outside", parent)
        self.setMinimumWidth(MIN_WIDTH)
        self.choice = LATER
        body, layout = self.body, self.body_layout
        explanation = QLabel(EXPLANATION, body)
        explanation.setObjectName("DialogQuestion")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        for row in rows:
            label = note(f"•  {row}", body)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(label)
        layout.addStretch(0)

        self.agent_button = self.set_primary("Resolve with Agent", lambda: self._choose(AGENT))
        self.agent_button.setToolTip(AGENT_TIP)
        self.theirs_button = self.add_button("Take Theirs", lambda: self._choose(THEIRS))
        self.theirs_button.setToolTip("Replace this window's unsaved edit with what is on disk")
        self.mine_button = self.add_button("Keep Mine", lambda: self._choose(MINE))
        self.mine_button.setToolTip("Save this window's edit over what the other writer put on disk")
        self.add_dismiss("Later")
        if agent_refusal:
            self.refuse(agent_refusal)

    def _choose(self, choice: str) -> None:
        self.choice = choice
        self.accept()

    def choose(self) -> str:
        """Run modally; one of :data:`AGENT`, :data:`THEIRS`, :data:`MINE`, :data:`LATER`."""
        self.exec()
        return self.choice


class OutsideChangesButton(QToolButton):
    """Hidden while nothing waits; clicking reopens the question."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("OutsideChangesButton")
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Changed here and outside — click to settle")
        self.hide()

    def set_waiting(self, count: int) -> None:
        if not count:
            self.hide()
            return
        noun = "entry" if count == 1 else "entries"
        self.setText(f"● {count} {noun} changed here and outside")
        self.show()
