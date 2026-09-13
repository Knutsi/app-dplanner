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

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QResizeEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dplanner.cli.checklist import MachineCheck, Reading, ordered, summary
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.signalling import GLYPH, Spinner, StatusLine, Tone
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.widgets import caption, note
from dplanner.theme.cards import detail_font
from dplanner.theme.icons import refresh_icon
from dplanner.theme.tokens import FIELD_GAP, ROW_LINE_GAP, SECTION_GAP

# Tall enough that a machine with every row shows them all without scrolling; it is a
# framed dialog, so the screen's 80 % still caps it and the person can drag it smaller.
DIALOG_SIZE = (660, 640)
TASK_KEY = "checklist.probe"
CHECKING = "checking…"
GREETING = "You can open this again from Tools ▸ Setup Checklist."
AT_START = "Open this at start when something required is missing"


def tone_for(check: MachineCheck, reading: Reading | None) -> Tone:
    """The four tones, derived rather than declared: the row has no state of its own.

    Not yet answered is busy — a probe is work with no known end, which is exactly what
    DESIGN.md's busy tone is for. A failing required check is the error tone; a failing
    recommendation is information, because advice shouted in red is not advice.
    """
    if reading is None:
        return "busy"
    if reading.ok:
        return "ok"
    return "error" if check.required else "info"


class _Row(QWidget):
    """One check: its status line, the remedy under it, and the button the remedy names.

    Two lines, DESIGN.md's rich row: the *what* on the first, in the tone, with the glyph on
    it; the *why* under it in secondary ink a point smaller, and only while there is one.
    **Both elide and neither wraps** — a row that grew taller as the dialog narrowed would
    be a height that depends on a width inside a scroll area, which is how the calendar once
    took the process down (CLAUDE.md's *Checks*). The full words are the tooltip.
    """

    def __init__(self, check: MachineCheck, parent: QWidget, remedy: Callable[[str], None]) -> None:
        super().__init__(parent)
        self.check = check
        self.reading: Reading | None = None
        self.said = ""  # The row's full words, before the width cuts them.
        self.why_words = ""
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
        # Under the *words* of the line above, not under its glyph: the glyph is the name's.
        self.why.setIndent(QFontMetrics(self.line.font()).horizontalAdvance(f"{GLYPH} "))
        self.why.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.why.hide()
        words.addWidget(self.why)

        self.button: QPushButton | None = None
        remedial = check.remedy
        if remedial is not None and remedial.action:
            self.button = QPushButton(remedial.verb or "Fix…", self)
            self.button.setAutoDefault(False)
            self.button.setToolTip(remedial.words)
            self.button.clicked.connect(lambda: remedy(remedial.action))
            # It keeps its room while hidden, the way an UpdatingIndicator does: a row that
            # is well has no precondition to teach, and no row moves when one is fixed.
            policy = self.button.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            self.button.setSizePolicy(policy)
            self.button.hide()
            layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignTop)
        self.show_reading(None)

    def show_reading(self, reading: Reading | None) -> None:
        """Say where this check stands. ``None`` is "being probed right now"."""
        self.reading = reading
        detail = CHECKING if reading is None else reading.detail
        self.said = f"{self.check.label} — {detail}" if detail else self.check.label
        remedial = self.check.remedy
        self.why_words = "" if reading is None or reading.ok or remedial is None else remedial.words
        self.why.setVisible(bool(self.why_words))
        self.setToolTip("\n".join(part for part in (self.said, self.why_words) if part))
        self._elide()

    def offer(self, *, settled: bool) -> None:
        """Show the remedy on a row that needs it — never while a sweep is still running.

        Its room is kept either way, so a fixed row and a failing one are the same shape.
        """
        if self.button is not None:
            self.button.setVisible(settled and self.reading is not None and not self.reading.ok)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        """Re-cut both lines to the width there is. Nothing here changes the row's height."""
        room = self.line.width()
        self.line.say(_cut(self.said, self.line.font(), room), tone_for(self.check, self.reading))
        if self.why_words:
            self.why.setText(_cut(self.why_words, self.why.font(), self.why.width()))


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
        at_start: bool = True,
        on_at_start: Callable[[bool], None] = lambda _on: None,
        greeting: bool = False,
    ) -> None:
        super().__init__("Setup Checklist", parent, size=DIALOG_SIZE)
        self._checks = ordered(checks)
        self._readings: dict[str, Reading] = {}
        self._remedy = remedy
        self._runner = TaskRunner(tasks, parent=self)

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
            row = _Row(check, page, self._run_remedy)
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
        self.at_start.setChecked(at_start)
        self.at_start.toggled.connect(lambda on: on_at_start(bool(on)))
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

    def _busy(self, busy: bool) -> None:
        if not busy:
            self._settled()

    def _settled(self) -> None:
        self.spinner.stop()
        self.recheck.setEnabled(True)
        rows = [
            (check, self._readings[check.id])
            for check in self._checks
            if check.id in self._readings
        ]
        missing = any(check.required and not reading.ok for check, reading in rows)
        advice = any(not check.required and not reading.ok for check, reading in rows)
        tone: Tone = "error" if missing else ("info" if advice else "ok")
        self.status.say(summary(rows), tone)
        for row in self.rows:
            row.offer(settled=True)
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
