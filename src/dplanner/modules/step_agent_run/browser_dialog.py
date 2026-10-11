"""The Agents browser, and the words the status-bar button wears (``button_text``).

Pure widgets, on the task centre's pattern: the module feeds them the run list and the
callbacks; they only render. The browser is a ``DialogFrame`` over a ``RowWell``, rows kept by
run across every tick. A live row offers *Show Terminal* and *Reveal* — the first greyed per
run with the reason when that run's terminal cannot be raised; an ended row keeps its outcome
until dismissed, with what the run consumed on its status line once the harness's record was
read, and the command that picks the agent up again as a note under it.

**A headless run is a row too** (``headless.py``) — a playbook's stage, an ``agent run
--headless`` — with *Follow*, *Open Session* and *Reveal*: what it is doing in the card's own
words, who runs it, when it last said anything and what it has consumed. *Follow* opens a
terminal tailing its turns; *Open Session* takes its session into one, greyed with the reason
while a turn runs. It is never dismissed: it leaves the list a day after it ends, or at *Clear
ended*.

**The list is what is happening now, newest first.** The runs still going are on top, in the
order a person would look for them — the one just launched at the eye's first stop — and the
ones that are over are not listed at all until *Show ended* asks for them, under the live
ones. A browser that kept every run this machine ever launched made the live ones something
to scroll for, and a clear that has to be remembered is a list that is never clean; this way
the default list empties itself. Each group is ordered by the very stamp its rows print,
so the times read down the list.

**Clearing is offered where the rows are.** *Clear ended* comes up with *Show ended* and is
greyed without it: a verb that deletes what the list is not showing acts blind.

The status line's tone is the run's mood: busy while it runs, ok once it finished, the error
tone when it failed or was lost, plain when its terminal was closed. Every edit here is live,
so the footer is Close and nothing wears the accent.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from PySide6.QtWidgets import QCheckBox, QWidget

from dplanner.framework.dialog import DialogFrame
from dplanner.framework.row_well import RowWell, WellRow
from dplanner.framework.signalling import Tone
from dplanner.framework.widgets import EmptyState
from dplanner.modules.agent_usage.aspect import brief_words, words
from dplanner.modules.step_agent_run.headless import HeadlessRun, ago
from dplanner.modules.step_agent_run.runs import CLOSED, AgentRun, describe

BROWSER_SIZE = (560, 400)
NO_RUNS = "No agent has been launched from this window, and none runs headless."
SHOW_ENDED = "Show ended"
SHOW_ENDED_TIP = "List the runs that are over, under the ones still running"
# An ended run's mood by its outcome; a run whose directory is gone is lost, which is an error.
ENDED_TONES: dict[str, Tone] = {"finished": "ok", "failed": "error", CLOSED: "info"}
# The card's tones (``passes.Standing.tone``) in the status line's: a headless row says its
# run in the strip's own words, so it wears the strip's own mood.
STRIP_TONES: dict[str, Tone] = {
    "": "info",
    "busy": "busy",
    "warn": "warn",
    "good": "ok",
    "bad": "error",
}
FOLLOW_TIP = "Watch the run's turns in a terminal as they stream — read-only"
OPEN_SESSION_TIP = (
    "Take the agent's session into a terminal of your own; the run stops being the playbook's"
)
type Listed = AgentRun | HeadlessRun


def _clock(stamp: str) -> str:
    """An ISO stamp as the local wall-clock time, or "" for a stamp this build cannot read."""
    try:
        return datetime.fromisoformat(stamp).astimezone().strftime("%H:%M")
    except ValueError:
        return ""


def listed(runs: Sequence[Listed], show_ended: bool) -> list[Listed]:
    """What the browser lists, top to bottom: the live runs newest first, then the ended
    ones — only where they were asked for — newest first under them. Terminal and headless
    runs are one list: what matters is what is happening, not how it was launched.

    Each group is sorted on the stamp its own rows show, ``since`` for a live run and ``at``
    for one that is over, so a reader going down the list is going back in time.
    """
    live = sorted((run for run in runs if run.live), key=lambda run: run.launched, reverse=True)
    if not show_ended:
        return live
    over = sorted((run for run in runs if not run.live), key=lambda run: run.ended, reverse=True)
    return [*live, *over]


def empty_words(live: int, ended: int, show_ended: bool) -> str:
    """What stands where the well would be when it lists nothing: this window has launched
    no agent, or none is running and the ended ones were not asked for — an empty state per
    filter, naming the switch that has the rest."""
    if live or (show_ended and ended):
        return ""
    if not ended:
        return NO_RUNS
    which = "the run that ended" if ended == 1 else f"the {ended} that ended"
    return f"No agent is running — tick {SHOW_ENDED} for {which}."


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


def button_text(
    runs: list[AgentRun], title_of: Callable[[str], str], headless: Sequence[HeadlessRun] = ()
) -> str:
    """The status-bar words: one live run by name, else a count, else the last outcome, else
    nothing. A headless run counts as running while it is not over — parked included, since
    it is still somebody's to answer."""
    live = [run.step_id for run in runs if run.live] + [run.step for run in headless if run.live]
    if len(live) == 1:
        return f"Agent on “{title_of(live[0])}”"
    if live:
        return f"{len(live)} agents running"
    if len(runs) == 1:
        return f"Agent on “{title_of(runs[0].step_id)}” — {describe(runs[0], '')}"
    return f"{len(runs)} agent runs ended" if runs else ""


