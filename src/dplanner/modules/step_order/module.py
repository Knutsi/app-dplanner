"""The order a project can be done in, as a tab beside the graph it came from.

A project is a graph, and this answers the question a graph is for: what can be started now,
and what has to wait for what. The walk itself is the domain's — this module renders it and
adds nothing to the model.

**Nothing here is stored.** The order is recomputed whenever the graph changes, which is what
makes it impossible for it to disagree with the graph. See ``domain/ordering.py``.

Three seams, all established elsewhere in this application:

- **Selecting a step publishes the selection scope**, so the Step menu's verbs target it —
  this view never learns that those verbs exist.
- **Activating one opens its details**, by running ``steps.details`` against a context
  naming exactly that row's step — the same registry path the menus use, so whoever owns
  the dialog is not this module's business.
- **The estimates arrive as an answer, not as data to interpret.** Whoever owns them hands
  over the order already carrying each step's days. This module never learns what an
  estimate is stored as, and there is a working default for a build with nobody to ask.

**A second tab reads the same order for what it consumed**: *Expenditure* — each step's
agent runs from the project's usage ledger, in tokens, against what its estimate predicted
(``expenditure.py`` has its columns and words, ``domain/expenditure.py`` the walk). The same
rows, switches and gestures as the order; its own Deps are three callbacks, since where the
ledger lives and how a rate is learned are the composition root's to know.

What the order page says under its caption is the **volume**: the estimated days the order comes
to, over how many steps, and how many nobody has sized — the sentence ``dplanner order
show``, ``estimate rollup`` and the Estimates tab all print (``planning/schedule.py``'s
``volume_words``). It replaced a paragraph explaining what a wave is, which is now the
caption's own info glyph, and the serial calendar the table used to run out beside it.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QVBoxLayout, QWidget

from dplanner.core.fsio import write_csv
from dplanner.domain.expenditure import Rate, Row, Spent, expenditure, models_in
from dplanner.domain.model import Library, NodeId, Project, ProjectId, Step, StepId
from dplanner.domain.ordering import Placed, placed
from dplanner.framework.action_menu import build_menu
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.activity import (
    EntityActivity,
    follow_project,
    follow_project_tabs,
    project_tab_title,
)
from dplanner.framework.context import (
    SCOPE_SELECTION,
    Context,
    ContextNode,
    ContextService,
    Uri,
    activity_uri,
    selection_uri,
)
from dplanner.framework.debounce import Debounced, DebounceService
from dplanner.framework.signalling import UpdatingIndicator
from dplanner.framework.step_selection import focused_project
from dplanner.framework.tabs import TabHost
from dplanner.framework.toolbar import ActionToolbar
from dplanner.framework.widgets import EmptyState, captioned, note
from dplanner.modules.step_order.cli import wave_label
from dplanner.modules.step_order.expenditure import (
    EXPENDITURE_KIND,
    columns,
    export_rows,
    rate_words,
    row_cells,
)
from dplanner.modules.step_order.expenditure import (
    volume_words as spent_words,
)
from dplanner.modules.step_order.export import order_rows
from dplanner.modules.step_order.view import OrderTable, StepTable
from dplanner.planning.estimate import start_of
from dplanner.planning.schedule import Scheduled, schedule, volume, volume_words
from dplanner.theme.icons import list_icon, spark_icon

MODULE_ID = "step_order"
ORDER_KIND = "order"

PANEL_MARGIN = 16
CAPTION_GAP = 6
BLOCK_GAP = 12
SWITCH_GAP = 16
# How often the Expenditure tab looks at the ledger: another process writes it.
LEDGER_POLL_MS = 2000


def _no_aspects(_step_id: StepId) -> list[str]:
    return []


def _step_context(step_id: StepId) -> Context:
    """A context naming exactly one step — what a row's double-click runs a verb against."""
    return Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step_id)),)})


def _no_milestone(_step_id: StepId) -> str:
    return ""


