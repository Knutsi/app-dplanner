"""The milestone list under the calendar, and the palette picker that colours it.

One list, where there were two: every stretch of work in the order the graph lands
them — its shade, its label, where it begins and where it lands. A milestone with no date
of its own begins when the previous one lands; the *Begin…* button turns that into a date
field pre-filled with that very day, so choosing a date is one click and an edit, and the
cross beside it hands the decision back to the sequence. Beside the field, the date the
milestone lands for the chosen team and how long its stretch took — so what you set and
what it answers sit on one line, and a reader never crosses from one list to another.
The work after the last milestone is a row too, without controls; the whole closes the
list under a rule.

Milestones are shaded from one colour map — the project's :class:`Palette` — and the
picker offers the maps by name with a strip of each. The swatch on a row offers the map's
shades, a custom colour, and *Automatic*, which hands the shade back to the sequence.

Picking a row emphasises that milestone's stretch in the calendar; picking it again lets
go. Double-clicking opens the step's details, the one gesture every table in the
application answers. Nothing here writes: a row reports the date or the colour it was
given through a signal, the picker reports a palette id, and the hosting page turns each
into the undoable command — the contract every input here keeps.
"""

from dataclasses import dataclass, field
from datetime import date

from PySide6.QtCore import QDate, QLocale, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
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
from dplanner.modules.time_estimates.progress import Tally
from dplanner.modules.time_estimates.schedule import (
    PALETTES,
    SWATCH_SHADES,
    Palette,
    shades,
)
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
STRIP_WIDTH = 56
STRIP_HEIGHT = 12
STRIP_RADIUS = 3

# The date fields use the words the calendar uses, so a day reads one way everywhere —
# English explicitly, for ``format_date``'s reason.
DATE_FORMAT = "d MMM yyyy"


@dataclass(frozen=True)
class MilestoneEntry:
    """One stretch as the list shows it: a milestone, or the work after the last one."""

    key: str  # The milestone's step id, or "" for the work after the last one.
    label: str
    title: str
    color: QColor
    chosen: bool  # The colour was picked, not dealt.
    start: date | None  # Its own date, or None: it begins when the previous lands.
    default_start: date  # Where the sequence begins it — what *Begin…* pre-fills.
    finish: date | None
    days: float
    steps: int
    asked: date | None  # A date asked for that the sequence could not keep.
    # What has landed toward this milestone — everything through its stretch — and
    # which measure the row's percentage reads.
    landed: Tally = field(default_factory=Tally)
    by_days: bool = False

    @property
    def is_milestone(self) -> bool:
        return bool(self.key)

    @property
    def share(self) -> float | None:
        return self.landed.share(self.by_days)


def percent(share: float | None) -> str:
    return "—" if share is None else f"{share:.0%}"


def landed_words(landed: Tally) -> str:
    """The percentage's tooltip: both measures in full, so the row's one number never
    has to say which it is."""
    return (
        f"{landed.done} of {landed.steps} steps done · "
        f"{format_days(landed.done_days)} of {format_days(landed.days)} estimated"
    )


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


def strip_icon(found: Palette) -> QIcon:
    """The map as a strip, dark to light — what a palette looks like before it is dealt."""
    pixmap = QPixmap(QSize(STRIP_WIDTH, STRIP_HEIGHT))
    pixmap.fill(Qt.GlobalColor.transparent)
    gradient = QLinearGradient(QPointF(0, 0), QPointF(STRIP_WIDTH, 0))
    last = len(found.stops) - 1
    for index, stop in enumerate(found.stops):
        gradient.setColorAt(index / last, QColor(stop))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(QRectF(0, 0, STRIP_WIDTH, STRIP_HEIGHT), STRIP_RADIUS, STRIP_RADIUS)
    painter.end()
    return QIcon(pixmap)


class PalettePicker(QComboBox):
    """The colour maps by name, each with its strip; ``palette_picked`` carries the id."""

    palette_picked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loading = False
        self.setIconSize(QSize(STRIP_WIDTH, STRIP_HEIGHT))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        for found in PALETTES:
            self.addItem(strip_icon(found), found.name, found.id)
        self.currentIndexChanged.connect(self._on_index)

    def show_palette(self, found: Palette) -> None:
        self._loading = True
        try:
            self.setCurrentIndex(self.findData(found.id))
        finally:
            self._loading = False

    @property
    def palette_id(self) -> str:
        return str(self.currentData())

    def _on_index(self) -> None:
        if not self._loading:
            self.palette_picked.emit(self.palette_id)


class Swatch(QToolButton):
    """A milestone's colour, and the menu that changes it.

    ``color_picked`` carries a hex string, or None for *Automatic*. The menu is built on
    every open, so its icons are painted fresh (the pop-up rule every menu here keeps) and
    its shades are the current palette's.
    """

    color_picked = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(PALETTES[0].stops[0])
        self._chosen = False
        self._palette = PALETTES[0]
        self.setFixedSize(SWATCH, SWATCH)
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Colour")
        self.clicked.connect(self._open)

    def show_color(self, color: QColor, chosen: bool, found: Palette) -> None:
        self._color = QColor(color)
        self._chosen = chosen
        self._palette = found
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
        for index, hex_color in enumerate(shades(self._palette, SWATCH_SHADES), start=1):
            action = QAction(dot_icon(QColor(hex_color)), f"{self._palette.name} {index}", menu)
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


