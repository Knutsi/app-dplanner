"""The quit-time question, when repositories still hold unrecorded planning changes.

Files are already on disk — autosave put them there — so nothing is *lost* whichever
button is pressed; what is at stake is whether the changes get recorded as a version
before the window goes. That is why the three answers are honest: **Commit & Quit**
records the checked repositories (the default, everything checked), **Quit Without
Committing** leaves them dirty for next time, and **Cancel** stays.

One commit message covers every checked repository: a quit-time save is one gesture, and
the per-repo default ("Save: <timestamp>") stands in when the field is left empty.
"""

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class DirtyRepoRow:
    """One repository with uncommitted planning changes, described for the user."""

    label: str  # "~/Code/widget · 3 files — Search Rewrite, Billing"


class ExitDialog(QDialog):
    """Which dirty repositories to commit on the way out, and with what message."""

    def __init__(self, rows: list[DirtyRepoRow], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ExitDialog")
        self.setWindowTitle("Record Changes Before Quitting")
        self.discard = False

        prose = QLabel("These repositories have planning changes that are not committed.")
        prose.setWordWrap(True)

        self._checks: list[QCheckBox] = []
        layout = QVBoxLayout(self)
        layout.addWidget(prose)
        for row in rows:
            check = QCheckBox(row.label)
            check.setChecked(True)
            self._checks.append(check)
            layout.addWidget(check)

        self._message = QLineEdit(self)
        self._message.setObjectName("ExitCommitMessage")
        self._message.setPlaceholderText("Describe this save (optional)")
        layout.addWidget(self._message)

        buttons = QDialogButtonBox(self)
        commit = buttons.addButton("Commit && Quit", QDialogButtonBox.ButtonRole.AcceptRole)
        skip = buttons.addButton(
            "Quit Without Committing", QDialogButtonBox.ButtonRole.DestructiveRole
        )
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        commit.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        skip.clicked.connect(self._quit_without_committing)
        layout.addWidget(buttons)

    def _quit_without_committing(self) -> None:
        self.discard = True
        self.accept()

    def checked_rows(self) -> list[int]:
        """Indices of the repositories the user left checked, in the given order."""
        return [index for index, check in enumerate(self._checks) if check.isChecked()]

    def message(self) -> str:
        return self._message.text().strip()
