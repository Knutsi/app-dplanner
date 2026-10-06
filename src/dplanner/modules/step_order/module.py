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

What the order page says under its caption is the **volume**: the estimated days the order comes
to, over how many steps, and how many nobody has sized — the sentence ``dplanner order
show``, ``estimate rollup`` and the Estimates tab all print (``planning/schedule.py``'s
``volume_words``). It replaced a paragraph explaining what a wave is, which is now the
caption's own info glyph, and the serial calendar the table used to run out beside it.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QWidget

from dplanner.core.fsio import write_csv
from dplanner.domain.model import Library, NodeId, Step, StepId
from dplanner.domain.ordering import placed
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.activity import (
    follow_project_tabs,
)
from dplanner.framework.context import (
    Context,
    ContextService,
)
from dplanner.framework.debounce import DebounceService
from dplanner.framework.step_selection import focused_project
from dplanner.framework.tabs import TabHost
from dplanner.modules.step_order.activity import ORDER_KIND, OrderActivity, schedule_rows
from dplanner.modules.step_order.export import order_rows
from dplanner.theme.icons import list_icon

MODULE_ID = "step_order"


def _no_aspects(_step_id: StepId) -> list[str]:
    return []


def _no_milestone(_step_id: StepId) -> str:
    return ""


def _no_color(_step_id: StepId) -> str:
    return ""


def _no_icons(_step_id: StepId) -> tuple[str, ...]:
    return ()


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


class StepOrderModule:
    id = MODULE_ID

    def __init__(self, deps: StepOrderDeps) -> None:
        self._deps = deps

    def open(self, project_id: NodeId, *, preview: bool = False) -> None:
        self._deps.tabs.open(ORDER_KIND, project_id, preview=preview)

    def register(self) -> None:
        deps = self._deps

        def factory(target: str | None) -> OrderActivity:
            assert target is not None
            return OrderActivity(deps, target)

        deps.tabs.register_factory(ORDER_KIND, factory)
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
        follow_project_tabs(deps.tabs, OrderActivity, deps.library)

    def _on_a_project(self, context: Context) -> ActionState:
        return DISABLED if focused_project(context, self._deps.library) is None else ENABLED

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
            schedule_rows(deps.library, project_id, order), deps.step_aspects, deps.milestone_label
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
