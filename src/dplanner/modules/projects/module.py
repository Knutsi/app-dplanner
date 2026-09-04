"""Projects: the folder in the index, and what you can do to a project.

The tab a project opens into belongs to ``project_editor``; this module never learns what an
activity is. It is handed an ``open_project`` callback and calls it, which is the same seam
the plan tree used before it and the reason two features can render the same thing without
meeting.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QTreeWidgetItem, QWidget

from dplanner.domain.model import Library, NodeId, ProjectId
from dplanner.domain.store import ProjectProblem
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import ContextService
from dplanner.framework.debounce import DebounceService
from dplanner.framework.index_panel import IndexSegment, IndexSegmentRegistry
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService

# ProjectEntry is re-exported: contributors are wired through this module's Deps, and the
# composition root imports a module's surface from its module.py alone.
from dplanner.modules.projects.index import ProjectEntry as ProjectEntry
from dplanner.modules.projects.index import ProjectsSegment
from dplanner.modules.projects.verbs import ProjectVerbs
from dplanner.theme.icons import container_icon

MODULE_ID = "projects"


@dataclass(frozen=True)
class ProjectsDeps:
    library: Library
    actions: ActionRegistry
    context: ContextService
    debounce: DebounceService
    undo: UndoService[Library]
    segments: IndexSegmentRegistry
    theme: ThemeService
    parent: QWidget
    # Show a project — the "Open Project" verb's callback, wired by the composition root
    # to the project editor, which this module never imports. In the tree, opening the
    # graph is the Steps entry's job, not the project row's.
    open_project: Callable[[NodeId], None]
    # The store's half of Remove from Library, wired by the composition root.
    detach: Callable[[ProjectId], None]
    # Library entries that failed to open — shown greyed with the reason.
    problems: Callable[[], list[ProjectProblem]]
    # Rows other modules put under each project, wired by the composition root.
    entries: tuple[ProjectEntry, ...] = ()


class ProjectsModule:
    id = MODULE_ID

    def __init__(self, deps: ProjectsDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        ProjectVerbs(
            library=deps.library,
            undo=deps.undo,
            parent=deps.parent,
            open_project=deps.open_project,
            detach=deps.detach,
        ).register_into(deps.actions)

        def segment(root: QTreeWidgetItem) -> ProjectsSegment:
            return ProjectsSegment(
                root=root,
                library=deps.library,
                context=deps.context,
                actions=deps.actions,
                theme=deps.theme,
                entries=deps.entries,
                problems=deps.problems,
                debounce=deps.debounce,
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
