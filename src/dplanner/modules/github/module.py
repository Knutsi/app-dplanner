"""The GitHub aspect, in the running application: the GitHub tab and the PR refresher."""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Step, StepId
from dplanner.framework.action_registry import (
    DISABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.tasks import TaskService
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import confirm
from dplanner.modules.github.aspect import DATA_FORMAT, MODULE_ID, SPEC, enabled, read, write_state
from dplanner.modules.github.gh import which_gh
from dplanner.modules.github.notice import maybe_warn
from dplanner.modules.github.refresh import PrRefresher
from dplanner.modules.github.section import GithubSection


@dataclass(frozen=True)
class GithubDeps:
    library: Library
    undo: UndoService[Library]
    sections: InspectorSectionRegistry
    tasks: TaskService
    actions: ActionRegistry
    parent: QWidget  # The window: owns the refresher and parents the missing-gh notice.
    # step id -> the repository URL that step's refs belong to. project_repo's rule (the
    # project's own repository over the library's), arriving through the composition root.
    repository_for: Callable[[StepId], str]


class GithubModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: GithubDeps) -> None:
        self._deps = deps

    def _current(self, context: Context) -> ActionState:
        step = self._focused(context)
        if step is None:
            return DISABLED
        return ActionState(checked=enabled(step))

    def _toggle(self, context: Context) -> None:
        step = self._focused(context)
        if step is None:
            return
        if not enabled(step):
            self._deps.undo.push(
                SetModuleDataCommand(step.id, MODULE_ID, write_state(True), label="Track on GitHub")
            )
            return
        if read(step) is not None and not confirm(
            self._deps.parent,
            "Clear GitHub",
            f"Remove the branch and pull request from {step.title or 'this step'!r}?"
            " They are not kept.",
        ):
            return
        self._deps.undo.push(
            SetModuleDataCommand(step.id, MODULE_ID, write_state(False), label="Clear GitHub")
        )

    def _focused(self, context: Context) -> Step | None:
        step_id = context.focus_entity("step")
        if step_id is None or not self._deps.library.has(step_id):
            return None
        return self._deps.library.step(step_id)

    def register(self) -> None:
        deps = self._deps
        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.tab",
                label=SPEC.label,
                order=70,  # After Milestone (50) and Handoff (60).
                factory=lambda: GithubSection(
                    deps.library, deps.undo, deps.repository_for, deps.tasks
                ),
                shown_for=lambda step_id: (
                    step_id is not None
                    and deps.library.has(step_id)
                    and enabled(deps.library.step(step_id))
                ),
            )
        )
        deps.actions.register(
            ActionSpec(
                id="github.toggle",
                label=SPEC.label,
                menu="Step",
                group="type",
                submenu="Type",
                order=100,
                tip="Track this step's branch and pull request; fill them in on the tab",
                state=self._current,
                run=self._toggle,
            )
        )
        PrRefresher(deps.library, deps.tasks, deps.repository_for, parent=deps.parent).start()
        # Deferred past the window's show; notice.py keeps it to once per process.
        QTimer.singleShot(
            0, lambda: maybe_warn(deps.parent, installed=lambda: which_gh() is not None)
        )
