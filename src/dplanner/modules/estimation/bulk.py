"""The Estimates tab: many steps sized in one sitting.

The step detail panel answers "how big is this one"; this activity answers "how big is all
of it". One row per step — title, a line of description, and the same
:class:`~dplanner.modules.estimation.quick_input.EstimateInput` the panel uses — so running
down a project is a glance and a chip per step, not a click per step first.

**Scope and filter are different questions.** The scope is *which steps this sitting is
about* — the canvas selection that opened the tab, or the whole project — and the summary
counts over it. The filter is *which of those to look at right now*: hiding the sized rows
is how you run down what is left, showing only them is how you review. Filtering hides rows
rather than rebuilding them, and not only for economy: an estimate committed from a row's
own chip arrives back synchronously, and rebuilding the table inside that chip's clicked
handler would delete the widget mid-signal. Rebuilds happen only on structural change,
rescoping, and scope switches — none of which originate inside a row.

There is one Estimates tab per project, keyed by :func:`activity_uri`, and re-running the
action rescopes it rather than opening a second one.
"""

from functools import partial
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.model import NodeId, Product, Project, Step, StepId, TextEdit
from dplanner.domain.ordering import placed
from dplanner.domain.schedule import format_days
from dplanner.framework.action_menu import build_menu
from dplanner.framework.activity import ActivityBase
from dplanner.framework.context import (
    SCOPE_ACTIVITY,
    SCOPE_SELECTION,
    ContextNode,
    Uri,
    activity_uri,
    entity_uri,
    selection_uri,
)
from dplanner.modules.estimation.aspect import MODULE_ID, read
from dplanner.modules.estimation.quick_input import EstimateInput, push_estimate

if TYPE_CHECKING:
    # Resolved only for typing: module.py imports this file to register the factory.
    from dplanner.modules.estimation.module import EstimationDeps

ESTIMATE_KIND = "estimate"

STEP_COLUMN = 0
DESCRIPTION_COLUMN = 1
ESTIMATE_COLUMN = 2
COLUMNS = ("Step", "Description", "Estimate")

# The step id on a row, so a click can say which step it means.
STEP_ROLE = int(Qt.ItemDataRole.UserRole) + 1

FILTER_ALL = "all"
FILTER_UNESTIMATED = "unestimated"
FILTER_ESTIMATED = "estimated"
FILTERS = (
    (FILTER_ALL, "All"),
    (FILTER_UNESTIMATED, "Unestimated"),
    (FILTER_ESTIMATED, "Estimated"),
)

# DESIGN.md's page metrics, as the order view uses them.
PANEL_MARGIN = 16
CAPTION_GAP = 6
BLOCK_GAP = 12
GROUP_GAP = 12
BUTTON_GAP = 8

# A row holds a spin box and a chip row, so it is taller than a text-only list row.
ROW_HEIGHT = 44

# Secondary text as opacity rather than a theme colour: an item has only the palette, and an
# alpha-derived secondary is theme-independent by construction (DESIGN.md exception #1).
SECONDARY_ALPHA = 160


