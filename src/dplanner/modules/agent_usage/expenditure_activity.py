"""What each step's agents consumed, in the order the work can be done — the Expenditure
tab's columns, cells and words (the activity is ``module.py``'s ``ExpenditureActivity``).

The Order tab with other columns: the same rows (``framework/step_table.py``), the same
switches, the same gestures, and after the title what the ledger says each step's runs
consumed — fresh input, cache reads, output — the running total down the order, what was
expected of each step and the running offset between the two (``domain/expenditure.py``).
**Tokens, never money**: a token's price depends on the plan, the tier and the mode, and on
a subscription nothing is spent at all.

**Expected is learned**, from the tokens of work (fresh input and output) finished steps
consumed per estimated day — the library's other projects first, this one when nothing else
has history, which the volume line's tooltip says. With no history the expected columns are
empty rather than invented. The offset reads down the order: a finished row says how far the
work so far is over or under what its estimates predicted, in the tone a status takes —
under or on is ``ok``, up to a quarter over ``warn``, beyond that ``error``.

**By model** adds an in/out pair per model the project used, most work first — a playbook
runs one step on several. The CSV export is long, a row per step and model, so a new model
adds rows a spreadsheet pivots on, never columns.
"""

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QVBoxLayout, QWidget

from dplanner.domain.agents import short_count
from dplanner.domain.expenditure import ELSEWHERE, Rate, Row, Spent, expenditure, models_in, totals
from dplanner.domain.model import NodeId, ProjectId, StepId
from dplanner.domain.ordering import placed
from dplanner.framework.action_menu import build_menu
from dplanner.framework.activity import (
    EntityActivity,
    follow_project,
    project_tab_title,
)
from dplanner.framework.context import (
    SCOPE_SELECTION,
    Context,
    ContextNode,
    Uri,
    activity_uri,
    selection_uri,
)
from dplanner.framework.debounce import Debounced
from dplanner.framework.signalling import Tone, UpdatingIndicator, tone_colour
from dplanner.framework.step_table import StepTable
from dplanner.framework.table import Cell, Column
from dplanner.framework.toolbar import ActionToolbar
from dplanner.framework.widgets import EmptyState, captioned, note
from dplanner.modules.agent_usage.aspect import (
    ledger_stamp,
    step_spent,
    token_rate,
)
from dplanner.planning.estimate import start_of
from dplanner.planning.kinds import key_of, works_nobody
from dplanner.planning.milestone import read as milestone_label
from dplanner.planning.schedule import schedule

if TYPE_CHECKING:  # module.py imports this file, so the Deps arrive as a forward name.
    from dplanner.modules.agent_usage.module import AgentUsageDeps


EXPENDITURE_KIND = "expenditure"
# How often the Expenditure tab looks at the ledger: another process writes it.
LEDGER_POLL_MS = 2000
# How far over its estimates the work so far may run before the offset says so loudly.
WARN_OVER = 0.25

TOTALS = (
    Column("Runs", numeric=True),
    Column("Models"),
    Column("In", numeric=True),
    Column("Cached", numeric=True),
    Column("Out", numeric=True),
)
RUNNING = (
    Column("Running", numeric=True),
    Column("Expected", numeric=True),
    Column("Running expected", numeric=True),
    # The last column takes the slack.
    Column("Offset"),
)


def columns(models: Sequence[str] = ()) -> tuple[Column, ...]:
    """The columns after the title, all in tokens: the totals, an in/out pair per model
    when asked for, and the running sums."""
    pairs = tuple(
        Column(f"{model} {side}", numeric=True) for model in models for side in ("in", "out")
    )
    return (*TOTALS, *pairs, *RUNNING)


def offset_tone(offset: float) -> Tone:
    """The tone of the number as it is shown: +0% is on budget, whatever the decimals."""
    if round(offset * 100) <= 0:
        return "ok"
    return "warn" if offset <= WARN_OVER else "error"


def offset_words(offset: float | None) -> str:
    return "" if offset is None else f"{round(offset * 100):+d}%"


def row_cells(row: Row, fixed: bool, models: Sequence[str] = ()) -> list[Cell]:
    """A row's cells after the title, in ``columns(models)``'s order. A count of nothing is
    an empty cell, not a zero: most steps have no runs, and a column of zeros reads louder
    than the few that do."""
    spent = row.spent
    tokens = spent.tokens

    def count(value: float | None) -> Cell:
        return Cell(short_count(value) if value else "", emphasis=fixed)

    cells = [
        count(spent.runs),
        Cell(", ".join(sorted(spent.models)), secondary=True, emphasis=fixed),
        count(tokens.input),
        count(tokens.cached),
        count(tokens.output),
    ]
    for model in models:
        used = spent.models.get(model)
        cells += [count(used.input if used else 0), count(used.output if used else 0)]
    cells += [
        count(row.running),
        count(row.expected),
        count(row.running_expected),
        Cell(
            offset_words(row.offset),
            ink=None if row.offset is None else tone_colour(offset_tone(row.offset)),
            emphasis=fixed,
        ),
    ]
    return cells


