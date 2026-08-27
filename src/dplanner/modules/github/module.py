"""The GitHub aspect, in the running application: the GitHub tab and the PR refresher."""

from dataclasses import dataclass

from PySide6.QtCore import QObject

from dplanner.domain.model import Product
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.tasks import TaskService
from dplanner.framework.undo import UndoService
from dplanner.modules.github.aspect import DATA_FORMAT, MODULE_ID, SPEC
from dplanner.modules.github.refresh import PrRefresher
from dplanner.modules.github.section import GithubSection


@dataclass(frozen=True)
class GithubDeps:
    product: Product
    undo: UndoService[Product]
    sections: InspectorSectionRegistry
    tasks: TaskService
    parent: QObject  # Owns the refresher, so its timer dies with the window.


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
                order=50,
                factory=lambda: GithubSection(deps.product, deps.undo),
            )
        )
        PrRefresher(deps.product, deps.tasks, parent=deps.parent).start()
