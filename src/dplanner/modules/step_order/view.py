"""The order view's table: one row per step, in the order the work can be done.

A table rather than a nested list, because the thing being shown *is* a sorted sequence and
the first thing you want from one is a position. The wave rides along as a column: two steps
sharing a wave can be started together, and the first wave is the answer to "what now".

Every row wears the glyph of what it is — a tag for a milestone, the layer stack for a
feature, a card for a work step — and the host can *narrow* the table to the steps or to
the features: the rows the other kind occupies are hidden, never removed, so the numbering,
the accumulated days and the milestone rules still read as the whole order. A milestone
is never hidden; with only the milestones and the features showing, the table is the
roadmap — what each milestone adds.

The schedule columns come from ``domain/schedule.py`` and are rendered with its own
formatter, so this table and ``dplanner schedule show`` cannot express one number two ways.

Rebuilt whenever the graph changes. A project holds tens of steps, so a whole redraw is
cheaper to read than a diff and cannot go stale.
"""

from collections.abc import Callable, Sequence

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from dplanner.domain.model import StepId
from dplanner.domain.schedule import Scheduled, format_date, format_days
from dplanner.modules.step_order.export import since_milestone
from dplanner.theme.icons import key_badge_icon, layers_icon, step_icon
from dplanner.theme.tones import recoloured

COLUMNS = ("#", "Step", "Wave", "Estimate", "Accumulated", "Since milestone", "Date", "")
TITLE_COLUMN = 1
ESTIMATE_COLUMN = 3
ACCUMULATED_COLUMN = 4
SINCE_MILESTONE_COLUMN = 5
DATE_COLUMN = 6
ASPECTS_COLUMN = 7

# Numbers line up on the right; everything else — headers included (DESIGN.md's *Tables*) —
# reads from the left.
NUMERIC_COLUMNS = (ESTIMATE_COLUMN, ACCUMULATED_COLUMN, SINCE_MILESTONE_COLUMN)

# The step id on a row, so a click can say which step it means.
STEP_ROLE = int(Qt.ItemDataRole.UserRole) + 1
# The milestone label on every cell of a milestone row, so the delegate can mark it from any
# column's index. Falsy on ordinary rows.
MILESTONE_ROLE = int(Qt.ItemDataRole.UserRole) + 2
# The milestone's own shade of the project's colour map, as "#rrggbb"; "" is the family.
COLOR_ROLE = int(Qt.ItemDataRole.UserRole) + 3

# DESIGN.md's row metrics for a list of rich items; a milestone row gets air under its rule.
ROW_HEIGHT = 28
MILESTONE_ROW_EXTRA = 8

# What a row is, read off the kind vocabulary: a milestone is always shown, a feature and a
# work step each follow their own switch on the host.
KIND_MILESTONE = "milestone"
KIND_FEATURE = "feature"
KIND_STEP = "step"

# The milestone row's marks, low-alpha so they read on every theme (DESIGN.md exception #2).
# The rule closes the block of work that lands in the milestone. The colours here are the
# family every milestone wore before the project's colour map reached this table; a row that
# carries a shade (``COLOR_ROLE``) is these alphas over *its* hue, so the row, the card on
# the canvas and the band in the calendar are one milestone in one colour.
MILESTONE_ROW_TINT = QColor(150, 130, 220, 22)
MILESTONE_RULE = QColor(150, 130, 220, 160)

# Secondary text as opacity rather than a theme colour: an item has only the palette, and an
# alpha-derived secondary is theme-independent by construction (DESIGN.md exception #1).
SECONDARY_ALPHA = 160

_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def _kind(kinds: tuple[str, ...], milestone: bool) -> str:
    """Which switch a row follows. A milestone answers to none; a feature that is also a
    milestone is a milestone first, the way its icon leads with the tag."""
    if milestone or "tag" in kinds:
        return KIND_MILESTONE
    return KIND_FEATURE if "layers" in kinds else KIND_STEP


class _MilestoneRowDelegate(QStyledItemDelegate):
    """Marks a milestone row: a low-alpha tint under it and a rule along its bottom.

    The grid is off, so each cell's bottom segment joins into the one horizontal line in
    the table — "everything above this lands in the milestone". The flag and the milestone's
    shade are read off the index (``MILESTONE_ROLE``, ``COLOR_ROLE``), never asked of a
    callback, so painting stays a pure function of the model.
    """

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        if not index.data(MILESTONE_ROLE):
            super().paint(painter, option, index)
            return
        shade = index.data(COLOR_ROLE) or ""
        tint = recoloured(MILESTONE_ROW_TINT, shade) if shade else MILESTONE_ROW_TINT
        rule = recoloured(MILESTONE_RULE, shade) if shade else MILESTONE_RULE
        painter.fillRect(option.rect, tint)
        super().paint(painter, option, index)  # Text and selection paint over the tint.
        painter.save()
        painter.setPen(QPen(rule, 1.0))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        painter.restore()


