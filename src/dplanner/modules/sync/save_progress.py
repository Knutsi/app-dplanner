"""What a save is doing, while the window waits for it: one row per repository.

Quitting with uncommitted planning changes used to run the save on the GUI thread with
nothing on screen — a frozen window for as long as publishing, committing and pushing took.
It runs as an ordinary task now, and this is what watches it: a modal frame listing every
repository being recorded, each row a :class:`StatusLine` saying where that one has got to,
over a determinate bar — DESIGN.md's *Signalling* names this very case ("a save over 3
repositories"), and the fraction is honest because the repositories are counted before the
first one starts.

The close is *deferred*, not blocked: the close guard starts the save, returns "not yet",
and the window closes when this dialog ends. So nothing is tearing down while the save runs,
which is what made the old synchronous exception necessary — ``ARCHITECTURE.md``'s *Save
spans repositories; the exit dialog says what it records* has the reasoning. While the save
runs the dialog cannot be dismissed: a save nobody can see is exactly what this replaced.
"""

from collections.abc import Sequence

from PySide6.QtWidgets import QProgressBar, QWidget

from dplanner.framework.dialog import DialogFrame
from dplanner.framework.signalling import StatusLine, Tone
from dplanner.framework.widgets import note
from dplanner.modules.sync.service import COMMITTING, NOTHING, PUBLISHING, SAVED

# What each phase says on its repository's row. A row not yet reached says only its name.
_PHRASES: dict[str, tuple[str, Tone]] = {
    PUBLISHING: ("writing the report site", "busy"),
    COMMITTING: ("committing", "busy"),
    SAVED: ("recorded", "ok"),
    NOTHING: ("nothing to save", "info"),
}


class SaveProgressDialog(DialogFrame):
    """One row per repository being recorded, and the count over them."""

    def __init__(self, labels: Sequence[str], parent: QWidget | None = None) -> None:
        super().__init__(
            "Saving",
            parent,
            lead="Recording a version in each repository with planning changes.",
        )
        self._labels = list(labels)
        self._running = True
        self._done = 0
        self._rows = [StatusLine(self.body) for _ in self._labels]
        for row, label in zip(self._rows, self._labels, strict=True):
            row.say(label)  # Its own ink: waiting is not a state (DESIGN.md's *Signalling*).
            self.body_layout.addWidget(row)
        self._count = note("", self.body)
        self.body_layout.addWidget(self._count)
        self.bar = QProgressBar(self.body)
        self.bar.setRange(0, len(self._labels))
        self.bar.setTextVisible(False)  # The words are the note's; the bar is the shape.
        self.body_layout.addWidget(self.bar)
        self._recount()

    def step(self, index: int, phase: str) -> None:
        """A repository reached ``phase``. Indices are the save's own, so a skip is fine."""
        if not 0 <= index < len(self._rows):
            return
        phrase, tone = _PHRASES.get(phase, ("", "info"))
        label = self._labels[index]
        self._rows[index].say(f"{label} — {phrase}" if phrase else label, tone)
        if phase in (SAVED, NOTHING):
            self._done = max(self._done, index + 1)
            self._recount()

    def stopped(self, error: str) -> None:
        """The save ended badly: say so here rather than losing it, and offer both exits."""
        self._running = False
        for row, label in zip(self._rows, self._labels, strict=True):
            if row.tone() == "busy":
                # The stored label, never the row's words: a label carries an em dash of its
                # own ("~/Code/widget · 3 files — Discovery") and splitting on it loses half.
                row.say(f"{label} — not recorded", "error")
        self.status.say(error, "error")
        # Quitting with the work uncommitted is a different exit that costs something, so it
        # takes the destructive slot; Stay is the dismiss, and the default, so Enter records
        # nothing by accident.
        self.add_button("Close Anyway", self.accept, destructive=True)
        self.add_dismiss("Stay")

    def reject(self) -> None:
        """Escape is refused while the save runs — there is nothing to go back to."""
        if self._running:
            return
        super().reject()

    def accept(self) -> None:
        self._running = False
        super().accept()

    def _recount(self) -> None:
        total = len(self._labels)
        self.bar.setValue(self._done)
        plural = "repository" if total == 1 else "repositories"
        self._count.setText(f"{self._done} of {total} {plural} recorded")
