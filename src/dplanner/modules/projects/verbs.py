"""What a person can do to a project, as action specs.

Every one is a pure function of the :class:`Context`, which is what lets the same spec be
correct in the menu bar, the command palette and the index tree's right-click menu without
any of them coordinating — and lets a test evaluate one by handing it a constructed context.

Settings… opens the module's Project dialog, where every edit is live and undoable; Move
Plan… opens its wizard, on any project — the plan's repository is a choice that can be
made again, and the one that got it wrong the first time is the one that needs to.
**Share Project… is the one that sits in File**, beside Open Project…, because the two are
one round trip: what this writes is what that reads. It is still a verb on a project, so
it is a spec here like the rest and greyed with the same state.

The **membership** band is everything that changes whether a project is in this library:
Archive, Restore and Remove from Library. None of it touches the undo stack (a removed
project's files stay on disk, and Ctrl+Z could not honestly re-attach them); the root
applies each with the library's own origin, like any directly-applied external change. An
archived project is not in the model, so it is published as ``archived_project`` keyed by
its directory — every other Project verb reads ``project`` and never mistakes one for a
project it could open. Remove from Library acts on either: the archive is the library's
too, and a second verb to forget an archived row would be the same verb twice.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QWidget

from dplanner.domain.model import Library, NodeId, Project, ProjectId
from dplanner.domain.plan_repo import summary
from dplanner.domain.store import PROJECT_META
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import confirm
from dplanner.theme.icons import archive_icon, link_icon, move_icon, restore_icon, trash_icon

# The selection kind an archived project is published under, keyed by its directory.
ARCHIVED_KIND = "archived_project"


@dataclass(frozen=True)
class ProjectVerbs:
    library: Library
    undo: UndoService[Library]
    parent: QWidget
    open_steps: Callable[[NodeId], None]
    # The root's membership face: the store lets go, then the model, off the undo stack.
    disconnect: Callable[[ProjectId], None]
    # The module's dialogs, on a project.
    settings: Callable[[ProjectId], None]
    move: Callable[[ProjectId], None]
    share: Callable[[ProjectId], None]
    # The archive, as the module runs it: a project out, a directory back, one forgotten.
    archive: Callable[[ProjectId], None]
    restore: Callable[[Path], None]
    forget: Callable[[Path], None]
    archived: Callable[[], list[Path]]
    show_archive: Callable[[], None]

    def register_into(self, actions: ActionRegistry) -> None:
        for spec in self._specs():
            actions.register(spec)

    def _specs(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                id="projects.settings",
                label="Project &Settings…",
                menu="Project",
                group="edit",
                order=20,
                tip="The project's name and summary, where its plan and its code live, "
                "and what both repositories have been up to",
                state=self._on_a_project,
                run=self._settings,
            ),
            ActionSpec(
                id="projects.move",
                label="&Move Plan…",
                menu="Project",
                group="edit",
                order=25,
                tip="Move the plan into a plan repository — out of the code it plans, "
                "or on to another one",
                state=self._on_a_project,
                run=self._move,
                icon=move_icon,
            ),
            ActionSpec(
                id="projects.share",
                label="&Share Project…",
                menu="File",
                group="project",
                order=30,
                tip="A link that sets this project up on somebody else's machine — "
                "both repositories, and where the plan sits in its own",
                state=self._on_a_project,
                run=self._share,
                icon=link_icon,
            ),
            ActionSpec(
                id="projects.archive",
                label="Arc&hive Project",
                menu="Project",
                group="membership",
                order=10,
                tip="Take this project out of the library and keep it in the Archive, "
                "where Restore Project brings it back",
                state=self._on_a_project,
                run=self._archive,
                icon=archive_icon,
            ),
            ActionSpec(
                id="projects.restore",
                label="Restor&e Project",
                menu="Project",
                group="membership",
                order=20,
                tip="Bring the archived project back into the library",
                state=self._restore_state,
                run=self._restore,
                icon=restore_icon,
            ),
            ActionSpec(
                id="projects.remove",
                label="Re&move from Library…",
                menu="Project",
                group="membership",
                order=30,
                tip="Take this project out of the library, or out of its archive; "
                "its files stay on disk",
                state=self._remove_state,
                run=self._remove,
                icon=trash_icon,
            ),
            ActionSpec(
                id="projects.show_archive",
                label="Show Archi&ve",
                menu="Project",
                group="membership",
                order=40,
                tip="The projects archived out of this library",
                run=lambda _context: self.show_archive(),
            ),
            ActionSpec(
                id="projects.open",
                label="Show &Steps",
                menu="Project",
                group="open",
                order=20,  # The index's order: Dashboard (5), Specs (10), Assets (15).
                tip="Show this project's graph",
                state=self._on_a_project,
                run=self._open,
            ),
        ]

    # -- state ---------------------------------------------------------------------------------

    def _on_a_project(self, context: Context) -> ActionState:
        return DISABLED if self._focused(context) is None else ENABLED

    def _focused(self, context: Context) -> Project | None:
        project_id = context.focus_entity("project")
        if project_id is None or not self.library.has(project_id):
            return None
        return self.library.project(project_id)

    def _picked_archive(self, context: Context) -> Path | None:
        """The one archived project the context picked, while the archive still lists it."""
        picked = context.selected_entity(ARCHIVED_KIND)
        if picked is None:
            return None
        directory = Path(picked)
        return directory if directory in self.archived() else None

    def _restore_state(self, context: Context) -> ActionState:
        directory = self._picked_archive(context)
        if directory is None:
            return ActionState(enabled=False, label="Restore Project — pick an archived project")
        if not (directory / PROJECT_META).is_file():  # One stat per announce, never a read.
            return ActionState(enabled=False, label="Restore Project — its folder is gone")
        return ENABLED

    def _remove_state(self, context: Context) -> ActionState:
        if self._focused(context) is None and self._picked_archive(context) is None:
            return DISABLED
        return ENABLED

    # -- run -----------------------------------------------------------------------------------

    def _settings(self, context: Context) -> None:
        project = self._focused(context)
        if project is not None:
            self.settings(project.id)

    def _move(self, context: Context) -> None:
        project = self._focused(context)
        if project is not None:
            self.move(project.id)

    def _share(self, context: Context) -> None:
        project = self._focused(context)
        if project is not None:
            self.share(project.id)

    def _archive(self, context: Context) -> None:
        project = self._focused(context)
        if project is not None:
            self.archive(project.id)

    def _restore(self, context: Context) -> None:
        directory = self._picked_archive(context)
        if directory is not None:
            self.restore(directory)

    def _remove(self, context: Context) -> None:
        project = self._focused(context)
        if project is not None:
            if confirm(
                self.parent,
                "Remove from Library",
                f"Remove “{project.title}” from this library? Its files stay on disk.",
                verb="Remove",
            ):
                self.disconnect(project.id)
            return
        directory = self._picked_archive(context)
        if directory is not None and confirm(
            self.parent,
            "Remove from Library",
            f"Remove “{summary(directory).title}” from this library's archive? "
            "Its files stay on disk.",
            verb="Remove",
        ):
            self.forget(directory)

    def _open(self, context: Context) -> None:
        project = self._focused(context)
        if project is not None:
            self.open_steps(project.id)
