"""The start-date bar: when a project's work begins.

A widget another surface hosts — the order view puts it above its table — told which project
it is for and nothing else. It never learns what hosts it, and the host never learns that a
start date is module data.

**A date the user has not set is not "today".** The field reads "Not set" until somebody
picks one, and the schedule shows totals without dates until then. Guessing a start would put
plausible dates against every step of a plan nobody had scheduled.
"""

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QDateEdit, QHBoxLayout, QLabel, QPushButton, QWidget

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import NodeId, Product, ProjectId
from dplanner.framework.undo import UndoService
from dplanner.modules.estimation.aspect import MODULE_ID
from dplanner.modules.estimation.schedule import read_start, write_start

# DESIGN.md's 4-point scale. The bar carries no outer margin: its host owns those.
ROW_GAP = 8

# The bottom of the range doubles as "no date": QDateEdit shows its special text there, which
# is the only way a date field can be empty without inventing a second control to mean it.
UNSET = QDate(1900, 1, 1)


class StartDateBar(QWidget):
    """One project's start date, committed as an undoable command like any other edit."""

    def __init__(
        self,
        product: Product,
        undo: UndoService[Product],
        project_id: ProjectId,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._product = product
        self._undo = undo
        self._project_id = project_id
        self._loading = False

        caption = QLabel("Start date", self)
        caption.setObjectName("InspectorCaption")

        self.date = QDateEdit(self)
        self.date.setCalendarPopup(True)
        self.date.setMinimumDate(UNSET)
        self.date.setSpecialValueText("Not set")
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.date.dateChanged.connect(self._commit)

        self.clear = QPushButton("Clear", self)
        self.clear.setObjectName("ToolbarButton")
        self.clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear.clicked.connect(lambda: self.date.setDate(UNSET))

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(ROW_GAP)
        row.addWidget(caption)
        row.addWidget(self.date)
        row.addWidget(self.clear)
        row.addStretch(1)

        self._unsubscribe = product.module_data_changed.connect(self._on_module_data)
        self._load()

    # -- the host's side of the contract -------------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def dispose(self) -> None:
        self._unsubscribe()

    # -- internals -----------------------------------------------------------------------------

    def _load(self) -> None:
        start = None
        if self._product.has(self._project_id):
            start = read_start(self._product.project(self._project_id))
        self._loading = True
        try:
            self.date.setDate(UNSET if start is None else QDate(start.year, start.month, start.day))
            self.clear.setEnabled(start is not None)
        finally:
            self._loading = False

    def _commit(self) -> None:
        if self._loading or not self._product.has(self._project_id):
            return
        picked = self.date.date()
        start = None if picked == UNSET else date(picked.year(), picked.month(), picked.day())
        self.clear.setEnabled(start is not None)
        entry = write_start(start)
        project = self._product.project(self._project_id)
        if entry == project.module_data.get(MODULE_ID, {}):
            return
        self._undo.push(
            SetModuleDataCommand(
                self._project_id, MODULE_ID, entry, view_origin=self, label="Set Start Date"
            )
        )

    def _on_module_data(self, node_id: NodeId, module_id: str, origin: object) -> None:
        if node_id != self._project_id or module_id != MODULE_ID or origin is self:
            return
        self._load()
