"""The staffing heatmap, and the focus control the calendar lens is priced with.

One custom-painted grid instead of two tables of strings, because the report's job is
*magnitude*: which staffings are fast, where the floor is, which axis still buys time.
Each tile carries one number (through ``domain/schedule.py``'s formatter, so the tab and
``dplanner schedule matrix`` cannot print one number two ways) over a sequential tint —
one hue, more time is more ink. The tint is reinforcement, never the only channel: the
value is printed in every tile, and the flat lightest region *is* the dependency floor,
so "more capacity changes nothing" is visible as uniform colour rather than needing a
legend.

The tint is a constant low-alpha colour (DESIGN.md's deliberate exception #2) so it reads
on every theme; everything else — text, headers, the selection ring — comes from the
palette at paint time, never stored.

Clicking a tile selects a scenario; the hosting page turns that into its headline. The
widget itself only renders and reports, like every input here.

Rebuilt whole whenever the model changes — twelve simulations over tens of steps, cheaper
to redo than to diff (the order table's argument).
"""

from collections.abc import Callable

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetricsF,
    QHelpEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSpinBox, QToolTip, QWidget

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, NodeId, ProjectId
from dplanner.domain.schedule import format_days
from dplanner.framework.undo import UndoService
from dplanner.modules.time_estimates.schedule import (
    MODULE_ID,
    Cell,
    read_efficiency,
    write_efficiency,
)

# Secondary text as opacity rather than a theme colour — DESIGN.md exception #1, the same
# constant the order table uses.
SECONDARY_ALPHA = 160

# Two makespans are "the same" within this; the calendar grid divides by the focus factor,
# so exact equality with its floor would be float luck.
FLOOR_TOLERANCE = 1e-9

ROW_GAP = 8

# The sequential tint: one blue, low-alpha over the surface (DESIGN.md exception #2), so
# more time reads as more ink on every theme. The span is deliberately modest — the tint
# orients, the printed number answers.
TINT = QColor(95, 135, 215)
TINT_MIN_ALPHA = 18
TINT_MAX_ALPHA = 88

# Tile geometry: 4-point-scale gaps doing the separating (never borders), mark-spec
# rounding, and a hit target comfortably past the 24 px minimum.
TILE_WIDTH = 84
TILE_HEIGHT = 40
TILE_GAP = 4
TILE_RADIUS = 4
HEADER_GAP = 6
SELECTION_PEN = 2.0


class FocusBar(QWidget):
    """The focus factor: how much of a person's working day this project gets.

    ``StartDateBar``'s twin, one module over — committed as an undoable command, echoes
    suppressed by origin, reloaded when anything else writes the factor.
    """

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        project_id: ProjectId,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._product = library
        self._undo = undo
        self._project_id = project_id
        self._loading = False

        caption = QLabel("Human focus", self)
        caption.setObjectName("InspectorCaption")

        self.percent = QSpinBox(self)
        self.percent.setRange(10, 100)
        self.percent.setSingleStep(5)
        self.percent.setSuffix("%")
        # Arrow steps commit as they land; typing commits on Enter or focus-out, so a
        # half-typed "6" on the way to "60" never reaches the model.
        self.percent.setKeyboardTracking(False)
        self.percent.valueChanged.connect(self._commit)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(ROW_GAP)
        row.addWidget(caption)
        row.addWidget(self.percent)
        row.addStretch(1)

        self._unsubscribe = library.module_data_changed.connect(self._on_module_data)
        self._load()

    def dispose(self) -> None:
        self._unsubscribe()

    def _load(self) -> None:
        if not self._product.has(self._project_id):
            return
        efficiency = read_efficiency(self._product.project(self._project_id))
        self._loading = True
        try:
            self.percent.setValue(round(efficiency * 100))
        finally:
            self._loading = False

    def _commit(self) -> None:
        if self._loading or not self._product.has(self._project_id):
            return
        entry = write_efficiency(self.percent.value() / 100)
        project = self._product.project(self._project_id)
        if entry == project.module_data.get(MODULE_ID, {}):
            return
        self._undo.push(
            SetModuleDataCommand(
                self._project_id, MODULE_ID, entry, view_origin=self, label="Set Focus"
            )
        )

    def _on_module_data(self, node_id: NodeId, module_id: str, origin: object) -> None:
        if node_id != self._project_id or module_id != MODULE_ID or origin is self:
            return
        self._load()


def _agent_header(count: int, collapsed: bool) -> str:
    if collapsed:
        return "any agents"
    return f"{count} {'agent' if count == 1 else 'agents'}"


def _human_label(count: int) -> str:
    return f"{count} {'human' if count == 1 else 'humans'}"


