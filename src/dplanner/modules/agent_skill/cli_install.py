"""Putting the ``dplanner`` command on PATH, with the command shown before it runs.

The skill tells agents to run ``dplanner``, so the window offers the install that makes
that true — and shows the exact command first, because a dialog that runs something on the
user's machine owes them the something. The install resolves packages and may touch the
network, so it runs through ``TaskRunner``, never on the GUI thread, and the tool's own
output lands in the dialog — that is where uv says things worth reading, a bin directory
missing from PATH for instance.

The desktop launcher comes in the same go. With the box ticked, a successful install writes
this platform's launcher (``cli/desktop.py``) pointing at the ``dpw`` uv just put beside
``dplanner`` — ``uv tool dir --bin`` says where, which is why the dialog asks uv rather
than looking beside the build it happens to be running from — and Uninstall takes the
launcher out with the command, since a launcher opening nothing is worse than none.
"""

import shlex
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.cli.desktop import launcher_for, missing_executable_hint, window_executable
from dplanner.cli.main import PROG
from dplanner.cli.skill import (
    install_command,
    tool_bin_command,
    uninstall_command,
    worktree_warning,
)
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.identity import APP_NAME
from dplanner.theme.fonts import mono_font


class CliInstallDialog(QDialog):
    # Worker → GUI: the tool's output, queued because it is emitted off-thread.
    _done = Signal(str)

    def __init__(self, tasks: TaskService, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setObjectName("CliInstallDialog")
        self.setWindowTitle("Install dplanner Command")
        self.resize(560, 500)
        self._runner = TaskRunner(tasks, parent=self)
        self._command = install_command()
        self._launcher = launcher_for()

        caption = QLabel("Command", self)
        caption.setObjectName("InspectorCaption")
        self.command = QLabel(shlex.join(self._command), self)
        self.command.setFont(mono_font())
        self.command.setWordWrap(True)
        self.command.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.status_note = QLabel("", self)
        self.status_note.setObjectName("InspectorNote")
        self.status_note.setWordWrap(True)

        self.worktree_note = QLabel("", self)
        self.worktree_note.setObjectName("InspectorNote")
        self.worktree_note.setWordWrap(True)
        self.worktree_note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        warning = worktree_warning()
        if warning is None:
            self.worktree_note.hide()
        else:
            self.worktree_note.setText(f"Warning: {warning}")

        self.launcher_box = QCheckBox(
            f"Also add {APP_NAME} to the applications menu ({self._launcher.path})", self
        )
        self.launcher_box.setObjectName("CliInstallLauncherBox")
        self.launcher_box.setChecked(True)

        self.output = QPlainTextEdit(self)
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.setFont(mono_font())
        self.output.document().setDocumentMargin(12)
        self.output.setPlaceholderText("The command's output appears here after it runs.")

        self.primary = QPushButton(self)
        self.primary.setObjectName("PrimaryButton")
        self.primary.clicked.connect(self._install)
        self.uninstall_button = QPushButton("Uninstall", self)
        self.uninstall_button.clicked.connect(self._uninstall)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.addButton(self.primary, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(self.uninstall_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(caption)
        layout.addWidget(self.command)
        layout.addWidget(self.status_note)
        layout.addWidget(self.worktree_note)
        layout.addWidget(self.launcher_box)
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
        self.primary.setEnabled(True)
        self.uninstall_button.setEnabled(found is not None)

    def _install(self) -> None:
        with_launcher = self.launcher_box.isChecked()  # Read here: the body runs off-thread.

        def after() -> list[str]:
            if not with_launcher:
                return []
            where = subprocess.run(tool_bin_command(), capture_output=True, text=True)
            said = where.stdout.strip()
            bin_dirs = [Path(said)] if where.returncode == 0 and said else []
            executable = window_executable(bin_dirs)
            if executable is None:
                return [missing_executable_hint()]
            self._launcher.write(executable)
            return [f"Desktop launcher: {self._launcher.path} (opens {executable})"]

        self._run_command("Installing the dplanner command", self._command, after)

    def _uninstall(self) -> None:
        def after() -> list[str]:
            if self._launcher.remove():
                return [f"Removed the desktop launcher: {self._launcher.path}"]
            return []

        self._run_command("Uninstalling the dplanner command", uninstall_command(), after)

    def _run_command(self, label: str, command: list[str], after: Callable[[], list[str]]) -> None:
        def body() -> None:
            result = subprocess.run(command, capture_output=True, text=True)
            output = (result.stdout + result.stderr).strip()
            if result.returncode != 0:
                raise RuntimeError(output or f"{command[0]} exited with {result.returncode}")
            self._done.emit("\n".join([output, *after()]).strip())

        if self._runner.run(label, body, key="agent_skill.cli_install"):
            self.primary.setEnabled(False)
            self.uninstall_button.setEnabled(False)

    def _finished(self, output: str) -> None:
        self.output.setPlainText(output)
        self._refresh()

    def _failed(self, error: str) -> None:
        self.output.setPlainText(error)
        self._refresh()
