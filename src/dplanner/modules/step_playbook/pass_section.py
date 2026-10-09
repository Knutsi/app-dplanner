"""The Playbook tab of Step Details: what the step's passes did, what they changed, and what
the person reviewing them does next.

It answers "how would I review it?" for a pass that ends with nothing but a phrase on the
card. Three blocks, over one reading:

- **Outcome** — every pass as a folding group of a table (the latest open, earlier ones
  folded), one row per record ``history.py`` reads: the work with the summary it gave, each
  review with its verdict and a row per finding (the implementer's reason beside a finding it
  declined), each answer to a gate. The well under it shows the picked row whole — the
  latest work summary until something else is picked.
- **What changed** — the latest run's worktree, its branch against its base, the commits and
  the diff stat (``changes.py``), the PR where one is recorded; *Open Diff* and *Open
  Worktree in Terminal* open a terminal there. No commits says so, and points at the summary.
- **Verbs** — *Accept* and *Send Back* mean what ``passes.choices`` says for the pass now:
  the open gate answered *Pass* or *Changes*, or for a pass that is through, the step done (a
  person's decision, one undo step) or another round with the note as its finding. Each is
  greyed with its reason. *Follow* and *Open Session* act on the picked row's run.

Reading is records and git, so it runs on a task whenever the tab is aimed, the pass's
records move (``PassStandings.changed``) or the step's data does; a read asked for while one
runs is made once it ends.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.agents import AgentHarness
from dplanner.domain.model import Library, Step, StepId
from dplanner.framework.markdown_view import MarkdownView
from dplanner.framework.signalling import StatusLine, Tone
from dplanner.framework.table import Cell, Column, Table
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.widgets import EmptyState, caption, note, quiet, well
from dplanner.modules.github import aspect as github
from dplanner.modules.github.aspect import GithubRefs
from dplanner.modules.step_playbook import changes
from dplanner.modules.step_playbook.changes import Work
from dplanner.modules.step_playbook.engine import facts_of
from dplanner.modules.step_playbook.history import (
    ANSWER,
    REVIEW,
    WORK,
    Event,
    Finding,
    PassHistory,
    history,
)
from dplanner.modules.step_playbook.passes import FIX, LOOK, Facts
from dplanner.modules.step_playbook.workflows import ACCEPTED, acceptance
from dplanner.theme.tokens import CAPTION_GAP, FIELD_GAP, PANEL_MARGIN, SECTION_GAP

NO_PASS = "This step has no playbook pass yet — Step ▸ Run Playbook starts one."
NO_SUMMARY = "No summary recorded."
FOCUS_KIND = "playbook"
# The card strip's tones, in the status line's words.
TONES: dict[str, Tone] = {"": "info", "busy": "busy", "warn": "warn", "good": "ok", "bad": "error"}
COLUMNS = (
    Column("What", detail=True, resize="stretch"),
    Column("Who"),
    Column("Stands"),
    Column("When"),
)
NOTE_LINES = 3


class RunVerbs(Protocol):
    """*Follow* and *Open Session* on one run, by its id — the Agents browser's verbs."""

    def run_refusals(self, project_dir: Path, run: str) -> tuple[str, str]:
        """Why it cannot be followed, and why its session cannot be opened; "" where it can."""
        ...

    def follow_by_id(self, project_dir: Path, run: str) -> None: ...

    def open_session_by_id(self, project_dir: Path, run: str) -> None: ...


class PassVerbs(Protocol):
    """The pass's verbs a ``dplanner`` process runs — the launch module's, as Stop is."""

    def accept_playbook(self, step: Step) -> None:
        """The pass's open gate answered *Pass*."""
        ...

    def send_back(self, step: Step, note: str) -> None: ...


# Open a terminal in a directory on a command (title, project id); told why none opened.
type OpenTerminal = Callable[[Path, str, Sequence[str], str, Callable[[str], None]], None]


@dataclass(frozen=True)
class _Reading:
    step_id: StepId
    passes: tuple[PassHistory, ...]
    work: Work
    difftool: bool


