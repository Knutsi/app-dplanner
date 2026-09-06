"""What a person can do to a project, as action specs.

Every one is a pure function of the :class:`Context`, which is what lets the same spec be
correct in the menu bar, the command palette and the index tree's right-click menu without
any of them coordinating — and lets a test evaluate one by handing it a constructed context.

Settings… opens the module's Project dialog, where every edit is live and undoable; Move
Plan… opens its wizard. Removal is a membership change, not an edit: it leaves the undo
stack alone (a removed project's files stay on disk, and Ctrl+Z could not honestly
re-attach them), so it carries its own origin like any directly-applied external change.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

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
from dplanner.theme.icons import move_icon

_MEMBERSHIP_ORIGIN: object = object()


@dataclass(frozen=True)
class ProjectVerbs:
    library: Library
    undo: UndoService[Library]
    parent: QWidget
    open_project: Callable[[NodeId], None]
    # The store's half of removal, wired by the composition root.
    detach: Callable[[ProjectId], None]
    # The module's two dialogs, on a project.
    settings: Callable[[ProjectId], None]
    move: Callable[[ProjectId], None]

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
                tip="Move the plan into a repository of its own",
                state=self._on_a_project,
                run=self._move,
                icon=move_icon,
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
        return DISABLED if self._focused(context) is None else ENABLED

    def _focused(self, context: Context) -> Project | None:
        project_id = context.focus_entity("project")
        if project_id is None or not self.library.has(project_id):
            return None
        return self.library.project(project_id)

    # -- run -----------------------------------------------------------------------------------

    def _settings(self, context: Context) -> None:
        project = self._focused(context)
        if project is not None:
            self.settings(project.id)

    def _move(self, context: Context) -> None:
        project = self._focused(context)
        if project is not None:
            self.move(project.id)

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
