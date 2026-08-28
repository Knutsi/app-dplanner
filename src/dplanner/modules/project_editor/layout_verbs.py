"""What a person can do with named layouts and auto-sorts, as action specs.

The layout *names* are data, so picking one is not an ActionSpec — the picker button calls
:meth:`LayoutVerbs.apply` with a name. Everything with a fixed identity — save, update,
rename, delete, and the sort algorithms — is a registered action, so it lands in the menu
bar, the palette and the picker's popup at once.

**Which layout is currently applied is per-user presentation state**, kept in
:mod:`~dplanner.framework.user_config` rather than the workspace: two people sharing a
repository can be looking at different layouts of the same graph, and applying one must not
dirty the plan for both.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QInputDialog, QWidget

from dplanner.domain.commands import CompositeCommand
from dplanner.domain.model import Library, NodeId, Project, Step, StepId
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context
from dplanner.framework.undo import UndoService
from dplanner.framework.user_config import get_global, set_global
from dplanner.framework.widgets import confirm
from dplanner.modules.project_editor.named_layouts import (
    Point,
    apply_layout_commands,
    delete_layout_command,
    position_commands,
    read_layouts,
    rename_layout_command,
    save_layout_command,
    snapshot,
)
from dplanner.modules.project_editor.positions import MODULE_ID
from dplanner.modules.project_editor.sorts import (
    layered_down,
    layered_flow,
    radial,
    spine,
    timeline,
)

# The picker's popup renders these in order, through the same state gates as every other
# presenter — the tuple is what keeps the popup honest.
SORT_ACTION_IDS: tuple[str, ...] = (
    "canvas.sort_flow",
    "canvas.sort_down",
    "canvas.sort_spine",
    "canvas.sort_timeline",
    "canvas.sort_radial",
)
MANAGE_ACTION_IDS: tuple[str, ...] = (
    "canvas.layout_save",
    "canvas.layout_update",
    "canvas.layout_rename",
    "canvas.layout_delete",
)


def current_layout_name(project_id: NodeId) -> str | None:
    """The layout this user last applied to this project, if any."""
    name = get_global(MODULE_ID, f"current_layout/{project_id}")
    return name if isinstance(name, str) else None


def set_current_layout_name(project_id: NodeId, name: str | None) -> None:
    set_global(MODULE_ID, f"current_layout/{project_id}", name)


@dataclass(frozen=True)
class LayoutVerbs:
    library: Library
    undo: UndoService[Library]
    parent: QWidget
    # Which project's graph these verbs act on: the one the current tab is showing.
    current_project: Callable[[], NodeId | None]
    status: Callable[[str], None]
    # How long a step takes, from whichever module owns estimates — the timeline sort's
    # one outside fact, handed in so this module never learns whose it is.
    days_for: Callable[[Step], float | None]

    def register_into(self, actions: ActionRegistry) -> None:
        for spec in self._specs():
            actions.register(spec)

    def _specs(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                id="canvas.sort_flow",
                label="Layered &Flow",
                menu="View",
                group="canvas",
                submenu="Sort",
                order=10,
                tip="Dependency depth left to right, columns centred, crossings reduced",
                state=self._with_steps,
                run=self._sort_flow,
            ),
            ActionSpec(
                id="canvas.sort_down",
                label="Layered &Down",
                menu="View",
                group="canvas",
                submenu="Sort",
                order=20,
                tip="The same layering, flowing top to bottom",
                state=self._with_steps,
                run=self._sort_down,
            ),
            ActionSpec(
                id="canvas.sort_spine",
                label="&Spine",
                menu="View",
                group="canvas",
                submenu="Sort",
                order=30,
                tip="The longest chain on a central line, feeders branching above and below",
                state=self._with_steps,
                run=self._sort_spine,
            ),
            ActionSpec(
                id="canvas.sort_timeline",
                label="&Timeline",
                menu="View",
                group="canvas",
                submenu="Sort",
                order=40,
                tip="Left to right by earliest start, using the steps' estimates",
                state=self._with_steps,
                run=self._sort_timeline,
            ),
            ActionSpec(
                id="canvas.sort_radial",
                label="&Radial",
                menu="View",
                group="canvas",
                submenu="Sort",
                order=50,
                tip="Rings fanned out from the selected step — or the most connected one",
                state=self._with_steps,
                run=self._sort_radial,
            ),
            ActionSpec(
                id="canvas.layout_save",
                label="Save Layout &As…",
                menu="View",
                group="canvas",
                submenu="Layout",
                order=10,
                tip="Snapshot the graph's current arrangement under a name",
                state=self._in_a_project,
                run=self._save,
            ),
            ActionSpec(
                id="canvas.layout_update",
                label="&Update Layout",
                menu="View",
                group="canvas",
                submenu="Layout",
                order=20,
                tip="Store the current arrangement over the applied layout",
                state=self._update_state,
                run=self._update,
            ),
            ActionSpec(
                id="canvas.layout_rename",
                label="Rena&me Layout…",
                menu="View",
                group="canvas",
                submenu="Layout",
                order=30,
                tip="Give the applied layout a new name",
                state=self._with_applied,
                run=self._rename,
            ),
            ActionSpec(
                id="canvas.layout_delete",
                label="Delete La&yout…",
                menu="View",
                group="canvas",
                submenu="Layout",
                order=40,
                tip="Forget the applied layout. The graph itself is untouched",
                state=self._delete_state,
                run=self._delete,
            ),
        ]

    # -- picking, from the button --------------------------------------------------------------

    def apply(self, project_id: NodeId, name: str) -> None:
        """Put the graph back the way this layout had it — one undo step."""
        if not self.library.has(project_id):
            return
        project = self.library.project(project_id)
        if name not in read_layouts(project):
            return
        commands = apply_layout_commands(self.library, project, name)
        if commands:
            self.undo.push(CompositeCommand(f'Apply Layout "{name}"', commands))
            self.undo.break_coalescing()
        set_current_layout_name(project_id, name)
        self.status(f"Applied layout “{name}”")

    # -- state ---------------------------------------------------------------------------------

    def _project(self) -> Project | None:
        project_id = self.current_project()
        if project_id is None or not self.library.has(project_id):
            return None
        return self.library.project(project_id)

    def _applied(self) -> tuple[Project, str] | None:
        """The current tab's project and its applied layout, when both still exist."""
        project = self._project()
        if project is None:
            return None
        name = current_layout_name(project.id)
        if name is None or name not in read_layouts(project):
            return None
        return project, name

    def _in_a_project(self, _context: Context) -> ActionState:
        return ENABLED if self._project() is not None else DISABLED

    def _with_steps(self, _context: Context) -> ActionState:
        project = self._project()
        return ENABLED if project is not None and project.steps else DISABLED

    def _with_applied(self, _context: Context) -> ActionState:
        return ENABLED if self._applied() is not None else DISABLED

    def _update_state(self, _context: Context) -> ActionState:
        found = self._applied()
        if found is None:
            # The label teaches the precondition: there is nothing to update over.
            return ActionState(enabled=False, label="&Update Layout — none applied")
        return ActionState(label=f'&Update Layout "{found[1]}"')

    def _delete_state(self, _context: Context) -> ActionState:
        found = self._applied()
        if found is None:
            return DISABLED
        return ActionState(label=f'Delete La&yout "{found[1]}"…')

    # -- the sorts -----------------------------------------------------------------------------

    def _run_sort(self, label: str, placed: dict[StepId, Point]) -> None:
        if not placed:
            return
        self.undo.push(CompositeCommand(label, position_commands(placed, label)))
        self.undo.break_coalescing()
        self.status(f"Sorted: {label}")

    def _sort_flow(self, _context: Context) -> None:
        project = self._project()
        if project is None:
            return
        self._run_sort("Layered Flow", layered_flow(self.library, project))

    def _sort_down(self, _context: Context) -> None:
        project = self._project()
        if project is None:
            return
        self._run_sort("Layered Down", layered_down(self.library, project))

    def _sort_spine(self, _context: Context) -> None:
        project = self._project()
        if project is None:
            return
        self._run_sort("Spine Layout", spine(self.library, project))

    def _sort_timeline(self, _context: Context) -> None:
        project = self._project()
        if project is None:
            return
        placed = timeline(self.library, project, days_for=self.days_for)
        self._run_sort("Timeline Layout", placed)

    def _sort_radial(self, context: Context) -> None:
        project = self._project()
        if project is None:
            return
        chosen = context.selected_entities("step")
        center = chosen[0] if len(chosen) == 1 else None
        self._run_sort("Radial Layout", radial(self.library, project, center=center))

    # -- run -----------------------------------------------------------------------------------

    def _save(self, _context: Context) -> None:
        project = self._project()
        if project is None:
            return  # The state gate already prevents this; stay honest.
        name, accepted = QInputDialog.getText(self.parent, "Save Layout", "Layout name:")
        name = name.strip()
        if not accepted or not name:
            return
        if name in read_layouts(project) and not confirm(
            self.parent, "Save Layout", f"Replace the layout “{name}”?"
        ):
            return
        snap = snapshot(self.library, project)
        self.undo.push(save_layout_command(project, name, snap, view_origin=None))
        self.undo.break_coalescing()
        set_current_layout_name(project.id, name)
        self.status(f"Saved layout “{name}”")

    def _update(self, _context: Context) -> None:
        found = self._applied()
        if found is None:
            return
        project, name = found
        snap = snapshot(self.library, project)
        self.undo.push(
            save_layout_command(project, name, snap, label=f'Update Layout "{name}"')
        )
        self.undo.break_coalescing()
        self.status(f"Updated layout “{name}”")

    def _rename(self, _context: Context) -> None:
        found = self._applied()
        if found is None:
            return
        project, old = found
        new, accepted = QInputDialog.getText(
            self.parent, "Rename Layout", "Layout name:", text=old
        )
        new = new.strip()
        if not accepted or not new or new == old:
            return
        if new in read_layouts(project):
            self.status(f"A layout named “{new}” already exists")
            return
        self.undo.push(rename_layout_command(project, old, new))
        self.undo.break_coalescing()
        set_current_layout_name(project.id, new)

    def _delete(self, _context: Context) -> None:
        found = self._applied()
        if found is None:
            return
        project, name = found
        if not confirm(self.parent, "Delete Layout", f"Delete the layout “{name}”?"):
            return
        self.undo.push(delete_layout_command(project, name))
        self.undo.break_coalescing()
        set_current_layout_name(project.id, None)