class OrderTable(QTableWidget):
    """Steps in topological order: index, name, wave, what they cost, when they land."""

    def __init__(
        self,
        wave_label: Callable[[int], str],
        step_aspects: Callable[[StepId], list[str]],
        milestone_label: Callable[[StepId], str] = lambda _step_id: "",
        step_icons: Callable[[StepId], tuple[str, ...]] = lambda _step_id: (),
        milestone_color: Callable[[StepId], str] = lambda _step_id: "",
        step_key: Callable[[StepId], str] = lambda _step_id: "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(0, len(COLUMNS), parent)
        self.setObjectName("OrderTable")
        self._wave_label = wave_label
        self._step_aspects = step_aspects
        self._milestone_label = milestone_label
        self._step_icons = step_icons
        self._milestone_color = milestone_color
        self._step_key = step_key
        self._kinds: list[str] = []  # One per row, in row order.
        self._shown = {KIND_STEP: True, KIND_FEATURE: True}
        self.setItemDelegate(_MilestoneRowDelegate(self))

        self.setHorizontalHeaderLabels(list(COLUMNS))
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setWordWrap(False)

        header = self.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for column in range(len(COLUMNS)):
            mode = (
                QHeaderView.ResizeMode.Interactive
                if column == TITLE_COLUMN
                else QHeaderView.ResizeMode.ResizeToContents
            )
            header.setSectionResizeMode(column, mode)
        # The last column takes the slack, so the aspects have room and nothing else moves.
        header.setStretchLastSection(True)
        header.setHighlightSections(False)

    def show_order(self, order: Sequence[Scheduled]) -> None:
        selected = self.selected_step()
        spans = since_milestone(order, self._milestone_label)
        self.setRowCount(len(order))
        self._kinds = []
        for row, scheduled in enumerate(order):
            place = scheduled.place
            span = spans.get(place.step.id)
            cells = (
                str(place.index),
                place.step.title or "Untitled step",
                self._wave_label(place.wave - 1),
                format_days(scheduled.days),
                format_days(scheduled.accumulated),
                format_days(span) if span is not None else "",
                format_date(scheduled.finish) if scheduled.finish else "",
                " · ".join(self._step_aspects(place.step.id)),
            )
            milestone = self._milestone_label(place.step.id)
            kinds = self._step_icons(place.step.id)
            shade = self._milestone_color(place.step.id) if milestone else ""
            self._kinds.append(_kind(kinds, bool(milestone)))
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(STEP_ROLE, place.step.id)
                item.setData(MILESTONE_ROLE, milestone)
                item.setData(COLOR_ROLE, shade)
                # A milestone's own answers — its name, the span it closes, its date — read
                # bold at full strength, so a glance down the column finds the milestones;
                # the foreground is deliberately not set, so it stays the palette's and live.
                highlighted = bool(milestone) and column in (
                    TITLE_COLUMN,
                    SINCE_MILESTONE_COLUMN,
                    DATE_COLUMN,
                )
                if column != TITLE_COLUMN and not highlighted:
                    faded = self.palette().text().color()
                    faded.setAlpha(SECONDARY_ALPHA)
                    item.setForeground(faded)
                if highlighted:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                if column == TITLE_COLUMN:
                    item.setIcon(self._title_icon(kinds, place.step.id, shade))
                if column in NUMERIC_COLUMNS:
                    item.setTextAlignment(_RIGHT)
                self.setItem(row, column, item)
            self.setRowHeight(row, ROW_HEIGHT + (MILESTONE_ROW_EXTRA if milestone else 0))
        # A column of blanks says less than an absent one: nothing estimated, no Date column;
        # no milestone to measure to (or no days to measure with), no Since-milestone column.
        undated = all(s.finish is None for s in order)
        self.setColumnHidden(DATE_COLUMN, undated)
        self.setColumnHidden(SINCE_MILESTONE_COLUMN, undated or not spans)
        self.resizeColumnToContents(TITLE_COLUMN)
        self._apply_filter()
        if selected is not None:
            self.select_step(selected)

    def show_kinds(self, *, steps: bool, features: bool) -> None:
        """Narrow the table to the work steps, the features, both or — with neither — the
        milestones alone. Rows hide rather than leave, so the order stays whole."""
        self._shown = {KIND_STEP: steps, KIND_FEATURE: features}
        self._apply_filter()

    def _apply_filter(self) -> None:
        for row, kind in enumerate(self._kinds):
            self.setRowHidden(row, not self._shown.get(kind, True))

    def kind_at(self, row: int) -> str:
        return self._kinds[row]

    def _title_icon(self, kinds: tuple[str, ...], step_id: StepId, shade: str) -> QIcon:
        """What the row is, in the canvas medallions' vocabulary: the **key as a badge** for
        a milestone, the layer stack for a feature, the card for a work step.

        One icon per row: a step that is several things at once leads with the rarer claim
        ("tag" sorts first), and the trailing aspects column still says the rest. A milestone
        wears its key rather than a tag glyph (DESIGN.md's *Tables*) — the key is what a
        milestone is known by across the graph — in its own shade of the project's map.
        """
        faded = QColor(self.palette().text().color())
        faded.setAlpha(SECONDARY_ALPHA)
        if "tag" in kinds:
            return key_badge_icon(self._step_key(step_id), shade or MILESTONE_RULE)
        if "layers" in kinds:
            return layers_icon(faded)
        return step_icon(faded)

    def step_at(self, row: int) -> StepId | None:
        item = self.item(row, 0)
        if item is None:
            return None
        found = item.data(STEP_ROLE)
        return found if isinstance(found, str) else None

    def selected_step(self) -> StepId | None:
        return self.step_at(self.currentRow()) if self.currentRow() >= 0 else None

    def select_step(self, step_id: StepId) -> None:
        for row in range(self.rowCount()):
            if self.step_at(row) == step_id:
                self.selectRow(row)
                return
