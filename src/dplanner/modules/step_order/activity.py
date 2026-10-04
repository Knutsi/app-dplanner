"""The Order tab: one row per step, in the order the work can be done.

A table rather than a nested list, because the thing being shown *is* a sorted sequence and
the first thing you want from one is a position. The wave rides along as a column: two steps
sharing a wave can be started together, and the first wave is the answer to "what now".

The row look — the glyph of what a step is, the milestone's badge and shade, the done mark,
the kind switches — is ``framework/step_table.py``'s :class:`StepTable`, which the
Expenditure tab (``agent_usage``) hosts too; this table follows it with the wave, the
estimate and the aspects.

**No calendar.** The table once ran the order out as dates — accumulated days, days since
the last milestone, a landing date per row — one worker after another from a start date
set on this page. That is not how the work happens and not how the plan is scheduled
(``schedule`` simulates two pools of workers), so the tab states the volume instead
and leaves dating to ``dplanner schedule show``. The estimate stays: it is the step's own
fact, rendered with ``planning/schedule.py``'s formatter so this table and the terminal
cannot express one number two ways.

Rebuilt whenever the graph changes. A project holds tens of steps, so a whole redraw is
cheaper to read than a diff and cannot go stale.
"""

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QVBoxLayout, QWidget

from dplanner.domain.model import Library, NodeId, Project, ProjectId, StepId
from dplanner.domain.ordering import Placed, placed
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
from dplanner.framework.signalling import UpdatingIndicator
from dplanner.framework.step_table import LEAD, StepTable
from dplanner.framework.table import Cell, Column
from dplanner.framework.toolbar import ActionToolbar
from dplanner.framework.widgets import EmptyState, captioned, note
from dplanner.modules.step_order.cli import wave_label
from dplanner.planning.estimate import start_of
from dplanner.planning.schedule import Scheduled, format_days, schedule, volume, volume_words

if TYPE_CHECKING:  # module.py imports this file, so the Deps arrive as a forward name.
    from dplanner.modules.step_order.module import StepOrderDeps


COLUMNS = (
    *LEAD,
    Column("Wave"),
    Column("Estimate", numeric=True),
    # What the aspect modules say about the step; the last column takes the slack.
    Column(""),
)
# Positions in ``COLUMNS``, for whoever reads a row back by column rather than by name.
TITLE_COLUMN = 1
ESTIMATE_COLUMN = 3
ASPECTS_COLUMN = 4


class OrderTable(StepTable):
    """The order: each step's wave, its estimate and what its aspects say."""

    def __init__(
        self,
        wave_label: Callable[[int], str],
        step_aspects: Callable[[StepId], list[str]],
        milestone_label: Callable[[StepId], str] = lambda _step_id: "",
        step_icons: Callable[[StepId], tuple[str, ...]] = lambda _step_id: (),
        milestone_color: Callable[[StepId], str] = lambda _step_id: "",
        step_key: Callable[[StepId], str] = lambda _step_id: "",
        step_done: Callable[[StepId], bool] = lambda _step_id: False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            COLUMNS[len(LEAD) :],
            milestone_label,
            step_icons,
            milestone_color,
            step_key,
            step_done,
            parent,
        )
        self._wave_label = wave_label
        self._step_aspects = step_aspects

    def show_order(self, order: Sequence[Scheduled]) -> None:
        days = {scheduled.place.step.id: scheduled.days for scheduled in order}

        def trailing(place: Placed, fixed: bool) -> Sequence[Cell]:
            return (
                Cell(self._wave_label(place.wave - 1), emphasis=fixed),
                Cell(format_days(days[place.step.id]), emphasis=fixed),
                Cell(
                    " · ".join(self._step_aspects(place.step.id)),
                    secondary=not fixed,
                    emphasis=fixed,
                ),
            )

        self.show_steps([scheduled.place for scheduled in order], trailing)


ORDER_KIND = "order"


PANEL_MARGIN = 16


CAPTION_GAP = 6


BLOCK_GAP = 12


SWITCH_GAP = 16


def _step_context(step_id: StepId) -> Context:
    """A context naming exactly one step — what a row's double-click runs a verb against."""
    return Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step_id)),)})


def schedule_rows(
    library: Library, project_id: ProjectId, order: Sequence[Placed]
) -> list[Scheduled]:
    """The order carrying what each step costs and when it lands, from the project's start."""
    return schedule(order, start_of(library.project(project_id)))


class OrderActivity(EntityActivity):
    """One project's steps, in waves."""

    def __init__(self, deps: "StepOrderDeps", project_id: NodeId) -> None:
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
        scheduled = schedule_rows(self._deps.library, self.project_id, order)
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
