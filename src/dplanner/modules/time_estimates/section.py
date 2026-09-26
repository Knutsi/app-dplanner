"""The Schedule block on a milestone's Details tab: when its stretch begins, and its colour.

A milestone's stretch begins where the one before it lands — unless it is given a day of its
own, which holds its work back to that day (a day before the previous landing is pushed, and
``dplanner schedule matrix`` says so). Its colour is its place on the project's colour map
unless one is chosen. Both are this module's entry on the milestone's step
(``schedule.write_milestone``), set here as one undoable command and by ``dplanner schedule
milestone`` alike. They moved here from the Time tab's milestone table when the table gave
way to the shift view: a milestone's own assumptions are edited where the milestone is.
"""

from collections.abc import Callable
from datetime import date
from typing import Any

from PySide6.QtCore import QDate, QLocale, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDateEdit,
    QHBoxLayout,
    QMenu,
    QToolButton,
    QVBoxLayout,
)

from dplanner.domain.model import Library, Step
from dplanner.framework.module_data_section import FIELD_GAP, ModuleDataSection
from dplanner.framework.table import DATE_FORMAT
from dplanner.framework.undo import UndoService
from dplanner.modules.time_estimates.schedule import (
    MODULE_ID,
    SWATCH_SHADES,
    WHOLE_COLOR,
    read_color,
    read_palette,
    read_start,
    write_milestone,
)
from dplanner.theme.palettes import shades

DOT = 10
ICON = 16
AUTOMATIC = "Automatic"


def dot_icon(color: QColor) -> QIcon:
    pixmap = QPixmap(QSize(ICON, ICON))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    inset = (ICON - DOT) / 2
    painter.drawEllipse(QRectF(inset, inset, DOT, DOT))
    painter.end()
    return QIcon(pixmap)


class MilestoneScheduleSection(ModuleDataSection):
    """A day of its own to begin on, or none; a colour of its own, or the map's."""

    def __init__(
        self, library: Library, undo: UndoService[Library], today: Callable[[], date]
    ) -> None:
        super().__init__(library, undo, module_id=MODULE_ID, undo_label="Schedule Milestone")
        self._today = today  # The day a date of its own is offered from, before it has one.
        self._color: str | None = None

        self.own_start = QCheckBox("Begins on a day of its own", self)
        self.own_start.setToolTip("Otherwise its stretch begins where the one before it lands")
        self.own_start.toggled.connect(self._on_own_start)
        self.start = QDateEdit(self)
        self.start.setCalendarPopup(True)
        self.start.setLocale(QLocale(QLocale.Language.English))
        self.start.setDisplayFormat(DATE_FORMAT)
        self.start.setKeyboardTracking(False)
        self.start.dateChanged.connect(lambda _day: self.commit())
        self.colour = QToolButton(self)
        self.colour.setObjectName("ToolbarButton")
        self.colour.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.colour.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.colour.setToolTip("A shade of the project's map, a colour of its own, or Automatic")
        self._menu = QMenu(self.colour)
        self._menu.aboutToShow.connect(self._fill_colours)
        self.colour.setMenu(self._menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(FIELD_GAP)
        begins = QHBoxLayout()
        layout.addLayout(begins)  # Before it is filled: a parentless layout leaks.
        begins.setSpacing(FIELD_GAP)
        begins.addWidget(self.own_start)
        begins.addWidget(self.start)
        begins.addStretch(1)
        colour = QHBoxLayout()
        layout.addLayout(colour)
        colour.addWidget(self.colour)
        colour.addStretch(1)

    # -- ModuleDataSection -----------------------------------------------------------------------

    def load_step(self, step: Step | None) -> None:
        start = read_start(step) if step is not None else None
        self.own_start.setChecked(start is not None)
        self.start.setEnabled(start is not None)
        shown = start or self._today()
        self.start.setDate(QDate(shown.year, shown.month, shown.day))
        self._color = read_color(step) if step is not None else None
        self.colour.setText(self._color or AUTOMATIC)
        self.colour.setIcon(dot_icon(QColor(self._color or WHOLE_COLOR)))

    def entry(self, step: Step) -> dict[str, Any]:
        picked = self.start.date()
        start = (
            date(picked.year(), picked.month(), picked.day())
            if self.own_start.isChecked()
            else None
        )
        return write_milestone(start, self._color)

    # -- input -----------------------------------------------------------------------------------

    def _on_own_start(self, on: bool) -> None:
        self.start.setEnabled(on)
        self.commit()

    def pick_colour(self, color: str | None) -> None:
        """A colour of its own, or None to hand it back to the map."""
        self._color = color
        self.commit()

    def colour_labels(self) -> list[str]:
        """What the menu offers, as a test reads it."""
        self._fill_colours()
        return [action.text() for action in self._menu.actions() if not action.isSeparator()]

    def _fill_colours(self) -> None:
        self._menu.clear()
        step = self.step()
        if step is None:
            return
        found = read_palette(self._library.project_of(step.id))
        for index, hex_color in enumerate(shades(found, SWATCH_SHADES), start=1):
            action = self._menu.addAction(dot_icon(QColor(hex_color)), f"{found.name} {index}")
            action.triggered.connect(
                lambda _checked=False, chosen=hex_color: self.pick_colour(chosen)
            )
        self._menu.addSeparator()
        custom = self._menu.addAction("Custom…")
        custom.triggered.connect(lambda _checked=False: self._custom())
        automatic = self._menu.addAction(AUTOMATIC)
        automatic.setEnabled(self._color is not None)
        automatic.triggered.connect(lambda _checked=False: self.pick_colour(None))

    def _custom(self) -> None:
        picked = QColorDialog.getColor(QColor(self._color or WHOLE_COLOR), self, "Milestone colour")
        if picked.isValid():
            self.pick_colour(picked.name())
