"""What a person can do with named layouts and auto-sorts, as action specs.

The layout *names* are data, so picking one is not an ActionSpec — the picker button calls
:meth:`LayoutVerbs.apply` with a name. Everything with a fixed identity — save, update,
rename, delete, and the sort algorithms — is a registered action, so it lands in the menu
bar, the palette and the picker's popup at once.

**Which layout is currently applied is per-user presentation state**, kept in
:mod:`~dplanner.framework.user_config` rather than the workspace: two people sharing a
repository can be looking at different layouts of the same graph, and applying one must not
dirty the plan for both. **So is whether the graph is in Wave view**, per project: its seats
are derived on every sync and never saved, and *Keep This Arrangement* is the one verb that
writes them — a sort in kind, so one undo step (``ARCHITECTURE.md``'s *Wave view derives
positions; only Free view saves them*). Applying a layout or a sort leaves Wave view first,
since what it writes is what Free view shows.
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
from dplanner.modules.project_editor.placement import positions
from dplanner.modules.project_editor.positions import MODULE_ID
from dplanner.modules.project_editor.sorts import (
    layered_down,
    layered_flow,
    radial,
    spine,
    tidy,
    timeline,
    waves,
)
from dplanner.theme.icons import sort_icon

# The picker's popup renders these in order, through the same state gates as every other
# presenter — the tuple is what keeps the popup honest.
SORT_ACTION_IDS: tuple[str, ...] = (
    "canvas.sort_flow",
    "canvas.sort_down",
    "canvas.sort_spine",
    "canvas.sort_timeline",
    "canvas.sort_radial",
    "canvas.sort_tidy",
)
# Wave view and its one way of writing: the picker's popup leads with them, since the picker
# names the arrangement the canvas is showing.
WAVE_ACTION_IDS: tuple[str, ...] = ("canvas.waves", "canvas.waves_keep")
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


def wave_view(project_id: NodeId) -> bool:
    """Whether this user looks at this project's graph in Wave view — off unless turned on."""
    return get_global(MODULE_ID, f"waves/{project_id}") is True


def set_wave_view(project_id: NodeId, on: bool) -> None:
    set_global(MODULE_ID, f"waves/{project_id}", on)