class MatrixView(QWidget):
    """People down, agents across, a makespan tile in every seat.

    ``scenario_changed`` fires when a click or an arrow key moves the selection; the
    selected (humans, agents) pair is ``selection``. Tooltips come from ``tooltip_for``,
    handed in by the host so this widget never learns what the other lens would say.
    """

    scenario_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cells: dict[tuple[int, int], Cell] = {}
        self._humans: tuple[int, ...] = ()
        self._agents: tuple[int, ...] = ()
        self._floor = 0.0
        self._collapsed = False
        self._span = (0.0, 0.0)  # (min days, max days) across the shown cells
        self.selection: tuple[int, int] = (1, 1)
        self.tooltip_for: Callable[[Cell], str] | None = None
        self._gutter = 0.0
        self._header = 0.0
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # -- the host's side of the contract -------------------------------------------------------

    def show_cells(self, cells: tuple[Cell, ...], floor: float, collapse_agents: bool) -> None:
        self._collapsed = collapse_agents
        shown = tuple(cell for cell in cells if not collapse_agents or cell.agents == 1)
        self._cells = {(cell.humans, cell.agents): cell for cell in shown}
        self._humans = tuple(sorted({cell.humans for cell in shown}))
        self._agents = tuple(sorted({cell.agents for cell in shown}))
        self._floor = floor
        days = [cell.days for cell in shown]
        self._span = (min(days, default=0.0), max(days, default=0.0))
        if self.selection not in self._cells and self._humans and self._agents:
            self.selection = (self._humans[0], self._agents[0])
        metrics = QFontMetricsF(self.font())
        self._gutter = max(
            (metrics.horizontalAdvance(_human_label(count)) for count in self._humans),
            default=0.0,
        ) + ROW_GAP
        self._header = metrics.height() + HEADER_GAP
        width = self._gutter + len(self._agents) * (TILE_WIDTH + TILE_GAP) - TILE_GAP
        height = self._header + len(self._humans) * (TILE_HEIGHT + TILE_GAP) - TILE_GAP
        self.setFixedSize(round(width), round(height))
        self.update()

    def select(self, humans: int, agents: int) -> None:
        if (humans, agents) not in self._cells or (humans, agents) == self.selection:
            return
        self.selection = (humans, agents)
        self.update()
        self.scenario_changed.emit()

    # -- what the tests read off the widget ----------------------------------------------------

    @property
    def human_counts(self) -> tuple[int, ...]:
        return self._humans

    @property
    def agent_counts(self) -> tuple[int, ...]:
        return self._agents

    def header_text(self, agents: int) -> str:
        return _agent_header(agents, self._collapsed)

    def value_at(self, humans: int, agents: int) -> str:
        return format_days(self._cells[(humans, agents)].days)

    def tint_alpha(self, humans: int, agents: int) -> int:
        """The tile's ink, scaled across the shown span — the floor region is lightest."""
        low, high = self._span
        if high - low <= FLOOR_TOLERANCE:
            return TINT_MIN_ALPHA
        share = (self._cells[(humans, agents)].days - low) / (high - low)
        return round(TINT_MIN_ALPHA + share * (TINT_MAX_ALPHA - TINT_MIN_ALPHA))

    # -- painting ------------------------------------------------------------------------------

    def _tile_rect(self, row: int, column: int) -> QRectF:
        return QRectF(
            self._gutter + column * (TILE_WIDTH + TILE_GAP),
            self._header + row * (TILE_HEIGHT + TILE_GAP),
            TILE_WIDTH,
            TILE_HEIGHT,
        )

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ink = self.palette().text().color()
        secondary = QColor(ink)
        secondary.setAlpha(SECONDARY_ALPHA)
        # Headers read from the left with everything else (DESIGN.md's table rule).
        painter.setPen(secondary)
        for column, agents in enumerate(self._agents):
            slot = self._tile_rect(0, column)
            painter.drawText(
                QRectF(slot.left(), 0.0, slot.width(), self._header - HEADER_GAP),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.header_text(agents),
            )
        for row, humans in enumerate(self._humans):
            seat = self._tile_rect(row, 0)
            painter.drawText(
                QRectF(0.0, seat.top(), self._gutter - ROW_GAP, seat.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                _human_label(humans),
            )
        for row, humans in enumerate(self._humans):
            for column, agents in enumerate(self._agents):
                rect = self._tile_rect(row, column)
                tint = QColor(TINT)
                tint.setAlpha(self.tint_alpha(humans, agents))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(tint)
                painter.drawRoundedRect(rect, TILE_RADIUS, TILE_RADIUS)
                if (humans, agents) == self.selection:
                    ring = QPen(self.palette().highlight().color(), SELECTION_PEN)
                    painter.setPen(ring)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    inset = SELECTION_PEN / 2
                    painter.drawRoundedRect(
                        rect.adjusted(inset, inset, -inset, -inset), TILE_RADIUS, TILE_RADIUS
                    )
                painter.setPen(ink)
                painter.drawText(
                    rect,
                    Qt.AlignmentFlag.AlignCenter,
                    self.value_at(humans, agents),
                )
        painter.end()

    # -- input ---------------------------------------------------------------------------------

    def _seat_at(self, position: QPointF) -> tuple[int, int] | None:
        for row, humans in enumerate(self._humans):
            for column, agents in enumerate(self._agents):
                # The gap belongs to the tile's hit area — no dead pixels between seats.
                rect = self._tile_rect(row, column).adjusted(0, 0, TILE_GAP, TILE_GAP)
                if rect.contains(position):
                    return (humans, agents)
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        seat = self._seat_at(event.position())
        if seat is not None:
            self.select(*seat)
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        steps = {
            Qt.Key.Key_Left: (0, -1),
            Qt.Key.Key_Right: (0, 1),
            Qt.Key.Key_Up: (-1, 0),
            Qt.Key.Key_Down: (1, 0),
        }
        step = steps.get(Qt.Key(event.key()))
        if step is None or not self._humans:
            super().keyPressEvent(event)
            return
        row = self._humans.index(self.selection[0]) + step[0]
        column = self._agents.index(self.selection[1]) + step[1]
        if 0 <= row < len(self._humans) and 0 <= column < len(self._agents):
            self.select(self._humans[row], self._agents[column])

    def event(self, found: QEvent) -> bool:
        if found.type() == QEvent.Type.ToolTip and self.tooltip_for is not None:
            assert isinstance(found, QHelpEvent)
            seat = self._seat_at(QPointF(found.pos()))
            if seat is not None:
                QToolTip.showText(found.globalPos(), self.tooltip_for(self._cells[seat]), self)
            else:
                QToolTip.hideText()
            return True
        return super().event(found)