def _secondary(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName("InspectorNote")
    return label


class MilestoneRow(QWidget):
    """One stretch: swatch, label over title, where it begins, where it lands, how long.

    A selection ring when it is the emphasised one, and the two gestures — press to pick,
    double-click to open. The remainder row (key "") has no swatch menu and no date
    controls: there is no milestone to colour or to date.
    """

    picked = Signal(str)
    activated = Signal(str)
    start_changed = Signal(str, object)  # (step id, date | None)
    color_changed = Signal(str, object)  # (step id, hex | None)

    def __init__(
        self, key: str, date_width: int, days_width: int, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.key = key
        self._selected = False
        self._loading = False
        self._default_start = date.today()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.swatch = Swatch(self)
        self.swatch.color_picked.connect(lambda color: self.color_changed.emit(self.key, color))
        self.dot = QLabel(self)  # The remainder's colour, with no menu behind it.
        self.dot.setFixedSize(SWATCH, SWATCH)
        self.dot.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.name = QLabel(self)
        self.title = _secondary("", self)

        # -- where it begins: the sequence's day, or a date of its own --------------------
        self.begin = QWidget(self)
        self.date = QDateEdit(self.begin)
        self.date.setCalendarPopup(True)
        self.date.setLocale(QLocale(QLocale.Language.English))
        self.date.setDisplayFormat(DATE_FORMAT)
        self.date.setToolTip("The day this milestone's work begins")
        # Arrow steps commit as they land; typing commits on Enter or focus-out, so a
        # half-typed year never reaches the model.
        self.date.setKeyboardTracking(False)
        self.date.dateChanged.connect(self._commit_date)

        self.clear = QToolButton(self.begin)
        self.clear.setAutoRaise(True)
        self.clear.setIcon(close_icon(self.palette().text().color().name()))
        self.clear.setToolTip("Begin when the previous milestone lands")
        self.clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear.clicked.connect(lambda: self.start_changed.emit(self.key, None))

        self.set_date = QToolButton(self.begin)
        self.set_date.setObjectName("ToolbarButton")
        self.set_date.setText("Begin…")
        self.set_date.setToolTip("Begin this milestone's work on a date of its own")
        self.set_date.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_date.clicked.connect(
            lambda: self.start_changed.emit(self.key, self._default_start)
        )
        begin = QHBoxLayout(self.begin)
        begin.setContentsMargins(0, 0, 0, 0)
        begin.setSpacing(LINE_GAP)
        begin.addStretch(1)
        begin.addWidget(self.set_date)
        begin.addWidget(self.date)
        begin.addWidget(self.clear)
        # One width whichever control shows, so the columns to the right line up.
        self.begin.setFixedWidth(
            self.date.sizeHint().width() + LINE_GAP + self.clear.sizeHint().width()
        )

        # -- where it lands, and how long it took ---------------------------------------
        self.when = QLabel(self)
        self.when.setMinimumWidth(date_width)
        self.when.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.days = _secondary("", self)
        self.days.setMinimumWidth(days_width)
        self.days.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        # How much of the work through this milestone has landed.
        self.progress = QLabel(self)
        self.progress.setMinimumWidth(days_width)
        self.progress.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        words = QVBoxLayout()
        words.setContentsMargins(0, 0, 0, 0)
        words.setSpacing(LINE_GAP)
        words.addWidget(self.name)
        words.addWidget(self.title)

        row = QHBoxLayout(self)
        row.setContentsMargins(ROW_PAD_H, ROW_PAD_V, ROW_PAD_H, ROW_PAD_V)
        row.setSpacing(COLUMN_GAP)
        row.addWidget(self.swatch)
        row.addWidget(self.dot)
        row.addLayout(words, 1)
        row.addWidget(self.begin)
        row.addWidget(self.when)
        row.addWidget(self.days)
        row.addWidget(self.progress)

    def load(self, entry: MilestoneEntry, found: Palette) -> None:
        self._loading = True
        try:
            milestone = entry.is_milestone
            self.swatch.setVisible(milestone)
            self.dot.setVisible(not milestone)
            self.swatch.show_color(entry.color, entry.chosen, found)
            self.dot.setPixmap(dot_icon(entry.color).pixmap(ICON, ICON))
            self.name.setText(entry.label)
            self.name.setObjectName("" if milestone else "InspectorNote")
            self.title.setText(entry.title)
            self.title.setVisible(bool(entry.title) and entry.title != entry.label)
            self._default_start = entry.default_start
            dated = entry.start is not None
            self.begin.setVisible(milestone)
            self.date.setVisible(dated)
            self.clear.setVisible(dated)
            self.set_date.setVisible(not dated)
            if entry.start is not None:
                self.date.setDate(QDate(entry.start.year, entry.start.month, entry.start.day))
            self.when.setText(format_date(entry.finish) if entry.finish else "—")
            self.days.setText(format_days(entry.days))
            self.progress.setText(percent(entry.share))
            self.progress.setToolTip(landed_words(entry.landed))
            steps = f"{entry.steps} step{'s' if entry.steps != 1 else ''}"
            tip = (
                f"{steps} — nothing estimated, so no date"
                if entry.finish is None
                else f"{steps} · lands {format_date(entry.finish)}"
            )
            if entry.asked is not None:
                self.when.setText(f"⚠ {self.when.text()}")
                tip += (
                    f"\nAsked to begin {format_date(entry.asked)}, but the previous milestone "
                    "lands later — it runs after that instead."
                )
            self.setToolTip(tip)
        finally:
            self._loading = False

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

    def _commit_date(self) -> None:
        if self._loading:
            return
        picked = self.date.date()
        self.start_changed.emit(self.key, date(picked.year(), picked.month(), picked.day()))


class MilestoneList(QWidget):
    """The stretches in sequence, one row each, kept across refreshes; the whole under a
    rule.

    Rows are reconciled by key rather than rebuilt: the field the user is typing in is
    the one the model change came from, and destroying it mid-signal is how a widget dies
    with its C++ side already gone. Gone milestones leave, new ones join, and the order
    follows the graph.
    """

    picked = Signal(str)
    activated = Signal(str)
    start_changed = Signal(str, object)
    color_changed = Signal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: dict[str, MilestoneRow] = {}
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.empty = _secondary("No milestones yet · Step ▸ Type ▸ Milestone", self)
        self.empty.setWordWrap(True)
        self.total = QWidget(self)
        self.total_rule = card_rule(self.total)
        self.total_when = QLabel(self.total)
        self.total_days = _secondary("", self.total)
        self.total_progress = QLabel(self.total)
        total_row = QHBoxLayout()
        total_row.setContentsMargins(ROW_PAD_H, ROW_PAD_V, ROW_PAD_H, ROW_PAD_V)
        total_row.setSpacing(COLUMN_GAP)
        total_row.addSpacing(SWATCH)
        total_row.addWidget(_secondary("All work", self.total), 1)
        total_row.addWidget(self.total_when)
        total_row.addWidget(self.total_days)
        total_row.addWidget(self.total_progress)
        total_layout = QVBoxLayout(self.total)
        total_layout.setContentsMargins(0, 0, 0, 0)
        total_layout.setSpacing(0)
        total_layout.addWidget(self.total_rule)
        total_layout.addLayout(total_row)
        self._layout.addWidget(self.total)
        self._layout.addWidget(self.empty)

    def show_entries(
        self,
        entries: list[MilestoneEntry],
        selected: str | None,
        *,
        found: Palette,
        finish: date | None,
        days: float,
        share: float | None = None,
    ) -> None:
        wanted = {entry.key for entry in entries}
        for key in tuple(self._rows):
            if key not in wanted:
                gone = self._rows.pop(key)
                self._layout.removeWidget(gone)
                gone.hide()
                gone.deleteLater()
        # Both answer columns are as wide as their widest plausible text, so the Begin
        # controls line up down the list whatever each row's numbers happen to be.
        date_width = self.fontMetrics().horizontalAdvance("⚠ 30 September") + COLUMN_GAP
        days_width = self.fontMetrics().horizontalAdvance("99.9w")
        for index, entry in enumerate(entries):
            row = self._rows.get(entry.key)
            if row is None:
                row = MilestoneRow(entry.key, date_width, days_width, self)
                row.picked.connect(self.picked)
                row.activated.connect(self.activated)
                row.start_changed.connect(self.start_changed)
                row.color_changed.connect(self.color_changed)
                self._rows[entry.key] = row
            self._layout.removeWidget(row)
            self._layout.insertWidget(index, row)
            row.load(entry, found)
            row.set_selected(entry.is_milestone and entry.key == selected)
        # Kept in layout order, so ``keys`` reads the dict and never the layout: a
        # QLayoutItem wrapper ``itemAt()`` hands out is a double delete waiting for a gc
        # pass (CLAUDE.md's crash notes).
        self._rows = {entry.key: self._rows[entry.key] for entry in entries}
        # The whole is worth a line of its own only when it is more than one stretch.
        self.total.setVisible(len(entries) > 1)
        self.total_when.setText(format_date(finish) if finish else "—")
        self.total_when.setMinimumWidth(date_width)
        self.total_when.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.total_days.setMinimumWidth(days_width)
        self.total_days.setText(format_days(days))
        self.total_progress.setMinimumWidth(days_width)
        self.total_progress.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.total_progress.setText(percent(share))
        self.empty.setVisible(not any(entry.is_milestone for entry in entries))

    def row(self, step_id: StepId) -> MilestoneRow:
        return self._rows[step_id]

    @property
    def rows(self) -> tuple[MilestoneRow, ...]:
        """Top to bottom, as laid out — the remainder row included."""
        return tuple(self._rows.values())

    @property
    def keys(self) -> tuple[StepId, ...]:
        """The milestones top to bottom, as laid out."""
        return tuple(key for key in self._rows if key)
