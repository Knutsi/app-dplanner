"""The Project menu's **membership** band, as action specs: Archive, Restore and Remove from
Library — everything that changes whether a project is in this library.

None of it touches the undo stack (a removed project's files stay on disk, and Ctrl+Z could
not honestly re-attach them); the root applies each with the library's own origin, like any
directly-applied external change. An archived project is not in the model, so it is
published as ``archived_project`` keyed by its directory — every other Project verb reads
``project`` and never mistakes one for a project it could open. Remove from Library acts on
either: the archive is the library's too, and a second verb to forget an archived row would
be the same verb twice — which is why the band lives here whole, beside the archive.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QWidget

from dplanner.domain.model import Library, Project, ProjectId
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
from dplanner.framework.widgets import confirm
from dplanner.theme.icons import archive_icon, restore_icon, trash_icon

# The selection kind an archived project is published under, keyed by its directory.
ARCHIVED_KIND = "archived_project"


@dataclass(frozen=True)
class MembershipVerbs:
    library: Library
    parent: QWidget
    # The root's membership face: the store lets go, then the model, off the undo stack.
    disconnect: Callable[[ProjectId], None]
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
        # The ids keep the `projects.` prefix they were stored under in toolbars and keymaps.
        return [
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
                label="&Remove from Library…",
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
                label="A&rchive",
                menu="Go",
                group="archive",
                order=10,
                tip="The projects archived out of this library",
                run=lambda _context: self.show_archive(),
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
