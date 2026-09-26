"""History: the tab as it was recorded on an earlier day.

A face on the tab's strip — ``History``, or ``History · 3 Oct`` while it looks back — that
drops a popover: a slider over the days the recorder wrote a row, and today, a step either
way; the day it stands on in words; *Back to Today* while it looks back; and how many days
there are to look at. Every move is announced as it happens (:attr:`HistoryButton.moved`:
the day, None for today), so the page follows the slider rather than waiting for it to be
let go. On a recorded day the page reads that day's record — its dates, its scope, what was
done — as today it reads the live plan, and nothing on it writes; it needs nothing DPlanner
does not already store (``progress_history``).
"""

from collections.abc import Sequence
from datetime import date

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from dplanner.domain.schedule import format_date, short_date
from dplanner.framework.popover import PopoverButton
from dplanner.framework.slider_row import SliderRow
from dplanner.framework.widgets import note, quiet
from dplanner.theme.tokens import FIELD_GAP

HISTORY_TIP = "Look back at the tab as it was recorded on an earlier day"
BACK_TO_TODAY = "Back to Today"


class HistoryButton(PopoverButton):
    """``moved`` carries the day the slider reached — None when it is back on today."""

    moved = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("History", parent, tip=HISTORY_TIP)
        panel = self.popover
        self.days = SliderRow(panel, earlier="The record before", later="The record after")
        self.days.setMinimumWidth(260)
        self.days.moved.connect(self._on_moved)
        panel.body.addWidget(self.days)
        row = QHBoxLayout()
        panel.body.addLayout(row)  # Before it is filled: a parentless layout leaks.
        row.setSpacing(FIELD_GAP)
        self.said = note("", panel)
        row.addWidget(self.said, 1)
        self.back = quiet(QPushButton(BACK_TO_TODAY, panel))
        self.back.clicked.connect(self.back_to_today)
        row.addWidget(self.back)
        self.how_many = note("", panel)
        self.how_many.setWordWrap(True)
        panel.body.addWidget(self.how_many)
        self._days: tuple[date, ...] = ()
        self._today = date.min

    def show_history(self, recorded: Sequence[date], today: date, shown: date) -> None:
        """The recorded days and today, standing on ``shown`` — placing it, never a move."""
        days = tuple(sorted({day for day in recorded if day < today} | {today}))
        self._days, self._today = days, today
        self.days.set_count(len(days))
        at = max((index for index, day in enumerate(days) if day <= shown), default=0)
        self.days.set_value(at)
        self._say(days[at])
        earlier = len(days) - 1
        self.how_many.setText(
            f"{earlier} recorded day{'' if earlier == 1 else 's'}, from "
            f"{short_date(days[0], today)}. Looking back, the page reads each day's record; "
            "nothing is written."
            if earlier
            else "Nothing recorded before today yet."
        )

    @property
    def looking_back(self) -> bool:
        return bool(self._days) and self._days[self.days.value()] != self._today

    def back_to_today(self) -> None:
        self.days.set_value(len(self._days) - 1, say=True)

    def _on_moved(self, index: int) -> None:
        day = self._days[index]
        self._say(day)
        self.moved.emit(None if day == self._today else day)

    def _say(self, day: date) -> None:
        today = self._today
        back = day != today
        self.setText(f"History · {short_date(day, today)}" if back else "History")
        self.setToolTip(
            f"Showing the tab as recorded {format_date(day, today)}; nothing can be changed"
            if back
            else HISTORY_TIP
        )
        self.said.setText(f"as recorded {format_date(day, today)}" if back else "today")
        self.back.setVisible(back)
