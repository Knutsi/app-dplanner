"""The Estimates tab: many steps sized in one sitting.

The step detail panel answers "how big is this one"; this activity answers "how big is all of
it". One row per step — its title, its estimate and a line of its description — on the table
primitive, the estimate edited in place: pick a row and type, or double-click the number, and
Enter commits it as the same undoable command the panel writes. The quick sizes are the Step
▸ Estimate verbs, dropped from the strip's *Size* face over every picked row at once — one
undo entry however many — and offered by the canvas's right-click and the menu bar too.

**Scope and filter are different questions.** The scope is *which steps this sitting is
about* — the canvas selection that opened the tab, or the whole project — and the volume line
counts over it. The filter is *which of those to look at right now*: hiding the sized rows is
how you run down what is left, showing only them is how you review. Both are selectors on the
strip, in words.

**A committed estimate hides its row; it never rebuilds the table.** The echo of an edit
arrives inside the editor's own commit, and a rebuild there would take the index away from
under the open editor — so an estimate writes its cell and re-applies the filter, and only a
change of shape (a step born or gone, a link, a rename, a description) rebuilds, after a
quiet spell.

There is one Estimates tab per project, keyed by :func:`activity_uri`, and re-running the
action rescopes it rather than opening a second one.
"""

from typing import TYPE_CHECKING

from PySide6.QtCore import QItemSelectionModel, QPoint, Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QMenu, QVBoxLayout, QWidget

from dplanner.domain.model import Library, NodeId, Project, Step, StepId
from dplanner.domain.ordering import placed
from dplanner.domain.schedule import volume_words
from dplanner.framework.action_menu import build_menu
from dplanner.framework.activity import EntityActivity, follow_project
from dplanner.framework.context import (
    SCOPE_SELECTION,
    Context,
    ContextNode,
    Uri,
    activity_uri,
    selection_uri,
)
from dplanner.framework.debounce import Debounced
from dplanner.framework.list_rows import HOST_ROLE
from dplanner.framework.signalling import UpdatingIndicator
from dplanner.framework.table import Cell, Column, NumberEditor, Table
from dplanner.framework.toolbar import Toolbar
from dplanner.framework.widgets import EmptyState, captioned, note
from dplanner.modules.estimation.aspect import MODULE_ID, read
from dplanner.modules.estimation.quick_input import MAX_DAYS, QUARTER, UNESTIMATED, push_estimate
from dplanner.theme.icons import gauge_icon
from dplanner.theme.tokens import CAPTION_GAP, FIELD_GAP, PANEL_MARGIN, SECTION_GAP

if TYPE_CHECKING:
    # Resolved only for typing: module.py imports this file to register the factory.
    from dplanner.modules.estimation.module import EstimationDeps

ESTIMATE_KIND = "estimate"

# One step under zero is "no estimate", printed as a dash; zero is a claim of its own.
DAYS = NumberEditor(UNESTIMATED, MAX_DAYS, QUARTER, decimals=2, suffix=" d", blank_text="—")
COLUMNS = (
    Column("Step", resize="interactive"),
    Column("Estimate", numeric=True, editor=DAYS),
    Column("Description", resize="stretch"),
)
STEP_COLUMN, ESTIMATE_COLUMN, DESCRIPTION_COLUMN = range(3)
STEP_ROLE = HOST_ROLE

SCOPE_PICKED = "selection"
SCOPE_PROJECT = "project"

FILTER_ALL = "all"
FILTER_UNESTIMATED = "unestimated"
FILTER_ESTIMATED = "estimated"
FILTERS = (
    (FILTER_ALL, "All steps"),
    (FILTER_UNESTIMATED, "Unestimated"),
    (FILTER_ESTIMATED, "Estimated"),
)

HINT = "Working days. Pick a row and type its size, or size several picked rows at once from Size."
NO_STEPS = "No steps here yet — add some on the graph."
ALL_SIZED = "Every step here is estimated."
NONE_SIZED = "Nothing here is estimated yet."


def _step_context(step_id: StepId) -> Context:
    """A context naming exactly one step — what a row's double-click runs a verb against."""
    return Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step_id)),)})


def _selector(parent: QWidget, tip: str, entries: tuple[tuple[str, str], ...]) -> QComboBox:
    box = QComboBox(parent)
    box.setToolTip(tip)
    box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
    for key, label in entries:
        box.addItem(label, key)
    return box