def _no_color(_step_id: StepId) -> str:
    return ""


def _no_icons(_step_id: StepId) -> tuple[str, ...]:
    return ()


def _scheduled(library: Library, project_id: ProjectId, order: Sequence[Placed]) -> list[Scheduled]:
    """The order carrying what each step costs and when it lands, from the project's start."""
    return schedule(order, start_of(library.project(project_id)))


@dataclass(frozen=True)
class StepOrderDeps:
    library: Library
    actions: ActionRegistry
    context: ContextService
    parent: QWidget  # The CSV export's file dialog needs a window to parent on.
    debounce: DebounceService
    tabs: TabHost
    # What the aspect modules have to say about a step, one short phrase each.
    step_aspects: Callable[[StepId], list[str]] = field(default=_no_aspects)
    # The label of the milestone a step is, "" otherwise. Wired by the composition root;
    # this module never learns who owns milestones.
    milestone_label: Callable[[StepId], str] = field(default=_no_milestone)
    # What kind of thing a step is, in the canvas medallions' vocabulary ("tag", "layers"),
    # so the title column wears the same marks the graph does. Wired by the composition
    # root; this module never learns which aspects the kinds stand for.
    step_icons: Callable[[StepId], tuple[str, ...]] = field(default=_no_icons)
    # A milestone's own shade of the project's colour map, and the key its row wears as
    # a badge. Both from the composition root: which map a project uses is one module's
    # assumption and a step's key is another's letter, and this one learns neither.
    milestone_color: Callable[[StepId], str] = field(default=_no_color)
    step_key: Callable[[StepId], str] = field(default=_no_color)
    # Whether a step is work at all: a wait is not, and is no part of the volume.
    counts_as_work: Callable[[Step], bool] = field(default=lambda _step: True)
    # Whether a step is finished — its row wears the done mark and its title is in italic.
    # Wired by the composition root; this module never learns where a status is stored.
    step_done: Callable[[StepId], bool] = field(default=lambda _step_id: False)
    # What each step's agent runs consumed, per model, from the project's usage ledger; the
    # tokens of work a finished step consumed per estimated day (None with no history);
    # and what the ledger looks like on disk, polled. All three from the composition root,
    # which knows where a ledger lives and which projects a rate is learned from.
    step_spent: Callable[[ProjectId], Mapping[StepId, Spent]] = field(default=lambda _p: {})
    token_rate: Callable[[ProjectId], Rate | None] = field(default=lambda _p: None)
    ledger_stamp: Callable[[ProjectId], object] = field(default=lambda _p: None)


