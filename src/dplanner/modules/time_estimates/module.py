"""How long the project takes with a stated team, as a tab beside the graph it prices.

``schedule show`` and the order table print the brackets — serial, critical path. This tab
prints what lands between them: a small grid of people by coding agents, each cell the
simulated makespan under that cap, once in project working days and once in calendar days
with a person's divided focus priced in. The simulation is the domain's
(``parallel_finish``); this module renders it and stores exactly one thing — the focus
factor (see ``schedule.py`` beside this file).

The estimate, agent-step and start-date readers arrive as functions on the Deps, so this
module never learns what an estimate is stored as or what marks a step for an agent — the
same seams the progression board uses.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from dplanner.domain.model import Library, NodeId, Project, ProjectId, Step
from dplanner.domain.schedule import format_days
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.activity import EntityActivity, follow_entity_tabs
from dplanner.framework.context import Context, ContextService, Uri, activity_uri
from dplanner.framework.tabs import TabHost
from dplanner.framework.undo import UndoService
from dplanner.modules.time_estimates.schedule import MODULE_ID, read_efficiency, time_report
from dplanner.modules.time_estimates.view import FocusBar, MatrixTable

TIME_KIND = "time"

PANEL_MARGIN = 16
CAPTION_GAP = 6
BLOCK_GAP = 12


class StartBar(Protocol):
    """The control the calendar grid is measured from.

    Consumer-owned interface, satisfied structurally by the estimation module's start-date
    bar via the composition root — the order view's arrangement, redeclared here because
    modules never import each other.
    """

    @property
    def widget(self) -> QWidget: ...

    def dispose(self) -> None: ...


@dataclass(frozen=True)
class TimeEstimatesDeps:
    library: Library
    undo: UndoService[Library]
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    # Estimates and agent-ness through the aspects' Qt-free readers — the matrix never
    # learns what either is stored as.
    days_for: Callable[[Step], float | None]
    is_agent: Callable[[Step], bool]
    # When the project's work begins; whoever owns start dates answers.
    start_of: Callable[[ProjectId], date]
    # The widget that sets that date. None is a legitimate build.
    start_bar: Callable[[ProjectId, QWidget], StartBar] | None = None


class TimeEstimatesActivity(EntityActivity):
    """One project's staffing matrix, twice: project days, then calendar days."""

    def __init__(self, deps: TimeEstimatesDeps, project_id: NodeId) -> None:
        super().__init__(deps.context, "project", project_id)
        self._deps = deps
        self._product = deps.library
        self.project_id = project_id

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(CAPTION_GAP)

        caption = QLabel("Time Estimates", page)
        caption.setObjectName("InspectorCaption")
        layout.addWidget(caption)

        self.start_bar: StartBar | None = None
        layout.addSpacing(BLOCK_GAP)
        if deps.start_bar is not None:
            self.start_bar = deps.start_bar(project_id, page)
            layout.addWidget(self.start_bar.widget)
        self.focus_bar = FocusBar(deps.library, deps.undo, project_id, page)
        layout.addWidget(self.focus_bar)
        layout.addSpacing(BLOCK_GAP)

        self.summary = QLabel(page)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.unestimated_note = QLabel(page)
        self.unestimated_note.setObjectName("InspectorNote")
        self.unestimated_note.setWordWrap(True)
        layout.addWidget(self.unestimated_note)

        layout.addSpacing(BLOCK_GAP)
        self.parallel_caption = QLabel("Parallel-adjusted time", page)
        self.parallel_caption.setObjectName("InspectorCaption")
        layout.addWidget(self.parallel_caption)
        self.parallel = MatrixTable(page)
        layout.addWidget(self.parallel)

        layout.addSpacing(BLOCK_GAP)
        self.calendar_caption = QLabel("Calendar time", page)
        self.calendar_caption.setObjectName("InspectorCaption")
        layout.addWidget(self.calendar_caption)
        self.calendar = MatrixTable(page)
        layout.addWidget(self.calendar)

        self.agent_note = QLabel(
            "No agent steps — agent capacity does not change these numbers. Mark steps for "
            "agent execution under Step ▸ Type.",
            page,
        )
        self.agent_note.setObjectName("InspectorNote")
        self.agent_note.setWordWrap(True)
        layout.addWidget(self.agent_note)

        layout.addStretch(1)

        self._widget = page
        self._unsubscribes = [
            self._product.structure_changed.connect(lambda *_a: self._refresh()),
            self._product.edges_changed.connect(lambda *_a: self._refresh()),
            self._product.module_data_changed.connect(lambda *_a: self._refresh()),
            # A separate agent instruction is prose, and carrying one marks the step as
            # agent work — so a text edit can move a step between pools.
            self._product.text_edited.connect(lambda *_a: self._refresh()),
        ]
        self._refresh()

    # -- the activity contract -----------------------------------------------------------------

    @property
    def uri(self) -> Uri:
        return activity_uri(TIME_KIND, self.project_id)

    @property
    def title(self) -> str:
        return f"{self._project().title or 'Untitled project'} — Time Estimates"

    @property
    def widget(self) -> QWidget:
        return self._widget

    def close(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self.focus_bar.dispose()
        if self.start_bar is not None:
            self.start_bar.dispose()

    # -- internals -----------------------------------------------------------------------------

    def _project(self) -> Project:
        return self._product.project(self.project_id)

    def _refresh(self) -> None:
        if not self._product.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        deps = self._deps
        project = self._project()
        report = time_report(
            self._product,
            project,
            deps.days_for,
            deps.is_agent,
            start=deps.start_of(self.project_id),
            efficiency=read_efficiency(project),
        )
        has_report = report is not None
        for widget in (
            self.parallel_caption,
            self.parallel,
            self.calendar_caption,
            self.calendar,
        ):
            widget.setVisible(has_report)
        if report is None:
            self.summary.setText("No steps yet — the matrix appears with the first one.")
            self.unestimated_note.setVisible(False)
            self.agent_note.setVisible(False)
            return
        self.summary.setText(
            f"{format_days(report.total_days)} of work — "
            f"{format_days(report.human_days)} human, {format_days(report.agent_days)} "
            f"agent · dependency floor {format_days(report.floor)}"
        )
        self.unestimated_note.setVisible(report.unestimated > 0)
        self.unestimated_note.setText(
            f"{report.unestimated} step{'s' if report.unestimated != 1 else ''} "
            "unestimated — they run as zero days here."
        )
        collapse = not report.has_agent_steps
        self.parallel.show_cells(report.parallel, report.floor, collapse)
        self.calendar.show_cells(report.calendar, report.calendar_floor, collapse)
        self.agent_note.setVisible(collapse)


class TimeEstimatesModule:
    id = MODULE_ID

    def __init__(self, deps: TimeEstimatesDeps) -> None:
        self._deps = deps

    def open(self, project_id: NodeId, *, preview: bool = False) -> None:
        self._deps.tabs.open(TIME_KIND, project_id, preview=preview)

    def register(self) -> None:
        deps = self._deps

        def factory(target: str | None) -> TimeEstimatesActivity:
            assert target is not None
            return TimeEstimatesActivity(deps, target)

        deps.tabs.register_factory(TIME_KIND, factory)
        deps.actions.register(
            ActionSpec(
                id="time.open",
                label="Show &Time Estimates",
                menu="Project",
                group="open",
                order=40,
                tip="How long the project takes with people and agents in parallel",
                state=self._on_a_project,
                run=self._open,
            )
        )
        follow_entity_tabs(
            deps.tabs,
            TimeEstimatesActivity,
            deps.library.has,
            closes_on=deps.library.structure_changed,
            retitles_on=deps.library.field_changed,
        )

    def _on_a_project(self, context: Context) -> ActionState:
        project_id = context.focus_entity("project")
        if project_id is None or not self._deps.library.has(project_id):
            return DISABLED
        return ENABLED

    def _open(self, context: Context) -> None:
        project_id = context.focus_entity("project")
        if project_id is not None:
            self.open(project_id)
