"""Agent-run widgets: the status-bar words and the Agents browser.

Pure widgets, on the task centre's pattern: the module feeds them the run list and the
callbacks; they only render. The browser is a ``DialogFrame`` over a ``RowWell``, rows kept by
run across every tick. A live row offers *Show Terminal* and *Reveal* — the first greyed per
run with the reason when that run's terminal cannot be raised; an ended row keeps its outcome
until dismissed, with what the run consumed on its status line once the harness's record was
read, and the command that picks the agent up again as a note under it.

The status line's tone is the run's mood: busy while it runs, ok once it finished, the error
tone when it failed or was lost, plain when its terminal was closed. Every edit here is live,
so the footer is Close and nothing wears the accent.
"""

from collections.abc import Callable
from datetime import datetime

from PySide6.QtWidgets import QWidget

from dplanner.framework.dialog import DialogFrame
from dplanner.framework.row_well import RowWell, WellRow
from dplanner.framework.signalling import Tone
from dplanner.framework.widgets import EmptyState
from dplanner.modules.step_agent_run.runs import CLOSED, AgentRun, describe
from dplanner.modules.step_agent_run.usage import brief_words

BROWSER_SIZE = (560, 400)
NO_RUNS = "No agent has been launched from this window."
# An ended run's mood by its outcome; a run whose directory is gone is lost, which is an error.
ENDED_TONES: dict[str, Tone] = {"finished": "ok", "failed": "error", CLOSED: "info"}


def _clock(stamp: str) -> str:
    """An ISO stamp as the local wall-clock time, or "" for a stamp this build cannot read."""
    try:
        return datetime.fromisoformat(stamp).astimezone().strftime("%H:%M")
    except ValueError:
        return ""


def status_of(run: AgentRun, state: str) -> tuple[str, Tone]:
    """The row's status line and its tone: what the run is doing, when it began (or ended),
    and what it was handed. The size comes off the run, so a live one says it too — the
    tokens beside it cannot be read back until the shell ends."""
    phrase = describe(run, state)
    when = _clock(run.ended if run.ended else run.launched)
    if when:
        phrase = f"{phrase} · {'since' if run.live else 'at'} {when}"
    briefed = brief_words(run.prompt_chars)
    words = f"{phrase} · {briefed}" if briefed else phrase
    return words, "busy" if run.live else ENDED_TONES.get(run.outcome, "error")


def button_text(runs: list[AgentRun], title_of: Callable[[str], str]) -> str:
    """The status-bar words: one live run by name, else a count, else the last outcome, else
    nothing."""
    live = [run for run in runs if run.live]
    if len(live) == 1:
        return f"Agent on “{title_of(live[0].step_id)}”"
    if live:
        return f"{len(live)} agents running"
    if len(runs) == 1:
        return f"Agent on “{title_of(runs[0].step_id)}” — {describe(runs[0], '')}"
    return f"{len(runs)} agent runs ended" if runs else ""


class AgentRow(WellRow):
    """One run: the step's title with its verbs, its status line, and how to pick it up."""

    def __init__(
        self,
        run: AgentRun,
        title_of: Callable[[str], str],
        state_of: Callable[[str], str],
        show_terminal: Callable[[AgentRun], None],
        reveal: Callable[[AgentRun], None],
        forget: Callable[[AgentRun], None],
    ) -> None:
        super().__init__()
        self.run = run
        self._title_of = title_of
        self._state_of = state_of
        self.terminal_button = self.add_button("Show Terminal", lambda: show_terminal(self.run))
        self.reveal_button = self.add_button(
            "Reveal", lambda: reveal(self.run), tip="Select the step in its project"
        )
        self.add_dismiss(
            lambda: forget(self.run), tip="Stop tracking this run (the terminal is left alone)"
        )
        self.refresh(run, "")

    def refresh(self, run: AgentRun, focus_reason: str, resume: str = "", usage: str = "") -> None:
        self.run = run
        self.title.setText(self._title_of(run.step_id))
        words, tone = status_of(run, self._state_of(run.step_id))
        self.status.say(f"{words} · {usage}" if usage else words, tone)
        self.terminal_button.setVisible(run.live)
        self.terminal_button.setEnabled(not focus_reason)
        self.terminal_button.setToolTip(focus_reason or "Bring the agent's terminal to the front")
        # An ended run's way back, selectable so it can be pasted into a terminal.
        self.set_note(f"Pick it up again: {resume}" if resume and not run.live else "")


class AgentBrowserDialog(DialogFrame):
    """Live and ended runs as rows kept by run."""

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
        super().__init__("Agents", parent, size=BROWSER_SIZE)
        self.setObjectName("AgentBrowserDialog")
        self._title_of = title_of
        self._state_of = state_of
        self._show_terminal = show_terminal
        self._reveal = reveal
        self._forget = forget
        self.well = RowWell(self.body)
        self.body_layout.addWidget(self.well, 1)
        self.empty = EmptyState(NO_RUNS, self.body, stands_in_for=self.well)
        self.body_layout.addWidget(self.empty, 1)
        self.clear_button = self.add_button("Clear ended", clear_ended)
        self.clear_button.setEnabled(False)  # Disabled, never hidden: nothing has ended.
        self.close_button = self.add_dismiss("Close")

    def rows(self) -> list[AgentRow]:
        """The listed runs' rows, top to bottom."""
        return [row for row in self.well.rows() if isinstance(row, AgentRow)]

    def row(self, key: str) -> AgentRow | None:
        """The row of the run whose directory is ``key``."""
        found = self.well.row(key)
        return found if isinstance(found, AgentRow) else None

    def refresh(
        self,
        runs: list[AgentRun],
        reason_of: Callable[[AgentRun], str],
        resume_of: Callable[[AgentRun], str],
        usage_of: Callable[[AgentRun], str] = lambda _run: "",
    ) -> None:
        by_key = {run.key: run for run in runs}

        def build(key: str) -> AgentRow:
            return AgentRow(
                by_key[key],
                self._title_of,
                self._state_of,
                self._show_terminal,
                self._reveal,
                self._forget,
            )

        def update(key: str, row: AgentRow) -> None:
            run = by_key[key]
            row.refresh(run, reason_of(run), resume_of(run), usage_of(run))

        self.well.reconcile(list(by_key), build, update)
        live = sum(1 for run in runs if run.live)
        ended = len(runs) - live
        parts = ([f"{live} running"] if live else []) + ([f"{ended} ended"] if ended else [])
        self.status.say(" · ".join(parts))
        self.empty.say("" if runs else NO_RUNS)
        self.clear_button.setEnabled(ended > 0)
