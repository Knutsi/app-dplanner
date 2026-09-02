"""The two milestone lists beside the calendar: the one you set, and the one it answers.

On the left, under the staffing picker, every milestone in the order the graph lands
them — its colour, its label, and where its stretch of work begins. A milestone with no
date of its own begins when the previous one lands; the *Date…* button turns that into a
date field pre-filled with that very day, so choosing a date is one click and an edit,
and the cross beside it hands the decision back to the sequence. The swatch offers the
palette by name, a custom colour, and *Automatic*.

On the right, under the calendar, the same milestones with the dates they land for the
chosen team. Both lists are painted the same way — a colour dot, the label as primary
text, the rest secondary — so a reader crosses from one to the other without re-reading.

Picking a row on either side emphasises that milestone's stretch in the calendar; picking
it again lets go. Double-clicking opens the step's details, the one gesture every table
in the application answers. Neither list writes anything: a row reports the date or the
colour it was given through a signal, and the hosting page turns that into the undoable
command — the contract every input here keeps.
"""

from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import QDate, QLocale, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QColorDialog,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.model import StepId
from dplanner.domain.schedule import format_date, format_days
from dplanner.framework.cards import card_rule
from dplanner.modules.time_estimates.schedule import PALETTE
from dplanner.theme.icons import close_icon

# DESIGN.md's rows of rich items: 10 px vertical and 12 px horizontal padding, the row's
# content lines 4 px apart; the 4-point scale for everything else.
ROW_PAD_V = 10
ROW_PAD_H = 12
LINE_GAP = 4
COLUMN_GAP = 12
ROW_RADIUS = 4
SELECTION_PEN = 1.5
SELECTION_FILL_ALPHA = 20

DOT = 10
SWATCH = 24  # A hit target comfortably past the 24 px minimum.
ICON = 16

# What the swatch menu calls each palette slot — the hue's name, in palette order.
PALETTE_NAMES = ("Blue", "Orange", "Teal", "Amber", "Pink", "Green", "Violet", "Red")

# The date fields use the words the calendar uses, so a day reads one way everywhere —
# English explicitly, for ``format_date``'s reason.
DATE_FORMAT = "d MMM yyyy"


@dataclass(frozen=True)
class MilestoneEntry:
    """One milestone as the settable list shows it."""

    step_id: StepId
    label: str
    title: str
    color: QColor
    chosen: bool  # The colour was picked, not dealt.
    start: date | None  # Its own date, or None: it begins when the previous lands.
    default_start: date  # Where the sequence begins it — what *Date…* pre-fills.


@dataclass(frozen=True)
class Landing:
    """One stretch as the answering list shows it."""

    key: str  # The milestone's step id, or "" for the work after the last one.
    label: str
    color: QColor
    finish: date | None
    days: float
    steps: int
    asked: date | None  # A date asked for that the sequence could not keep.


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


class Swatch(QToolButton):
    """A milestone's colour, and the menu that changes it.

    ``color_picked`` carries a hex string, or None for *Automatic*. The menu is built on
    every open, so its icons are painted fresh (the pop-up rule every menu here keeps).
    """

    color_picked = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(PALETTE[0])
        self._chosen = False
        self.setFixedSize(SWATCH, SWATCH)
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Colour")
        self.clicked.connect(self._open)

    def show_color(self, color: QColor, chosen: bool) -> None:
        self._color = QColor(color)
        self._chosen = chosen
        self.update()

    @property
    def color(self) -> QColor:
        return QColor(self._color)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        inset = (SWATCH - DOT) / 2
        painter.drawEllipse(QRectF(inset, inset, DOT, DOT))
        painter.end()

    def menu(self) -> QMenu:
        menu = QMenu(self)
        for hex_color, name in zip(PALETTE, PALETTE_NAMES, strict=True):
            action = QAction(dot_icon(QColor(hex_color)), name, menu)
            action.triggered.connect(lambda _checked=False, chosen=hex_color: self._pick(chosen))
            menu.addAction(action)
        menu.addSeparator()
        custom = QAction("Custom…", menu)
        custom.triggered.connect(self._custom)
        menu.addAction(custom)
        automatic = QAction("Automatic", menu)
        automatic.setEnabled(self._chosen)
        automatic.triggered.connect(lambda: self.color_picked.emit(None))
        menu.addAction(automatic)
        return menu

    def _open(self) -> None:
        self.menu().exec(self.mapToGlobal(self.rect().bottomLeft()))

    def _pick(self, hex_color: str) -> None:
        self.color_picked.emit(hex_color)

    def _custom(self) -> None:
        picked = QColorDialog.getColor(self._color, self, "Milestone colour")
        if picked.isValid():
            self.color_picked.emit(picked.name())


