"""The GitHub aspect, in the running application: the GitHub tab and the PR refresher."""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from dplanner.domain.model import Library, StepId
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.tasks import TaskService
from dplanner.framework.undo import UndoService
from dplanner.modules.github.aspect import DATA_FORMAT, MODULE_ID, SPEC
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
    parent: QWidget  # The window: owns the refresher and parents the missing-gh notice.
    # step id -> the repository URL that step's refs belong to. project_repo's rule (the
    # project's own repository over the library's), arriving through the composition root.
    repository_for: Callable[[StepId], str]


class GithubModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: GithubDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.sections.register(
            InspectorSection(
                id=f"{MODULE_ID}.tab",
                label=SPEC.label,
                order=70,  # After Release (50) and Handoff (60).
                factory=lambda: GithubSection(
                    deps.library, deps.undo, deps.repository_for, deps.tasks
                ),
            )
        )
        PrRefresher(deps.library, deps.tasks, deps.repository_for, parent=deps.parent).start()
        # Deferred past the window's show; notice.py keeps it to once per process.
        QTimer.singleShot(
            0, lambda: maybe_warn(deps.parent, installed=lambda: which_gh() is not None)
        )
