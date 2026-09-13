"""What a test result looks like on screen: its words, its colour and its chip.

Shared by the step panel's Tests tab and the Tests table, so a failed test reads the same
wherever it is shown. The colours are **constant** ``QColor``s rather than theme fields —
``DESIGN.md``'s second deliberate exception, the same stance the progression board takes:
a status means one thing, and it must mean it on all twenty-two themes.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QWidget

from dplanner.modules.testing.runs import Outcome

# Semantic result colours, constant across themes (DESIGN.md deliberate exception #2).
OK_TINT = QColor(46, 160, 67)
FAILED_TINT = QColor(219, 68, 55)
SKIPPED_TINT = QColor(210, 153, 34)

TINTS = {"ok": OK_TINT, "failed": FAILED_TINT, "skipped": SKIPPED_TINT}
WORDS = {"ok": "Ok", "failed": "Failed", "skipped": "Skipped", "pending": "Not run"}
# The order results are offered in, wherever they are: the menus, the strip.
RESULT_ORDER = ("ok", "failed", "skipped", "pending")

# A failed row is the one you came for, so it is the only one tinted; a wall of green
# would shout at every reader who was not looking for it.
FAILED_ROW_TINT = QColor(219, 68, 55, 26)


def word(status: str) -> str:
    return WORDS.get(status, status)


def tint(status: str) -> QColor | None:
    """The colour for a status, or ``None`` for pending — which is an absence, not a state."""
    return TINTS.get(status)


def outcome_line(outcome: Outcome | None) -> str:
    """Where a result came from, in one secondary line: the run, and what was noted."""
    if outcome is None:
        return ""
    where = outcome.run.label or outcome.run.id
    note = f" — {outcome.result.note}" if outcome.result.note else ""
    return f"{where}{note}"


class StatusChip(QLabel):
    """A dot and a word. Not a filled pill: at card size a pill is louder than the title."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.show_status("pending")

    def show_status(self, status: str) -> None:
        colour = tint(status)
        if colour is None:
            self.setText(WORDS["pending"])
            # Pending has no colour of its own; it borrows the panel's secondary text.
            self.setObjectName("InspectorNote")
        else:
            self.setText(f"● {word(status)}")
            self.setObjectName("")
            self.setStyleSheet(f"color: {colour.name()};")
        self.style().unpolish(self)
        self.style().polish(self)
