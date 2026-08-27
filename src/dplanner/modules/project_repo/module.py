"""The repo association, in the running application: a card in the project panel.

Registers an :class:`InspectorSection` into the detail-card registry the project panel
renders — the same contract the step panel's tabs use, with a card stack for a host.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from dplanner.domain.model import Product
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.undo import UndoService
from dplanner.modules.project_repo.fields import RepoFieldsWidget
from dplanner.modules.project_repo.repo import DATA_FORMAT, MODULE_ID
from dplanner.theme.icons import branch_icon


@dataclass(frozen=True)
class ProjectRepoDeps:
    product: Product
    undo: UndoService[Product]
    # The project panel's card registry — services.detail_cards at the composition root.
    cards: InspectorSectionRegistry = field(default_factory=InspectorSectionRegistry)
    # Advisory probes for the status line, wired by the composition root from the storage
    # layer (this module may not name a provider). None simply leaves that fact unsaid.
    is_git_repo: Callable[[Path], bool] | None = None
    gh_installed: Callable[[], bool] | None = None
    gh_signed_in: Callable[[], bool] | None = None


class ProjectRepoModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: ProjectRepoDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps

        def make_fields() -> RepoFieldsWidget:
            return RepoFieldsWidget(
                deps.product,
                deps.undo,
                is_git_repo=deps.is_git_repo,
                gh_installed=deps.gh_installed,
                gh_signed_in=deps.gh_signed_in,
            )

        deps.cards.register(
            InspectorSection(
                id=f"{MODULE_ID}.card",
                label="Repository",
                order=10,
                factory=make_fields,
                icon=branch_icon,
            )
        )
