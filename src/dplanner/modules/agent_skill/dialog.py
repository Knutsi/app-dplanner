"""The skill, shown before it touches disk.

The dialog is a preview with verbs: where the files go, what each one says, and a button
whose label is the state — Install when nothing is there, Update when the copy on disk is
not this build's, disabled when the bytes already match. It stays open across Install and
Remove and re-reads the disk after each, so what it shows is always what is true, using the
same ``install``/``uninstall``/``status`` functions the CLI uses.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from dplanner.cli.skill import REFERENCE_FILE, SKILL_FILE, install, path_hint, status, uninstall
from dplanner.theme.fonts import mono_font

_TAB_TITLES = {
    SKILL_FILE: "Skill",
    REFERENCE_FILE: "Reference",
}

_STATUS_NOTES = {
    "missing": "Not installed yet.",
    "stale": "Installed, but not from this build — Update rewrites it.",
    "installed": "Installed and current.",
}

_PROJECT_HINT = "`dplanner skill install --project` installs into a repository instead."

_PRIMARY_LABELS = {
    "missing": "Install",
    "stale": "Update",
    "installed": "Update",
}


class AgentSkillDialog(QDialog):
    def __init__(self, files: dict[str, str], directory: Path, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setObjectName("AgentSkillDialog")
        self.setWindowTitle("Agent Skill")
        self.resize(760, 560)
        self._files = files
        self._directory = directory

        caption = QLabel("Destination", self)
        caption.setObjectName("InspectorCaption")
        destination = QLabel(str(directory), self)
        destination.setWordWrap(True)

        self.status_note = QLabel("", self)
        self.status_note.setObjectName("InspectorNote")
        self.status_note.setWordWrap(True)

        self.path_note = QLabel("", self)
        self.path_note.setObjectName("InspectorNote")
        self.path_note.setWordWrap(True)
        self.path_note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        hint = path_hint()
        if hint is None:
            self.path_note.hide()
        else:
            self.path_note.setText(
                "The skill tells agents to run `dplanner`, which is not on PATH — "
                f"put it there with:  {hint}  "
                "(Tools ▸ Install dplanner Command… runs it for you.)"
            )

        # The generated files are hard-wrapped by the generator (HELP_WIDTH), so the
        # preview shows them as authored: monospace, no soft wrapping on top.
        self.tabs = QTabWidget(self)
        for name, content in files.items():
            view = QPlainTextEdit(self)
            view.setPlainText(content)
            view.setReadOnly(True)
            view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            view.setFont(mono_font())
            view.document().setDocumentMargin(12)
            self.tabs.addTab(view, _TAB_TITLES.get(name, name))

        self.primary = QPushButton(self)
        self.primary.setObjectName("PrimaryButton")
        self.primary.clicked.connect(self._install)
        self.remove_button = QPushButton("Remove", self)
        self.remove_button.clicked.connect(self._remove)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.addButton(self.primary, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(self.remove_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(caption)
        layout.addWidget(destination)
        layout.addWidget(self.status_note)
        layout.addWidget(self.path_note)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(buttons)

        self._refresh()

    def _install(self) -> None:
        install(self._files, self._directory)
        self._refresh()

    def _remove(self) -> None:
        uninstall(self._files, self._directory)
        self._refresh()

    def _refresh(self) -> None:
        state = status(self._files, self._directory)
        self.primary.setText(_PRIMARY_LABELS[state])
        self.primary.setEnabled(state != "installed")
        self.remove_button.setEnabled(state != "missing")
        self.status_note.setText(f"{_STATUS_NOTES[state]} {_PROJECT_HINT}")