def volume_words(rows: Sequence[Row], finished: int, work: int) -> str:
    """The line under the caption: how far along, what it consumed, and how that compares."""
    total = totals(rows)
    said = (
        f"{finished} of {work} finished · {short_count(total.input)} in · "
        f"{short_count(total.cached)} cached · {short_count(total.output)} out"
    )
    last = next((row.offset for row in reversed(rows) if row.offset is not None), None)
    if last is not None:
        said += f" · {abs(round(last * 100))}% {'over' if last > 0 else 'under'} expected"
    return said


def rate_words(rate: Rate | None) -> str:
    """Where *expected* comes from, for the volume line's tooltip."""
    if rate is None:
        return (
            "Nothing is expected yet: a step's expected tokens are learned from finished"
            " steps that have an estimate and recorded agent runs."
        )
    where = "the library's other projects" if rate.source == ELSEWHERE else "this project"
    plural = "s" if rate.steps != 1 else ""
    return (
        f"Expected is the step's estimate times {short_count(rate.per_day)} tokens of work"
        f" (fresh input and output) per estimated day, learned from {rate.steps} finished"
        f" step{plural} in {where}."
    )


def export_rows(
    rows: Sequence[Row], key_of: Callable[[StepId], str], done_of: Callable[[StepId], bool]
) -> list[list[str]]:
    """One CSV row per step and model, so a new model adds rows, never columns."""
    out = [["#", "Key", "Step", "Finished", "Runs", "Model", "In", "Cached", "Out"]]
    for row in rows:
        step = row.place.step
        for model, counts in sorted(row.spent.models.items()):
            out.append(
                [
                    str(row.place.index),
                    key_of(step.id),
                    step.title,
                    "yes" if done_of(step.id) else "",
                    str(row.spent.runs),
                    model,
                    str(counts.input),
                    str(counts.cached),
                    str(counts.output),
                ]
            )
    return out


PANEL_MARGIN = 16


CAPTION_GAP = 6


BLOCK_GAP = 12


SWITCH_GAP = 16


def _step_context(step_id: StepId) -> Context:
    """A context naming exactly one step — what a row's double-click runs a verb against."""
    return Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step_id)),)})


def rate_of(deps: "AgentUsageDeps", project_id: ProjectId) -> Rate | None:
    """Tokens of work per estimated day, learned from the library's finished steps."""
    return token_rate(deps.store, deps.library, project_id, lambda s: deps.step_done(s.id))


class ExpenditureActivity(EntityActivity):
    """One project's steps, in order, with what their agents consumed."""

    def __init__(self, deps: "AgentUsageDeps", project_id: NodeId) -> None:
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
        self._stamp = ledger_stamp(deps.store, self.project_id)
        rate = rate_of(deps, self.project_id)
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
        work = [row.place.step for row in rows if not works_nobody(row.place.step)]
        finished = sum(deps.step_done(step.id) for step in work)
        self.volume.setText(volume_words(rows, finished, len(work)))
        self.volume.setToolTip(rate_words(rate))
        self.volume.setVisible(bool(rows))
        self.empty.say("" if rows else "Steps appear here in the order they can be done.")

    def _check_ledger(self) -> None:
        if not self._product.has(self.project_id):
            return
        if ledger_stamp(self._deps.store, self.project_id) != self._stamp:
            self._refresh_soon.trigger()

    def _new_table(self, models: Sequence[str]) -> StepTable:
        # Built parentless and adopted by the layout: a Table built as the child of a page
        # already on screen kept an 18-pixel header the stylesheet never padded
        # (NOTES-FOR-APPFRAME.md has the measurement).
        deps = self._deps
        table = StepTable(
            columns(models),
            lambda step_id: milestone_label(deps.library.step(step_id)),
            deps.step_icons,
            deps.milestone_color,
            lambda step_id: key_of(deps.library.step(step_id)),
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


def expenditure_of(deps: "AgentUsageDeps", project_id: ProjectId, rate: Rate | None) -> list[Row]:
    """The project's order with what each step consumed — the tab's rows and the export's."""
    project = deps.library.project(project_id)
    order = placed(deps.library, project)
    days = {row.place.step.id: row.days for row in schedule(order, start_of(project))}
    spent = step_spent(deps.store, project_id)
    return expenditure(
        order,
        lambda step: spent.get(step.id, Spent()),
        lambda step: days.get(step.id),
        lambda step: deps.step_done(step.id),
        rate,
    )
