"""What a person can do to a project, as action specs.

Every one is a pure function of the :class:`Context`, which is what lets the same spec be
correct in the menu bar, the command palette and the index tree's right-click menu without
any of them coordinating — and lets a test evaluate one by handing it a constructed context.

Each verb builds a command from ``domain/commands.py`` and pushes it. The CLI builds the
same commands from ``cli.py``; that shared vocabulary is what keeps the two surfaces
honest with each other.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QInputDialog, QWidget

from dplanner.domain.commands import SetFieldCommand
from dplanner.domain.model import Library, NodeId, Project, ProjectId
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

# Removal is a membership change, not an edit: it leaves the undo stack alone (a removed
# project's files stay on disk, and Ctrl+Z could not honestly re-attach them), so it
# carries its own origin like any directly-applied external change.
_MEMBERSHIP_ORIGIN: object = object()


@dataclass(frozen=True)
class ProjectVerbs:
    library: Library
    undo: UndoService[Library]
    parent: QWidget
    open_project: Callable[[NodeId], None]
    # The store's half of removal, wired by the composition root.
    detach: Callable[[ProjectId], None]

    def register_into(self, actions: ActionRegistry) -> None:
        for spec in self._specs():
            actions.register(spec)

    def _specs(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                id="projects.rename",
                label="&Rename Project…",
                menu="Project",
                group="edit",
                order=20,
                tip="Change what this project is called",
                state=self._on_a_project,
                run=self._rename,
            ),
            ActionSpec(
                id="projects.remove",
                label="Re&move from Library…",
                menu="Project",
                group="edit",
                order=30,
                tip="Take this project out of the library; its files stay on disk",
                state=self._on_a_project,
                run=self._remove,
            ),
            ActionSpec(
                id="projects.open",
                label="&Open Project",
                menu="Project",
                group="open",
                order=10,
                tip="Show this project in a tab",
                state=self._on_a_project,
                run=self._open,
            ),
        ]

    # -- state ---------------------------------------------------------------------------------

    def _on_a_project(self, context: Context) -> ActionState:
        project_id = context.focus_entity("project")
        if project_id is None or not self.library.has(project_id):
            return DISABLED
        return ENABLED

    def _focused(self, context: Context) -> Project | None:
        project_id = context.focus_entity("project")
        if project_id is None or not self.library.has(project_id):
            return None
        return self.library.project(project_id)

    # -- run -----------------------------------------------------------------------------------

    def _rename(self, context: Context) -> None:
        project = self._focused(context)
        if project is None:
            return  # The state gate already prevents this; stay honest.
        title, accepted = QInputDialog.getText(
            self.parent, "Rename Project", "Project name:", text=project.title
        )
        if accepted and title.strip():
            self.undo.push(SetFieldCommand(project.id, "title", title.strip()))

    def _remove(self, context: Context) -> None:
        project = self._focused(context)
        if project is None:
            return
        if confirm(
            self.parent,
            "Remove from Library",
            f"Remove {project.title!r} from this library? Its files stay on disk.",
        ):
            self.library.remove_child(project.id, origin=_MEMBERSHIP_ORIGIN)
            self.detach(project.id)

    def _open(self, context: Context) -> None:
        project = self._focused(context)
        if project is not None:
            self.open_project(project.id)
