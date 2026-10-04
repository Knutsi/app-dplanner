"""Save Snapshot…: the title a saved snapshot is found by, and a note saying what the
occasion was. A title already taken is refused *in the dialog*, with the reason where the
finger is, because a saved snapshot is named exactly so that it can be told from the others.
"""

from collections.abc import Sequence

from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QWidget

from dplanner.framework.dialog import DialogFrame
from dplanner.framework.signalling import StatusLine
from dplanner.framework.widgets import block, caption
from dplanner.theme.tokens import SECTION_GAP

NOTE_LINES = 4


class SaveSnapshotDialog(DialogFrame):
    """A title the snapshot is found by, and a note on what the occasion was."""

    def __init__(self, taken: Sequence[str], parent: QWidget | None = None) -> None:
        super().__init__("Save Snapshot", parent)
        self._taken = {title.strip().lower() for title in taken}
        self.title = QLineEdit(self.body)
        self.title.setPlaceholderText("What we thought on 1 November")
        self.title.textChanged.connect(self._check)
        # Under the field it is about, in the error tone, only while the title is taken.
        self.reason = StatusLine(self.body)
        block(self.body_layout, caption("Title", self.body), self.title, self.reason)
        self.note = QPlainTextEdit(self.body)
        self.note.setPlaceholderText("What the occasion was, for whoever compares against it")
        self.note.setFixedHeight(self.note.fontMetrics().lineSpacing() * NOTE_LINES + SECTION_GAP)
        block(self.body_layout, caption("Note", self.body), self.note)
        self.add_dismiss()
        self.set_primary("Save", self.accept)
        self._check()

    def values(self) -> tuple[str, str]:
        return self.title.text().strip(), self.note.toPlainText().strip()

    def _check(self) -> None:
        """Save is offered only for a title that is new: the reason sits under the field
        rather than arriving as a refusal after the click."""
        title = self.title.text().strip()
        taken = bool(title) and title.lower() in self._taken
        self.reason.say(f"A snapshot called “{title}” is already saved." if taken else "", "error")
        primary = self.primary()
        if primary is not None:
            primary.setEnabled(bool(title) and not taken)
