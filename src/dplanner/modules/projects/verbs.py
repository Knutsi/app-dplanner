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

from dplanner.domain.commands import AddNodeCommand, RemoveNodeCommand, SetFieldCommand
from dplanner.domain.model import NodeId, Product, Project
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


@dataclass(frozen=True)
class ProjectVerbs:
    product: Product
    undo: UndoService[Product]
    parent: QWidget
    open_project: Callable[[NodeId], None]

    def register_into(self, actions: ActionRegistry) -> None:
        for spec in self._specs():
            actions.register(spec)

    def _specs(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                id="projects.new",
                label="&New Project…",
                menu="Project",
                group="edit",
                order=10,
                shortcut="Ctrl+Shift+P",
                tip="Add a project to this product",
                run=self._new,
            ),
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
                id="projects.delete",
                label="&Delete Project",
                menu="Project",
                group="edit",
                order=30,
                tip="Remove this project and all of its steps",
                state=self._on_a_project,
                run=self._delete,
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
        if project_id is None or not self.product.has(project_id):
            return DISABLED
        return ENABLED

    def _focused(self, context: Context) -> Project | None:
        project_id = context.focus_entity("project")
        if project_id is None or not self.product.has(project_id):
            return None
        return self.product.project(project_id)

    # -- run -----------------------------------------------------------------------------------

    def _new(self, _context: Context) -> None:
        title, accepted = QInputDialog.getText(self.parent, "New Project", "Project name:")
        if not accepted or not title.strip():
            return
        project = Project(title=title.strip())
        self.undo.push(AddNodeCommand(self.product.id, project))
        self.open_project(project.id)

    def _rename(self, context: Context) -> None:
        project = self._focused(context)
        if project is None:
            return  # The state gate already prevents this; stay honest.
        title, accepted = QInputDialog.getText(
            self.parent, "Rename Project", "Project name:", text=project.title
        )
        if accepted and title.strip():
            self.undo.push(SetFieldCommand(project.id, "title", title.strip()))

    def _delete(self, context: Context) -> None:
        project = self._focused(context)
        if project is None:
            return
        steps = len(project.steps)
        detail = f" and its {steps} step{'s' if steps != 1 else ''}" if steps else ""
        if confirm(self.parent, "Delete Project", f"Delete {project.title!r}{detail}?"):
            self.undo.push(RemoveNodeCommand(project.id))

    def _open(self, context: Context) -> None:
        project = self._focused(context)
        if project is not None:
            self.open_project(project.id)
