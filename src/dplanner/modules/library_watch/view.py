"""What the window shows when an outside change collides with an unsaved edit: the modal
that asks, and the status-bar button that keeps the question reachable after *Later*."""

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

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


class ConflictDialog(QDialog):
    """Four ways out: hand both versions to the agent, take theirs, keep ours, or later."""

    def __init__(self, rows: Sequence[str], agent_refusal: str, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Changed Here and Outside")
        self.setMinimumWidth(520)
        self.choice = LATER

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        explanation = QLabel(EXPLANATION)
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        for row in rows:
            label = QLabel(f"•  {row}")
            label.setObjectName("InspectorNote")
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(label)

        buttons = QDialogButtonBox()
        # The reason a way out is closed sits in its label — the rule every greyed menu
        # entry follows — rather than in a tooltip most readers never find.
        agent_label = "Resolve with Agent" + (f" — {agent_refusal}" if agent_refusal else "")
        self.agent_button = QPushButton(agent_label)
        self.agent_button.setObjectName("PrimaryButton")
        self.agent_button.setEnabled(not agent_refusal)
        self.agent_button.setToolTip(AGENT_TIP)
        theirs = QPushButton("Take Theirs")
        theirs.setToolTip("Replace this window's unsaved edit with what is on disk")
        mine = QPushButton("Keep Mine")
        mine.setToolTip("Save this window's edit over what the other writer put on disk")
        later = QPushButton("Later")
        buttons.addButton(self.agent_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(theirs, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(mine, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(later, QDialogButtonBox.ButtonRole.RejectRole)
        for button, choice in ((self.agent_button, AGENT), (theirs, THEIRS), (mine, MINE)):
            button.clicked.connect(lambda _checked=False, c=choice: self._choose(c))
        later.clicked.connect(self.reject)
        layout.addWidget(buttons)
        (self.agent_button if not agent_refusal else later).setDefault(True)

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
