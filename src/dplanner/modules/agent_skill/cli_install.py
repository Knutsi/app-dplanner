"""Putting the ``dplanner`` command on PATH, with the command shown before it runs.

The skill tells agents to run ``dplanner``, so the window offers the install that makes
that true — and shows the exact command first, because a dialog that runs something on the
user's machine owes them the something. The install resolves packages and may touch the
network, so it runs through ``TaskRunner``, never on the GUI thread, and the tool's own
output lands in the dialog — that is where uv says things worth reading, a bin directory
missing from PATH for instance.
"""

import shlex
import shutil
import subprocess

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.cli.main import PROG
from dplanner.cli.skill import install_command
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.theme.fonts import mono_font


class CliInstallDialog(QDialog):
    # Worker → GUI: the tool's output, queued because it is emitted off-thread.
    _done = Signal(str)

    def __init__(self, tasks: TaskService, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setObjectName("CliInstallDialog")
        self.setWindowTitle("Install dplanner Command")
        self.resize(560, 360)
        self._runner = TaskRunner(tasks, parent=self)
        self._command = install_command()

        caption = QLabel("Command", self)
        caption.setObjectName("InspectorCaption")
        self.command = QLabel(shlex.join(self._command), self)
        self.command.setFont(mono_font())
        self.command.setWordWrap(True)
        self.command.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.status_note = QLabel("", self)
        self.status_note.setObjectName("InspectorNote")
        self.status_note.setWordWrap(True)

        self.output = QPlainTextEdit(self)
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.setFont(mono_font())
        self.output.document().setDocumentMargin(12)
        self.output.setPlaceholderText("The command's output appears here after it runs.")

        self.primary = QPushButton(self)
        self.primary.setObjectName("PrimaryButton")
        self.primary.clicked.connect(self._install)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.addButton(self.primary, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(caption)
        layout.addWidget(self.command)
        layout.addWidget(self.status_note)
        layout.addWidget(self.output, 1)
        layout.addWidget(buttons)

        self._done.connect(self._finished)
        self._runner.failed.connect(self._failed)
        self._refresh()

    def _refresh(self) -> None:
        found = shutil.which(PROG)
        if found is None:
            self.status_note.setText("The dplanner command is not on PATH yet.")
            self.primary.setText("Install")
        else:
            self.status_note.setText(
                f"dplanner resolves at {found} — installing again refreshes it."
            )
            self.primary.setText("Reinstall")

    def _install(self) -> None:
        command = self._command

        def body() -> None:
            result = subprocess.run(command, capture_output=True, text=True)
            output = (result.stdout + result.stderr).strip()
            if result.returncode != 0:
                raise RuntimeError(output or f"{command[0]} exited with {result.returncode}")
            self._done.emit(output)

        started = self._runner.run(
            "Installing the dplanner command", body, key="agent_skill.cli_install"
        )
        if started:
            self.primary.setEnabled(False)

    def _finished(self, output: str) -> None:
        self.output.setPlainText(output)
        self.primary.setEnabled(True)
        self._refresh()

    def _failed(self, error: str) -> None:
        self.output.setPlainText(error)
        self.primary.setEnabled(True)
        self._refresh()