@dataclass(frozen=True)
class _Row:
    """What a row of the outcome table stands for: its words in the well, and its run."""

    text: str
    run: str = ""


class PassSection(QWidget):
    def __init__(
        self,
        library: Library,
        *,
        project_dir: Callable[[StepId], Path],
        harnesses: tuple[AgentHarness, ...],
        runs: RunVerbs,
        verbs: PassVerbs,
        open_terminal: OpenTerminal,
        accept: Callable[[Step, str, str], str],
        tasks: TaskService | None,
        changed: Callable[[Callable[[str], None]], Callable[[], None]],
    ) -> None:
        super().__init__()
        self._library = library
        self._project_dir = project_dir
        self._harnesses = harnesses
        self._runs = runs
        self._verbs = verbs
        self._open_terminal = open_terminal
        self._accept = accept
        self._runner = TaskRunner(tasks, self) if tasks is not None else None
        self._step_id: StepId | None = None
        self._reading: _Reading | None = None
        self._result: list[_Reading] = []
        self._again = False
        self._rows: list[_Row] = []
        self._seen_passes: set[str] = set()

        self.head = StatusLine(self)
        self.said = StatusLine(self)
        self.accept_button = quiet(QPushButton("Accept", self))
        self.accept_button.clicked.connect(self._on_accept)
        self.send_back_button = quiet(QPushButton("Send Back", self))
        self.send_back_button.clicked.connect(self._on_send_back)
        self.note_edit = QPlainTextEdit(self)
        self.note_edit.setPlaceholderText("What must change — the note the work is sent back with")
        self.note_edit.setFixedHeight(self.note_edit.fontMetrics().height() * NOTE_LINES + 12)
        self.note_edit.textChanged.connect(self._show_verbs)

        self.table = Table(COLUMNS, parent=self)
        self.table.currentCellChanged.connect(lambda *_cells: self._show_picked())
        self.detail = MarkdownView(self)
        well(self.detail)
        self.follow_button = quiet(QPushButton("Follow", self))
        self.follow_button.clicked.connect(lambda: self._on_run(self._runs.follow_by_id))
        self.open_session_button = quiet(QPushButton("Open Session", self))
        self.open_session_button.clicked.connect(
            lambda: self._on_run(self._runs.open_session_by_id)
        )

        self.where = note("", self)
        self.commits = note("", self)
        self.open_pr_button = quiet(QPushButton("Open PR", self))
        self.open_pr_button.clicked.connect(self._on_open_pr)
        self.open_diff_button = quiet(QPushButton("Open Diff", self))
        self.open_diff_button.clicked.connect(self._on_open_diff)
        self.open_worktree_button = quiet(QPushButton("Open Worktree in Terminal", self))
        self.open_worktree_button.clicked.connect(self._on_open_worktree)

        self.content = QWidget(self)
        self.empty = EmptyState(NO_PASS, self, stands_in_for=self.content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        outer.addWidget(self.content, 1)
        outer.addWidget(self.empty, 1)

        column = QVBoxLayout(self.content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(SECTION_GAP)
        column.addWidget(self.head)
        _row(column, self.accept_button, self.send_back_button).addStretch(1)
        column.addWidget(self.note_edit)
        column.addWidget(self.said)

        outcome = QVBoxLayout()
        column.addLayout(outcome, 1)
        outcome.setSpacing(CAPTION_GAP)
        outcome.addWidget(caption("Outcome", self))
        outcome.addWidget(self.table, 2)
        outcome.addWidget(self.detail, 1)
        _row(outcome, self.follow_button, self.open_session_button).addStretch(1)

        changed_block = QVBoxLayout()
        column.addLayout(changed_block)
        changed_block.setSpacing(CAPTION_GAP)
        changed_block.addWidget(caption("What changed", self))
        changed_block.addWidget(self.where)
        changed_block.addWidget(self.commits)
        _row(
            changed_block, self.open_diff_button, self.open_worktree_button, self.open_pr_button
        ).addStretch(1)

        self._unsubscribe = changed(self._on_records)
        self.empty.say(NO_PASS)

    # -- InspectorExtension ---------------------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def show_target(self, target_id: str | None) -> None:
        if target_id != self._step_id:
            self.note_edit.clear()
            self.said.clear()
        self._step_id = target_id if target_id and self._library.has(target_id) else None
        self.refresh()

    def focus_entity(self, kind: str, entity_id: str) -> bool:
        """The tab the card's playbook strip opens: it answers for its own step."""
        return kind == FOCUS_KIND and entity_id == self._step_id

    def dispose(self) -> None:
        self._unsubscribe()

    # -- reading -----------------------------------------------------------------------------

    def refresh(self) -> None:
        """Read the shown step's passes and work again — on the task, or once it ends."""
        if self._step_id is None:
            self._apply(None)
            return
        step = self._library.step(self._step_id)
        # What the plan says of the step is read here, where the model may be; the worker
        # reads files and git with plain data alone.
        step_id, facts, refs = step.id, facts_of(step), github.read(step)
        project_dir, harnesses = self._project_dir(step.id), self._harnesses

        def body() -> None:
            self._result.append(_read(step_id, facts, refs, project_dir, harnesses))

        if self._runner is None:
            body()
            self._delivered()
            return
        if self._runner.is_busy():
            self._again = True
            return
        if self._runner.run("Reading the step's playbook passes", body):
            self._runner.busy_changed.connect(self._finished)

    def _finished(self, busy: bool) -> None:
        if busy or self._runner is None:
            return
        self._runner.busy_changed.disconnect(self._finished)
        self._delivered()
        if self._again:
            self._again = False
            self.refresh()

    def _delivered(self) -> None:
        reading = self._result.pop() if self._result else None
        self._result.clear()
        if reading is not None and reading.step_id == self._step_id:
            self._apply(reading)

    def _on_records(self, project_id: str) -> None:
        step = self._step()
        if step is not None and self._library.project_of(step.id).id == project_id:
            self.refresh()

    # -- showing -----------------------------------------------------------------------------

    def _apply(self, reading: _Reading | None) -> None:
        self._reading = reading
        latest = reading.passes[0] if reading is not None and reading.passes else None
        self.empty.say("" if latest is not None else NO_PASS)
        if reading is None or latest is None:
            return
        stands = latest.standing
        self.head.say(
            f"{stands.phrase or 'No pass under way'} · {latest.playbook} · pass {latest.pass_id}",
            TONES.get(stands.tone, "info"),
        )
        self._fill_table(reading.passes)
        self._show_work(reading.work)
        self._show_verbs()

    def _fill_table(self, passes: tuple[PassHistory, ...]) -> None:
        table = self.table
        table.clear_rows()
        self._rows = []
        latest_work = -1
        for index, each in enumerate(passes):
            if each.pass_id not in self._seen_passes:
                # A pass met for the first time opens if it is the latest, else folds.
                self._seen_passes.add(each.pass_id)
                table.set_collapsed(each.pass_id, index > 0)
            table.add_heading(
                f"Pass {each.pass_id} · {each.playbook} · {each.standing.phrase}",
                key=each.pass_id,
            )
            self._rows.append(_Row(""))
            for event in each.events:
                row = self._add_event(event)
                if index == 0 and event.kind == WORK:
                    latest_work = row
                for finding in event.findings:
                    self._add_finding(finding, event.run)
        table.fit_columns()
        if latest_work >= 0:
            table.setCurrentCell(latest_work, 0)
        else:
            self.detail.show_markdown(passes[0].summary or NO_SUMMARY)
        self._show_run_verbs()

    def _add_event(self, event: Event) -> int:
        what, detail, text = _event_words(event)
        self._rows.append(_Row(text, event.run))
        return self.table.add_row(
            [Cell(what, detail=detail), event.who, event.state, _when(event.at)]
        )

    def _add_finding(self, finding: Finding, run: str) -> None:
        where = f"{finding.where} — " if finding.where else ""
        declined = f"declined: {finding.declined}" if finding.declined else ""
        self._rows.append(_Row(_finding_text(finding), run))
        self.table.add_row(
            [
                Cell(f"↳ {finding.text}", detail=f"{where}{finding.evidence}".strip(" —")),
                finding.severity or "note",
                Cell("declined" if finding.declined else "", tooltip=declined),
                "",
            ]
        )

    def _show_picked(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self._rows) and self._rows[row].text:
            self.detail.show_markdown(self._rows[row].text)
        self._show_run_verbs()

    def _picked_run(self) -> str:
        row = self.table.currentRow()
        if 0 <= row < len(self._rows) and self._rows[row].run:
            return self._rows[row].run
        latest = self._latest()
        return latest.runs[-1].run if latest is not None and latest.runs else ""

    def _show_run_verbs(self) -> None:
        run = self._picked_run()
        if not run or self._step_id is None:
            follow = opened = "no run picked"
        else:
            follow, opened = self._runs.run_refusals(self._project_dir(self._step_id), run)
        _verb(self.follow_button, follow, f"Follow run {run} in a terminal, read-only")
        _verb(
            self.open_session_button,
            opened,
            f"Take run {run}'s session in a terminal: the pass ends, taken over by you",
        )

    def _show_work(self, work: Work) -> None:
        if work.refusal:
            self.where.setText(f"{work.directory or 'No worktree'} — {work.refusal}")
            self.commits.setText("")
        else:
            self.where.setText(
                f"{work.branch} against {work.base} · {work.stat or 'no changes'}\n{work.directory}"
            )
            if work.commits:
                lines = [f"{sha}  {subject}" for sha, subject in work.commits]
                lines += [f"… and {work.more} more"] if work.more else []
                self.commits.setText("\n".join(lines))
            else:
                self.commits.setText(
                    f"No commits on {work.branch} since {work.base} — the work is in the"
                    " summary above."
                )
        self.open_pr_button.setVisible(bool(work.pr_url))
        self.open_pr_button.setText(f"Open PR {work.pr_label}" if work.pr_label else "Open PR")
        _verb(self.open_diff_button, "" if work.compared else work.refusal or "nothing to compare")
        worktree = "" if work.directory and Path(work.directory).is_dir() else "no worktree here"
        _verb(self.open_worktree_button, worktree if not work.refusal else work.refusal)

    def _show_verbs(self) -> None:
        latest = self._latest()
        if latest is None:
            return
        chosen = latest.choices
        gate = chosen.gate
        self.accept_button.setText("Pass" if gate is not None else "Accept")
        _verb(
            self.accept_button,
            chosen.accept,
            f"Answer {gate.short} Pass: the playbook goes on"
            if gate is not None
            else "Set the step done: you looked at the work, and it stands",
        )
        why = chosen.send_back or (
            "" if self.note_edit.toPlainText().strip() else "write what must change first"
        )
        _verb(
            self.send_back_button,
            why,
            f"Answer {gate.short} with the note: the work goes back for another round"
            if gate is not None
            else "Another round of the work, with the note as its finding — the round cap holds",
        )
        self.note_edit.setEnabled(not chosen.send_back)

    def _latest(self) -> PassHistory | None:
        reading = self._reading
        return reading.passes[0] if reading is not None and reading.passes else None

    # -- verbs -------------------------------------------------------------------------------

    def _step(self) -> Step | None:
        if self._step_id is None or not self._library.has(self._step_id):
            return None
        return self._library.step(self._step_id)

    def _on_accept(self) -> None:
        step, latest = self._step(), self._latest()
        if step is None or latest is None or latest.choices.accept:
            return
        if latest.choices.gate is not None:
            self._verbs.accept_playbook(step)
            self.said.say(f"Answering {latest.choices.gate.short} Pass…", "busy")
            return
        why = self._accept(step, acceptance(latest.pass_id, latest.playbook), ACCEPTED)
        self.said.say(why or "Accepted — the step is done", "error" if why else "ok")
        self.refresh()

    def _on_send_back(self) -> None:
        step, latest = self._step(), self._latest()
        words = self.note_edit.toPlainText().strip()
        if step is None or latest is None or latest.choices.send_back or not words:
            return
        self._verbs.send_back(step, words)
        self.note_edit.clear()
        self.said.say("Sending the work back…", "busy")

    def _on_run(self, act: Callable[[Path, str], None]) -> None:
        run = self._picked_run()
        if run and self._step_id is not None:
            act(self._project_dir(self._step_id), run)

    def _on_open_pr(self) -> None:
        if self._reading is not None and self._reading.work.pr_url:
            QDesktopServices.openUrl(QUrl(self._reading.work.pr_url))

    def _on_open_diff(self) -> None:
        reading = self._reading
        if reading is not None and reading.work.compared:
            argv = changes.diff_argv(reading.work, reading.difftool)
            self._terminal(reading.work.directory, f"Diff {reading.work.branch}", argv)

    def _on_open_worktree(self) -> None:
        reading = self._reading
        if reading is not None and reading.work.directory:
            self._terminal(reading.work.directory, f"Worktree {reading.work.branch}", ())

    def _terminal(self, directory: str, title: str, argv: Sequence[str]) -> None:
        step = self._step()
        if step is None:
            return
        project = self._library.project_of(step.id).id

        def opened(why: str) -> None:
            self.said.say(
                f"No terminal opened — {why}" if why else f"{title} opened",
                "error" if why else "ok",
            )

        self._open_terminal(Path(directory), title, argv, project, opened)


def _read(
    step_id: StepId,
    facts: Facts,
    refs: GithubRefs | None,
    project_dir: Path,
    harnesses: tuple[AgentHarness, ...],
) -> _Reading:
    """Every pass of the step, and what its latest worked run changed — off the GUI thread."""
    passes = history(project_dir, step_id, facts, datetime.now(UTC), harnesses)
    runs = [run for run in passes[0].runs if run.directory] if passes else []
    work = changes.read_work(runs[-1] if runs else None, refs)
    difftool = work.compared and changes.has_difftool(Path(work.directory))
    return _Reading(step_id, passes, work, difftool)


def _row(layout: QVBoxLayout, *buttons: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    layout.addLayout(row)
    row.setSpacing(FIELD_GAP)
    for button in buttons:
        row.addWidget(button)
    return row


def _verb(button: QPushButton, why: str, tip: str = "") -> None:
    """Enabled, or greyed with its reason as the tooltip."""
    button.setEnabled(not why)
    button.setToolTip(f"Not now: {why}" if why else tip)


def _stage(stage: str, attempt: int) -> str:
    named = {FIX: "Fix", LOOK: "Your look"}.get(stage) or stage.replace("-", " ").capitalize()
    return f"{named} · attempt {attempt}" if attempt > 1 else named


def _event_words(event: Event) -> tuple[str, str, str]:
    """(the row's first line, its second, the well's words) for one record."""
    title = _stage(event.stage, event.attempt)
    if event.kind == WORK:
        first = event.summary.strip().splitlines()[0] if event.summary.strip() else NO_SUMMARY
        return title, first, f"### {title}\n\n{event.summary or NO_SUMMARY}"
    if event.kind == REVIEW:
        verdict = event.outcome or "no verdict"
        lines = [f"### {title} — {verdict}", "", event.summary or ""]
        lines += [f"- {_finding_text(f)}" for f in event.findings]
        return f"{title} — {verdict}", event.summary, "\n".join(lines)
    assert event.kind == ANSWER
    said = event.outcome or "not answered yet"
    text = f"### {event.question} · {title}\n\n{event.summary}\n\n**{said}**"
    return f"{event.question} — {said}", event.summary, text


def _finding_text(finding: Finding) -> str:
    parts = [f"**{finding.severity or 'note'}** {finding.text}"]
    if finding.where:
        parts.append(f"`{finding.where}`")
    if finding.evidence:
        parts.append(f"— {finding.evidence}")
    if finding.declined:
        parts.append(f"\n\n  *Declined:* {finding.declined}")
    return " ".join(parts)


def _when(stamp: str) -> str:
    try:
        moment = datetime.fromisoformat(stamp).astimezone()
    except ValueError:
        return ""
    return f"{moment.day} {moment:%b %H:%M}"
