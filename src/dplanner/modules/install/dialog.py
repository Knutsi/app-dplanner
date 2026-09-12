"""Installing DPlanner from the window: three rows and one button.

What the window adds over ``dplanner install all`` is that somebody who has never opened a
terminal can see the state before acting on it — the command, the desktop launcher and the
agent skill, each saying what it is and what is wrong with it, with one button that brings
all three up to date. It writes what the verb writes, through the same functions
(``cli/install.py``), because a second implementation would drift the way the two dialogs
this replaced did.

The install resolves packages and may touch the network, so it runs through ``TaskRunner``,
never on the GUI thread, and what it did lands in the pane below — that is where uv says the
things worth reading, a bin directory missing from PATH for instance. The rows re-read the
disk afterwards, so what they show is always what is true.
"""

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.cli.install import (
    LAUNCHER,
    SKILL,
    Item,
    Outcome,
    apply,
    items,
    remove,
    report_lines,
    summary,
    worktree_warning,
)
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.theme.fonts import mono_font

# The one button says what pressing it would do; anything already there is refreshed.
_PRIMARY_LABELS = {"missing": "Install", "stale": "Update", "installed": "Update"}


class _Row(QWidget):
    """One item: what it is and how it stands on line one, why on line two."""

    def __init__(self, item: Item, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("InstallRow")
        # A QWidget subclass paints no stylesheet border unless told to; the hairline
        # between rows is a QSS border-bottom, and the last row has no row to part from.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.label = QLabel(item.label, self)
        self.state = QLabel(self)
        self.state.setObjectName("InstallRowState")
        self.note = QLabel(self)
        self.note.setObjectName("InstallRowNote")
        self.note.setWordWrap(True)

        title_line = QHBoxLayout()
        title_line.setContentsMargins(0, 0, 0, 0)
        title_line.setSpacing(12)
        title_line.addWidget(self.label, 1)
        title_line.addWidget(self.state)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)  # Rich-row metrics per DESIGN.md.
        layout.setSpacing(4)
        layout.addLayout(title_line)
        layout.addWidget(self.note)
        self.show_item(item)

    def show_item(self, item: Item) -> None:
        self.state.setText(item.state)
        self.note.setText(item.note)
        self.setToolTip("" if item.where is None else str(item.where))


class InstallDialog(QDialog):
    # Worker → GUI: what the act did to each of the three, queued because it is emitted
    # off-thread. Plain Outcomes — nothing Qt crosses the seam.
    _done = Signal(list)

    def __init__(self, tasks: TaskService, files: dict[str, str], parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setObjectName("InstallDialog")
        self.setWindowTitle("Install DPlanner")
        self.setMinimumSize(480, 380)
        self.resize(620, 460)
        self._files = files
        self._runner = TaskRunner(tasks, parent=self)

        read = items(self._files)
        self.well = QWidget(self)
        self.well.setObjectName("InstallWell")
        self.well.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        rows = QVBoxLayout(self.well)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)  # Rows carry their own padding and hairline.
        self.rows = [_Row(item, self.well) for item in read]
        for row in self.rows:
            rows.addWidget(row)
        self.rows[-1].setProperty("last", True)  # No row below it to be parted from.

        self.worktree_note = QLabel(self)
        self.worktree_note.setObjectName("InspectorNote")
        self.worktree_note.setWordWrap(True)
        self.worktree_note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        warning = worktree_warning()
        if warning is None:
            self.worktree_note.hide()
        else:
            self.worktree_note.setText(warning)

        self.output = QPlainTextEdit(self)
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.setFont(mono_font())
        self.output.document().setDocumentMargin(12)
        self.output.setPlaceholderText("What the install did appears here after it runs.")

        self.primary = QPushButton(self)
        self.primary.setObjectName("PrimaryButton")
        self.primary.clicked.connect(self._install)
        self.remove_button = QPushButton("Remove", self)
        self.remove_button.setToolTip(
            "Take out the desktop launcher and the agent skill; the command stays"
        )
        self.remove_button.clicked.connect(self._remove)
        self.close_button = QPushButton("Close", self)
        self.close_button.clicked.connect(self.reject)
        # Without an explicit default Qt promotes the first auto-default button — the
        # primary — and Enter would silently run the install.
        self.close_button.setDefault(True)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch(1)
        footer.addWidget(self.remove_button)
        footer.addWidget(self.primary)
        footer.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)  # Dialog metrics per DESIGN.md.
        layout.setSpacing(12)
        layout.addWidget(self.well)
        layout.addWidget(self.worktree_note)
        layout.addWidget(self.output, 1)
        layout.addLayout(footer)

        self._done.connect(self._finished)
        self._runner.failed.connect(self._failed)
        self._refresh()

    def _refresh(self) -> None:
        read = items(self._files)
        for row, item in zip(self.rows, read, strict=True):
            row.show_item(item)
        self.primary.setText(_PRIMARY_LABELS[summary(read)])
        self.primary.setEnabled(True)
        removable = {LAUNCHER, SKILL}
        self.remove_button.setEnabled(
            any(item.state != "missing" for item in read if item.id in removable)
        )

    def _install(self) -> None:
        files, done = self._files, self._done  # Read here: the body runs off-thread.
        self._start("Installing DPlanner", lambda: done.emit(apply(files)))

    def _remove(self) -> None:
        files, done = self._files, self._done
        self._start("Removing the DPlanner launcher and skill", lambda: done.emit(remove(files)))

    def _start(self, label: str, body: Callable[[], None]) -> None:
        if self._runner.run(label, body, key="install.dplanner"):
            self.primary.setEnabled(False)
            self.remove_button.setEnabled(False)

    def _finished(self, outcomes: list[Outcome]) -> None:
        self.output.setPlainText(report_lines(outcomes))
        self._refresh()

    def _failed(self, error: str) -> None:
        self.output.setPlainText(error)
        self._refresh()
