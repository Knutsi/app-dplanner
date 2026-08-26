"""A project open in a tab: its step graph, and the project form beside it.

The tab is the canvas and nothing else. What the user selects on it is published into the
context, and the window's panels — this module's project form, somebody else's step editor —
follow from there. So the graph does not host anything, and there is one detail panel in the
window however many projects are open side by side.

Three seams keep this module from knowing about anything else in the application:

- **The panel is anchored, not hosted.** ``register()`` puts :class:`ProjectPanel` in an area
  through ``deps.panels``; nothing here knows what else is in that area, and nothing there
  knows this exists.
- **The index opens projects through a callback** it is given, and never learns what an
  activity is.
- **What a node's second line says** comes from ``step_aspects``, supplied by the composition
  root from whatever aspect modules registered.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu, QWidget

from dplanner.domain.commands import (
    AddNodeCommand,
    Command,
    CompositeCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import NodeId, Product, Project, Step, StepId
from dplanner.framework.action_menu import build_menu
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.activity import ActivityBase
from dplanner.framework.context import (
    SCOPE_ACTIVITY,
    SCOPE_SELECTION,
    ContextNode,
    ContextService,
    Uri,
    activity_uri,
    entity_uri,
    selection_uri,
)
from dplanner.framework.panels import PanelArea, PanelRegistry, PanelSpec
from dplanner.framework.tabs import TabHost
from dplanner.framework.undo import UndoService
from dplanner.framework.window import StatusHost
from dplanner.modules.project_editor.graph import EdgeSpec, GraphScene, GraphView, NodeSpec
from dplanner.modules.project_editor.layout import positions
from dplanner.modules.project_editor.positions import DATA_FORMAT, write_position
from dplanner.modules.project_editor.positions import MODULE_ID as POSITION_KEY
from dplanner.modules.project_editor.project_panel import ProjectPanel
from dplanner.modules.project_editor.verbs import StepVerbs

MODULE_ID = "project_editor"
# The tab kind stays "project": the module is the editor, but the thing in the tab is still a
# project, and every `tabs.open("project", …)` in the application keeps working.
PROJECT_KIND = "project"
PANEL_ID = f"{MODULE_ID}.project"


def _no_aspects(_step_id: StepId) -> list[str]:
    return []


@dataclass(frozen=True)
class ProjectEditorDeps:
    product: Product
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    undo: UndoService[Product]
    status: StatusHost
    parent: QWidget
    panels: PanelRegistry
    # What the aspect modules have to say about a step, one short phrase each.
    step_aspects: Callable[[StepId], list[str]] = field(default=_no_aspects)


class ProjectActivity(ActivityBase):
    """One project, as a graph. What is selected on it is published; the panels follow."""

    def __init__(self, deps: ProjectEditorDeps, project_id: NodeId, verbs: StepVerbs) -> None:
        self._deps = deps
        self._product = deps.product
        self._verbs = verbs
        self.project_id = project_id
        # There is one selection scope, one detail panel and several panes on screen. Only
        # the pane the user is in may write to the scope: a background one re-syncing its
        # canvas — when a step is deleted, say — would otherwise clobber what the active pane
        # published, and the panel would follow it away from what the user is looking at.
        self._is_active = False

        self._scene = GraphScene(self._link_refusal)
        self._view = GraphView(self._scene)
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._on_context_menu)

        self._scene.focus_changed.connect(self._on_focus)
        self._scene.nodes_moved.connect(self._on_nodes_moved)
        self._scene.link_requested.connect(self._on_link_requested)
        self._scene.create_requested.connect(self._on_create)
        self._scene.delete_requested.connect(self._verbs.delete_many)

        self._unsubscribes = [
            self._product.structure_changed.connect(self._on_structure),
            self._product.edges_changed.connect(lambda *_a: self._sync()),
            self._product.field_changed.connect(self._on_field),
            self._product.module_data_changed.connect(self._on_module_data),
        ]
        self._sync()

    # -- the activity contract -----------------------------------------------------------------

    @property
    def uri(self) -> Uri:
        return activity_uri(PROJECT_KIND, self.project_id)

    @property
    def title(self) -> str:
        return self._project().title or "Untitled project"

    @property
    def widget(self) -> QWidget:
        return self._view

    def on_activated(self) -> None:
        self._is_active = True
        self._deps.context.set_scope(
            SCOPE_ACTIVITY,
            (ContextNode(self.uri, (("entity", entity_uri("project", self.project_id)),)),),
        )
        self._publish_selection(self._scene.selected_steps())

    def select_step(self, step_id: StepId) -> None:
        """Select one step on the canvas — how another view reveals something here."""
        self._scene.select_step(step_id)

    def on_deactivated(self) -> None:
        self._is_active = False
        self._deps.undo.break_coalescing()

    def close(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    # -- the graph -----------------------------------------------------------------------------

    def _project(self) -> Project:
        return self._product.project(self.project_id)

    def _link_refusal(self, waiter: StepId, source: StepId) -> str | None:
        return self._product.link_refusal(waiter, "requires", source)

    def _sync(self) -> None:
        if not self._product.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        project = self._project()
        placed = positions(self._product, project)
        nodes = [
            NodeSpec(
                step_id=step.id,
                title=step.title or "Untitled step",
                subtitle=" · ".join(self._deps.step_aspects(step.id)),
                x=placed[step.id][0],
                y=placed[step.id][1],
            )
            for step in project.steps
        ]
        edges = [
            EdgeSpec(waiter=step.id, source=source, kind=kind)
            for step in project.steps
            for kind, targets in step.edges.items()
            for source in targets
        ]
        self._scene.sync(nodes, edges)

    def _on_structure(self, _parent_id: NodeId, _origin: object = None) -> None:
        if not self._product.has(self.project_id):
            return
        if self._scene.selected_step() is not None:
            # A step that has gone ends a typing burst: the next edit is about something else.
            self._deps.undo.break_coalescing()
        self._sync()

    def _on_field(self, _node_id: NodeId, _field_name: str, _origin: object) -> None:
        self._sync()

    def _on_module_data(self, _node_id: NodeId, _module_id: str, _origin: object) -> None:
        self._sync()

    # -- gestures become commands ----------------------------------------------------------------

    def _on_focus(self, selection: list[StepId]) -> None:
        # Publishing *is* how the detail panel learns: it reads the context and nothing here
        # reaches for it. One step is something to edit and several is not, and the panel is
        # the one place that decides that.
        self._deps.undo.break_coalescing()
        self._publish_selection(selection)

    def _publish_selection(self, selection: list[StepId]) -> None:
        if not self._is_active:
            return  # See _is_active: a background pane does not speak for the user.
        nodes = tuple(ContextNode(selection_uri("step", step_id)) for step_id in selection)
        self._deps.context.set_scope(SCOPE_SELECTION, nodes)

    def _move_command(self, step_id: StepId, x: float, y: float) -> Command:
        return SetModuleDataCommand(
            step_id, POSITION_KEY, write_position(x, y), view_origin=self, label="Move Step"
        )

    def _on_nodes_moved(self, moved: list[tuple[StepId, float, float]]) -> None:
        commands = [self._move_command(step_id, x, y) for step_id, x, y in moved]
        if not commands:
            return
        if len(commands) == 1:
            self._deps.undo.push(commands[0])
        else:
            self._deps.undo.push(CompositeCommand("Move Steps", list(commands)))
        # A drag is a gesture with a clear end. Without the seal, two drags of the same node
        # coalesce — that command merges on node and module with no time window — and Ctrl+Z
        # would jump back past a move made minutes ago.
        self._deps.undo.break_coalescing()

    def _on_link_requested(self, source: StepId, target: StepId) -> None:
        """A drop is not a special case: it selects both ends and runs the same verb the
        menu does, so the refusal, the label and the command all come from one place."""
        self._scene.select_steps([source, target])
        context = self._deps.context.current()
        state = self._deps.actions.spec("steps.link").state(context)
        if state.visible and state.enabled:
            self._deps.actions.run("steps.link", context)
        else:
            self._deps.status.show_status(state.label or "Those steps cannot be linked", 4000)

    def _on_create(self, x: float, y: float) -> None:
        step = Step(title="New step")
        self._deps.undo.push(
            CompositeCommand(
                "Add Step",
                [
                    AddNodeCommand(self.project_id, step),
                    self._move_command(step.id, x, y),
                ],
            )
        )
        self._scene.select_step(step.id)

    def _on_context_menu(self, position: object) -> None:
        from PySide6.QtCore import QPoint

        assert isinstance(position, QPoint)
        scene_pos = self._view.mapToScene(position)
        node = self._scene._node_at(scene_pos)
        if node is not None:
            self._scene.select_step(node.step_id)
        menu: QMenu = build_menu(self._deps.actions, self._deps.context, "Step", self._view)
        menu.exec(self._view.viewport().mapToGlobal(position))


class ProjectEditorModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: ProjectEditorDeps) -> None:
        self._deps = deps
        self._verbs = StepVerbs(
            product=deps.product,
            undo=deps.undo,
            parent=deps.parent,
            current_project=self._current_project,
        )

    def open(self, project_id: NodeId) -> None:
        """Show a project in a tab. Handed to the index segment as a plain function."""
        self._deps.tabs.open(PROJECT_KIND, project_id)

    def reveal(self, step_id: StepId) -> None:
        """Show the step's project and select it there.

        The capability the composition root hands to anything that lists steps — the order
        view today — so it can say "show me this one" without knowing what a canvas is.
        """
        if not self._deps.product.has(step_id):
            return
        project = self._deps.product.project_of(step_id)
        self.open(project.id)
        for activity in self._activities():
            if activity.project_id == project.id:
                activity.select_step(step_id)

    def register(self) -> None:
        deps = self._deps

        def factory(target: str | None) -> ProjectActivity:
            assert target is not None
            return ProjectActivity(deps, target, self._verbs)

        deps.tabs.register_factory(PROJECT_KIND, factory)
        # Order 10: above the step panel, because a project is what a step is part of.
        deps.panels.register(
            PanelSpec(
                id=PANEL_ID,
                title="Project",
                factory=lambda: ProjectPanel(deps.product, deps.undo),
                area=PanelArea.RIGHT,
                order=10,
            )
        )
        self._verbs.register_into(deps.actions)
        # A project that goes away takes its tab with it, and a rename reaches the tab.
        deps.product.structure_changed.connect(lambda *_args: self._close_orphan_tabs())
        deps.product.field_changed.connect(lambda *_args: self._retitle_tabs())

    # -- tabs ------------------------------------------------------------------------------------

    def _activities(self) -> list[ProjectActivity]:
        return [a for a in self._deps.tabs.activities() if isinstance(a, ProjectActivity)]

    def _current_project(self) -> NodeId | None:
        current = self._deps.tabs.current_activity()
        return current.project_id if isinstance(current, ProjectActivity) else None

    def _close_orphan_tabs(self) -> None:
        for activity in self._activities():
            if not self._deps.product.has(activity.project_id):
                self._deps.tabs.close_activity(activity)

    def _retitle_tabs(self) -> None:
        for activity in self._activities():
            if self._deps.product.has(activity.project_id):
                self._deps.tabs.set_tab_title(activity, activity.title)
