"""The staffing matrices, and the focus control the calendar one is priced with.

Two small tables of the same cells — project working days, then calendar days with landing
dates — because the comparison *is* the report: the gap between a cell and its calendar
twin is what divided attention costs. Both render through ``domain/schedule.py``'s
formatters, so the tab and ``dplanner schedule matrix`` cannot print one number two ways.

A cell sitting on the dependency floor fades to secondary: past that point more capacity
buys nothing, and the eye should go to the cells where it still does.

Rebuilt whole whenever the model changes — twelve simulations over tens of steps, cheaper
to redo than to diff (the order table's argument).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, NodeId, ProjectId
from dplanner.domain.schedule import format_date, format_days
from dplanner.framework.undo import UndoService
from dplanner.modules.time_estimates.schedule import (
    AGENTS,
    HUMANS,
    MODULE_ID,
    Cell,
    read_efficiency,
    write_efficiency,
)

LABEL_COLUMN = 0
COLUMNS = ("", *(f"{count} {'agent' if count == 1 else 'agents'}" for count in AGENTS))
ROW_LABELS = tuple(f"{count} {'human' if count == 1 else 'humans'}" for count in HUMANS)
ROW_HEIGHT = 28

# Secondary text as opacity rather than a theme colour — DESIGN.md exception #1, the same
# constant the order table uses.
SECONDARY_ALPHA = 160

# Two makespans are "the same" within this; the calendar grid divides by the focus factor,
# so exact equality with its floor would be float luck.
FLOOR_TOLERANCE = 1e-9

ROW_GAP = 8

_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def cell_text(cell: Cell) -> str:
    """One scenario as the tables and the CLI's calendar grid print it."""
    said = format_days(cell.days)
    if cell.finish is not None:
        said += f" · {format_date(cell.finish)}"
    return said


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


class MatrixTable(QTableWidget):
    """People down, agents across, a makespan in every cell. Numbers, not entities — no
    selection, no focus, nothing to click."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(len(HUMANS), len(COLUMNS), parent)
        self.setObjectName("TimeMatrixTable")
        self.setHorizontalHeaderLabels(list(COLUMNS))
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setWordWrap(False)
        self.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        header = self.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for column in range(len(COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(False)
        header.setHighlightSections(False)

    def show_cells(self, cells: tuple[Cell, ...], floor: float, collapse_agents: bool) -> None:
        at = {(cell.humans, cell.agents): cell for cell in cells}
        for row, humans in enumerate(HUMANS):
            self.setRowHeight(row, ROW_HEIGHT)
            label = QTableWidgetItem(ROW_LABELS[row])
            faded = self.palette().text().color()
            faded.setAlpha(SECONDARY_ALPHA)
            label.setForeground(faded)
            self.setItem(row, LABEL_COLUMN, label)
            for column, agents in enumerate(AGENTS, start=1):
                cell = at[(humans, agents)]
                item = QTableWidgetItem(cell_text(cell))
                item.setTextAlignment(_RIGHT)
                if abs(cell.days - floor) <= FLOOR_TOLERANCE:
                    item.setForeground(faded)
                    # The fade's one explanation — the page carries no legend for it.
                    item.setToolTip("On the dependency floor — more capacity no longer helps.")
                self.setItem(row, column, item)
        # A project with no agent steps answers the same in every column; one column
        # saying so beats four saying it four times (the order table hides its all-blank
        # Date column for the same reason).
        for column in range(2, len(COLUMNS)):
            self.setColumnHidden(column, collapse_agents)
        header = QTableWidgetItem("any agents" if collapse_agents else COLUMNS[1])
        self.setHorizontalHeaderItem(1, header)
        self.resizeColumnsToContents()
        self.updateGeometry()
