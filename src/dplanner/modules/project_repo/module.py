"""The repo association, in the running application: a widget other surfaces host.

Registers nothing — the module that owns a widget another feature hosts exposes a
``create_…()`` and the composition root hands it over (CLAUDE.md, how-to step 3). The
project panel is the one host today.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QWidget

from dplanner.domain.model import Product
from dplanner.framework.undo import UndoService
from dplanner.modules.project_repo.fields import RepoFieldsWidget
from dplanner.modules.project_repo.repo import DATA_FORMAT, MODULE_ID


@dataclass(frozen=True)
class ProjectRepoDeps:
    product: Product
    undo: UndoService[Product]
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

    def create_fields(self, parent: QWidget | None = None) -> RepoFieldsWidget:
        deps = self._deps
        return RepoFieldsWidget(
            deps.product,
            deps.undo,
            parent,
            is_git_repo=deps.is_git_repo,
            gh_installed=deps.gh_installed,
            gh_signed_in=deps.gh_signed_in,
        )

    def register(self) -> None:
        """Nothing to register: the widget is created for whoever hosts it."""