class OrderActivity(EntityActivity):
    """One project's steps, in waves."""

    def __init__(self, deps: StepOrderDeps, project_id: NodeId) -> None:
        super().__init__(deps.context, "project", project_id)
        self._deps = deps
        self._product = deps.library
        self.project_id = project_id

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(CAPTION_GAP)

        # The caption row carries one quiet Export button whose arrow renders File ▸ Export
        # — the same entries, never a copy — so the exports are found where the table is.
        # What a wave is stands behind the caption's info glyph rather than in a paragraph
        # under it (DESIGN.md's *Words*): it is a convention, and a convention is read once.
        head = QHBoxLayout()
        layout.addLayout(head)
        head.addWidget(
            captioned(
                "Order",
                page,
                hint="Steps in an order that never puts one before what it waits on. "
                "Everything in Wave 1 can be started now.",
            ),
            1,
        )
        self.toolbar = ActionToolbar(
            deps.actions,
            deps.context,
            ("report.html",),
            {"report.html": "Export"},
            page,
            menus={"report.html": ("File", "Export")},
        )
        head.addWidget(self.toolbar)
        self.updating = UpdatingIndicator(page)
        head.addWidget(self.updating)

        # A remark that changes with the data, which is what #InspectorNote is for.
        self.volume = note("", page)
        layout.addWidget(self.volume)
        layout.addSpacing(BLOCK_GAP)

        # Two perspectives on one order: the work steps, the features, or both — the
        # milestones are the fixed points either way, so unticking both leaves the roadmap.
        switches = QWidget(page)
        switch_row = QHBoxLayout(switches)
        switch_row.setContentsMargins(0, 0, 0, 0)
        switch_row.setSpacing(SWITCH_GAP)
        self.show_steps = QCheckBox("Steps", switches)
        self.show_features = QCheckBox("Features", switches)
        for switch in (self.show_steps, self.show_features):
            switch.setChecked(True)
            switch.toggled.connect(self._on_kinds)
            switch_row.addWidget(switch)
        switch_row.addStretch(1)
        layout.addWidget(switches)
        layout.addSpacing(CAPTION_GAP)

        self.table = OrderTable(
            wave_label,
            deps.step_aspects,
            deps.milestone_label,
            deps.step_icons,
            deps.milestone_color,
            deps.step_key,
            deps.step_done,
            page,
        )
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.cellActivated.connect(self._on_activated)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.table, 1)
        # One swap, and the table is what it stands in for (DESIGN.md's *Words*).
        self.empty = EmptyState(parent=page, stands_in_for=self.table)
        layout.addWidget(self.empty, 1)

        self._widget = page
        # After a quiet spell, not per signal: the table is rebuilt row by row.
        self._refresh_soon = Debounced(self._refresh, parent=page, service=deps.debounce)
        self.updating.follow(self._refresh_soon)
        self._unsubscribes = [
            # Every signal, this project only. The title column's kind icons read prose
            # presence (an agent instruction), so a text edit can change what a row wears.
            follow_project(self._product, self.project_id, self._refresh_soon.trigger),
        ]
        self._refresh()

    # -- the activity contract -----------------------------------------------------------------

    @property
    def uri(self) -> Uri:
        return activity_uri(ORDER_KIND, self.project_id)

    @property
    def title(self) -> str:
        return project_tab_title(self._product, self.project_id, "Order")

    @property
    def widget(self) -> QWidget:
        return self._widget

    def on_activated(self) -> None:
        super().on_activated()
        self._publish(self.table.selected_step())

    def close(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self.toolbar.dispose()

    # -- internals -----------------------------------------------------------------------------

    def _project(self) -> Project:
        return self._product.project(self.project_id)

    def _refresh(self) -> None:
        if not self._product.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        order = placed(self._product, self._project())
        scheduled = _scheduled(self._deps.library, self.project_id, order)
        self.table.show_order(scheduled)
        days = {row.place.step.id: row.days for row in scheduled}
        steps = [row.place.step for row in scheduled]
        said = volume(steps, self._deps.counts_as_work, days_for=lambda step: days[step.id])
        self.volume.setText(volume_words(*said))
        self.volume.setVisible(bool(scheduled))
        self.empty.say("" if scheduled else "Steps appear here in the order they can be done.")

    def _on_kinds(self) -> None:
        self.table.show_kinds(
            steps=self.show_steps.isChecked(), features=self.show_features.isChecked()
        )

    def _publish(self, step_id: StepId | None) -> None:
        nodes = () if step_id is None else (ContextNode(selection_uri("step", step_id)),)
        self.publish_selection(nodes)

    def _on_selection(self) -> None:
        self._publish(self.table.selected_step())

    def _on_activated(self, row: int, _column: int) -> None:
        step_id = self.table.step_at(row)
        if step_id is not None:
            # Against a context naming exactly this row's step, not the service's — the
            # double-click means the row under it even if a publish was suppressed.
            self._deps.actions.run("steps.details", _step_context(step_id))

    def _on_context_menu(self, position: object) -> None:
        assert isinstance(position, QPoint)
        row = self.table.rowAt(position.y())
        if self.table.step_at(row) is None:
            return
        self.table.selectRow(row)
        menu = build_menu(self._deps.actions, self._deps.context, "Step", self.table)
        menu.exec(self.table.viewport().mapToGlobal(position))


class ExpenditureActivity(EntityActivity):
    """One project's steps, in order, with what their agents consumed."""

    def __init__(self, deps: StepOrderDeps, project_id: NodeId) -> None:
        super().__init__(deps.context, "project", project_id)
        self._deps = deps
        self._product = deps.library
        self.project_id = project_id
        self._models: tuple[str, ...] = ()
        self._stamp: object = None

        page = QWidget()
        self._widget = page
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(CAPTION_GAP)
        head = QHBoxLayout()
        layout.addLayout(head)
        head.addWidget(
            captioned(
                "Expenditure",
                page,
                hint="Tokens each step's agent runs consumed — the main agent and every"
                " subagent — in the order the work can be done, against what the step's"
                " estimate predicted. Fresh input and output are the work; cache reads are"
                " context read again, counted apart.",
            ),
            1,
        )
        self.toolbar = ActionToolbar(
            deps.actions,
            deps.context,
            ("expenditure.export",),
            {"expenditure.export": "Export"},
            page,
            menus={"expenditure.export": ("File", "Export")},
        )
        head.addWidget(self.toolbar)
        self.updating = UpdatingIndicator(page)
        head.addWidget(self.updating)
        self.volume = note("", page)
        layout.addWidget(self.volume)
        layout.addSpacing(BLOCK_GAP)

        switches = QWidget(page)
        switch_row = QHBoxLayout(switches)
        switch_row.setContentsMargins(0, 0, 0, 0)
        switch_row.setSpacing(SWITCH_GAP)
        self.show_steps = QCheckBox("Steps", switches)
        self.show_features = QCheckBox("Features", switches)
        for switch in (self.show_steps, self.show_features):
            switch.setChecked(True)
            switch.toggled.connect(self._on_kinds)
            switch_row.addWidget(switch)
        # One step may run on several models (a playbook's stages): a pair of columns each.
        self.by_model = QCheckBox("By model", switches)
        self.by_model.toggled.connect(lambda _on: self._refresh())
        switch_row.addWidget(self.by_model)
        switch_row.addStretch(1)
        layout.addWidget(switches)
        layout.addSpacing(CAPTION_GAP)

        self._layout = layout
        self.table = self._new_table(())
        layout.addWidget(self.table, 1)
        self.empty = EmptyState(parent=page, stands_in_for=self.table)
        layout.addWidget(self.empty, 1)

        self._refresh_soon = Debounced(self._refresh, parent=page, service=deps.debounce)
        self.updating.follow(self._refresh_soon)
        self._unsubscribes = [
            follow_project(self._product, self.project_id, self._refresh_soon.trigger),
        ]
        # An agent's harvest writes the ledger from another process, and nothing in the
        # model says so: the tab looks, cheaply, and rebuilds only when it changed.
        self._poll = QTimer(page)
        self._poll.setInterval(LEDGER_POLL_MS)
        self._poll.timeout.connect(self._check_ledger)
        self._poll.start()
        self._refresh()

    # -- the activity contract -----------------------------------------------------------------

    @property
    def uri(self) -> Uri:
        return activity_uri(EXPENDITURE_KIND, self.project_id)

    @property
    def title(self) -> str:
        return project_tab_title(self._product, self.project_id, "Expenditure")

    @property
    def widget(self) -> QWidget:
        return self._widget

    def on_activated(self) -> None:
        super().on_activated()
        self._publish(self.table.selected_step())

    def close(self) -> None:
        self._poll.stop()
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self.toolbar.dispose()

    # -- internals -----------------------------------------------------------------------------

    def _refresh(self) -> None:
        if not self._product.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        deps = self._deps
        self._stamp = deps.ledger_stamp(self.project_id)
        rate = deps.token_rate(self.project_id)
        rows = expenditure_of(deps, self.project_id, rate)
        models = tuple(models_in(rows)) if self.by_model.isChecked() else ()
        if models != self._models:
            self._replace_table(models)
        by_step = {row.place.step.id: row for row in rows}
        self.table.show_steps(
            [row.place for row in rows],
            lambda place, fixed: row_cells(by_step[place.step.id], fixed, models),
        )
        self._on_kinds()
        work = [row.place.step for row in rows if deps.counts_as_work(row.place.step)]
        finished = sum(deps.step_done(step.id) for step in work)
        self.volume.setText(spent_words(rows, finished, len(work)))
        self.volume.setToolTip(rate_words(rate))
        self.volume.setVisible(bool(rows))
        self.empty.say("" if rows else "Steps appear here in the order they can be done.")

    def _check_ledger(self) -> None:
        if not self._product.has(self.project_id):
            return
        if self._deps.ledger_stamp(self.project_id) != self._stamp:
            self._refresh_soon.trigger()

    def _new_table(self, models: Sequence[str]) -> StepTable:
        # Built parentless and adopted by the layout: a Table built as the child of a page
        # already on screen kept an 18-pixel header the stylesheet never padded
        # (NOTES-FOR-APPFRAME.md has the measurement).
        deps = self._deps
        table = StepTable(
            columns(models),
            deps.milestone_label,
            deps.step_icons,
            deps.milestone_color,
            deps.step_key,
            deps.step_done,
        )
        table.itemSelectionChanged.connect(lambda: self._publish(table.selected_step()))
        table.cellActivated.connect(self._on_activated)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._on_context_menu)
        return table

    def _replace_table(self, models: Sequence[str]) -> None:
        """A table's columns are its own from birth: another set of models is another one."""
        old = self.table
        self.table = self._new_table(models)
        self._layout.replaceWidget(old, self.table)
        self.empty.stands_in_for = self.table
        old.hide()
        old.deleteLater()
        self._models = tuple(models)

    def _on_kinds(self) -> None:
        self.table.show_kinds(
            steps=self.show_steps.isChecked(), features=self.show_features.isChecked()
        )

    def _publish(self, step_id: StepId | None) -> None:
        nodes = () if step_id is None else (ContextNode(selection_uri("step", step_id)),)
        self.publish_selection(nodes)

    def _on_activated(self, row: int, _column: int) -> None:
        step_id = self.table.step_at(row)
        if step_id is not None:
            self._deps.actions.run("steps.details", _step_context(step_id))

    def _on_context_menu(self, position: object) -> None:
        assert isinstance(position, QPoint)
        row = self.table.rowAt(position.y())
        if self.table.step_at(row) is None:
            return
        self.table.selectRow(row)
        menu = build_menu(self._deps.actions, self._deps.context, "Step", self.table)
        menu.exec(self.table.viewport().mapToGlobal(position))


