"""What a person can do to a region, as action specs.

A region is annotation on the project's canvas — which is why these live under the Project
menu's canvas group rather than beside the step verbs. Add Region is a mode switch like
Connect: checked while the mode is on, read purely from the context. Rename and Delete act
on the selected regions, published into the context the same way steps and edges are, which
is what lets one Delete key mean all three through the keymap's first-allowed-wins chain.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QInputDialog, QWidget

from dplanner.domain.model import Library, NodeId, Project
from dplanner.framework.action_registry import (
    DISABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context
from dplanner.framework.undo import UndoService
from dplanner.modules.project_editor.modes import REGION_CREATE, mode_uri
from dplanner.modules.project_editor.regions import (
    Region,
    read_regions,
    set_regions_command,
)
from dplanner.modules.project_editor.selection import REGION_KIND


@dataclass(frozen=True)
class RegionVerbs:
    library: Library
    undo: UndoService[Library]
    parent: QWidget
    # Which project the current tab is showing, as for the step verbs.
    current_project: Callable[[], NodeId | None]
    set_region_mode: Callable[[bool], None]

    def register_into(self, actions: ActionRegistry) -> None:
        for spec in self._specs():
            actions.register(spec)

    def _specs(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                id="regions.new",
                label="&Add Region",
                menu="Project",
                group="canvas",
                submenu="Region",
                order=10,
                tip="Drag out a titled area behind the graph. Esc leaves",
                state=self._can_add,
                run=self._add,
            ),
            ActionSpec(
                id="regions.rename",
                label="&Rename Region…",
                menu="Project",
                group="canvas",
                submenu="Region",
                order=20,
                tip="Change what this region is called",
                state=self._one_selected,
                run=self._rename,
            ),
            ActionSpec(
                id="regions.delete",
                label="&Delete Region",
                menu="Project",
                group="canvas",
                submenu="Region",
                order=30,
                tip="Remove these regions. The steps inside stay where they are",
                state=self._can_delete,
                run=self._delete,
            ),
        ]

    # -- state ---------------------------------------------------------------------------------

    def _project(self) -> Project | None:
        project_id = self.current_project()
        if project_id is None or not self.library.has(project_id):
            return None
        return self.library.project(project_id)

    def _selected(self, context: Context) -> list[Region]:
        project = self._project()
        if project is None:
            return []
        chosen = set(context.selected_entities(REGION_KIND))
        return [region for region in read_regions(project) if region.id in chosen]

    def _can_add(self, context: Context) -> ActionState:
        if self._project() is None:
            return DISABLED
        # Checked while the mode is on — the same mechanism as the Connect button.
        return ActionState(checked=context.edge("mode") == mode_uri(REGION_CREATE))

    def _one_selected(self, context: Context) -> ActionState:
        return ActionState() if len(self._selected(context)) == 1 else DISABLED

    def _can_delete(self, context: Context) -> ActionState:
        chosen = self._selected(context)
        if not chosen:
            return DISABLED
        if len(chosen) == 1:
            return ActionState()
        return ActionState(label=f"&Delete {len(chosen)} Regions")

    # -- run -----------------------------------------------------------------------------------

    def _add(self, context: Context) -> None:
        self.set_region_mode(context.edge("mode") != mode_uri(REGION_CREATE))

    def _rename(self, context: Context) -> None:
        project = self._project()
        chosen = self._selected(context)
        if project is None or len(chosen) != 1:
            return  # The state gate already prevents this; stay honest.
        region = chosen[0]
        title, accepted = QInputDialog.getText(
            self.parent, "Rename Region", "Region name:", text=region.title
        )
        if not accepted or not title.strip():
            return
        renamed = [
            r.named(title.strip()) if r.id == region.id else r for r in read_regions(project)
        ]
        self.undo.push(set_regions_command(project, renamed, "Rename Region"))
        self.undo.break_coalescing()

    def _delete(self, context: Context) -> None:
        project = self._project()
        chosen = self._selected(context)
        if project is None or not chosen:
            return
        doomed = {region.id for region in chosen}
        kept = [region for region in read_regions(project) if region.id not in doomed]
        self.undo.push(set_regions_command(project, kept, "Delete Region"))
        self.undo.break_coalescing()