def headless_words(run: HeadlessRun, phrase: str, harness: str, now: datetime) -> str:
    """A headless row's status line: where it stands — the card's own phrase for its pass's
    latest run — then who runs it, when it last said anything and what it has consumed."""
    lead = phrase if run.latest_of_pass and phrase else run.state
    parts = [lead, run.callsign, harness, ago(run.activity, now)]
    if run.tokens.input or run.tokens.output:
        parts.append(words(run.tokens))
    return " · ".join(part for part in parts if part)


def stage_label(stage: str) -> str:
    """A stage id as a person reads it: ``review-2`` is *Review 2*."""
    return stage.replace("-", " ").capitalize()


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


class HeadlessRow(WellRow):
    """One headless run: the step and its stage, where it stands, and the ways to look at it."""

    def __init__(
        self,
        run: HeadlessRun,
        follow: Callable[[HeadlessRun], None],
        open_session: Callable[[HeadlessRun], None],
        reveal: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.run = run
        self.follow_button = self.add_button("Follow", lambda: follow(self.run))
        self.open_button = self.add_button("Open Session", lambda: open_session(self.run))
        self.reveal_button = self.add_button(
            "Reveal", lambda: reveal(self.run.step), tip="Select the step in its project"
        )

    def refresh(self, run: HeadlessRun, title: str, phrase: str, harness: str) -> None:
        self.run = run
        stage = stage_label(run.stage)
        self.title.setText(f"{title} · {stage}" if stage else title)
        tone = STRIP_TONES.get(run.tone, "info")
        self.status.say(headless_words(run, phrase, harness, datetime.now(UTC)), tone)
        self.follow_button.setEnabled(not run.follow_refusal)
        self.follow_button.setToolTip(
            f"Follow — {run.follow_refusal}" if run.follow_refusal else FOLLOW_TIP
        )
        self.open_button.setEnabled(not run.open_refusal)
        self.open_button.setToolTip(
            f"Open Session — {run.open_refusal}" if run.open_refusal else OPEN_SESSION_TIP
        )


class AgentBrowserDialog(DialogFrame):
    """The live runs as rows kept by run, newest first, and the ended ones under them
    where *Show ended* asks for them."""

    def __init__(
        self,
        parent: QWidget | None,
        title_of: Callable[[str], str],
        state_of: Callable[[str], str],
        show_terminal: Callable[[AgentRun], None],
        reveal: Callable[[AgentRun], None],
        forget: Callable[[AgentRun], None],
        clear_ended: Callable[[], None],
        relist: Callable[[], None],
        follow: Callable[[HeadlessRun], None] = lambda _run: None,
        open_session: Callable[[HeadlessRun], None] = lambda _run: None,
        reveal_step: Callable[[str], None] = lambda _step: None,
    ) -> None:
        super().__init__("Agents", parent, size=BROWSER_SIZE)
        self.setObjectName("AgentBrowserDialog")
        self._title_of = title_of
        self._state_of = state_of
        self._show_terminal = show_terminal
        self._reveal = reveal
        self._forget = forget
        self._follow = follow
        self._open_session = open_session
        self._reveal_step = reveal_step
        # The switch stands over the list, and stays there while the empty state has the
        # well's place: what it says is how a person gets the rest of the runs back.
        self.show_ended = QCheckBox(SHOW_ENDED, self.body)
        self.show_ended.setToolTip(SHOW_ENDED_TIP)
        self.show_ended.toggled.connect(lambda _on: relist())
        self.body_layout.addWidget(self.show_ended)
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

    def headless_row(self, run: str) -> HeadlessRow | None:
        """The row of the headless run ``run``."""
        found = self.well.row(f"run:{run}")
        return found if isinstance(found, HeadlessRow) else None

    def refresh(
        self,
        runs: list[AgentRun],
        reason_of: Callable[[AgentRun], str],
        resume_of: Callable[[AgentRun], str],
        usage_of: Callable[[AgentRun], str] = lambda _run: "",
        headless: Sequence[HeadlessRun] = (),
        phrase_of: Callable[[HeadlessRun], str] = lambda _run: "",
        harness_label: Callable[[str], str] = lambda harness: harness,
    ) -> None:
        showing_ended = self.show_ended.isChecked()
        everything: list[Listed] = [*runs, *headless]
        by_key = {run.key: run for run in listed(everything, showing_ended)}

        def build(key: str) -> WellRow:
            run = by_key[key]
            if isinstance(run, HeadlessRun):
                return HeadlessRow(run, self._follow, self._open_session, self._reveal_step)
            return AgentRow(
                run, self._title_of, self._state_of, self._show_terminal, self._reveal, self._forget
            )

        def update(key: str, row: WellRow) -> None:
            run = by_key[key]
            if isinstance(run, HeadlessRun) and isinstance(row, HeadlessRow):
                row.refresh(
                    run, self._title_of(run.step), phrase_of(run), harness_label(run.harness)
                )
            elif isinstance(run, AgentRun) and isinstance(row, AgentRow):
                row.refresh(run, reason_of(run), resume_of(run), usage_of(run))

        self.well.reconcile(list(by_key), build, update)
        live = sum(1 for run in everything if run.live)
        ended = len(everything) - live
        # The counts are of everything known, listed or not: an ended run the switch is keeping
        # off screen is still a run, and the footer is where it is said.
        parts = ([f"{live} running"] if live else []) + ([f"{ended} ended"] if ended else [])
        self.status.say(" · ".join(parts))
        self.empty.say(empty_words(live, ended, showing_ended))
        self.clear_button.setEnabled(ended > 0 and showing_ended)
        self.clear_button.setToolTip(
            "" if showing_ended else f"Tick {SHOW_ENDED} to clear the runs that are over"
        )
