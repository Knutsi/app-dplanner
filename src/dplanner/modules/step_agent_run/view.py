"""Agent-run widgets: the status-bar button and the Agents browser.

Pure widgets, on the task centre's pattern: the module feeds them the run list and the
callbacks; they only render. Browser rows are persistent widgets keyed by run and
reconciled on refresh, so a row survives a tick with its buttons' state intact. A live
row offers *Show Terminal* and *Reveal* — greyed per run with the reason when that run's
terminal cannot be raised; an ended row keeps its outcome until dismissed, with the
command that picks the agent up again under it when the wrapper recorded one.

Presentation follows DESIGN.md: the step's title on the primary line, the state or outcome
and the launch time on a secondary line, rows in a framed scrolling well, quiet buttons —
nothing here is the action the user came to perform, so nothing wears the accent.
"""

from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.modules.step_agent_run.runs import AgentRun, describe

LINE_GAP = 8


def _clock(stamp: str) -> str:
    """An ISO stamp as the local wall-clock time, or "" for a stamp this build cannot read."""
    try:
        return datetime.fromisoformat(stamp).astimezone().strftime("%H:%M")
    except ValueError:
        return ""


def status_text(run: AgentRun, state: str) -> str:
    """The row's secondary line: what the run is doing, and when it began (or ended)."""
    phrase = describe(run, state)
    when = _clock(run.ended if run.ended else run.launched)
    if not when:
        return phrase
    return f"{phrase} · {'since' if run.live else 'at'} {when}"


def button_text(runs: list[AgentRun], title_of: Callable[[str], str]) -> str:
    """The status-bar summary: one live run by name, else a count, else the last outcome."""
    live = [run for run in runs if run.live]
    if len(live) == 1:
        return f"Agent on “{title_of(live[0].step_id)}”"
    if live:
        return f"{len(live)} agents running"
    if len(runs) == 1:
        return f"Agent on “{title_of(runs[0].step_id)}” — {describe(runs[0], '')}"
    return f"{len(runs)} agent runs ended"


