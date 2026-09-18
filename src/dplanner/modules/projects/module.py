"""Projects: the folder in the index, what you can do to a project, and where it lives.

The tabs a project opens into belong to ``project_dashboard`` (its home) and
``project_editor`` (its graph); this module never learns what an activity is. It is handed
``open_dashboard`` and ``open_steps`` callbacks and calls them, which is the same seam the
plan tree used before it and the reason two features can render the same thing without
meeting.

Where a project lives is this module's other subject: the Project dialog (a column per
repository — its log, what it is and where it is here, and a ⋯ menu of everything that
changes either), the Repositories card on the Dashboard tab, Move Plan, and the *Settings
▸ Repositories* page. Git and GitHub reach it only through the :class:`RepositoryServices`
the composition root fills in.

Membership is here too — *File ▸ New Project…* (the Project dialog in create mode),
*Open Project…* (the wizard: a project link, or a plan repository browsed) and *Share
Project…*, which writes the link the wizard reads. They start from the same question,
which plan repository, and the same picker answers it. Adding a project happens **off the
undo stack**, through the root's ``connect_project`` with the library origin: creating one
initialises a repository and writes files an undo could never honestly take back. The
library file is rewritten by the store on the next autosave flush.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QTreeWidgetItem, QWidget

from dplanner.core.storage.locations import init_repo
from dplanner.core.storage.provider import StorageError
from dplanner.domain.model import Library, NodeId, Project, ProjectId
from dplanner.domain.project_link import LinkError, link_for
from dplanner.domain.relocate import RelocateError
from dplanner.domain.seed import seed_project
from dplanner.domain.store import ProjectProblem
from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.autosave import AutosaveService
from dplanner.framework.context import Context, ContextService
from dplanner.framework.debounce import DebounceService
from dplanner.framework.index_panel import IndexSegment, IndexSegmentRegistry
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.session import SessionControl
from dplanner.framework.settings_registry import SettingsSection, SettingsSectionRegistry
from dplanner.framework.tasks import TaskService
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import notice
from dplanner.framework.window import StatusHost
from dplanner.modules.projects.card import RepositoriesCard

# ProjectEntry is re-exported: contributors are wired through this module's Deps, and the
# composition root imports a module's surface from its module.py alone.
from dplanner.modules.projects.index import ProjectEntry as ProjectEntry
from dplanner.modules.projects.index import ProjectsSegment
from dplanner.modules.projects.move_dialog import MovePlanDialog
from dplanner.modules.projects.open_dialog import OpenProjectDialog
from dplanner.modules.projects.project_dialog import CREATE, ProjectDialog
from dplanner.modules.projects.repos import MODULE_ID, RepositoryServices, shown_path
from dplanner.modules.projects.settings_page import build_page
from dplanner.modules.projects.share_dialog import ShareProjectDialog
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
    # The Dashboard tab's card registry: the Repositories card goes there.
    cards: InspectorSectionRegistry
    # Show a project's graph — the "Show Steps" verb's and the Steps row's callback, wired
    # by the composition root to the project editor, which this module never imports.
    open_steps: Callable[[NodeId], None]
    # Show a project's Dashboard, as a preview tab or for keeps — what a click on the
    # project's own row in the index asks for. Wired by the composition root.
    open_dashboard: Callable[[NodeId, bool], None]
    # The store's half of Remove from Library, wired by the composition root.
    detach: Callable[[ProjectId], None]
    # Its other half: attach a directory and add the project to the library with the
    # membership origin, off the undo stack. Checkouts are recorded beside it, per
    # repository, through `repos.set_checkout`.
    connect_project: Callable[[Path], Project]
    # Every directory the library lists, opened or not — what the wizard greys.
    project_dirs: Callable[[], list[Path]]
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
        deps.actions.register(
            ActionSpec(
                id="projects.new",
                label="&New Project…",
                menu="File",
                group="project",
                order=10,
                shortcut="Ctrl+Shift+N",
                tip="Start a project in a plan repository and add it here",
                run=self.new_project,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="projects.add",
                label="&Open Project…",
                menu="File",
                group="project",
                order=20,
                shortcut="Ctrl+O",
                tip="Set up a project from a link somebody sent, or browse a plan repository",
                run=self.add_projects,
            )
        )
        ProjectVerbs(
            library=deps.library,
            undo=deps.undo,
            parent=deps.parent,
            open_steps=deps.open_steps,
            detach=deps.detach,
            settings=self.show_project,
            move=self.move_plan,
            share=self.share_project,
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
                open_dashboard=deps.open_dashboard,
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

    # -- membership ----------------------------------------------------------------------------

    def new_project(self, _context: Context) -> None:
        deps = self._deps
        dialog = ProjectDialog(
            deps.library,
            deps.undo,
            deps.repos,
            deps.tasks,
            deps.theme,
            move=self.move_plan,
            mode=CREATE,
            parent=deps.parent,
        )
        accepted = bool(dialog.exec())
        spec = dialog.spec() if accepted else None
        dialog.deleteLater()
        if spec is None:
            return
        try:
            if spec.plan.init:
                init_repo(spec.plan.root)
            directory = seed_project(
                spec.target, spec.title, summary=spec.summary, locations=spec.locations
            )
        except (StorageError, OSError) as error:
            notice(deps.parent, "New Project", f"Nothing was created — {error}")
            return
        project = deps.connect_project(directory)
        for repository, checkout in spec.checkouts:
            deps.repos.set_checkout(repository, checkout)
        deps.status.show_status(f"“{project.title or project.folder_name}” created", 4000)
        if spec.plan.publish:
            self._publish(spec.plan.root, spec.plan.publish)

    def add_projects(self, _context: Context) -> None:
        """*Open Project…*: the wizard answers with what is on disk, this connects it."""
        deps = self._deps
        dialog = OpenProjectDialog(
            deps.repos,
            deps.tasks,
            deps.theme,
            listed_dirs=deps.project_dirs(),
            listed_ids=[project.id for project in deps.library.projects],
            parent=deps.parent,
        )
        accepted = bool(dialog.exec())
        chosen = dialog.joined() if accepted else []
        dialog.deleteLater()
        added = [deps.connect_project(join.directory) for join in chosen]
        for join in chosen:
            for repository, checkout in join.checkouts:
                deps.repos.set_checkout(repository, checkout)
        if len(added) == 1:
            title = added[0].title or added[0].folder_name
            deps.status.show_status(f"“{title}” added to the library", 4000)
        elif added:
            deps.status.show_status(f"{len(added)} projects added to the library", 4000)

    def share_project(self, project_id: ProjectId) -> None:
        """*Share Project…*: the link, the file and the code, for one project.

        The refusals are the interesting half — a plan outside git, or in a repository
        nobody else can clone — and they are a `notice`, because the gesture is over by
        the time they are known and there is no dialog left to say it in.
        """
        deps = self._deps
        if not deps.library.has(project_id):
            return
        project = deps.library.project(project_id)
        try:
            link = link_for(
                project, deps.repos.project_dir(project_id), deps.repos.facts_of(project_id)
            )
        except LinkError as error:
            notice(deps.parent, "Share Project", f"There is nothing to share yet — {error}.")
            return
        dialog = ShareProjectDialog(link, deps.parent)
        dialog.exec()
        dialog.deleteLater()

    def _publish(self, root: Path, name: str) -> None:
        """Publish a plan repository made a moment ago. Synchronous, like the move it
        may follow: the repository was just written and the person is waiting on it —
        the one shape the wait cursor is honest for."""
        deps = self._deps
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            origin = deps.repos.publish(root, name)
        except (StorageError, OSError) as error:
            notice(deps.parent, "Publish to GitHub", f"{root.name} was not published — {error}")
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        deps.status.show_status(f"Published {root.name} as {origin or name}", 6000)

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
            QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                deps.repos.publish(chosen.root, chosen.publish)
            except (StorageError, OSError) as error:
                notes.append(f"not published to GitHub: {error}")
            finally:
                QGuiApplication.restoreOverrideCursor()
        where = shown_path(Path(target))
        # The move itself is recorded once, in the status bar; a notice only where the
        # move left something to know (DESIGN.md's fifth principle).
        if notes:
            notice(
                deps.parent,
                "Move Plan",
                f"The plan of “{title}” is now at {where}, but:\n\n"
                + "\n".join(f"• {note}" for note in notes),
            )
        deps.status.show_status(f"Moved the plan of “{title}” to {where}", 6000)
        deps.switcher.reload()

    def _refuse(self, reason: str) -> None:
        notice(self._deps.parent, "Move Plan", reason)

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
