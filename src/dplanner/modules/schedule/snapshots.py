"""Choosing which plan the page compares with (saving one is ``snapshot_dialog.py``).

The page compares the plan now with a plan *then*, picked here in the strip over it,
where the whole page's assumptions are set: a :class:`SnapshotPicker`, a button wearing
the name of the plan it reads, dropping a menu built when it opens (the swatch's pattern)
that offers the plan at the project's start, the plan a week ago, every snapshot somebody
saved, by title and day, and *Day…*, which asks for any recorded day. The button's tooltip
names the record that stood in for the pick, so which plans are compared is never a guess;
the picker only reports a :class:`Pick`, and the hosting page resolves it and re-renders —
the contract every input here keeps.
"""

from collections.abc import Sequence
from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QToolButton, QWidget

from dplanner.modules.schedule.progress import (
    A_WEEK_AGO,
    AT_START,
    Pick,
    Snapshot,
    find_saved,
)
from dplanner.planning.dates import format_date

START_LABEL = "Plan at start"
WEEK_LABEL = "Plan a week ago"
DAY_LABEL = "Day…"
FORGET_LABEL = "Forget saved snapshot"


def short_pick_words(pick: Pick, found: Snapshot | None, today: date) -> str:
    """The pick as the button wears it — short enough for a strip, where the tooltip
    carries ``progress.pick_words``'s full sentence."""
    if pick.kind == "start":
        return START_LABEL
    if pick.kind == "week":
        return WEEK_LABEL
    if pick.kind == "saved":
        return pick.title
    if pick.day is None:
        return DAY_LABEL
    return format_date(pick.day, today=today)


class SnapshotPicker(QToolButton):
    """Which recorded plan the page compares with: ``picked`` reports the :class:`Pick`
    the reader chose, ``forget`` names a saved snapshot to drop."""

    picked = Signal(object)  # Pick
    forget = Signal(str)  # A saved snapshot's title.

    def __init__(self, today: date, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pick = AT_START
        self._saved: tuple[Snapshot, ...] = ()
        self._today = today
        self.setObjectName("ToolbarButton")
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._menu = QMenu(self)
        self._menu.aboutToShow.connect(self._fill)
        self.setMenu(self._menu)
        self.setText(START_LABEL)

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
        self._entry(self._menu, START_LABEL, AT_START, checked=self._pick.kind == "start")
        # The anchor of a weekly review, beside the plan at start.
        self._entry(self._menu, WEEK_LABEL, A_WEEK_AGO, checked=self._pick.kind == "week")
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
