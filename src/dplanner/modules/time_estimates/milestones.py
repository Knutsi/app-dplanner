"""The milestones in sequence, one table, and the palette picker.

**One row per stretch, and everything about it on that row.** Its key badge in its shade, its
label over the step's own title, when it begins — the day the sequence gives it, quieter, or a
day of its own — where it lands, how long its stretch takes and how much of it has landed.
The row that leads the table is the whole plan (*All milestones*, or the one stretch there
is), and what *it* begins on is the project's own start. The work after the last milestone
is a row too, with no beginning to set: it starts when the last milestone lands.

It was two lists — **Start dates** above **Milestones** — then one list of hand-laid rows,
and it is a table now, because a reader compares landings, days and what has landed down a
column. A day is set where it is read: pick the row and type, or double-click the day, with
the calendar a click away; *Begin When the Previous Lands* on the strip hands the decision
back to the sequence, and *Milestone Colour…* gives the picked milestone a shade of its own.

Picking a row emphasises that milestone everywhere on the right — its stretch in the
calendar, its segment in the charts — and picking *All milestones* shows them all alike.
Double-clicking opens the step's details, the one gesture every table in the application
answers. Nothing here writes: the table reports the day it was given through a signal, the
picker reports a palette id, and the hosting page turns each into the undoable command.

A refresh over the same stretches writes their cells in place rather than rebuilding the
table, so the day being edited — the one the model change came from — stays where it is.
Milestones are shaded from one colour map, the project's :class:`Palette`, and the picker
offers the maps by name with a strip of each.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QComboBox, QWidget

from dplanner.domain.model import StepId
from dplanner.domain.schedule import format_date, format_days, short_date
from dplanner.framework.list_rows import HOST_ROLE
from dplanner.framework.table import DATE_FORMAT, Cell, Column, DateEditor, Table
from dplanner.modules.time_estimates.progress import Tally
from dplanner.theme.icons import PALETTE_STRIP, key_badge_icon, palette_strip_icon
from dplanner.theme.palettes import PALETTES, Palette

DOT = 10
ICON = 16

__all__ = ["DATE_FORMAT"]  # The date fields on the strip print a day the way the table does.

# The row that stands for the whole plan — every milestone at once.
ALL_KEY = "*"
ALL_LABEL = "All milestones"

MILESTONE_COLUMNS = (
    Column("Milestone", glyph=True, detail=True, resize="stretch"),
    Column("Begins", editor=DateEditor(words=short_date)),
    Column("Lands"),
    Column("Days", numeric=True),
    Column("Landed", numeric=True),
)
MILESTONE_COLUMN, BEGINS_COLUMN, LANDS_COLUMN, DAYS_COLUMN, LANDED_COLUMN = range(5)
KEY_ROLE = HOST_ROLE  # A row's key: a milestone's id, ALL_KEY, or "" for the remainder.
COLOR_ROLE = HOST_ROLE + 1  # The row's shade, as a hex name.


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
    # Whose beginning the row's control sets: the project's, on the row that leads the
    # list, or the milestone's own. A stretch that begins when the previous one lands
    # decides nothing and shows no control.
    sets_project: bool = False
    # The milestone's key (``M7``), worn as a badge in its shade; "" for the whole and the rest.
    badge: str = ""
    # What has landed toward this milestone — everything through its stretch.
    landed: Tally = field(default_factory=Tally)

    @property
    def is_milestone(self) -> bool:
        return bool(self.key) and self.key != ALL_KEY

    @property
    def share(self) -> float | None:
        return self.landed.share()


def percent(share: float | None) -> str:
    return "—" if share is None else f"{share:.0%}"


def landed_words(landed: Tally) -> str:
    """The percentage's tooltip: the days it is a share of, and the count beside them."""
    return (
        f"{format_days(landed.done_days)} of {format_days(landed.days)} estimated · "
        f"{landed.done} of {landed.steps} steps done"
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


class PalettePicker(QComboBox):
    """The colour maps by name, each with its strip; ``palette_picked`` carries the id."""

    palette_picked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loading = False
        self.setIconSize(PALETTE_STRIP)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        for found in PALETTES:
            self.addItem(palette_strip_icon(found), found.name, found.id)
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


def _tip(entry: MilestoneEntry) -> str:
    steps = f"{entry.steps} step{'s' if entry.steps != 1 else ''}"
    title = entry.title if entry.title and entry.title != entry.label else ""
    name = f"{entry.label} — {title}" if title else entry.label
    tip = (
        f"{name}\n{steps} — nothing estimated, so no date"
        if entry.finish is None
        else f"{name}\n{steps} · lands {format_date(entry.finish)}"
    )
    if entry.asked is not None:
        tip += (
            f"\nAsked to begin {format_date(entry.asked)}, but the previous milestone "
            "lands later — it runs after that instead."
        )
    return tip


class MilestoneTable(Table):
    """The stretches in sequence, a row each — what the page's calendar and plots are dated by."""

    picked = Signal(str)  # A row's key.
    activated = Signal(str)  # A milestone's step id.
    start_changed = Signal(str, object)  # (step id, the day it was given)
    project_changed = Signal(object)  # The day the project's work begins.

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(MILESTONE_COLUMNS, parent=parent)
        self._entries: dict[str, MilestoneEntry] = {}
        self._keys: tuple[str, ...] = ()
        self.itemSelectionChanged.connect(self._on_pick)
        self.cellActivated.connect(self._on_activated)
        self.edited.connect(self._on_edited)

    def show_entries(self, entries: Sequence[MilestoneEntry], selected: str) -> None:
        keys = tuple(entry.key for entry in entries)
        self._entries = {entry.key: entry for entry in entries}
        # Quiet while the rows are written: a refresh is not a pick.
        self.blockSignals(True)
        try:
            if keys != self._keys:
                self.clear_rows()
                for entry in entries:
                    self.add_row(self._cells(entry), data={KEY_ROLE: entry.key})
                self._keys = keys
            else:
                for row, entry in enumerate(entries):
                    for column, cell in enumerate(self._cells(entry)):
                        self.set_cell(row, column, cell)
            for row, entry in enumerate(entries):
                item = self.item(row, MILESTONE_COLUMN)
                if item is not None:
                    item.setData(COLOR_ROLE, entry.color.name())
            chosen = self.row_of(selected)
            if chosen is not None:
                self.selectRow(chosen)
        finally:
            self.blockSignals(False)

    @staticmethod
    def _cells(entry: MilestoneEntry) -> tuple[Cell, ...]:
        glyph = (
            key_badge_icon(entry.badge, entry.color)
            if entry.is_milestone and entry.badge
            else dot_icon(entry.color)
        )
        title = entry.title if entry.title and entry.title != entry.label else ""
        tip = _tip(entry)
        own = entry.start is not None
        lands = format_date(entry.finish) if entry.finish else "—"
        return (
            Cell(
                entry.label, detail=title, glyph=glyph, emphasis=entry.key == ALL_KEY, tooltip=tip
            ),
            # The day the sequence gives it reads quieter than a day of its own; the remainder
            # begins when the last milestone lands, and has nothing to set.
            Cell(
                value=entry.start if own else entry.default_start,
                secondary=not own,
                editable=entry.sets_project or entry.is_milestone,
            ),
            Cell(f"⚠ {lands}" if entry.asked is not None else lands, tooltip=tip),
            Cell(format_days(entry.days), secondary=True),
            Cell(percent(entry.share), tooltip=landed_words(entry.landed)),
        )

    @property
    def keys(self) -> tuple[StepId, ...]:
        """The milestones top to bottom — the whole and the remainder aside."""
        return tuple(key for key in self._keys if key and key != ALL_KEY)

    def key_at(self, row: int) -> str | None:
        item = self.item(row, MILESTONE_COLUMN)
        found = item.data(KEY_ROLE) if item is not None else None
        return found if isinstance(found, str) else None

    def row_of(self, key: str) -> int | None:
        return next((row for row, found in enumerate(self._keys) if found == key), None)

    def picked_key(self) -> str | None:
        rows = sorted({index.row() for index in self.selectedIndexes()})
        return self.key_at(rows[0]) if rows else None

    def _on_pick(self) -> None:
        key = self.picked_key()
        if key is not None:
            self.picked.emit(key)

    def _on_activated(self, row: int, column: int) -> None:
        key = self.key_at(row)
        if column != BEGINS_COLUMN and key and key != ALL_KEY:
            self.activated.emit(key)

    def _on_edited(self, row: int, column: int, value: object) -> None:
        key = self.key_at(row)
        entry = self._entries.get(key) if key is not None else None
        if column != BEGINS_COLUMN or entry is None or not isinstance(value, date):
            return
        if entry.sets_project:
            self.project_changed.emit(value)
        elif entry.is_milestone:
            self.start_changed.emit(entry.key, value)
