"""The Qt half: the Assets tab's module, its Deps, and the verb that opens it."""

from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from dplanner.domain.assets import AssetSource
from dplanner.domain.model import Library, NodeId
from dplanner.domain.store import FilesFor
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.activity import follow_entity_tabs
from dplanner.framework.context import Context, ContextService
from dplanner.framework.tabs import TabHost
from dplanner.framework.undo import UndoService
from dplanner.modules.project_assets.activity import ASSETS_KIND, AssetsActivity
from dplanner.modules.project_assets.cli import DATA_FORMAT, MODULE_ID


@dataclass(frozen=True)
class ProjectAssetsDeps:
    library: Library
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    undo: UndoService[Library]
    parent: QWidget
    # The store's file lookup — every module's areas, because the catalog is a union.
    # Wired by the composition root, which is the only place that knows the concrete store.
    files: FilesFor
    # Every module's slice of the catalog — the same tuple the CLI reports read.
    sources: tuple[AssetSource, ...]


class ProjectAssetsModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: ProjectAssetsDeps) -> None:
        self._deps = deps

    def open(self, project_id: NodeId, *, preview: bool = False) -> None:
        self._deps.tabs.open(ASSETS_KIND, project_id, preview=preview)

    def register(self) -> None:
        deps = self._deps

        def factory(target: str | None) -> AssetsActivity:
            assert target is not None
            return AssetsActivity(deps, target)

        deps.tabs.register_factory(ASSETS_KIND, factory)
        deps.actions.register(
            ActionSpec(
                id="assets.open",
                label="Open &Assets",
                menu="Project",
                group="open",
                order=35,
                tip="Every image and file this project carries, and what uses each",
                state=self._on_a_project,
                run=self._open,
            )
        )
        follow_entity_tabs(
            deps.tabs,
            AssetsActivity,
            deps.library.has,
            closes_on=deps.library.structure_changed,
            retitles_on=deps.library.field_changed,
        )

    def _on_a_project(self, context: Context) -> ActionState:
        project_id = context.focus_entity("project")
        if project_id is None or not self._deps.library.has(project_id):
            return DISABLED
        return ENABLED

    def _open(self, context: Context) -> None:
        project_id = context.focus_entity("project")
        if project_id is not None:
            self.open(project_id)
