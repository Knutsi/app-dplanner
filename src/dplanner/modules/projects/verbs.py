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

The membership band — Archive, Restore, Remove from Library — is ``project_archive``'s.
"""

from collections.abc import Callable
from dataclasses import dataclass

from dplanner.domain.model import Library, NodeId, Project, ProjectId
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context
from dplanner.theme.icons import link_icon, move_icon


@dataclass(frozen=True)
class ProjectVerbs:
    library: Library
    open_steps: Callable[[NodeId], None]
    # The module's dialogs, on a project.
    settings: Callable[[ProjectId], None]
    move: Callable[[ProjectId], None]
    share: Callable[[ProjectId], None]

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
                label="S&hare Project…",
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
                id="projects.open",
                label="St&eps",
                menu="Go",
                group="views",
                order=20,  # The index's order: Specs (10), Assets (15), then Steps.
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

    def _open(self, context: Context) -> None:
        project = self._focused(context)
        if project is not None:
            self.open_steps(project.id)
