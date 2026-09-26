"""The Wait block on a wait step's Details tab: until a day, or for working days.

One choice and its value, committed as one undoable command — the same entry ``dplanner wait
set`` writes. Switching the choice keeps the other's value in the field, so a reader trying
one against the other loses nothing until the entry is written.
"""

from collections.abc import Callable
from datetime import date
from typing import Any

from PySide6.QtCore import QDate, QLocale
from PySide6.QtWidgets import (
    QButtonGroup,
    QDateEdit,
    QDoubleSpinBox,
    QGridLayout,
    QRadioButton,
)

from dplanner.domain.model import Library, Step
from dplanner.domain.schedule import Wait
from dplanner.framework.module_data_section import FIELD_GAP, ModuleDataSection
from dplanner.framework.table import DATE_FORMAT
from dplanner.framework.undo import UndoService
from dplanner.modules.step_wait.aspect import MODULE_ID, read, write

DAYS_MOST = 250.0  # A year of working days; a longer wait is a milestone of its own.


class WaitSection(ModuleDataSection):
    """Until a day, or for working days — one of the two."""

    def __init__(
        self, library: Library, undo: UndoService[Library], today: Callable[[], date]
    ) -> None:
        super().__init__(library, undo, module_id=MODULE_ID, undo_label="Set Wait")
        self._today = today
        self.until_choice = QRadioButton("Until", self)
        self.until_choice.setToolTip("What requires this step may start on this day")
        self.days_choice = QRadioButton("For", self)
        self.days_choice.setToolTip("What requires this step waits this many working days")
        choices = QButtonGroup(self)
        choices.addButton(self.until_choice)
        choices.addButton(self.days_choice)
        self.until = QDateEdit(self)
        self.until.setCalendarPopup(True)
        self.until.setLocale(QLocale(QLocale.Language.English))
        self.until.setDisplayFormat(DATE_FORMAT)
        self.until.setKeyboardTracking(False)
        self.days = QDoubleSpinBox(self)
        self.days.setRange(0.0, DAYS_MOST)
        self.days.setDecimals(1)
        self.days.setSingleStep(1.0)
        self.days.setSuffix(" working days")
        self.days.setKeyboardTracking(False)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(FIELD_GAP)
        grid.setVerticalSpacing(FIELD_GAP)
        grid.addWidget(self.until_choice, 0, 0)
        grid.addWidget(self.until, 0, 1)
        grid.addWidget(self.days_choice, 1, 0)
        grid.addWidget(self.days, 1, 1)
        grid.setColumnStretch(2, 1)
        choices.buttonToggled.connect(lambda _button, on: self._on_choice(on))
        self.until.dateChanged.connect(lambda _day: self.commit())
        self.days.valueChanged.connect(lambda _days: self.commit())

    # -- ModuleDataSection -----------------------------------------------------------------------

    def load_step(self, step: Step | None) -> None:
        wait = read(step) if step is not None else None
        until = wait.until if wait is not None and wait.until is not None else self._today()
        self.until.setDate(QDate(until.year, until.month, until.day))
        self.days.setValue(wait.days if wait is not None and wait.until is None else 1.0)
        by_date = wait is not None and wait.until is not None
        self.until_choice.setChecked(by_date)
        self.days_choice.setChecked(not by_date)
        self._show_choice()

    def entry(self, step: Step) -> dict[str, Any]:
        if self.until_choice.isChecked():
            picked = self.until.date()
            return write(Wait(until=date(picked.year(), picked.month(), picked.day())))
        return write(Wait(days=self.days.value()))

    # -- input -----------------------------------------------------------------------------------

    def _on_choice(self, on: bool) -> None:
        if on:  # Each switch toggles two buttons; the one turned on commits.
            self._show_choice()
            self.commit()

    def _show_choice(self) -> None:
        self.until.setEnabled(self.until_choice.isChecked())
        self.days.setEnabled(self.days_choice.isChecked())