def expenditure_of(deps: StepOrderDeps, project_id: ProjectId, rate: Rate | None) -> list[Row]:
    """The project's order with what each step consumed — the tab's rows and the export's."""
    order = placed(deps.library, deps.library.project(project_id))
    days = {row.place.step.id: row.days for row in _scheduled(deps.library, project_id, order)}
    spent = deps.step_spent(project_id)
    return expenditure(
        order,
        lambda step: spent.get(step.id, Spent()),
        lambda step: days.get(step.id),
        lambda step: deps.step_done(step.id),
        rate,
    )


class StepOrderModule:
    id = MODULE_ID

    def __init__(self, deps: StepOrderDeps) -> None:
        self._deps = deps

    def open(self, project_id: NodeId, *, preview: bool = False) -> None:
        self._deps.tabs.open(ORDER_KIND, project_id, preview=preview)

    def open_expenditure(self, project_id: NodeId, *, preview: bool = False) -> None:
        self._deps.tabs.open(EXPENDITURE_KIND, project_id, preview=preview)

    def register(self) -> None:
        deps = self._deps

        def factory(target: str | None) -> OrderActivity:
            assert target is not None
            return OrderActivity(deps, target)

        deps.tabs.register_factory(ORDER_KIND, factory)

        def expenditure_factory(target: str | None) -> ExpenditureActivity:
            assert target is not None
            return ExpenditureActivity(deps, target)

        deps.tabs.register_factory(EXPENDITURE_KIND, expenditure_factory)
        # A surface of the project, so Go's — and the canvas strip's Go band runs the same
        # id. Its second seat is Step ▸ Show in, which a table's right-click offers and a
        # card's leaves to the index beside it. palette=False there: one palette entry.
        deps.actions.register(
            ActionSpec(
                id="order.open",
                label="&Order",
                menu="Go",
                group="views",
                order=25,
                icon=list_icon,
                tip="What can be started now, and what waits for what",
                state=self._on_a_project,
                run=self._open,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="order.open_step",
                label="&Order",
                menu="Step",
                group="surfaces",
                submenu="Show in",
                order=20,
                icon=list_icon,
                tip="What can be started now, and what waits for what",
                palette=False,
                state=self._on_a_project,
                run=self._open,
            )
        )
        # File ▸ Export ▸ Order List: the same rows the table shows, as a CSV a spreadsheet
        # can compute with. The submenu leaves room for other features' exports beside it.
        deps.actions.register(
            ActionSpec(
                id="order.export",
                label="&Order List (CSV)…",
                menu="File",
                group="export",
                submenu="Export",
                order=10,
                tip="Write the focused project's order to a CSV file",
                state=self._on_a_project,
                run=self._export,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="expenditure.open",
                label="E&xpenditure",
                menu="Go",
                group="views",
                order=27,
                icon=spark_icon,
                tip="What each step's agent runs consumed, in tokens, against what was expected",
                state=self._on_a_project,
                run=self._open_expenditure,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="expenditure.export",
                label="&Expenditure (CSV)…",
                menu="File",
                group="export",
                submenu="Export",
                order=15,
                tip="Write what the focused project's steps consumed to a CSV file:"
                " a row per step and model",
                state=self._on_a_project,
                run=self._export_expenditure,
            )
        )
        follow_project_tabs(deps.tabs, OrderActivity, deps.library)
        follow_project_tabs(deps.tabs, ExpenditureActivity, deps.library)

    def _on_a_project(self, context: Context) -> ActionState:
        return DISABLED if focused_project(context, self._deps.library) is None else ENABLED

    def _open_expenditure(self, context: Context) -> None:
        project = focused_project(context, self._deps.library)
        if project is not None:
            self.open_expenditure(project.id)

    def _export_expenditure(self, context: Context) -> None:
        deps = self._deps
        project = focused_project(context, deps.library)
        if project is None:
            return
        found = expenditure_of(deps, project.id, deps.token_rate(project.id))
        rows = export_rows(found, deps.step_key, deps.step_done)
        suggested = f"{project.title or 'Untitled project'} expenditure.csv"
        chosen, _filter = QFileDialog.getSaveFileName(
            deps.parent, "Export Expenditure", str(Path.home() / suggested), "CSV files (*.csv)"
        )
        if not chosen:
            return
        path = Path(chosen)
        write_csv(path if path.suffix.lower() == ".csv" else path.with_suffix(".csv"), rows)

    def _open(self, context: Context) -> None:
        project = focused_project(context, self._deps.library)
        if project is not None:
            self.open(project.id)

    def _export(self, context: Context) -> None:
        deps = self._deps
        project = focused_project(context, deps.library)
        if project is None:
            return
        project_id = project.id
        order = placed(deps.library, project)
        rows = order_rows(
            _scheduled(deps.library, project_id, order), deps.step_aspects, deps.milestone_label
        )
        suggested = f"{project.title or 'Untitled project'} order.csv"
        chosen, _filter = QFileDialog.getSaveFileName(
            deps.parent, "Export Order List", str(Path.home() / suggested), "CSV files (*.csv)"
        )
        if not chosen:
            return
        path = Path(chosen)
        if path.suffix.lower() != ".csv":
            path = path.with_suffix(".csv")
        write_csv(path, rows)
