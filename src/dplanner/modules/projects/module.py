"""Projects: the folder in the index, what you can do to a project, and where it lives.

The tab a project opens into belongs to ``project_editor``; this module never learns what
an activity is. It is handed an ``open_project`` callback and calls it, which is the same
seam the plan tree used before it and the reason two features can render the same thing
without meeting.

Where a project lives is this module's other subject: the Project dialog (settings above,
the plan's and the code's logs below), the Repositories card on the project panel, Move
Plan, and the *Settings ▸ Repositories* page. Git and GitHub reach it only through the
:class:`RepositoryServices` the composition root fills in.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QMessageBox, QTreeWidgetItem, QWidget

from dplanner.core.storage.provider import StorageError
from dplanner.domain.model import Library, NodeId, ProjectId
from dplanner.domain.relocate import RelocateError
from dplanner.domain.store import ProjectProblem
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.autosave import AutosaveService
from dplanner.framework.context import ContextService
from dplanner.framework.debounce import DebounceService
from dplanner.framework.index_panel import IndexSegment, IndexSegmentRegistry
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.session import SessionControl
from dplanner.framework.settings_registry import SettingsSection, SettingsSectionRegistry
from dplanner.framework.tasks import TaskService
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.framework.window import StatusHost
from dplanner.modules.projects.card import RepositoriesCard

# ProjectEntry is re-exported: contributors are wired through this module's Deps, and the
# composition root imports a module's surface from its module.py alone.
from dplanner.modules.projects.index import ProjectEntry as ProjectEntry
from dplanner.modules.projects.index import ProjectsSegment
from dplanner.modules.projects.move_dialog import MovePlanDialog
from dplanner.modules.projects.repos import MODULE_ID, RepositoryServices
from dplanner.modules.projects.repositories_folder import shown_path
from dplanner.modules.projects.settings_dialog import ProjectDialog
from dplanner.modules.projects.settings_page import build_page
from dplanner.modules.projects.verbs import ProjectVerbs
from dplanner.theme.icons import branch_icon, container_icon


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
    status: StatusHost
    tasks: TaskService
    autosave: AutosaveService
    switcher: SessionControl
    settings_sections: SettingsSectionRegistry
    # The project panel's card registry: the Repositories card goes there.
    cards: InspectorSectionRegistry
    # Show a project — the "Open Project" verb's callback, wired by the composition root
    # to the project editor, which this module never imports. In the tree, opening the
    # graph is the Steps entry's job, not the project row's.
    open_project: Callable[[NodeId], None]
    # The store's half of Remove from Library, wired by the composition root.
    detach: Callable[[ProjectId], None]
    # Library entries that failed to open — shown greyed with the reason.
    problems: Callable[[], list[ProjectProblem]]
    # Git and GitHub, as the composition root wires them.
    repos: RepositoryServices
    # Rows other modules put under each project, wired by the composition root.
    entries: tuple[ProjectEntry, ...] = ()


class ProjectsModule:
    id = MODULE_ID

    def __init__(self, deps: ProjectsDeps) -> None:
        self._deps = deps
        self._dialog: ProjectDialog | None = None

    def register(self) -> None:
        deps = self._deps
        ProjectVerbs(
            library=deps.library,
            undo=deps.undo,
            parent=deps.parent,
            open_project=deps.open_project,
            detach=deps.detach,
            settings=self.show_project,
            move=self.move_plan,
        ).register_into(deps.actions)

        deps.cards.register(
            InspectorSection(
                id=f"{MODULE_ID}.repositories",
                label="Repositories",
                order=10,  # Ahead of the agent instruction (20) and docs (30).
                icon=branch_icon,
                factory=lambda: RepositoriesCard(
                    deps.library, deps.repos, deps.actions, deps.context, deps.theme
                ),
            )
        )
        deps.settings_sections.register(
            SettingsSection(
                id=f"{MODULE_ID}.repositories", category=("Repositories",), factory=build_page
            )
        )

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
        self._say_where_plans_live()

    # -- the dialogs ---------------------------------------------------------------------------

    def show_project(self, project_id: ProjectId) -> None:
        """One Project dialog per window, re-aimed: every edit in it is live."""
        deps = self._deps
        if self._dialog is None:
            self._dialog = ProjectDialog(
                deps.library,
                deps.undo,
                deps.repos,
                deps.tasks,
                deps.theme,
                move=self.move_plan,
                parent=deps.parent,
            )
        self._dialog.show_project(project_id)
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()

    def move_plan(self, project_id: ProjectId) -> None:
        """Move the plan where the wizard says, then reload: the move rewrites the working
        tree, and every view that cached a directory is rebuilt rather than patched. This
        build is discarded by the reload — nothing after it may touch ``self``."""
        deps = self._deps
        library = deps.library
        if not library.has(project_id):
            return
        project = library.project(project_id)
        title = project.title or project.folder_name
        dialog = MovePlanDialog(
            title=title,
            folder_name=project.folder_name,
            facts=deps.repos.facts_of(project_id),
            services=deps.repos,
            tasks=deps.tasks,
            theme=deps.theme,
            parent=deps.parent,
        )
        accepted = bool(dialog.exec())
        target, chosen = dialog.target(), dialog.plan_target()
        dialog.deleteLater()
        if not accepted or target is None or chosen is None:
            return
        deps.autosave.flush_now()
        if deps.autosave.has_pending():
            self._refuse("The last edits could not be written to disk, so nothing was moved.")
            return
        deps.autosave.pause()
        try:
            moved = deps.repos.move_project(project_id, target, chosen.init)
        except RelocateError as error:
            deps.autosave.resume()
            self._refuse(str(error))
            return
        notes = list(moved.notes)
        if chosen.publish:
            try:
                deps.repos.publish(chosen.root, chosen.publish)
            except (StorageError, OSError) as error:
                notes.append(f"not published to GitHub: {error}")
        where = shown_path(Path(target))
        if notes:
            QMessageBox.information(
                deps.parent,
                "Move Plan",
                f"The plan of “{title}” is now at {where}.\n\n"
                + "\n".join(f"• {note}" for note in notes),
            )
        deps.status.show_status(f"Moved the plan of “{title}” to {where}", 6000)
        deps.switcher.reload()

    def _refuse(self, reason: str) -> None:
        QMessageBox.warning(self._deps.parent, "Move Plan", reason)

    # -- opening ---------------------------------------------------------------------------------

    def _say_where_plans_live(self) -> None:
        """The opening warning: how many plans still live inside their code repositories."""
        deps = self._deps
        inside = [
            project for project in deps.library.projects if deps.repos.facts_of(project.id).warns
        ]
        if not inside:
            return
        count = len(inside)
        if count == 1:
            what = f"“{inside[0].title or inside[0].folder_name}” lives inside its code repository"
        else:
            what = f"{count} plans live inside their code repositories"
        deps.status.show_status(
            f"{what} — Project ▸ Settings… to move it"
            if count == 1
            else f"{what} — Project ▸ Settings… to move them"
        )
