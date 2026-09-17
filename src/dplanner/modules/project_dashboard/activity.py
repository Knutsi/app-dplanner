"""The Dashboard tab: one project's home, opened about that project and never re-targeted."""

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget

from dplanner.domain.model import NodeId
from dplanner.framework.activity import EntityActivity, follow_project
from dplanner.framework.context import Uri, activity_uri
from dplanner.framework.debounce import Debounced
from dplanner.modules.project_dashboard.page import DashboardPage

if TYPE_CHECKING:  # module.py imports this file, so the Deps arrive as a forward name.
    from dplanner.modules.project_dashboard.module import ProjectDashboardDeps

DASHBOARD_KIND = "dashboard"


class DashboardActivity(EntityActivity):
    """The project's name and summary, and what each module has to say about it."""

    def __init__(self, deps: "ProjectDashboardDeps", project_id: NodeId) -> None:
        super().__init__(deps.context, "project", project_id)
        self._deps = deps
        self.project_id = project_id
        self.page = DashboardPage(
            deps.library, deps.undo, cards=deps.cards.sections(), theme=deps.theme
        )
        self.page.show_target(project_id)
        # Once per event-loop turn — the canvas's regime — so a rename made elsewhere lands
        # here as it is typed. This project only, and only its fields: the cards follow
        # their own documents.
        self._refresh_soon = Debounced(self._refresh, 0, parent=self.page, service=deps.debounce)
        self._unsubscribe = follow_project(
            deps.library,
            project_id,
            self._refresh_soon.trigger,
            signals=(deps.library.field_changed,),
        )

    @property
    def uri(self) -> Uri:
        return activity_uri(DASHBOARD_KIND, self.project_id)

    @property
    def title(self) -> str:
        project = self._deps.library.project(self.project_id)
        return f"{project.title or 'Untitled project'} — Dashboard"

    @property
    def widget(self) -> QWidget:
        return self.page

    def on_deactivated(self) -> None:
        super().on_deactivated()
        # The prose cards coalesce typing into one undo step; leaving the tab seals it.
        self._deps.undo.break_coalescing()

    def close(self) -> None:
        self._refresh_soon.cancel()
        self._unsubscribe()
        self.page.dispose()

    def _refresh(self) -> None:
        self.page.refresh()