class BulkEstimateActivity(ActivityBase):
    """One project's steps with an estimate input on every row."""

    def __init__(self, deps: "EstimationDeps", project_id: NodeId) -> None:
        self._deps = deps
        self._product: Product = deps.product
        self.project_id = project_id
        # The canvas selection this sitting is about, or None for the whole project.
        self._selection: tuple[StepId, ...] | None = None
        self._editors: dict[StepId, EstimateInput] = {}
        # Only the pane the user is in may write the selection scope — see CLAUDE.md's
        # "only the active pane speaks for the user".
        self._is_active = False

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(CAPTION_GAP)

        caption = QLabel("Estimates", page)
        caption.setObjectName("InspectorCaption")
        layout.addWidget(caption)

        note = QLabel(
            "Run down the list and size each step. Working days; a week is five.", page
        )
        note.setObjectName("InspectorNote")
        note.setWordWrap(True)
        layout.addWidget(note)

        layout.addSpacing(BLOCK_GAP)
        layout.addLayout(self._build_toolbar(page))

        self.table = self._build_table(page)
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.cellActivated.connect(self._on_row_activated)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.table, 1)

        self._widget = page
        self._unsubscribes = [
            self._product.structure_changed.connect(self._on_structure),
            self._product.edges_changed.connect(lambda *_a: self._rebuild()),
            self._product.field_changed.connect(lambda *_a: self._refresh_texts()),
            self._product.text_edited.connect(self._on_text),
            self._product.module_data_changed.connect(self._on_module_data),
        ]
        self._rebuild()

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
        self._is_active = True
        self._deps.context.set_scope(
            SCOPE_ACTIVITY,
            (ContextNode(self.uri, (("entity", entity_uri("project", self.project_id)),)),),
        )
        self._publish(self._selected_step())

    def on_deactivated(self) -> None:
        self._is_active = False

    def close(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    # -- scope ---------------------------------------------------------------------------------

    def set_scope(self, step_ids: tuple[StepId, ...]) -> None:
        """What this sitting is about: a selection, or ``()`` for the whole project."""
        self._selection = tuple(s for s in step_ids if self._product.has(s)) or None
        self._scope_bar.setVisible(self._selection is not None)
        if self._selection is not None:
            self._selection_button.setText(f"Selection ({len(self._selection)})")
            self._selection_button.setChecked(True)
        self._rebuild()
        self._focus_first_row()

    # -- building ------------------------------------------------------------------------------

    def _build_toolbar(self, page: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(GROUP_GAP)

        self._scope_bar = QWidget(page)
        scope_row = QHBoxLayout(self._scope_bar)
        scope_row.setContentsMargins(0, 0, 0, 0)
        scope_row.setSpacing(BUTTON_GAP)
        self._scope = QButtonGroup(page)
        self._scope.setExclusive(True)
        self._selection_button = self._toolbar_button(self._scope_bar, "Selection")
        self._whole_button = self._toolbar_button(self._scope_bar, "Whole project")
        for index, button in enumerate((self._selection_button, self._whole_button)):
            self._scope.addButton(button, index)
            scope_row.addWidget(button)
        self._scope.idClicked.connect(lambda _id: self._rebuild())
        self._scope_bar.setVisible(False)
        row.addWidget(self._scope_bar)

        self._filters = QButtonGroup(page)
        self._filters.setExclusive(True)
        for index, (_key, label) in enumerate(FILTERS):
            button = self._toolbar_button(page, label)
            self._filters.addButton(button, index)
            row.addWidget(button)
        self._filters.button(0).setChecked(True)
        self._filters.idClicked.connect(lambda _id: self._apply_filter())

        row.addStretch(1)
        self._summary = QLabel(page)
        self._summary.setObjectName("InspectorNote")
        row.addWidget(self._summary)
        return row

    @staticmethod
    def _toolbar_button(parent: QWidget, label: str) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName("ToolbarButton")
        button.setText(label)
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _build_table(self, page: QWidget) -> QTableWidget:
        table = QTableWidget(0, len(COLUMNS), page)
        table.setObjectName("EstimateTable")
        table.setHorizontalHeaderLabels(list(COLUMNS))
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setAlternatingRowColors(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setWordWrap(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(STEP_COLUMN, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(DESCRIPTION_COLUMN, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(ESTIMATE_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setHighlightSections(False)
        return table

    # -- what the table shows ------------------------------------------------------------------

    def _project(self) -> Project:
        return self._product.project(self.project_id)

    def _steps(self) -> list[Step]:
        """The rows: the selection in the order it was made, else the whole project in the
        order the work can be done."""
        if self._selection is not None and self._selection_button.isChecked():
            return [self._product.step(s) for s in self._selection]
        return [place.step for place in placed(self._product, self._project())]

    def _rebuild(self) -> None:
        """Replace every row. Never call from inside a row widget's own signal — see the
        module docstring; ``module_data_changed`` goes through hide/show instead."""
        if not self._product.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        selected = self._selected_step()
        table = self.table
        self._editors.clear()
        table.setRowCount(0)
        steps = self._steps()
        table.setRowCount(len(steps))
        for row, step in enumerate(steps):
            for column, text in ((STEP_COLUMN, ""), (DESCRIPTION_COLUMN, "")):
                item = QTableWidgetItem(text)
                item.setData(STEP_ROLE, step.id)
                self.table.setItem(row, column, item)
            editor = EstimateInput(table, horizontal=True)
            editor.show_days(read(step))
            editor.edited.connect(partial(self._commit, step.id, editor))
            table.setCellWidget(row, ESTIMATE_COLUMN, editor)
            self._editors[step.id] = editor
            table.setRowHeight(row, ROW_HEIGHT)
        self._refresh_texts()
        self._apply_filter()
        table.resizeColumnToContents(STEP_COLUMN)
        if selected is not None:
            self._select_row_of(selected)

    def _refresh_texts(self) -> None:
        """Titles and descriptions, rewritten in place — a text never moves a row."""
        faded = self.table.palette().text().color()
        faded.setAlpha(SECONDARY_ALPHA)
        for row in range(self.table.rowCount()):
            step_id = self._step_at(row)
            if step_id is None or not self._product.has(step_id):
                continue
            step = self._product.step(step_id)
            title = self.table.item(row, STEP_COLUMN)
            description = self.table.item(row, DESCRIPTION_COLUMN)
            if title is None or description is None:
                continue
            title.setText(step.title or "Untitled step")
            description.setText(self._deps.step_summary(step_id))
            description.setToolTip(self._deps.describe_step(step_id))
            description.setForeground(faded)

    def _apply_filter(self) -> None:
        wanted = FILTERS[max(self._filters.checkedId(), 0)][0]
        for row in range(self.table.rowCount()):
            step_id = self._step_at(row)
            if step_id is None or not self._product.has(step_id):
                continue
            estimated = read(self._product.step(step_id)) is not None
            hidden = (wanted == FILTER_UNESTIMATED and estimated) or (
                wanted == FILTER_ESTIMATED and not estimated
            )
            self.table.setRowHidden(row, hidden)
        self._update_summary()

    def _update_summary(self) -> None:
        """Counted over the scope, not the filter, so it never lies while rows are hidden."""
        days = [read(step) for step in self._steps()]
        sized = [d for d in days if d is not None]
        text = f"{len(sized)} of {len(days)} estimated"
        if sized:
            text += f" · {format_days(sum(sized))}"
        self._summary.setText(text)

    def _focus_first_row(self) -> None:
        for row in range(self.table.rowCount()):
            step_id = self._step_at(row)
            if step_id is not None and not self.table.isRowHidden(row):
                editor = self._editors.get(step_id)
                if editor is not None:
                    editor.days.setFocus()
                return

    # -- rows ----------------------------------------------------------------------------------

    def _step_at(self, row: int) -> StepId | None:
        item = self.table.item(row, STEP_COLUMN)
        if item is None:
            return None
        found = item.data(STEP_ROLE)
        return found if isinstance(found, str) else None

    def _selected_step(self) -> StepId | None:
        row = self.table.currentRow()
        return self._step_at(row) if row >= 0 else None

    def _select_row_of(self, step_id: StepId) -> None:
        for row in range(self.table.rowCount()):
            if self._step_at(row) == step_id:
                self.table.selectRow(row)
                return

    def _commit(self, step_id: StepId, editor: EstimateInput) -> None:
        if not self._product.has(step_id):
            return
        # Make the row current first, so the step detail panel shows the step being sized.
        self._select_row_of(step_id)
        push_estimate(self._product, self._deps.undo, step_id, editor.value(), origin=editor)

    # -- the model talking back ----------------------------------------------------------------

    def _on_structure(self, _node: NodeId, _origin: object) -> None:
        if not self._product.has(self.project_id):
            return  # The module's orphan hook closes this tab.
        if self._selection is not None:
            survivors = tuple(s for s in self._selection if self._product.has(s))
            if survivors != self._selection:
                self._selection = survivors or None
                self._scope_bar.setVisible(self._selection is not None)
                if self._selection is not None:
                    self._selection_button.setText(f"Selection ({len(self._selection)})")
        self._rebuild()

    def _on_text(self, _edit: TextEdit, _origin: object) -> None:
        self._refresh_texts()

    def _on_module_data(self, node_id: NodeId, module_id: str, origin: object) -> None:
        if module_id != MODULE_ID:
            return
        editor = self._editors.get(node_id)
        if editor is not None and origin is not editor:
            editor.show_days(read(self._product.step(node_id)))
        # Hide/show only — this handler runs synchronously inside a row's own chip click.
        self._apply_filter()

    # -- speaking for the user -----------------------------------------------------------------

    def _publish(self, step_id: StepId | None) -> None:
        if not self._is_active:
            return  # See _is_active: a background pane does not speak for the user.
        nodes = () if step_id is None else (ContextNode(selection_uri("step", step_id)),)
        self._deps.context.set_scope(SCOPE_SELECTION, nodes)

    def _on_selection(self) -> None:
        self._publish(self._selected_step())

    def _on_row_activated(self, row: int, _column: int) -> None:
        step_id = self._step_at(row)
        if step_id is not None:
            self._deps.reveal_step(step_id)

    def _on_context_menu(self, position: object) -> None:
        assert isinstance(position, QPoint)
        row = self.table.rowAt(position.y())
        if self._step_at(row) is None:
            return
        self.table.selectRow(row)
        menu: QMenu = build_menu(self._deps.actions, self._deps.context, "Step", self.table)
        menu.exec(self.table.viewport().mapToGlobal(position))
