"""The project's home tab, and the verb that opens it.

The page is the module's; the cards on it are everybody else's. A module with something
to say about a *project* registers an ``InspectorSection`` into ``services.project_cards``
— the same registry type the step editor's tabs and its Details blocks use, instantiated
once more because a host is addressed by which registry you register into — and this
module renders whatever is there when a tab opens, never learning whose it is. The index
opens the tab through the callback it is handed, the way it opens every other surface.
"""

from dataclasses import dataclass

from dplanner.domain.model import Library, NodeId
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.activity import follow_entity_tabs
from dplanner.framework.context import Context, ContextService
from dplanner.framework.debounce import DebounceService
from dplanner.framework.inspector import InspectorSectionRegistry
from dplanner.framework.tabs import TabHost
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.modules.project_dashboard.activity import DASHBOARD_KIND, DashboardActivity
from dplanner.theme.icons import project_icon

MODULE_ID = "project_dashboard"


@dataclass(frozen=True)
class ProjectDashboardDeps:
    library: Library
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    undo: UndoService[Library]
    debounce: DebounceService
    theme: ThemeService
    # Every section registered here becomes a card on the page; this module never learns
    # whose. Read when a tab opens, so every contributor must have registered by then.
    cards: InspectorSectionRegistry


class ProjectDashboardModule:
    id = MODULE_ID

    def __init__(self, deps: ProjectDashboardDeps) -> None:
        self._deps = deps

    def open(self, project_id: NodeId, *, preview: bool = False) -> None:
        self._deps.tabs.open(DASHBOARD_KIND, project_id, preview=preview)

    def register(self) -> None:
        deps = self._deps

        def factory(target: str | None) -> DashboardActivity:
            assert target is not None
            return DashboardActivity(deps, target)

        deps.tabs.register_factory(DASHBOARD_KIND, factory)
        deps.actions.register(
            ActionSpec(
                id="dashboard.open",
                label="Show Dash&board",
                menu="Project",
                group="open",
                order=5,  # First: it is the project's home.
                icon=project_icon,
                tip="The project's name and summary, and what each module has to say about it",
                state=self._on_a_project,
                run=self._open,
            )
        )
        follow_entity_tabs(
            deps.tabs,
            DashboardActivity,
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
