"""Choosing which two plans the plots compare, and saving one on purpose.

A comparison is two snapshots — a *then* and a *now* — and both are picked here, in the
strip over the page, where the whole page's assumptions are set. Each side is one
:class:`SnapshotPicker`: a button wearing the name of the plan it reads, dropping a menu
built when it opens (the swatch's pattern) that offers the side's own default — the plan
at the project's start, or the live plan now — every snapshot somebody saved, by title
and day, and *Day…*, which asks for any recorded day. The button's tooltip names the
record that stood in for the pick, so which plans are compared is never a guess; the
picker only reports a :class:`Pick`, and the hosting page resolves it and re-renders —
the contract every input here keeps.

:class:`SaveSnapshotDialog` asks for the title a saved snapshot is found by, and a note
saying what the occasion was. A title already taken is refused *in the dialog*, with the
reason where the finger is, because a saved snapshot is named exactly so that it can be
told from the others.
"""

from collections.abc import Sequence
from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLineEdit, QMenu, QPlainTextEdit, QToolButton, QWidget

from dplanner.domain.schedule import format_date
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.signalling import StatusLine
from dplanner.framework.widgets import block, caption
from dplanner.modules.time_estimates.progress import Pick, Snapshot, find_saved
from dplanner.theme.tokens import SECTION_GAP

NOTE_LINES = 4

# What the leading entry of each side is called.
START_LABEL = "Plan at start"
NOW_LABEL = "Now"
DAY_LABEL = "Day…"
FORGET_LABEL = "Forget saved snapshot"


def short_pick_words(pick: Pick, found: Snapshot | None, today: date) -> str:
    """The pick as the button wears it — short enough for a strip, where the tooltip
    carries ``progress.pick_words``'s full sentence."""
    if pick.kind == "now":
        return NOW_LABEL
    if pick.kind == "start":
        return START_LABEL
    if pick.kind == "saved":
        return pick.title
    if pick.day is None:
        return DAY_LABEL
    return format_date(pick.day, today=today)


class SnapshotPicker(QToolButton):
    """One side of the comparison: which recorded plan it reads.

    ``picked`` reports the :class:`Pick` the reader chose; ``forget`` names a saved
    snapshot to drop. ``leading`` is the side's own default — the plan at start for the
    then side, the live plan for the now side.
    """

    picked = Signal(object)  # Pick
    forget = Signal(str)  # A saved snapshot's title.

    def __init__(self, leading: Pick, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._leading = leading
        self._pick = leading
        self._saved: tuple[Snapshot, ...] = ()
        self._today = date.today()
        self.setObjectName("ToolbarButton")
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._menu = QMenu(self)
        self._menu.aboutToShow.connect(self._fill)
        self.setMenu(self._menu)
        self.setText(short_pick_words(leading, None, self._today))

    # -- the host's side of the contract -------------------------------------------------------

    def show_pick(
        self, pick: Pick, found: Snapshot | None, saved: Sequence[Snapshot], words: str, today: date
    ) -> None:
        """What the side reads now, the saved snapshots the menu offers, and the full
        sentence for the tooltip — empty when the pick found nothing to read."""
        self._pick = pick
        self._saved = tuple(saved)
        self._today = today
        self.setText(short_pick_words(pick, found, today))
        self.setToolTip(words or "Nothing recorded to compare with yet")

    @property
    def pick(self) -> Pick:
        return self._pick

    def menu_labels(self) -> list[str]:
        """The entries the menu offers, as a test reads them."""
        self._fill()
        return [action.text() for action in self._menu.actions() if not action.isSeparator()]

    # -- the menu, built when it opens -----------------------------------------------------------

    def _fill(self) -> None:
        self._menu.clear()
        leading = START_LABEL if self._leading.kind == "start" else NOW_LABEL
        self._entry(
            self._menu, leading, self._leading, checked=self._pick.kind == self._leading.kind
        )
        if self._saved:
            self._menu.addSeparator()
            for row in self._saved:
                label = f"{row.title} · {format_date(row.day, today=self._today)}"
                self._entry(
                    self._menu,
                    label,
                    Pick("saved", title=row.title),
                    checked=self._pick.kind == "saved"
                    and find_saved([row], self._pick.title) is not None,
                    tip=row.note,
                )
        self._menu.addSeparator()
        day = self._pick.day if self._pick.kind == "day" else None
        self._entry(
            self._menu, DAY_LABEL, Pick("day", day=day or self._today), checked=day is not None
        )
        if self._saved:
            self._menu.addSeparator()
            forget = self._menu.addMenu(FORGET_LABEL)
            for row in self._saved:
                action = QAction(row.title, forget)
                action.triggered.connect(
                    lambda _checked=False, title=row.title: self.forget.emit(title)
                )
                forget.addAction(action)

    def _entry(self, menu: QMenu, label: str, pick: Pick, *, checked: bool, tip: str = "") -> None:
        action = QAction(label, menu)
        action.setCheckable(True)
        action.setChecked(checked)
        action.setToolTip(tip)
        action.triggered.connect(lambda _checked=False, chosen=pick: self.picked.emit(chosen))
        menu.addAction(action)


class SaveSnapshotDialog(DialogFrame):
    """A title the snapshot is found by, and a note on what the occasion was."""

    def __init__(self, taken: Sequence[str], parent: QWidget | None = None) -> None:
        super().__init__("Save Snapshot", parent)
        self._taken = {title.strip().lower() for title in taken}
        self.title = QLineEdit(self.body)
        self.title.setPlaceholderText("What we thought on 1 November")
        self.title.textChanged.connect(self._check)
        # Under the field it is about, in the error tone, only while the title is taken.
        self.reason = StatusLine(self.body)
        block(self.body_layout, caption("Title", self.body), self.title, self.reason)
        self.note = QPlainTextEdit(self.body)
        self.note.setPlaceholderText("What the occasion was, for whoever compares against it")
        self.note.setFixedHeight(self.note.fontMetrics().lineSpacing() * NOTE_LINES + SECTION_GAP)
        block(self.body_layout, caption("Note", self.body), self.note)
        self.add_dismiss()
        self.set_primary("Save", self.accept)
        self._check()

    def values(self) -> tuple[str, str]:
        return self.title.text().strip(), self.note.toPlainText().strip()

    def _check(self) -> None:
        """Save is offered only for a title that is new: the reason sits under the field
        rather than arriving as a refusal after the click."""
        title = self.title.text().strip()
        taken = bool(title) and title.lower() in self._taken
        self.reason.say(f"A snapshot called “{title}” is already saved." if taken else "", "error")
        primary = self.primary()
        if primary is not None:
            primary.setEnabled(bool(title) and not taken)
