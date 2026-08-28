"""The start-date bar: when a project's work begins.

A widget another surface hosts — the order view puts it above its table — told which project
it is for and nothing else. It never learns what hosts it, and the host never learns that a
start date is module data.

**A project nobody has dated starts today.** The field opens on today's date and the
schedule reads from there, so a plan answers "when does this land" the moment it has
estimates. Nothing is written until somebody picks a different day — see ``start_of`` — so
the field showing a date and the workspace being clean are not in conflict.
"""

from datetime import date

from PySide6.QtCore import QDate, QLocale
from PySide6.QtWidgets import QDateEdit, QHBoxLayout, QLabel, QWidget

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, NodeId, ProjectId
from dplanner.framework.undo import UndoService
from dplanner.modules.estimation.aspect import MODULE_ID
from dplanner.modules.estimation.schedule import start_of, write_start

# DESIGN.md's 4-point scale. The bar carries no outer margin: its host owns those.
ROW_GAP = 8


class StartDateBar(QWidget):
    """One project's start date, committed as an undoable command like any other edit."""

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

        caption = QLabel("Start date", self)
        caption.setObjectName("InspectorCaption")

        self.date = QDateEdit(self)
        self.date.setCalendarPopup(True)
        # The same words the table and the terminal use, so one day reads one way
        # everywhere. English explicitly, for format_date's reason: MMMM is locale-dependent,
        # and a field reading "26. august" beside a column reading "26 August" is two answers.
        self.date.setLocale(QLocale(QLocale.Language.English))
        self.date.setDisplayFormat("d MMMM yyyy")
        self.date.dateChanged.connect(self._commit)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(ROW_GAP)
        row.addWidget(caption)
        row.addWidget(self.date)
        row.addStretch(1)

        self._unsubscribe = library.module_data_changed.connect(self._on_module_data)
        self._load()

    # -- the host's side of the contract -------------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def dispose(self) -> None:
        self._unsubscribe()

    # -- internals -----------------------------------------------------------------------------

    def _load(self) -> None:
        if not self._product.has(self._project_id):
            return
        start = start_of(self._product.project(self._project_id))
        self._loading = True
        try:
            self.date.setDate(QDate(start.year, start.month, start.day))
        finally:
            self._loading = False

    def _commit(self) -> None:
        if self._loading or not self._product.has(self._project_id):
            return
        picked = self.date.date()
        start = date(picked.year(), picked.month(), picked.day())
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