class BulkEstimateActivity(EntityActivity):
    """One project's steps, each estimate edited in place."""

    def __init__(self, deps: "EstimationDeps", project_id: NodeId) -> None:
        super().__init__(deps.context, "project", project_id)
        self._deps = deps
        self._product: Library = deps.library
        self.project_id = project_id
        # The canvas selection this sitting is about, or None for the whole project.
        self._selection: tuple[StepId, ...] | None = None

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(SECTION_GAP)

        head = QVBoxLayout()
        layout.addLayout(head)  # Before it is filled: a parentless layout leaks its items.
        head.setSpacing(CAPTION_GAP)
        head.addWidget(captioned("Estimates", page, hint=HINT))
        # Counted over the scope, never the filter, so it does not change while rows hide.
        self.volume = note("", page)
        head.addWidget(self.volume)

        strip = QHBoxLayout()
        layout.addLayout(strip)
        strip.setSpacing(FIELD_GAP)
        self.controls = Toolbar(page)
        self.size_face = self.controls.add_menu_face(
            "Size", gauge_icon, deps.actions, deps.context, "Step", submenu="Estimate"
        )
        self.controls.add_divider()
        self.scope_box = _selector(
            page,
            "Which steps this sitting is about",
            ((SCOPE_PICKED, "Selection"), (SCOPE_PROJECT, "Whole project")),
        )
        self.scope_box.currentIndexChanged.connect(lambda _index: self._refresh())
        self.controls.add_widget(self.scope_box)
        self.controls.set_shown(self.scope_box, False)
        self.filter_box = _selector(page, "Which of those steps to look at", FILTERS)
        self.filter_box.currentIndexChanged.connect(lambda _index: self._apply_filter())
        self.controls.add_widget(self.filter_box)
        strip.addWidget(self.controls, 1)
        # Outside the strip, so folding the verbs into … can never take it.
        self.updating = UpdatingIndicator(page)
        strip.addWidget(self.updating)

        self.table = Table(COLUMNS, selection="extended", parent=page)
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.cellActivated.connect(self._on_row_activated)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.table, 1)
        self.empty = EmptyState(parent=page, stands_in_for=self.table)
        layout.addWidget(self.empty, 1)

        self._widget = page
        # After a quiet spell: a change of shape rebuilds every row.
        self._refresh_soon = Debounced(self._refresh, parent=page, service=deps.debounce)
        self.updating.follow(self._refresh_soon)
        library = self._product
        self._unsubscribes = [
            follow_project(
                library,
                project_id,
                self._refresh_soon.trigger,
                signals=(
                    library.structure_changed,
                    library.edges_changed,
                    library.field_changed,
                    library.text_edited,
                ),
            ),
            # Not coalesced: an estimate lands in its cell at once, inside the editor's commit.
            library.module_data_changed.connect(self._on_module_data),
            self.table.edited.connect(self._on_edited),
        ]
        self._refresh()

    # -- the activity contract -----------------------------------------------------------------

    @property
    def uri(self) -> Uri:
        return activity_uri(ESTIMATE_KIND, self.project_id)

    @property
    def title(self) -> str:
        return f"{self._project().title or 'Untitled project'} — Estimates"

    @property
    def widget(self) -> QWidget:
        return self._widget

    def on_activated(self) -> None:
        super().on_activated()
        self._on_selection()

    def close(self) -> None:
        self._refresh_soon.cancel()
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self.controls.dispose()

    # -- scope and filter ----------------------------------------------------------------------

    def set_scope(self, step_ids: tuple[StepId, ...]) -> None:
        """What this sitting is about: a selection, or ``()`` for the whole project."""
        self._selection = tuple(s for s in step_ids if self._product.has(s)) or None
        self._show_scope()
        self._refresh()
        self._edit_first_row()

    def set_filter(self, key: str) -> None:
        """Which of the scope's rows to look at: one of ``FILTERS``' keys."""
        self.filter_box.setCurrentIndex(self.filter_box.findData(key))
        self._apply_filter()
        self._edit_first_row()

    @property
    def filter_key(self) -> str:
        return str(self.filter_box.currentData() or FILTER_ALL)

    def _show_scope(self) -> None:
        """A selector with one entry teaches nothing: the scope is offered only while a
        selection opened the tab, and names how many it holds."""
        chosen = self._selection is not None
        self.controls.set_shown(self.scope_box, chosen)
        self.scope_box.blockSignals(True)
        if self._selection is not None:
            self.scope_box.setItemText(0, f"Selection ({len(self._selection)})")
        self.scope_box.setCurrentIndex(0 if chosen else 1)
        self.scope_box.blockSignals(False)

    # -- what the table shows ------------------------------------------------------------------

    def _project(self) -> Project:
        return self._product.project(self.project_id)

    def _steps(self) -> list[Step]:
        """The rows: the selection in the order it was made, else the whole project in the
        order the work can be done."""
        if self._selection is not None and self.scope_box.currentData() == SCOPE_PICKED:
            return [self._product.step(s) for s in self._selection]
        return [place.step for place in placed(self._product, self._project())]

    def _refresh(self) -> None:
        """Replace every row. Never from inside the editor's commit — see the module
        docstring; an estimate goes through ``_on_module_data`` instead."""
        if not self._product.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        if self._selection is not None:
            survivors = tuple(s for s in self._selection if self._product.has(s))
            if survivors != self._selection:
                self._selection = survivors or None
                self._show_scope()
        picked = self._picked_steps()
        # Quiet while the rows are replaced: clearing and reselecting would announce the
        # selection twice, and a panel rebinding to the step inside the very signal that
        # brought the change would hear that change a second time.
        self.table.blockSignals(True)
        try:
            self.table.clear_rows()
            for step in self._steps():
                self.table.add_row(
                    (
                        Cell(step.title or "Untitled step"),
                        Cell(value=read(step)),
                        Cell(
                            self._deps.step_summary(step.id),
                            secondary=True,
                            tooltip=self._deps.describe_step(step.id),
                        ),
                    ),
                    data={STEP_ROLE: step.id},
                )
            self.table.fit_columns()
            self._reselect(picked)
        finally:
            self.table.blockSignals(False)
        if self._picked_steps() != picked:
            self._on_selection()  # A picked step left the scope.
        self._apply_filter()

    def _apply_filter(self) -> None:
        wanted = self.filter_key
        shown = 0
        for row in range(self.table.rowCount()):
            step_id = self._step_at(row)
            if step_id is None or not self._product.has(step_id):
                continue
            estimated = read(self._product.step(step_id)) is not None
            hidden = (wanted == FILTER_UNESTIMATED and estimated) or (
                wanted == FILTER_ESTIMATED and not estimated
            )
            self.table.setRowHidden(row, hidden)
            shown += not hidden
        self._update_volume()
        if not self.table.rowCount():
            said = NO_STEPS
        elif shown:
            said = ""
        else:
            said = ALL_SIZED if wanted == FILTER_UNESTIMATED else NONE_SIZED
        self.empty.say(said)

    def _update_volume(self) -> None:
        """The volume sentence the order table and ``estimate rollup`` print, over this scope:
        one wording, so the tab a person sizes steps in and the total they quote afterwards
        cannot disagree."""
        days = [read(step) for step in self._steps()]
        sized = [d for d in days if d is not None]
        self.volume.setText(
            volume_words(sum(sized), len(days), len(days) - len(sized)) if days else ""
        )

    def _edit_first_row(self) -> None:
        """Land in the first shown row's estimate, editing it: sizing is what comes next."""
        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row):
                self.table.setCurrentCell(row, ESTIMATE_COLUMN)
                self.table.edit(self.table.model().index(row, ESTIMATE_COLUMN))
                return

    # -- rows ----------------------------------------------------------------------------------

    def _step_at(self, row: int) -> StepId | None:
        item = self.table.item(row, STEP_COLUMN)
        found = item.data(STEP_ROLE) if item is not None else None
        return found if isinstance(found, str) else None

    def _row_of(self, step_id: StepId) -> int | None:
        return next(
            (row for row in range(self.table.rowCount()) if self._step_at(row) == step_id), None
        )

    def _picked_steps(self) -> list[StepId]:
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        return [step_id for row in rows if (step_id := self._step_at(row)) is not None]

    def _reselect(self, step_ids: list[StepId]) -> None:
        """Keep the picked rows across a rebuild, by step — the rows are new."""
        if not step_ids:
            return
        wanted = set(step_ids)
        model = self.table.selectionModel()
        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        for row in range(self.table.rowCount()):
            if self._step_at(row) in wanted:
                model.select(self.table.model().index(row, STEP_COLUMN), flags)

    def _on_edited(self, row: int, column: int, value: object) -> None:
        step_id = self._step_at(row)
        if column != ESTIMATE_COLUMN or step_id is None or not self._product.has(step_id):
            return
        days = float(value) if isinstance(value, int | float) else None
        push_estimate(self._product, self._deps.undo, step_id, days, origin=self.table)

    # -- the model talking back ----------------------------------------------------------------

    def _on_module_data(self, node_id: NodeId, module_id: str, origin: object) -> None:
        if module_id != MODULE_ID or not self._product.has(node_id):
            return
        row = self._row_of(node_id)
        if row is None:
            return
        if origin is not self.table:  # The table's own commit already wrote the cell.
            self.table.set_cell(row, ESTIMATE_COLUMN, Cell(value=read(self._product.step(node_id))))
        # Hide or show only: this runs inside the editor's own commit when the row wrote it.
        self._apply_filter()

    # -- speaking for the user -----------------------------------------------------------------

    def _on_selection(self) -> None:
        nodes = tuple(ContextNode(selection_uri("step", s)) for s in self._picked_steps())
        self.publish_selection(nodes)

    def _on_row_activated(self, row: int, column: int) -> None:
        step_id = self._step_at(row)
        if step_id is not None and column != ESTIMATE_COLUMN:
            # Against a context naming exactly this row's step, not the service's — the
            # double-click means the row under it even if a publish was suppressed.
            self._deps.actions.run("steps.details", _step_context(step_id))

    def _on_context_menu(self, position: QPoint) -> None:
        row = self.table.rowAt(position.y())
        step_id = self._step_at(row)
        if step_id is None:
            return
        if step_id not in self._picked_steps():
            self.table.selectRow(row)
        menu: QMenu = build_menu(self._deps.actions, self._deps.context, "Step", self.table)
        menu.exec(self.table.viewport().mapToGlobal(position))