@dataclass(frozen=True)
class LayoutVerbs:
    library: Library
    undo: UndoService[Library]
    parent: QWidget
    # Which project's graph these verbs act on: the one the current tab is showing.
    current_project: Callable[[], NodeId | None]
    status: Callable[[str], None]
    # How long a step takes, from whichever module owns estimates — the timeline sort's
    # and Wave view's one outside fact, handed in so this module never learns whose it is.
    days_for: Callable[[Step], float | None]
    # Put a project's tabs in or out of Wave view, remembered for this user: the module's,
    # because every tab showing that project follows.
    set_waves: Callable[[NodeId, bool], None]

    def register_into(self, actions: ActionRegistry) -> None:
        for spec in self._specs():
            actions.register(spec)

    def _specs(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                id="canvas.waves",
                label="&Waves",
                menu="Graph",
                group="arrange",
                # Before the Sort, Layout and Divide child menus, which claim the 10s and up:
                # a way of looking at the arrangement comes before the verbs that change it.
                order=1,
                tip="Every step in the column of its dependency depth, under a ruler of "
                "when each wave runs — derived, never saved (V)",
                state=self._waves_state,
                run=self._toggle_waves,
            ),
            ActionSpec(
                id="canvas.waves_keep",
                label="Keep T&his Arrangement",
                menu="Graph",
                group="arrange",
                order=2,
                tip="Save Wave view's arrangement as the graph's own, and go back to Free view",
                state=self._keep_state,
                run=self._keep_waves,
            ),
            ActionSpec(
                id="canvas.sort_flow",
                label="Layered &Flow",
                menu="Graph",
                group="arrange",
                submenu="Sort",
                order=10,
                icon=sort_icon,
                tip="Dependency depth left to right, columns centred, crossings reduced",
                state=self._with_steps,
                run=self._sort_flow,
            ),
            ActionSpec(
                id="canvas.sort_down",
                label="Layered &Down",
                menu="Graph",
                group="arrange",
                submenu="Sort",
                order=11,
                icon=sort_icon,
                tip="The same layering, flowing top to bottom",
                state=self._with_steps,
                run=self._sort_down,
            ),
            ActionSpec(
                id="canvas.sort_spine",
                label="&Spine",
                menu="Graph",
                group="arrange",
                submenu="Sort",
                order=12,
                icon=sort_icon,
                tip="The longest chain on a central line, feeders branching above and below",
                state=self._with_steps,
                run=self._sort_spine,
            ),
            ActionSpec(
                id="canvas.sort_timeline",
                label="&Timeline",
                menu="Graph",
                group="arrange",
                submenu="Sort",
                order=13,
                icon=sort_icon,
                tip="Left to right by earliest start, using the steps' estimates",
                state=self._with_steps,
                run=self._sort_timeline,
            ),
            ActionSpec(
                id="canvas.sort_radial",
                label="&Radial",
                menu="Graph",
                group="arrange",
                submenu="Sort",
                order=14,
                icon=sort_icon,
                tip="Rings fanned out from the selected step — or the most connected one",
                state=self._with_steps,
                run=self._sort_radial,
            ),
            ActionSpec(
                id="canvas.sort_tidy",
                label="T&idy",
                menu="Graph",
                group="arrange",
                submenu="Sort",
                order=15,
                icon=sort_icon,
                tip="Keep every cluster and its order; resolve overlaps, even the spacing "
                "to the pitch, close holes",
                state=self._with_steps,
                run=self._sort_tidy,
            ),
            ActionSpec(
                id="canvas.layout_save",
                label="Save Layout &As…",
                menu="Graph",
                group="arrange",
                submenu="Layout",
                order=20,
                tip="Snapshot the graph's current arrangement under a name",
                state=self._in_a_project,
                run=self._save,
            ),
            ActionSpec(
                id="canvas.layout_update",
                label="&Update Layout",
                menu="Graph",
                group="arrange",
                submenu="Layout",
                order=21,
                tip="Store the current arrangement over the applied layout",
                state=self._update_state,
                run=self._update,
            ),
            ActionSpec(
                id="canvas.layout_rename",
                label="Rena&me Layout…",
                menu="Graph",
                group="arrange",
                submenu="Layout",
                order=22,
                tip="Give the applied layout a new name",
                state=self._with_applied,
                run=self._rename,
            ),
            ActionSpec(
                id="canvas.layout_delete",
                label="Delete La&yout…",
                menu="Graph",
                group="arrange",
                submenu="Layout",
                order=23,
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
        self.set_waves(project_id, False)
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

    def _waves_state(self, _context: Context) -> ActionState:
        project = self._project()
        if project is None:
            return ActionState(enabled=False, checked=False)
        return ActionState(checked=wave_view(project.id))

    def _keep_state(self, _context: Context) -> ActionState:
        project = self._project()
        if project is None or not wave_view(project.id):
            return ActionState(enabled=False, label="Keep T&his Arrangement — not in Wave view")
        return ENABLED

    def _delete_state(self, _context: Context) -> ActionState:
        found = self._applied()
        if found is None:
            return DISABLED
        return ActionState(label=f'Delete La&yout "{found[1]}"…')

    # -- the sorts -----------------------------------------------------------------------------

    def _run_sort(
        self, project: Project, label: str, placed: dict[StepId, Point], said: str = ""
    ) -> None:
        if not placed:
            return
        self.set_waves(project.id, False)
        self.undo.push(CompositeCommand(label, position_commands(project, placed, label)))
        self.undo.break_coalescing()
        self.status(said or f"Sorted: {label}")

    # -- Wave view -----------------------------------------------------------------------------

    def _toggle_waves(self, _context: Context) -> None:
        project = self._project()
        if project is not None:
            self.set_waves(project.id, not wave_view(project.id))

    def _keep_waves(self, _context: Context) -> None:
        """Wave view's arrangement, written as the graph's own: the same columns and order,
        spaced for each card's own size — exactly what was shown while no card is resized —
        then Free view, showing it. ``dplanner layout sort <project> waves`` writes the same."""
        project = self._project()
        if project is None or not wave_view(project.id):
            return
        placed = waves(self.library, project, days_for=self.days_for)
        self._run_sort(project, "Keep Wave Arrangement", placed, "Kept Wave view's arrangement")

    def _sort_flow(self, _context: Context) -> None:
        project = self._project()
        if project is None:
            return
        self._run_sort(project, "Layered Flow", layered_flow(self.library, project))

    def _sort_down(self, _context: Context) -> None:
        project = self._project()
        if project is None:
            return
        self._run_sort(project, "Layered Down", layered_down(self.library, project))

    def _sort_spine(self, _context: Context) -> None:
        project = self._project()
        if project is None:
            return
        self._run_sort(project, "Spine Layout", spine(self.library, project))

    def _sort_timeline(self, _context: Context) -> None:
        project = self._project()
        if project is None:
            return
        placed = timeline(self.library, project, days_for=self.days_for)
        self._run_sort(project, "Timeline Layout", placed)

    def _sort_radial(self, context: Context) -> None:
        project = self._project()
        if project is None:
            return
        chosen = context.selected_entities("step")
        center = chosen[0] if len(chosen) == 1 else None
        self._run_sort(project, "Radial Layout", radial(self.library, project, center=center))

    def _sort_tidy(self, _context: Context) -> None:
        project = self._project()
        if project is None:
            return
        placed = tidy(project, positions(self.library, project))
        self._run_sort(project, "Tidy Layout", placed)

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
        self.undo.push(save_layout_command(project, name, snap, label=f'Update Layout "{name}"'))
        self.undo.break_coalescing()
        self.status(f"Updated layout “{name}”")

    def _rename(self, _context: Context) -> None:
        found = self._applied()
        if found is None:
            return
        project, old = found
        new, accepted = QInputDialog.getText(self.parent, "Rename Layout", "Layout name:", text=old)
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
