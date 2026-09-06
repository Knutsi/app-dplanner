"""The milestones in sequence, the start dates they are given, and the palette picker.

Two lists under the staffing grid, both fed from one :class:`MilestoneEntry` per stretch.
**Start dates** is what you set: the project's own start, and for each milestone the
sequence's day or a date of its own — the *Begin…* button turns the one into a field
pre-filled with the other, so choosing a date is one click and an edit, and the cross
beside it hands the decision back to the sequence. **Milestones** is what that answers:
every stretch of work in the order the graph lands them — its shade, its label, where it
lands, how long its stretch took and how much of it has landed. The work after the last
milestone is a row too, without a swatch menu; and the row that leads the list is *All
milestones*, the whole plan on one line, picked when no milestone is.

Picking a row emphasises that milestone everywhere on the right — its stretch in the
calendar, its segment in the charts — and picking *All milestones* shows them all alike.
Double-clicking opens the step's details, the one gesture every table in the application
answers. Nothing here writes: a row reports the date or the colour it was given through a
signal, the picker reports a palette id, and the hosting page turns each into the undoable
command — the contract every input here keeps.

Rows are reconciled by key rather than rebuilt (:func:`reconcile`): the field the user is
typing in is the one the model change came from, and destroying it mid-signal is how a
widget dies with its C++ side already gone. Gone milestones leave, new ones join, and
the order follows the graph.

Milestones are shaded from one colour map — the project's :class:`Palette` — and the
picker offers the maps by name with a strip of each. The swatch on a row offers the map's
shades, a custom colour, and *Automatic*, which hands the shade back to the sequence.
"""

from collections.abc import Callable, Sequence
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
# A start-date row is a label and one control: half the padding of a rich row.
DATE_ROW_PAD_V = 4

DOT = 10
SWATCH = 24  # A hit target comfortably past the 24 px minimum.
ICON = 16
STRIP_WIDTH = 56
STRIP_HEIGHT = 12
STRIP_RADIUS = 3

# The date fields use the words the calendar uses, so a day reads one way everywhere —
# English explicitly, for ``format_date``'s reason.
DATE_FORMAT = "d MMM yyyy"

# The row that stands for the whole plan — every milestone at once.
ALL_KEY = "*"
ALL_LABEL = "All milestones"


@dataclass(frozen=True)
class MilestoneEntry:
    """One stretch as the lists show it: a milestone, the work after the last one (key
    ``""``), or the whole (:data:`ALL_KEY`)."""

    key: str
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
        return bool(self.key) and self.key != ALL_KEY

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


def reconcile[W: QWidget, E](
    layout: QVBoxLayout,
    rows: dict[str, W],
    entries: Sequence[E],
    key_of: Callable[[E], str],
    make: Callable[[E], W],
    *,
    first: int = 0,
) -> dict[str, W]:
    """The rows for ``entries``, in their order, from ``first`` in the layout: gone keys
    leave, new keys are made, the rest move. Returns the rows keyed in layout order, so
    a reader never asks the layout — a QLayoutItem wrapper ``itemAt()`` hands out is a
    double delete waiting for a gc pass (CLAUDE.md's crash notes)."""
    wanted = {key_of(entry) for entry in entries}
    for key in tuple(rows):
        if key not in wanted:
            gone = rows.pop(key)
            layout.removeWidget(gone)
            gone.hide()
            gone.deleteLater()
    kept: dict[str, W] = {}
    for index, entry in enumerate(entries):
        key = key_of(entry)
        row = rows.get(key)
        if row is None:
            row = make(entry)
        layout.removeWidget(row)
        layout.insertWidget(first + index, row)
        kept[key] = row
    return kept


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


def _date_edit(parent: QWidget, tip: str) -> QDateEdit:
    edit = QDateEdit(parent)
    edit.setCalendarPopup(True)
    edit.setLocale(QLocale(QLocale.Language.English))
    edit.setDisplayFormat(DATE_FORMAT)
    edit.setToolTip(tip)
    # Arrow steps commit as they land; typing commits on Enter or focus-out, so a
    # half-typed year never reaches the model.
    edit.setKeyboardTracking(False)
    return edit


