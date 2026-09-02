"""A project open in a tab: its step graph, a toolbar over it, and the project form beside it.

The tab is the canvas and its verbs. What the user selects on it is published into the
context, and the window's panels — this module's project form, somebody else's step editor —
follow from there. So the graph does not host anything, and there is one detail panel in the
window however many projects are open side by side.

Four seams keep this module from knowing about anything else in the application:

- **The panel is anchored, not hosted.** ``register()`` puts :class:`ProjectPanel` in an area
  through ``deps.panels``; nothing here knows what else is in that area, and nothing there
  knows this exists.
- **The index opens projects through a callback** it is given, and never learns what an
  activity is.
- **What a node's second line says** comes from ``step_aspects``, supplied by the composition
  root from whatever aspect modules registered.
- **The toolbar names verbs it does not own** — the app shell's undo pair, the order module's
  ``order.open`` — and reaches them through the registry alone. See ``canvas_toolbar.py``.

**The canvas publishes its mode into the context** as an edge on the activity node, so
``steps.connect`` can decide whether it is checked from the context alone. That is the whole
mechanism behind the toolbar's mode switch, and why there is no other one.

**The marks are the module's**, read from the per-user store once and pushed to every open
canvas when they change — a way of looking at graphs, not a fact about one project, so a tab
opened later wears the same marks and a second window would too.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtWidgets import QMenu, QVBoxLayout, QWidget

from dplanner.cli.command import CliError
from dplanner.domain.commands import (
    Command,
    CompositeCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import Library, NodeId, Project, Step, StepId
from dplanner.domain.store import FilesFor
from dplanner.framework.action_menu import build_menu
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.activity import EntityActivity, follow_entity_tabs
from dplanner.framework.context import (
    SCOPE_ACTIVITY,
    ContextNode,
    ContextService,
    Uri,
    activity_uri,
    entity_uri,
    selection_uri,
)
from dplanner.framework.inspector import InspectorSectionRegistry
from dplanner.framework.panels import PanelArea, PanelRegistry, PanelSpec
from dplanner.framework.tabs import TabHost
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.framework.user_config import get_global, set_global
from dplanner.framework.window import StatusHost
from dplanner.modules.project_editor.canvas_toolbar import CanvasToolbar
from dplanner.modules.project_editor.canvas_verbs import CanvasVerbs
from dplanner.modules.project_editor.clipboard import PastePolicy
from dplanner.modules.project_editor.clipboard_verbs import ClipboardVerbs, ClipboardWatch
from dplanner.modules.project_editor.graph import GraphScene, GraphView, NodeSpec
from dplanner.modules.project_editor.items import StepNodeItem
from dplanner.modules.project_editor.kinds import CanvasDrop, StepKind
from dplanner.modules.project_editor.layout_button import LayoutButton
from dplanner.modules.project_editor.layout_verbs import LayoutVerbs
from dplanner.modules.project_editor.marks import Marks, ports
from dplanner.modules.project_editor.modes import (
    CONNECT,
    LASSO,
    REGION_CREATE,
    CanvasDeps,
    ConnectMode,
    IdleMode,
    LassoMode,
    ModeBase,
    RegionCreateMode,
)
from dplanner.modules.project_editor.modes import mode_uri as canvas_mode_uri
from dplanner.modules.project_editor.placement import below, positions
from dplanner.modules.project_editor.positions import DATA_FORMAT, centred_on, write_position
from dplanner.modules.project_editor.positions import MODULE_ID as POSITION_KEY
from dplanner.modules.project_editor.project_panel import ProjectPanel
from dplanner.modules.project_editor.region_verbs import RegionVerbs
from dplanner.modules.project_editor.regions import (
    new_region,
    read_regions,
    set_regions_command,
)
from dplanner.modules.project_editor.renderers import NodeAccent
from dplanner.modules.project_editor.selection import (
    EDGE_KIND,
    REGION_KIND,
    CanvasSelection,
    EdgeRef,
)
from dplanner.modules.project_editor.verbs import StepVerbs

MODULE_ID = "project_editor"
# The tab kind stays "project": the module is the editor, but the thing in the tab is still a
# project, and every `tabs.open("project", …)` in the application keeps working.
PROJECT_KIND = "project"
PANEL_ID = f"{MODULE_ID}.project"
# The per-user key the marks are kept under — see marks.py.
MARKS_KEY = "marks"

# The modes a verb can switch on by name. Every other mode is a gesture that starts itself.
SWITCHABLE_MODES: dict[str, Callable[[CanvasDeps], ModeBase]] = {
    CONNECT: ConnectMode,
    LASSO: LassoMode,
    REGION_CREATE: RegionCreateMode,
}


def _no_aspects(_step_id: StepId) -> list[str]:
    return []


def _no_accent(_step_id: StepId) -> NodeAccent:
    return NodeAccent()


def _no_days(_step: Step) -> float | None:
    return None


@dataclass(frozen=True)
class ProjectEditorDeps:
    library: Library
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    undo: UndoService[Library]
    status: StatusHost
    parent: QWidget
    panels: PanelRegistry
    theme: ThemeService
    # Where a step's attachments live, for a copy to carry them.
    files: FilesFor
    # What the aspect modules have to say about a step, one short phrase each.
    step_aspects: Callable[[StepId], list[str]] = field(default=_no_aspects)
    # How a step should look beyond its text — muted, badged — in the canvas's own
    # vocabulary, so the editor never learns which aspects mean what.
    step_accent: Callable[[StepId], NodeAccent] = field(default=_no_accent)
    # How long a step takes, from whichever module owns estimates — the timeline sort reads
    # time through this, the same seam domain/schedule.py uses one level down.
    days_for: Callable[[Step], float | None] = field(default=_no_days)
    # The project panel renders every section registered here as a card — the registry the
    # composition root exposes as services.detail_cards. This module never learns whose.
    cards: InspectorSectionRegistry = field(default_factory=InspectorSectionRegistry)
    # What the New submenu offers besides a plain step. Named by the composition root, so
    # this module never learns what a feature or a milestone is — see kinds.py.
    step_kinds: tuple[StepKind, ...] = ()
    # A copied step carries its attachments: the file areas to read are the asset catalog's
    # sources, and what a copy may not carry is each owner's policy — see clipboard.py.
    file_modules: tuple[str, ...] = ()
    paste_policies: tuple[PastePolicy, ...] = ()
    # What the canvas takes by drop, named by the composition root — see kinds.py.
    drops: tuple[CanvasDrop, ...] = ()


class ProjectActivity(EntityActivity):
    """One project, as a graph. What is selected on it is published; the panels follow."""

    def __init__(
        self,
        deps: ProjectEditorDeps,
        project_id: NodeId,
        verbs: StepVerbs,
        layout_verbs: LayoutVerbs,
        marks: Marks | None = None,
    ) -> None:
        # Only the pane the user is in may write to the selection scope: a background one
        # re-syncing its canvas — when a step is deleted, say — would otherwise clobber
        # what the active pane published. EntityActivity owns that rule.
        super().__init__(deps.context, "project", project_id)
        self._deps = deps
        self._product = deps.library
        self._verbs = verbs
        self._layout_verbs = layout_verbs
        self.project_id = project_id

        self._scene = GraphScene(self._link_refusal)
        self._scene.set_marks(marks or Marks())
        self._view = GraphView(
            self._scene,
            base_mode=IdleMode,
            status=lambda text: deps.status.show_status(text, 4000),
            run_action=self.run_action,
            accepts=self._accepts_drop,
            dropped=self._on_drop,
        )
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._on_context_menu)
        self._page, self._toolbar = self._build_page()

        self._scene.selection_changed.connect(self._on_selection)
        self._scene.nodes_moved.connect(self._on_nodes_moved)
        self._scene.link_requested.connect(self._on_link_requested)
        self._scene.create_requested.connect(self._on_create)
        self._scene.region_create_requested.connect(self._on_region_create)
        self._scene.regions_moved.connect(self._on_regions_moved)
        self._scene.region_resized.connect(self._on_region_resized)
        self._view.modes.changed.connect(lambda _name: self._publish_activity())

        self._unsubscribes = [
            self._product.structure_changed.connect(self._on_structure),
            self._product.edges_changed.connect(lambda *_a: self._sync()),
            self._product.field_changed.connect(self._on_field),
            self._product.module_data_changed.connect(self._on_module_data),
            # Prose reaches the node too — the spark glyph and the subtitle's summaries
            # read module_text — and sync diffs before repainting, so a keystroke that
            # changes neither is free.
            self._product.text_edited.connect(lambda *_a: self._sync()),
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
        return self._page

    def on_activated(self) -> None:
        super().on_activated()
        self._publish_selection(self._scene.selection())
        # The canvas has its own key bindings, so it has to actually hold the keyboard.
        self._view.setFocus()

    def select_step(self, step_id: StepId) -> None:
        """Select one step on the canvas — how another view reveals something here."""
        self._scene.select_step(step_id)

    def select_steps(self, step_ids: list[StepId]) -> None:
        """Replace the selection with these steps — Select All's way in."""
        self._scene.select_steps(step_ids)

    def set_mode(self, name: str, on: bool) -> None:
        """Enter or leave one of the switchable modes. Escape leaves from the keyboard."""
        if on:
            if self._view.modes.current().name != name:
                self._view.modes.push(SWITCHABLE_MODES[name](self._view.deps))
        elif self._view.modes.current().name == name:
            self._view.modes.pop()

    def set_marks(self, marks: Marks) -> None:
        """The user changed which marks are on; every canvas hears it, this one here."""
        self._scene.set_marks(marks)

    def frame(self) -> None:
        self._view.frame_content()

    def run_action(self, action_id: str) -> bool:
        """Run a verb against the current context, honouring its state gate.

        The one path from this tab to the vocabulary: the keymap uses it, the mode stack uses
        it, and so does a link the user just drew. Its answer — did the gate allow it — is
        what lets one key name several verbs and mean the one that applies.
        """
        context = self._deps.context.current()
        state = self._deps.actions.spec(action_id).state(context)
        if not (state.visible and state.enabled):
            return False
        self._deps.actions.run(action_id, context)
        return True

    def on_deactivated(self) -> None:
        super().on_deactivated()
        # A mode is something the user is in, and they are no longer in this pane.
        self._view.modes.pop_to_base()
        self._deps.undo.break_coalescing()

    def close(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self._layout_button.dispose()
        self._toolbar.dispose()
        self._view.modes.dispose()

    # -- the page ------------------------------------------------------------------------------

    def _build_page(self) -> tuple[QWidget, CanvasToolbar]:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self._layout_button = LayoutButton(
            self._product,
            self.project_id,
            self._deps.actions,
            self._deps.context,
            self._layout_verbs,
        )
        toolbar = CanvasToolbar(
            self._deps.actions,
            self._deps.context,
            self._deps.theme,
            page,
            trailing=self._layout_button,
        )
        column.addWidget(toolbar)
        column.addWidget(self._view, 1)
        return page, toolbar

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
        connected = ports(project.steps)
        nodes = [
            NodeSpec(
                step_id=step.id,
                title=step.title or "Untitled step",
                subtitle=" · ".join(self._deps.step_aspects(step.id)),
                x=placed[step.id][0],
                y=placed[step.id][1],
                accent=self._deps.step_accent(step.id),
                ports=connected[step.id],
            )
            for step in project.steps
        ]
        edges = [
            EdgeRef(waiter=step.id, kind=kind, source=source)
            for step in project.steps
            for kind, targets in step.edges.items()
            for source in targets
        ]
        self._scene.sync(nodes, edges, read_regions(project))

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

    def _on_selection(self, selection: CanvasSelection) -> None:
        # Publishing *is* how the detail panel learns: it reads the context and nothing here
        # reaches for it. One step is something to edit and several is not, and the panel is
        # the one place that decides that.
        self._deps.undo.break_coalescing()
        self._publish_selection(selection)

    def activity_nodes(self) -> tuple[ContextNode, ...]:
        # The base's entity edge, plus the canvas's current input mode — a mode-switch
        # action's checked state is a pure function of the context.
        return (
            ContextNode(
                self.uri,
                (
                    ("entity", entity_uri("project", self.project_id)),
                    ("mode", canvas_mode_uri(self._view.modes.current().name)),
                ),
            ),
        )

    def _publish_activity(self) -> None:
        if not self._is_active:
            return
        self._deps.context.set_scope(SCOPE_ACTIVITY, self.activity_nodes())

    def _publish_selection(self, selection: CanvasSelection) -> None:
        nodes = (
            tuple(ContextNode(selection_uri("step", step_id)) for step_id in selection.steps)
            + tuple(
                ContextNode(selection_uri(EDGE_KIND, edge.entity_id())) for edge in selection.edges
            )
            + tuple(
                ContextNode(selection_uri(REGION_KIND, region_id))
                for region_id in selection.regions
            )
        )
        self.publish_selection(nodes)

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
        if not self.run_action("steps.link"):
            state = self._deps.actions.spec("steps.link").state(self._deps.context.current())
            self._deps.status.show_status(state.label or "Those steps cannot be linked", 4000)

    def _on_create(self, x: float, y: float) -> None:
        """Double-click on empty space: the same creation the New verbs run, unprompted."""
        self._verbs.create(self.project_id, "New step", at=(x, y))

    def _accepts_drop(self, mime: QMimeData) -> bool:
        return any(mime.hasFormat(drop.mime_type) for drop in self._deps.drops)

    def _on_drop(self, mime: QMimeData, scene_pos: QPointF) -> None:
        """Something dropped on empty canvas: the handler for its type places it, and a
        refusal — a feature already placed, a payload from another project — goes to the
        status bar in the same words the CLI would use."""
        for drop in self._deps.drops:
            if not mime.hasFormat(drop.mime_type):
                continue
            at = centred_on(scene_pos.x(), scene_pos.y())
            try:
                placed = drop.place(self.project_id, bytes(mime.data(drop.mime_type).data()), at)
            except CliError as error:
                self._deps.status.show_status(str(error), 4000)
                return
            if placed:
                self.note_placed(placed)
            return

    def note_placed(self, step_ids: list[StepId]) -> None:
        """Steps were just placed on this canvas — born here, or pasted.

        Two things follow from that and neither belongs to the verb: they become the
        selection, so the panel beside the canvas is already showing what was made; and the
        remembered point steps past them, so pressing New or Paste twice leaves two rows
        rather than one hiding another. The double-click lands here too — it pointed at a
        spot in exactly the same sense.
        """
        self._scene.select_steps(step_ids)
        point = self._view.last_click
        if point is not None:
            placed = positions(self._product, self._project())
            ys = [placed[s][1] for s in step_ids if s in placed]
            height = max(ys) - min(ys) if ys else 0.0
            self._view.note_click(QPointF(*below(point.x(), point.y() + height)))

    def new_step_position(self) -> tuple[float, float] | None:
        """The top-left a new node should take: centred on wherever the user last pointed.

        None until this canvas has been clicked at all, which is what keeps New from a
        freshly opened tab placing a node under the ambient layout's first slot.
        """
        point = self._view.last_click
        return None if point is None else centred_on(point.x(), point.y())

    def _on_region_create(self, x: float, y: float, w: float, h: float) -> None:
        project = self._project()
        created = new_region("Region", x, y, w, h)
        self._deps.undo.push(
            set_regions_command(
                project, [*read_regions(project), created], "Add Region", view_origin=self
            )
        )
        self._deps.undo.break_coalescing()
        self._scene.select_region(created.id)

    def _on_regions_moved(
        self,
        moves: list[tuple[str, float, float]],
        carried: list[tuple[StepId, float, float]],
    ) -> None:
        project = self._project()
        placed = {region_id: (x, y) for region_id, x, y in moves}
        updated = [
            region.moved_to(*placed[region.id]) if region.id in placed else region
            for region in read_regions(project)
        ]
        label = "Move Region" if len(moves) == 1 else f"Move {len(moves)} Regions"
        commands: list[Command] = [set_regions_command(project, updated, label, view_origin=self)]
        commands += [self._move_command(step_id, x, y) for step_id, x, y in carried]
        if len(commands) == 1:
            self._deps.undo.push(commands[0])
        else:
            self._deps.undo.push(CompositeCommand(label, commands))
        self._deps.undo.break_coalescing()

    def _on_region_resized(self, region_id: str, x: float, y: float, w: float, h: float) -> None:
        project = self._project()
        updated = [
            region.moved_to(x, y).sized(w, h) if region.id == region_id else region
            for region in read_regions(project)
        ]
        self._deps.undo.push(
            set_regions_command(project, updated, "Resize Region", view_origin=self)
        )
        self._deps.undo.break_coalescing()

    def _select_for_menu(self, node: StepNodeItem | None) -> None:
        """Make the thing under the cursor current — without collapsing a multi-selection
        the click landed inside, or the menu's verbs would lose the other N-1 steps."""
        if node is not None and node.step_id not in self._scene.selection().steps:
            self._scene.select_step(node.step_id)

    def _on_context_menu(self, position: object) -> None:
        from PySide6.QtCore import QPoint

        assert isinstance(position, QPoint)
        scene_pos = self._view.mapToScene(position)
        node = self._scene.node_at(scene_pos)
        region = self._scene.region_at(scene_pos) if node is None else None
        if region is not None:
            if region.region_id not in self._scene.selection().regions:
                self._scene.select_region(region.region_id)
            menu: QMenu = build_menu(
                self._deps.actions, self._deps.context, "Project", self._view, submenu="Region"
            )
        else:
            # New places a node where the menu was raised, so the right-click counts as a
            # click — the keyboard menu key sends no press, and would otherwise reuse a
            # stale point.
            self._view.note_click(scene_pos)
            self._select_for_menu(node)
            menu = build_menu(self._deps.actions, self._deps.context, "Step", self._view)
        menu.exec(self._view.viewport().mapToGlobal(position))


class ProjectEditorModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: ProjectEditorDeps) -> None:
        self._deps = deps
        self._marks = Marks.from_json(get_global(MODULE_ID, MARKS_KEY))
        self._verbs = StepVerbs(
            library=deps.library,
            undo=deps.undo,
            parent=deps.parent,
            current_project=self._current_project,
            step_kinds=deps.step_kinds,
            new_position=self._new_step_position,
            placed=self._on_placed,
        )
        # The watcher is a child of the window, which is what disconnects it from the
        # process-global clipboard when this build is discarded.
        self._clipboard = ClipboardWatch(deps.parent, deps.context)
        self._clipboard_verbs = ClipboardVerbs(
            library=deps.library,
            undo=deps.undo,
            files=deps.files,
            file_modules=deps.file_modules,
            held=self._clipboard.count,
            current_project=self._current_project,
            new_position=self._new_step_position,
            placed=self._on_placed,
            policies=deps.paste_policies,
        )
        self._layout_verbs = LayoutVerbs(
            library=deps.library,
            undo=deps.undo,
            parent=deps.parent,
            current_project=self._current_project,
            status=lambda text: deps.status.show_status(text, 4000),
            days_for=deps.days_for,
        )
        self._canvas_verbs = CanvasVerbs(
            library=deps.library,
            current_project=self._current_project,
            select_step=self.reveal,
            select_steps=self._select_steps,
            set_mode=self._set_mode,
            frame=self._frame,
            marks=lambda: self._marks,
            set_mark=self._set_mark,
        )
        self._region_verbs = RegionVerbs(
            library=deps.library,
            undo=deps.undo,
            parent=deps.parent,
            current_project=self._current_project,
            set_region_mode=lambda on: self._set_mode(REGION_CREATE, on),
        )

    def open(self, project_id: NodeId, *, preview: bool = False) -> None:
        """Show a project in a tab. Handed to the index segment as a plain function."""
        self._deps.tabs.open(PROJECT_KIND, project_id, preview=preview)

    def create_step(
        self,
        project_id: NodeId,
        title: str,
        *,
        kind: StepKind | None = None,
        at: tuple[float, float] | None = None,
    ) -> Step:
        """Give birth to a step the way the New verbs do — the seam a drop handler in the
        composition root places through, so a dropped feature is one undo step with its
        marker and its position like any other placed step."""
        return self._verbs.create(project_id, title, kind=kind, at=at)

    def reveal(self, step_id: StepId) -> None:
        """Show the step's project and select it there.

        What the ``steps.reveal`` verb does, and how the Go movement verbs land: any view
        that lists steps reaches this through the registry without knowing what a canvas is.
        """
        if not self._deps.library.has(step_id):
            return
        project = self._deps.library.project_of(step_id)
        self.open(project.id)
        for activity in self._activities():
            if activity.project_id == project.id:
                activity.select_step(step_id)

    def register(self) -> None:
        deps = self._deps

        def factory(target: str | None) -> ProjectActivity:
            assert target is not None
            return ProjectActivity(deps, target, self._verbs, self._layout_verbs, self._marks)

        deps.tabs.register_factory(PROJECT_KIND, factory)
        # Order 10: above the step panel, because a project is what a step is part of.
        deps.panels.register(
            PanelSpec(
                id=PANEL_ID,
                title="Project",
                factory=lambda: ProjectPanel(
                    deps.library, deps.undo, cards=deps.cards.sections(), theme=deps.theme
                ),
                area=PanelArea.RIGHT,
                order=10,
            )
        )
        self._verbs.register_into(deps.actions)
        self._clipboard_verbs.register_into(deps.actions)
        self._canvas_verbs.register_into(deps.actions)
        self._layout_verbs.register_into(deps.actions)
        self._region_verbs.register_into(deps.actions)
        # A project that goes away takes its tab with it, and a rename reaches the tab.
        follow_entity_tabs(
            deps.tabs,
            ProjectActivity,
            deps.library.has,
            closes_on=deps.library.structure_changed,
            retitles_on=deps.library.field_changed,
        )

    # -- tabs ------------------------------------------------------------------------------------

    def _activities(self) -> list[ProjectActivity]:
        return [a for a in self._deps.tabs.activities() if isinstance(a, ProjectActivity)]

    def _current_activity(self) -> ProjectActivity | None:
        current = self._deps.tabs.current_activity()
        return current if isinstance(current, ProjectActivity) else None

    def _current_project(self) -> NodeId | None:
        current = self._current_activity()
        return current.project_id if current is not None else None

    def _new_step_position(self) -> tuple[float, float] | None:
        current = self._current_activity()
        return current.new_step_position() if current is not None else None

    def _on_placed(self, step_ids: list[StepId]) -> None:
        current = self._current_activity()
        if current is not None:
            current.note_placed(step_ids)

    def _set_mode(self, name: str, on: bool) -> None:
        current = self._current_activity()
        if current is not None:
            current.set_mode(name, on)

    def _set_mark(self, name: str, on: bool) -> None:
        """Flip one mark for every canvas, now and later, and let the toggles re-ask."""
        self._marks = self._marks.with_(name, on)
        set_global(MODULE_ID, MARKS_KEY, self._marks.to_json())
        for activity in self._activities():
            activity.set_marks(self._marks)
        self._deps.context.refresh()

    def _select_steps(self, step_ids: list[StepId]) -> None:
        current = self._current_activity()
        if current is not None:
            current.select_steps(step_ids)

    def _frame(self) -> None:
        current = self._current_activity()
        if current is not None:
            current.frame()
