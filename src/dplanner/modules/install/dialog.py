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
from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

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
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.signalling import TICKED, UNTICKED, StatusLine, Tone
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.widgets import make_text_well, note
from dplanner.theme.fonts import mono_font
from dplanner.theme.tokens import ROW_LINE_GAP, ROW_PADDING_H, ROW_PADDING_V

DIALOG_SIZE = (620, 460)
# The one button says what pressing it would do; anything already there is refreshed.
_PRIMARY_LABELS = {"missing": "Install", "stale": "Update", "installed": "Update"}


def _tone(item: Item) -> Tone:
    """The Setup Checklist's rule, so the two lists read as one: a missing piece is the
    error tone when an agent needs it — the command and the skill — and information for
    the launcher, which is worth knowing rather than wrong."""
    if item.state == "installed":
        return "ok"
    return "info" if item.id == LAUNCHER else "error"


class _Row(QWidget):
    """One item: what it is and how it stands on line one, why on line two."""

    def __init__(self, item: Item, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("InstallRow")
        # A QWidget subclass paints no stylesheet border unless told to; the hairline
        # between rows is a QSS border-bottom, and the last row has no row to part from.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.line = StatusLine(self)
        self.note = note("", self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(ROW_PADDING_H, ROW_PADDING_V, ROW_PADDING_H, ROW_PADDING_V)
        layout.setSpacing(ROW_LINE_GAP)
        layout.addWidget(self.line)
        layout.addWidget(self.note)
        self.show_item(item)

    def show_item(self, item: Item) -> None:
        self.item = item
        installed = item.state == "installed"
        self.line.say(
            f"{item.label} — {item.state}", _tone(item), glyph=TICKED if installed else UNTICKED
        )
        self.note.setText(item.note)
        self.setToolTip("" if item.where is None else str(item.where))


class InstallDialog(DialogFrame):
    # Worker → GUI: what the act did to each of the three, queued because it is emitted
    # off-thread. Plain Outcomes — nothing Qt crosses the seam.
    _done = Signal(list)

    def __init__(self, tasks: TaskService, files: dict[str, str], parent: QWidget | None) -> None:
        super().__init__("Install DPlanner", parent, size=DIALOG_SIZE)
        self._files = files
        self._runner = TaskRunner(tasks, parent=self)
        body, layout = self.body, self.body_layout

        read = items(self._files)
        self.well = QWidget(body)
        self.well.setObjectName("InstallWell")
        self.well.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        rows = QVBoxLayout(self.well)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)  # Rows carry their own padding and hairline.
        self.rows = [_Row(item, self.well) for item in read]
        for row in self.rows:
            rows.addWidget(row)
        self.rows[-1].setProperty("last", True)  # No row below it to be parted from.
        layout.addWidget(self.well)

        self.worktree_note = note("", body)
        self.worktree_note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        warning = worktree_warning()
        if warning is None:
            self.worktree_note.hide()
        else:
            self.worktree_note.setText(warning)
        layout.addWidget(self.worktree_note)

        self.output = QPlainTextEdit(body)
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.setFont(mono_font())
        make_text_well(self.output)
        self.output.setPlaceholderText("What the install did appears here after it runs.")
        # Skipped when the dialog opens — the primary is the first stop, so Enter is
        # visibly Install — but a click still lets the pane be copied from.
        self.output.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        layout.addWidget(self.output, 1)

        self.remove_button = self.add_button("Remove", self._remove, destructive=True)
        self.remove_button.setToolTip(
            "Take out the desktop launcher and the agent skill; the command stays"
        )
        self.add_dismiss("Close")
        self.install_button = self.set_primary("", self._install)

        self._done.connect(self._finished)
        self._runner.failed.connect(self._failed)
        self._refresh()

    def _refresh(self) -> None:
        """Re-read the disk into the rows and the button; the status slot is left alone,
        because it says what the last act came to."""
        read = items(self._files)
        for row, item in zip(self.rows, read, strict=True):
            row.show_item(item)
        self.install_button.setText(_PRIMARY_LABELS[summary(read)])
        self.install_button.setEnabled(True)
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
            self.install_button.setEnabled(False)
            self.remove_button.setEnabled(False)
            self.status.say(f"{label}…", "busy")

    def _finished(self, outcomes: list[Outcome]) -> None:
        self.output.setPlainText(report_lines(outcomes))
        if all(outcome.ok for outcome in outcomes):
            self.status.say("Done", "ok")
        else:
            self.status.say("Something failed — the pane below says what", "error")
        self._refresh()

    def _failed(self, error: str) -> None:
        self.output.setPlainText(error)
        self.status.say(error, "error")
        self._refresh()