def _to_date(picked: QDate) -> date:
    return date(picked.year(), picked.month(), picked.day())


class StartRow(QWidget):
    """One start date: a name, and the sequence's day or a date of its own.

    ``start_changed`` carries the key and the date, or None for *begin when the previous
    milestone lands*. A row that is always dated — the project's own start — shows the
    field alone, with neither *Begin…* nor the cross.
    """

    start_changed = Signal(str, object)  # (key, date | None)

    def __init__(self, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self._loading = False
        self._default_start = date.today()

        self.name = QLabel(self)

        self.controls = QWidget(self)
        self.date = _date_edit(self.controls, "The day this work begins")
        self.date.dateChanged.connect(self._commit_date)

        self.clear = QToolButton(self.controls)
        self.clear.setAutoRaise(True)
        self.clear.setIcon(close_icon(self.palette().text().color().name()))
        self.clear.setToolTip("Begin when the previous milestone lands")
        self.clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear.clicked.connect(lambda: self.start_changed.emit(self.key, None))

        self.set_date = QToolButton(self.controls)
        self.set_date.setObjectName("ToolbarButton")
        self.set_date.setText("Begin…")
        self.set_date.setToolTip("Begin this milestone's work on a date of its own")
        self.set_date.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_date.clicked.connect(
            lambda: self.start_changed.emit(self.key, self._default_start)
        )
        controls = QHBoxLayout(self.controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(LINE_GAP)
        controls.addStretch(1)
        controls.addWidget(self.set_date)
        controls.addWidget(self.date)
        controls.addWidget(self.clear)
        # One width whichever control shows, so the column lines up down the table.
        self.controls.setFixedWidth(
            self.date.sizeHint().width() + LINE_GAP + self.clear.sizeHint().width()
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(ROW_PAD_H, DATE_ROW_PAD_V, ROW_PAD_H, DATE_ROW_PAD_V)
        row.setSpacing(COLUMN_GAP)
        row.addWidget(self.name, 1)
        row.addWidget(self.controls)

    def load(
        self, label: str, start: date | None, default_start: date, *, optional: bool = True
    ) -> None:
        """``optional`` rows may hand the date back to the sequence; the project's start
        cannot, so it shows the field alone."""
        self._loading = True
        try:
            self.name.setText(label)
            self._default_start = default_start
            dated = start is not None
            self.date.setVisible(dated)
            self.clear.setVisible(dated and optional)
            self.set_date.setVisible(not dated)
            if start is not None:
                self.date.setDate(QDate(start.year, start.month, start.day))
        finally:
            self._loading = False

    def _commit_date(self) -> None:
        if not self._loading:
            self.start_changed.emit(self.key, _to_date(self.date.date()))


class StartDates(QWidget):
    """The start dates in sequence: the project's, then one row per milestone.

    ``project_changed`` carries the project's new start; ``start_changed`` a milestone's
    (the step id, and the date or None). Kept across refreshes like the milestone list.
    """

    project_changed = Signal(object)  # a datetime.date
    start_changed = Signal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: dict[str, StartRow] = {}
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.project = StartRow("", self)
        self.project.start_changed.connect(lambda _key, when: self.project_changed.emit(when))
        self._layout.addWidget(self.project)

    def show_entries(self, entries: Sequence[MilestoneEntry], project_start: date) -> None:
        self.project.load("Project", project_start, project_start, optional=False)
        milestones = [entry for entry in entries if entry.is_milestone]
        self._rows = reconcile(
            self._layout, self._rows, milestones, lambda e: e.key, self._make, first=1
        )
        for entry in milestones:
            self._rows[entry.key].load(entry.label, entry.start, entry.default_start)

    def _make(self, entry: MilestoneEntry) -> StartRow:
        row = StartRow(entry.key, self)
        row.start_changed.connect(self.start_changed)
        return row

    def row(self, step_id: StepId) -> StartRow:
        return self._rows[step_id]

    @property
    def keys(self) -> tuple[StepId, ...]:
        return tuple(self._rows)


class MilestoneRow(QWidget):
    """One stretch: swatch, label over title, where it lands, how long, how much landed.

    A selection ring when it is the emphasised one, and the two gestures — press to pick,
    double-click to open. The whole (:data:`ALL_KEY`) and the remainder (key "") have a
    dot in place of the swatch menu: there is no milestone to colour.
    """

    picked = Signal(str)
    activated = Signal(str)
    color_changed = Signal(str, object)  # (step id, hex | None)

    def __init__(
        self, key: str, date_width: int, days_width: int, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.key = key
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.swatch = Swatch(self)
        self.swatch.color_picked.connect(lambda color: self.color_changed.emit(self.key, color))
        self.dot = QLabel(self)  # The whole's and the remainder's colour, with no menu.
        self.dot.setFixedSize(SWATCH, SWATCH)
        self.dot.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.name = QLabel(self)
        self.title = _secondary("", self)

        # -- where it lands, how long it took, how much of it has landed ------------------
        self.when = QLabel(self)
        self.when.setMinimumWidth(date_width)
        self.when.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.days = _secondary("", self)
        self.days.setMinimumWidth(days_width)
        self.days.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
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
        row.addWidget(self.when)
        row.addWidget(self.days)
        row.addWidget(self.progress)

    def load(self, entry: MilestoneEntry, found: Palette) -> None:
        milestone = entry.is_milestone
        self.swatch.setVisible(milestone)
        self.dot.setVisible(not milestone)
        self.swatch.show_color(entry.color, entry.chosen, found)
        self.dot.setPixmap(dot_icon(entry.color).pixmap(ICON, ICON))
        self.name.setText(entry.label)
        self.name.setObjectName("InspectorNote" if not entry.key else "")
        self.title.setText(entry.title)
        self.title.setVisible(bool(entry.title) and entry.title != entry.label)
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
        if event.button() == Qt.MouseButton.LeftButton and self.key and self.key != ALL_KEY:
            self.activated.emit(self.key)
        super().mouseDoubleClickEvent(event)


class MilestoneList(QWidget):
    """The stretches in sequence, one row each, kept across refreshes.

    ``selected`` is the key whose row wears the ring: a milestone's id, or
    :data:`ALL_KEY` when the whole is what is being looked at.
    """

    picked = Signal(str)
    activated = Signal(str)
    color_changed = Signal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: dict[str, MilestoneRow] = {}
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.empty = _secondary("No milestones yet · Step ▸ Type ▸ Milestone", self)
        self.empty.setWordWrap(True)
        self._layout.addWidget(self.empty)

    def show_entries(
        self, entries: Sequence[MilestoneEntry], selected: str, *, found: Palette
    ) -> None:
        # Both answer columns are as wide as their widest plausible text, so the columns
        # line up down the list whatever each row's numbers happen to be.
        date_width = self.fontMetrics().horizontalAdvance("⚠ 30 September") + COLUMN_GAP
        days_width = self.fontMetrics().horizontalAdvance("99.9w")

        def make(entry: MilestoneEntry) -> MilestoneRow:
            row = MilestoneRow(entry.key, date_width, days_width, self)
            row.picked.connect(self.picked)
            row.activated.connect(self.activated)
            row.color_changed.connect(self.color_changed)
            return row

        self._rows = reconcile(self._layout, self._rows, entries, lambda e: e.key, make)
        for entry in entries:
            row = self._rows[entry.key]
            row.load(entry, found)
            row.set_selected(entry.key == selected)
        self.empty.setVisible(not any(entry.is_milestone for entry in entries))

    def row(self, step_id: StepId) -> MilestoneRow:
        return self._rows[step_id]

    @property
    def rows(self) -> tuple[MilestoneRow, ...]:
        """Top to bottom, as laid out — the whole and the remainder included."""
        return tuple(self._rows.values())

    @property
    def keys(self) -> tuple[StepId, ...]:
        """The milestones top to bottom, as laid out."""
        return tuple(key for key in self._rows if key and key != ALL_KEY)