class AgentStatusButton(QToolButton):
    """Shows live (or lingering ended) runs; clicking opens the browser."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AgentStatusButton")
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Launched agents — click to open")
        self.hide()

    def show_runs(self, runs: list[AgentRun], title_of: Callable[[str], str]) -> None:
        if not runs:
            self.hide()
            return
        self.setText(button_text(runs, title_of))
        self.show()


class AgentRow(QWidget):
    """One run: the step's title with its actions, and a status line under it."""

    def __init__(
        self,
        run: AgentRun,
        title_of: Callable[[str], str],
        state_of: Callable[[str], str],
        show_terminal: Callable[[AgentRun], None],
        reveal: Callable[[AgentRun], None],
        forget: Callable[[AgentRun], None],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.run = run
        self._title_of = title_of
        self._state_of = state_of
        self.setObjectName("AgentRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        title_line = QHBoxLayout()
        title_line.setContentsMargins(0, 0, 0, 0)
        title_line.setSpacing(LINE_GAP)
        self.title = QLabel(self)
        self.title.setWordWrap(True)
        title_line.addWidget(self.title, 1)

        self.terminal_button = QToolButton(self)
        self.terminal_button.setObjectName("AgentRowTerminal")
        self.terminal_button.setText("Show Terminal")
        self.terminal_button.clicked.connect(lambda: show_terminal(self.run))
        title_line.addWidget(self.terminal_button)

        self.reveal_button = QToolButton(self)
        self.reveal_button.setObjectName("AgentRowReveal")
        self.reveal_button.setText("Reveal")
        self.reveal_button.setToolTip("Select the step in its project")
        self.reveal_button.clicked.connect(lambda: reveal(self.run))
        title_line.addWidget(self.reveal_button)

        forget_button = QToolButton(self)
        forget_button.setObjectName("AgentRowForget")
        forget_button.setText("✕")
        forget_button.setAutoRaise(True)
        forget_button.setToolTip("Stop tracking this run (the terminal is left alone)")
        forget_button.clicked.connect(lambda: forget(self.run))
        title_line.addWidget(forget_button)

        self.status = QLabel(self)
        self.status.setObjectName("AgentRowStatus")
        self.status.setWordWrap(True)

        # An ended run's way back: the command that resumes the agent where it stopped,
        # selectable so it can be pasted into a terminal.
        self.resume = QLabel(self)
        self.resume.setObjectName("AgentRowResume")
        self.resume.setWordWrap(True)
        self.resume.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.resume.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)  # Rich-row metrics per DESIGN.md.
        layout.setSpacing(4)
        layout.addLayout(title_line)
        layout.addWidget(self.status)
        layout.addWidget(self.resume)
        self.refresh(run, "")

    def refresh(self, run: AgentRun, focus_reason: str, resume: str = "") -> None:
        self.run = run
        self.title.setText(self._title_of(run.step_id))
        self.status.setText(status_text(run, self._state_of(run.step_id)))
        self.terminal_button.setVisible(run.live)
        self.terminal_button.setEnabled(not focus_reason)
        self.terminal_button.setToolTip(focus_reason or "Bring the agent's terminal to the front")
        self.resume.setText(f"Pick it up again: {resume}" if resume else "")
        self.resume.setVisible(bool(resume) and not run.live)


class AgentBrowserDialog(QDialog):
    """Live and ended runs as persistent rows, reconciled by run."""

    def __init__(
        self,
        parent: QWidget | None,
        title_of: Callable[[str], str],
        state_of: Callable[[str], str],
        show_terminal: Callable[[AgentRun], None],
        reveal: Callable[[AgentRun], None],
        forget: Callable[[AgentRun], None],
        clear_ended: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AgentBrowserDialog")
        self.setWindowTitle("Agents")
        self.setMinimumSize(440, 300)
        self.resize(520, 380)
        self._title_of = title_of
        self._state_of = state_of
        self._show_terminal = show_terminal
        self._reveal = reveal
        self._forget = forget
        self._rows: dict[str, AgentRow] = {}

        self._rows_host = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        self.empty = QLabel("No agent has been launched from this window.")
        self.empty.setObjectName("AgentBrowserEmpty")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rows_layout.addStretch(1)
        self._rows_layout.addWidget(self.empty)
        self._rows_layout.addStretch(1)

        self.well = QScrollArea(self)
        self.well.setObjectName("AgentBrowserWell")
        self.well.setWidgetResizable(True)
        self.well.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.well.setWidget(self._rows_host)
        self._rows_host.setAutoFillBackground(False)

        self.summary = QLabel(self)
        self.summary.setObjectName("AgentBrowserSummary")
        self.clear_button = QPushButton("Clear ended", self)
        self.clear_button.clicked.connect(lambda: clear_ended())
        self.clear_button.hide()
        self.close_button = QPushButton("Close", self)
        self.close_button.clicked.connect(self.reject)
        self.close_button.setDefault(True)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addWidget(self.summary)
        footer.addStretch(1)
        footer.addWidget(self.clear_button)
        footer.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(self.well, 1)
        layout.addLayout(footer)

    def refresh(
        self,
        runs: list[AgentRun],
        reason_of: Callable[[AgentRun], str],
        resume_of: Callable[[AgentRun], str],
    ) -> None:
        wanted = {run.key for run in runs}
        for key, row in list(self._rows.items()):
            if key not in wanted:
                self._rows_layout.removeWidget(row)
                row.hide()
                row.deleteLater()
                del self._rows[key]
        for run in runs:
            existing = self._rows.get(run.key)
            if existing is None:
                existing = AgentRow(
                    run,
                    self._title_of,
                    self._state_of,
                    self._show_terminal,
                    self._reveal,
                    self._forget,
                    self._rows_host,
                )
                self._rows_layout.insertWidget(len(self._rows), existing)
                self._rows[run.key] = existing
            existing.refresh(run, reason_of(run), resume_of(run))
        live = sum(1 for run in runs if run.live)
        ended = len(runs) - live
        parts = ([f"{live} running"] if live else []) + ([f"{ended} ended"] if ended else [])
        self.summary.setText(" · ".join(parts))
        self.empty.setVisible(not runs)
        self.clear_button.setVisible(ended > 0)
