"""What this machine has, in one modal: a status line per check, with its remedy.

DESIGN.md's *A machine without gh* names this surface and its shape — "The Checklist is
where this machine's facts live, one status line each with its remedy" — so a row is a
:class:`StatusLine`, the same one ``modules/sync/save_progress.py`` puts one of per
repository — and **not** a fourth copy of the framed, hairlined well the task browser, the
agent browser and the install dialog each hand-rolled, which DESIGN.md's audit warns
against. Nothing here sets a style name of its own: the frame, the caption and the status
line carry every rule.

**The probes run off the GUI thread**, one ``TaskRunner`` body that walks the checks and
reports each answer as it lands — plain strings and a bool over a Qt signal, because the
worker must never hold the last reference to anything Qt-related. Rows start in the busy
tone saying *checking…* and settle one at a time.

**A remedy that DPlanner can run is a button on its row**, named by the remedy's verb and
running the owning module's own action id through the registry; a remedy nobody can run for
you is the row's words and, in the terminal, the command to type. That is what lets the
install module offer its dialog here without this module importing it.

**One motion, on the primary.** *Re-check* carries a glyph so the ``Spinner`` turns in it
while the probes run; no row has a spinner of its own.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QFontMetrics, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.cli.checklist import (
    Machine,
    MachineCheck,
    Reading,
    command_for,
    ordered,
    summary,
    this_machine,
)
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.signalling import Spinner, StatusLine, Tone
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.widgets import caption, note
from dplanner.theme.cards import detail_font
from dplanner.theme.icons import external_icon, refresh_icon
from dplanner.theme.tokens import FIELD_GAP, ROW_LINE_GAP, SECTION_GAP

# Tall enough that a machine with every row shows them all without scrolling; it is a
# framed dialog, so the screen's 80 % still caps it and the person can drag it smaller.
DIALOG_SIZE = (680, 720)
TASK_KEY = "checklist.probe"
HEADING = "Setup Checklist"
CHECKING = "checking…"
GREETING = "You can open this again from Tools ▸ Setup Checklist."
AT_START = "Open this at start when something required is missing"
MUTE = "Don't warn me about this again"
UNMUTE = "Warn me about this again"
COPY = "Copy the command"
MUTED = "not warning about this"

# The row's mark. A checklist is a list of things that should be true, so it reads as one:
# ticked when it is, an empty box when it is not, and the tone still carries the mood.
TICKED = "\u2611"
UNTICKED = "\u2610"
# The ⋮ that carries a row's own verbs. A character rather than a painted icon, for the
# Project dialog's reason: it names no verb, and every platform's font has it.
ELLIPSIS = "\u22ee"


def tone_for(check: MachineCheck, reading: Reading | None, *, muted: bool = False) -> Tone:
    """The four tones, derived rather than declared: the row has no state of its own.

    Not yet answered is busy — a probe is work with no known end, which is exactly what
    DESIGN.md's busy tone is for. A failing required check is the error tone; a failing
    recommendation is information, because advice shouted in red is not advice. A **muted**
    row is never the error tone whatever it found: muting changes what nags, never what is
    true, and a row nobody asked to be warned about is not a warning.
    """
    if reading is None:
        return "busy"
    if reading.ok:
        return "ok"
    return "info" if muted or not check.required else "error"


@dataclass(frozen=True)
class Preferences:
    """What the *person* has said about the checklist — never what the machine found.

    The module reads and writes these through ``user_config``; the dialog only shows them
    and reports a change. Nothing here reaches a probe, and nothing here reaches the CLI:
    ``dplanner checklist show`` is the machine's truth for an agent, and stays unmuted.
    """

    at_start: bool = True
    muted: frozenset[str] = frozenset()
    on_at_start: Callable[[bool], None] = lambda _on: None
    on_mute: Callable[[str, bool], None] = lambda _check_id, _muted: None


class _Row(QWidget):
    """One check: its status line, the remedy under it, and the verbs the remedy offers.

    Two lines, DESIGN.md's rich row: the *what* on the first, in the tone, with the mark on
    it; the *why* under it in secondary ink a point smaller, and only while there is one.
    **Both elide and neither wraps** — a row that grew taller as the dialog narrowed would
    be a height that depends on a width inside a scroll area, which is how the calendar once
    took the process down (CLAUDE.md's *Checks*). The full words are the tooltip.

    On the right, at most three: the remedy's own button where DPlanner can run the fix, a
    link where somebody else's page is the answer, and a ⋮ carrying what this row can be
    told — the two or three verbs DESIGN.md allows on one thing before they fold.
    """

    def __init__(
        self,
        check: MachineCheck,
        parent: QWidget,
        remedy: Callable[[str], None],
        mute: Callable[[str, bool], None],
        machine: Machine,
    ) -> None:
        super().__init__(parent)
        self.check = check
        self.machine = machine
        self.reading: Reading | None = None
        self.muted = False
        self.said = ""  # The row's full words, before the width cuts them.
        self.why_words = ""
        self._mute = mute
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(FIELD_GAP)
        words = QVBoxLayout()
        layout.addLayout(words, 1)  # Added before it is filled: CLAUDE.md's layout-item rule.
        words.setContentsMargins(0, 0, 0, 0)
        words.setSpacing(ROW_LINE_GAP)
        self.line = StatusLine(self)
        self.line.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        words.addWidget(self.line)
        self.why = QLabel(self)
        self.why.setObjectName("InspectorNote")
        self.why.setFont(detail_font(self.font()))
        # Under the *words* of the line above, not under its mark: the mark is the name's.
        self.why.setIndent(QFontMetrics(self.line.font()).horizontalAdvance(f"{TICKED} "))
        self.why.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.why.hide()
        words.addWidget(self.why)

        remedial = check.remedy
        self.button: QPushButton | None = None
        if remedial is not None and remedial.action:
            self.button = QPushButton(remedial.verb or "Fix…", self)
            self.button.setAutoDefault(False)
            self.button.setToolTip(remedial.words)
            self.button.clicked.connect(lambda: remedy(remedial.action))
            layout.addWidget(_kept(self.button), 0, Qt.AlignmentFlag.AlignTop)

        self.link: QToolButton | None = None
        if remedial is not None and remedial.url:
            self.link = QToolButton(self)
            self.link.setAutoRaise(True)
            self.link.setIcon(external_icon(self.palette().color(self.foregroundRole()).name()))
            self.link.setToolTip(f"Open {remedial.url}")
            self.link.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(remedial.url)))
            layout.addWidget(_kept(self.link), 0, Qt.AlignmentFlag.AlignTop)

        self.menu_button = QToolButton(self)
        self.menu_button.setAutoRaise(True)
        self.menu_button.setText(ELLIPSIS)
        self.menu_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.menu_button.setToolTip(f"What to do about {check.label}")
        self.menu_button.clicked.connect(self.popup)
        layout.addWidget(self.menu_button, 0, Qt.AlignmentFlag.AlignTop)
        self.show_reading(None)

    # -- what it says ------------------------------------------------------------------

    def show_reading(self, reading: Reading | None, *, muted: bool | None = None) -> None:
        """Say where this check stands. ``None`` is "being probed right now"."""
        self.reading = reading
        self.muted = self.muted if muted is None else muted
        detail = CHECKING if reading is None else reading.detail
        self.said = f"{self.check.label} — {detail}" if detail else self.check.label
        self.why_words = self._why_words()
        self.why.setVisible(bool(self.why_words))
        self.setToolTip("\n".join(part for part in (self.said, self.why_words) if part))
        self._elide()

    def _why_words(self) -> str:
        """The second line: what to do about it, and the line to type where there is one."""
        remedial = self.check.remedy
        if self.reading is None or self.reading.ok or remedial is None:
            return MUTED if self.muted and self.reading is not None else ""
        command = command_for(remedial, self.machine)
        parts = [remedial.words, f"`{command}`" if command else ""]
        if self.muted:
            parts.append(f"({MUTED})")
        return "  ".join(part for part in parts if part)

    def offer(self, *, settled: bool) -> None:
        """Show the remedy on a row that needs it — never while a sweep is still running.

        Its room is kept either way, so a fixed row and a failing one are the same shape.
        """
        wanted = settled and self.reading is not None and not self.reading.ok
        if self.button is not None:
            self.button.setVisible(wanted)
        if self.link is not None:
            self.link.setVisible(wanted)

    # -- what it can be told -----------------------------------------------------------

    def entries(self) -> list[tuple[str, Callable[[], None]]]:
        """What the ⋮ would offer right now — asked afresh, and what a test reads."""
        offered: list[tuple[str, Callable[[], None]]] = [
            (UNMUTE if self.muted else MUTE, lambda: self._mute(self.check.id, not self.muted))
        ]
        remedial = self.check.remedy
        command = command_for(remedial, self.machine) if remedial is not None else ""
        if command:
            offered.append((COPY, lambda: _to_clipboard(command)))
        return offered

    def menu(self) -> QMenu:
        """The ⋮ as it stands. Built afresh every time, as every menu here is."""
        menu = QMenu(self)
        for label, run in self.entries():
            menu.addAction(label).triggered.connect(lambda _checked=False, run=run: run())
        return menu

    def popup(self) -> None:
        menu = self.menu()
        menu.exec(self.menu_button.mapToGlobal(self.menu_button.rect().bottomLeft()))

    # -- the width -----------------------------------------------------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        """Re-cut both lines to the width there is. Nothing here changes the row's height."""
        ticked = self.reading is not None and self.reading.ok
        self.line.say(
            _cut(self.said, self.line.font(), self.line.width()),
            tone_for(self.check, self.reading, muted=self.muted),
            glyph=TICKED if ticked else UNTICKED,
        )
        if self.why_words:
            self.why.setText(_cut(self.why_words, self.why.font(), self.why.width()))


def _kept(widget: QWidget) -> QWidget:
    """Keep a widget's room while it is hidden, the way an UpdatingIndicator does: a row
    that is well has no precondition to teach, and no row moves when one is fixed."""
    policy = widget.sizePolicy()
    policy.setRetainSizeWhenHidden(True)
    widget.setSizePolicy(policy)
    widget.hide()
    return widget


def _to_clipboard(text: str) -> None:
    clipboard = QApplication.clipboard()
    if clipboard is not None:
        clipboard.setText(text)


def _cut(words: str, font: QFont, room: int) -> str:
    if room <= 0:
        return words
    return QFontMetrics(font).elidedText(words, Qt.TextElideMode.ElideRight, room)


class ChecklistDialog(DialogFrame):
    """The rows, grouped, with *Re-check* and whatever remedies this build can run."""

    answered = Signal(str, bool, str)  # check id, ok, detail — plain data, off-thread.
    # GUI-side, carrying ``{check id: Reading}``: what a whole sweep found. The module keeps
    # it for the menu entry's count, and a test waits on it.
    settled = Signal(object)

    def __init__(
        self,
        checks: Sequence[MachineCheck],
        tasks: TaskService,
        remedy: Callable[[str], None],
        parent: QWidget | None = None,
        *,
        prefs: Preferences | None = None,
        greeting: bool = False,
        machine: Machine | None = None,
    ) -> None:
        super().__init__(HEADING, parent, size=DIALOG_SIZE)
        self._checks = ordered(checks)
        self._readings: dict[str, Reading] = {}
        self._remedy = remedy
        self._prefs = Preferences() if prefs is None else prefs
        self._muted = set(self._prefs.muted)
        self.machine = this_machine() if machine is None else machine
        self._runner = TaskRunner(tasks, parent=self)
        # The one dialog in the application that prints a heading, because it is the one
        # that opens itself: nobody clicked an entry naming it. DialogFrame's docstring
        # has the rule, and DESIGN.md's *Dialogs* has the exception in writing.
        self.set_heading(HEADING)

        page = QWidget(self)
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(ROW_LINE_GAP)
        self.rows: list[_Row] = []
        group = ""
        for check in self._checks:
            if check.group != group:
                group = check.group
                if self.rows:
                    column.addSpacing(SECTION_GAP - ROW_LINE_GAP)
                column.addWidget(caption(group, page))
            row = _Row(check, page, self._run_remedy, self._on_mute, self.machine)
            row.show_reading(None, muted=check.id in self._muted)
            self.rows.append(row)
            column.addWidget(row)
        column.addStretch(1)

        self.area = QScrollArea(self.body)
        self.area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.area.setWidgetResizable(True)
        # Every row elides, so there is never anything to the right to scroll to.
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.area.setWidget(page)
        self.body_layout.addWidget(self.area, 1)

        self.at_start = QCheckBox(AT_START, self.body)
        self.at_start.setChecked(self._prefs.at_start)
        self.at_start.toggled.connect(lambda on: self._prefs.on_at_start(bool(on)))
        self.body_layout.addWidget(self.at_start)
        if greeting:
            # Said before the person closes rather than in a box after it — a state is said
            # where the person is looking (DESIGN.md's *How people move through it*).
            self.body_layout.addWidget(note(GREETING, self.body))

        self.add_dismiss("Close")
        self.recheck = self.set_primary("Re-check", self.probe)
        self.recheck.setIcon(refresh_icon(self.palette().color(self.foregroundRole())))
        self.spinner = Spinner(self).attach(self.recheck)

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.answered.connect(self._answered)
        # The sweep is over when the *runner* says so, not when the last probe answered: the
        # worker's own last signal is queued ahead of the runner's completion, so a Re-check
        # pressed on it would find the runner still busy and do nothing at all.
        self._runner.busy_changed.connect(self._busy)
        self._runner.failed.connect(self._failed)
        self.probe()

    # -- probing ---------------------------------------------------------------------

    def probe(self) -> None:
        """Ask every check again, off the GUI thread. A run already going is left alone."""
        checks, answered = self._checks, self.answered

        def body() -> None:
            for check in checks:
                reading = check.probe()
                answered.emit(check.id, reading.ok, reading.detail)

        if not self._runner.run("Checking this machine", body, key=TASK_KEY):
            return
        self._readings.clear()
        for row in self.rows:
            row.show_reading(None)
            row.offer(settled=False)
        self.recheck.setEnabled(False)
        self.spinner.start()
        self.status.say("Checking this machine…", "busy")

    def _answered(self, check_id: str, ok: bool, detail: str) -> None:
        reading = Reading(ok=ok, detail=detail)
        self._readings[check_id] = reading
        for row in self.rows:
            if row.check.id == check_id:
                row.show_reading(reading)

    def _on_mute(self, check_id: str, muted: bool) -> None:
        """A row was told whether to warn. The preference is the module's to keep; what
        changes here is what the footer counts and how loudly the row reads."""
        self._muted.add(check_id) if muted else self._muted.discard(check_id)
        self._prefs.on_mute(check_id, muted)
        for row in self.rows:
            if row.check.id == check_id:
                row.show_reading(self._readings.get(check_id), muted=muted)
        self._settled()

    def counted(self) -> list[tuple[MachineCheck, Reading]]:
        """The rows the footer and the start-up decision read: what has answered, minus what
        the person has asked not to be warned about."""
        return [
            (check, self._readings[check.id])
            for check in self._checks
            if check.id in self._readings and check.id not in self._muted
        ]

    def _busy(self, busy: bool) -> None:
        if not busy:
            self._settled()

    def _settled(self) -> None:
        self.spinner.stop()
        self.recheck.setEnabled(True)
        rows = self.counted()
        missing = any(check.required and not reading.ok for check, reading in rows)
        advice = any(not check.required and not reading.ok for check, reading in rows)
        tone: Tone = "error" if missing else ("info" if advice else "ok")
        self.status.say(summary(rows), tone)
        for row in self.rows:
            row.offer(settled=True)
        # Every reading, muted or not: what to *count* is the module's business, because
        # the preference is, and a muted row that is unmuted later must not be a blank.
        self.settled.emit(dict(self._readings))

    def _failed(self, error: str) -> None:
        self.spinner.stop()
        self.recheck.setEnabled(True)
        self.status.say(error, "error")

    # -- remedies --------------------------------------------------------------------

    def _run_remedy(self, action_id: str) -> None:
        """Run the owning module's own verb, then ask again — a modal remedy has closed by
        the time this returns, and a row that was fixed should say so at once."""
        self._remedy(action_id)
        self.probe()
