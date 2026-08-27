"""Projects: the folder in the index, and what you can do to a project.

The tab a project opens into belongs to ``project_editor``; this module never learns what an
activity is. It is handed an ``open_project`` callback and calls it, which is the same seam
the plan tree used before it and the reason two features can render the same thing without
meeting.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QTreeWidgetItem, QWidget

from dplanner.domain.model import NodeId, Product
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import ContextService
from dplanner.framework.index_panel import IndexSegment, IndexSegmentRegistry
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.modules.projects.index import ProjectEntry, ProjectsSegment
from dplanner.modules.projects.verbs import ProjectVerbs
from dplanner.theme.icons import container_icon

MODULE_ID = "projects"


@dataclass(frozen=True)
class ProjectsDeps:
    product: Product
    actions: ActionRegistry
    context: ContextService
    undo: UndoService[Product]
    segments: IndexSegmentRegistry
    theme: ThemeService
    parent: QWidget
    # Show a project. Wired by the composition root to the project editor, which this
    # module never imports.
    open_project: Callable[[NodeId], None]
    # Rows other modules put under each project, wired by the composition root.
    entries: tuple[ProjectEntry, ...] = ()


class ProjectsModule:
    id = MODULE_ID

    def __init__(self, deps: ProjectsDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        ProjectVerbs(
            product=deps.product,
            undo=deps.undo,
            parent=deps.parent,
            open_project=deps.open_project,
        ).register_into(deps.actions)

        def segment(root: QTreeWidgetItem) -> ProjectsSegment:
            return ProjectsSegment(
                root=root,
                product=deps.product,
                context=deps.context,
                actions=deps.actions,
                theme=deps.theme,
                open_project=deps.open_project,
                entries=deps.entries,
            )

        deps.segments.register(
            IndexSegment(
                id="projects",
                label="Projects",
                factory=segment,
                order=10,
                icon=container_icon,
            )
        )
