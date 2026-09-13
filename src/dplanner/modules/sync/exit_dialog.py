"""The quit-time question, when repositories still hold unrecorded planning changes.

Files are already on disk — autosave put them there — so nothing is *lost* whichever
button is pressed; what is at stake is whether the changes get recorded as a version
before the window goes. That is why the three answers are honest: **Commit & Quit**
records the checked repositories (the default, everything checked), **Quit Without
Committing** leaves them dirty for next time, and **Cancel** stays.

One commit message covers every checked repository: a quit-time save is one gesture, and
the per-repo default ("Save: <timestamp>") stands in when the field is left empty.

It is a :class:`DialogFrame` (DESIGN.md's *Dialogs*): what is at stake as the body's first
line, the repositories under it, and a footer whose slots put *Quit Without Committing* in
the destructive place — a different exit that costs something, as far from the accent as the
footer allows — with Cancel beside the primary, where the eye goes to leave.
"""

from dataclasses import dataclass

from PySide6.QtWidgets import QCheckBox, QLineEdit, QVBoxLayout, QWidget

from dplanner.framework.dialog import DialogFrame
from dplanner.framework.widgets import caption, note
from dplanner.theme.tokens import CAPTION_GAP


@dataclass(frozen=True)
class DirtyRepoRow:
    """One repository with uncommitted planning changes, described for the user."""

    label: str  # "~/Code/widget · 3 files — Search Rewrite, Billing"


class ExitDialog(DialogFrame):
    """Which dirty repositories to commit on the way out, and with what message."""

    def __init__(self, rows: list[DirtyRepoRow], parent: QWidget | None = None) -> None:
        super().__init__("Record Changes Before Quitting", parent)
        self.setObjectName("ExitDialog")
        self.discard = False

        count = len(rows)
        has = "repository has" if count == 1 else "repositories have"
        self.body_layout.addWidget(
            note(f"{count} {has} planning changes that are not committed.", self.body)
        )

        self._checks: list[QCheckBox] = []
        for row in rows:
            check = QCheckBox(row.label, self.body)
            check.setChecked(True)
            self._checks.append(check)
            self.body_layout.addWidget(check)

        field = QVBoxLayout()
        field.setSpacing(CAPTION_GAP)
        self.body_layout.addLayout(field)  # Before it is filled: a parentless layout leaks.
        field.addWidget(caption("Message", self.body))
        self._message = QLineEdit(self.body)
        self._message.setObjectName("ExitCommitMessage")
        self._message.setPlaceholderText("Describe this save (optional)")
        field.addWidget(self._message)
        # Spare height goes to the bottom: without it a resized dialog pulls the caption
        # away from the field it is over, which is the one thing a caption must not do.
        self.body_layout.addStretch(1)

        self.add_button("Quit Without Committing", self._quit_without_committing, destructive=True)
        self.add_dismiss()
        self.set_primary("Commit && Quit", self.accept)

    def _quit_without_committing(self) -> None:
        self.discard = True
        self.accept()

    def checked_rows(self) -> list[int]:
        """Indices of the repositories the user left checked, in the given order."""
        return [index for index, check in enumerate(self._checks) if check.isChecked()]

    def message(self) -> str:
        return self._message.text().strip()