class _Row(QWidget):
    """A pickable row: a selection ring when it is the emphasised one, and the two
    gestures — press to pick, double-click to open."""

    picked = Signal(str)
    activated = Signal(str)

    def __init__(self, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_selected(self, selected: bool) -> None:
        if selected != self._selected:
            self._selected = selected
            self.update()

    @property
    def selected(self) -> bool:
        return self._selected

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        if not self._selected:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = self.palette().highlight().color()
        fill = QColor(accent)
        fill.setAlpha(SELECTION_FILL_ALPHA)
        painter.setPen(QPen(accent, SELECTION_PEN))
        painter.setBrush(fill)
        inset = SELECTION_PEN / 2
        painter.drawRoundedRect(
            QRectF(self.rect()).adjusted(inset, inset, -inset, -inset), ROW_RADIUS, ROW_RADIUS
        )
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self.key)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton and self.key:
            self.activated.emit(self.key)
        super().mouseDoubleClickEvent(event)


def _secondary(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName("InspectorNote")
    return label


class MilestoneRow(_Row):
    """One settable milestone: swatch, label over title, and its start."""

    start_changed = Signal(str, object)  # (step id, date | None)
    color_changed = Signal(str, object)  # (step id, hex | None)

    def __init__(self, step_id: StepId, parent: QWidget | None = None) -> None:
        super().__init__(step_id, parent)
        self._loading = False
        self._default_start = date.today()

        self.swatch = Swatch(self)
        self.swatch.color_picked.connect(lambda color: self.color_changed.emit(self.key, color))

        self.name = QLabel(self)
        self.title = _secondary("", self)

        self.date = QDateEdit(self)
        self.date.setCalendarPopup(True)
        self.date.setLocale(QLocale(QLocale.Language.English))
        self.date.setDisplayFormat(DATE_FORMAT)
        # Arrow steps commit as they land; typing commits on Enter or focus-out, so a
        # half-typed year never reaches the model.
        self.date.setKeyboardTracking(False)
        self.date.dateChanged.connect(self._commit_date)

        self.clear = QToolButton(self)
        self.clear.setAutoRaise(True)
        self.clear.setIcon(close_icon(self.palette().text().color().name()))
        self.clear.setToolTip("Begin when the previous milestone lands")
        self.clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear.clicked.connect(lambda: self.start_changed.emit(self.key, None))

        self.set_date = QToolButton(self)
        self.set_date.setObjectName("ToolbarButton")
        self.set_date.setText("Date…")
        self.set_date.setToolTip("Begin this milestone's work on a date of its own")
        self.set_date.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_date.clicked.connect(
            lambda: self.start_changed.emit(self.key, self._default_start)
        )

        words = QVBoxLayout()
        words.setContentsMargins(0, 0, 0, 0)
        words.setSpacing(LINE_GAP)
        words.addWidget(self.name)
        words.addWidget(self.title)

        row = QHBoxLayout(self)
        row.setContentsMargins(ROW_PAD_H, ROW_PAD_V, ROW_PAD_H, ROW_PAD_V)
        row.setSpacing(COLUMN_GAP)
        row.addWidget(self.swatch)
        row.addLayout(words, 1)
        row.addWidget(self.date)
        row.addWidget(self.clear)
        row.addWidget(self.set_date)

    def load(self, entry: MilestoneEntry) -> None:
        self._loading = True
        try:
            self.swatch.show_color(entry.color, entry.chosen)
            self.name.setText(entry.label)
            self.title.setText(entry.title)
            self.title.setVisible(bool(entry.title) and entry.title != entry.label)
            self._default_start = entry.default_start
            dated = entry.start is not None
            self.date.setVisible(dated)
            self.clear.setVisible(dated)
            self.set_date.setVisible(not dated)
            if entry.start is not None:
                self.date.setDate(QDate(entry.start.year, entry.start.month, entry.start.day))
        finally:
            self._loading = False

    def _commit_date(self) -> None:
        if self._loading:
            return
        picked = self.date.date()
        self.start_changed.emit(self.key, date(picked.year(), picked.month(), picked.day()))


class MilestoneList(QWidget):
    """The settable milestones, one row each, kept across refreshes.

    Rows are reconciled by step id rather than rebuilt: the field the user is typing in
    is the one the model change came from, and destroying it mid-signal is how a widget
    dies with its C++ side already gone. Gone milestones leave, new ones join, and the
    order follows the graph.
    """

    picked = Signal(str)
    activated = Signal(str)
    start_changed = Signal(str, object)
    color_changed = Signal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: dict[StepId, MilestoneRow] = {}
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.empty = _secondary("No milestones yet · Step ▸ Type ▸ Milestone", self)
        self.empty.setWordWrap(True)
        self._layout.addWidget(self.empty)

    def show_entries(self, entries: list[MilestoneEntry], selected: str | None) -> None:
        wanted = {entry.step_id for entry in entries}
        for step_id in tuple(self._rows):
            if step_id not in wanted:
                gone = self._rows.pop(step_id)
                self._layout.removeWidget(gone)
                gone.hide()
                gone.deleteLater()
        for index, entry in enumerate(entries):
            row = self._rows.get(entry.step_id)
            if row is None:
                row = MilestoneRow(entry.step_id, self)
                row.picked.connect(self.picked)
                row.activated.connect(self.activated)
                row.start_changed.connect(self.start_changed)
                row.color_changed.connect(self.color_changed)
                self._rows[entry.step_id] = row
            self._layout.removeWidget(row)
            self._layout.insertWidget(index, row)
            row.load(entry)
            row.set_selected(entry.step_id == selected)
        self.empty.setVisible(not entries)

    def row(self, step_id: StepId) -> MilestoneRow:
        return self._rows[step_id]

    @property
    def keys(self) -> tuple[StepId, ...]:
        keys: list[StepId] = []
        for index in range(self._layout.count()):
            item = self._layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if isinstance(widget, MilestoneRow):
                keys.append(widget.key)
        return tuple(keys)


class LandingRow(_Row):
    """One stretch's answer: dot, label, the day it lands, how long it took."""

    def __init__(self, landing: Landing, date_width: int, parent: QWidget | None = None) -> None:
        super().__init__(landing.key, parent)
        self.landing = landing
        dot = QLabel(self)
        dot.setPixmap(dot_icon(landing.color).pixmap(ICON, ICON))
        dot.setFixedSize(SWATCH, SWATCH)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.name = QLabel(landing.label, self)
        if not landing.key:
            self.name.setObjectName("InspectorNote")
        self.when = QLabel(format_date(landing.finish) if landing.finish else "—", self)
        self.when.setMinimumWidth(date_width)
        self.when.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.days = _secondary(format_days(landing.days), self)
        self.days.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        steps = f"{landing.steps} step{'s' if landing.steps != 1 else ''}"
        if landing.finish is None:
            tip = f"{steps} — nothing estimated, so no date"
        else:
            tip = f"{steps} · lands {format_date(landing.finish)}"
        if landing.asked is not None:
            self.when.setText(f"⚠ {self.when.text()}")
            tip += (
                f"\nAsked to begin {format_date(landing.asked)}, but the previous milestone "
                "lands later — it runs after that instead."
            )
        self.setToolTip(tip)

        row = QHBoxLayout(self)
        row.setContentsMargins(ROW_PAD_H, ROW_PAD_V, ROW_PAD_H, ROW_PAD_V)
        row.setSpacing(COLUMN_GAP)
        row.addWidget(dot)
        row.addWidget(self.name, 1)
        row.addWidget(self.when)
        row.addWidget(self.days)


class LandingList(QWidget):
    """The stretches in sequence with their landing dates, and the whole under a rule."""

    picked = Signal(str)
    activated = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[LandingRow] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.total = QWidget(self)
        self.total_rule = card_rule(self.total)
        self.total_when = QLabel(self.total)
        self.total_days = _secondary("", self.total)
        total_row = QHBoxLayout()
        total_row.setContentsMargins(ROW_PAD_H, ROW_PAD_V, ROW_PAD_H, ROW_PAD_V)
        total_row.setSpacing(COLUMN_GAP)
        total_row.addSpacing(SWATCH)
        total_row.addWidget(_secondary("All work", self.total), 1)
        total_row.addWidget(self.total_when)
        total_row.addWidget(self.total_days)
        total_layout = QVBoxLayout(self.total)
        total_layout.setContentsMargins(0, 0, 0, 0)
        total_layout.setSpacing(0)
        total_layout.addWidget(self.total_rule)
        total_layout.addLayout(total_row)
        self._layout.addWidget(self.total)

    def show_landings(
        self,
        landings: list[Landing],
        selected: str | None,
        *,
        finish: date | None,
        days: float,
    ) -> None:
        for row in self._rows:
            self._layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        self._rows.clear()
        date_width = self.fontMetrics().horizontalAdvance("⚠ 30 September") + COLUMN_GAP
        for index, landing in enumerate(landings):
            row = LandingRow(landing, date_width, self)
            row.picked.connect(self.picked)
            row.activated.connect(self.activated)
            row.set_selected(bool(landing.key) and landing.key == selected)
            self._layout.insertWidget(index, row)
            self._rows.append(row)
        # The whole is worth a line of its own only when it is more than one stretch.
        self.total.setVisible(len(landings) > 1)
        self.total_when.setText(format_date(finish) if finish else "—")
        self.total_when.setMinimumWidth(date_width)
        self.total_when.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.total_days.setText(format_days(days))

    @property
    def rows(self) -> tuple[LandingRow, ...]:
        return tuple(self._rows)
