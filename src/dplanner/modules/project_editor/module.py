"""A project open in a tab: its step graph, a toolbar over it, and the Problems list beside it.

The tab is the canvas and its verbs. What the user selects on it is published into the
context, and every verb and panel in the window follows from there; the project's own forms
are *Project ▸ Settings…*, and a step's editor is a modal.

Three seams keep this module from knowing about anything else in the application:

- **The panel beside the canvas is hosted, never known.** The composition root hands over a
  ``SidePanel`` — a name, a glyph and a way to build the widget — and this module stands it
  in a splitter (``framework/side_panel.py``) without learning whose it is.
- **The index opens projects through a callback** it is given, and never learns what an
  activity is.
- **The toolbar names verbs it does not own** — the app shell's undo pair, the order module's
  ``order.open`` — and reaches them through the registry alone. See ``canvas_toolbar.py``.

**The canvas publishes its mode into the context** as an edge on the activity node, so
``steps.connect`` can decide whether it is checked from the context alone. That is the whole
mechanism behind the toolbar's mode switch, and why there is no other one.

**The look is the module's** — the marks, the spotlight, the background under the graph and
whether gestures snap to its grid, one ``Look`` (``look.py``) — read from the per-user store
once and pushed to every open canvas when it changes: a way of looking at graphs, not a fact about
one project, so a tab opened later wears the same look and a second window would too.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QMenu, QVBoxLayout, QWidget

from dplanner.core.signals import Signal as CoreSignal
from dplanner.domain.commands import (
    Command,
    CompositeCommand,
    redirect_edges_command,
)
from dplanner.domain.model import (
    SOURCE,
    WAITER,
    Edge,
    EdgeEnd,
    Library,
    NodeId,
    Project,
    Redirection,
    Step,
    StepId,
)
from dplanner.domain.ordering import ports
from dplanner.domain.store import FilesFor
from dplanner.framework.action_menu import fill_bands
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.activity import EntityActivity, follow_project, follow_project_tabs
from dplanner.framework.context import (
    SCOPE_ACTIVITY,
    SCOPE_SELECTION,
    Context,
    ContextNode,
    ContextService,
    Uri,
    activity_uri,
    entity_uri,
    selection_uri,
)
from dplanner.framework.debounce import Debounced, DebounceService
from dplanner.framework.picker import PickerDialog
from dplanner.framework.side_panel import HostedSidePanel, SidePanel
from dplanner.framework.tabs import TabHost
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.framework.user_config import get_global, set_global
from dplanner.framework.window import StatusHost
from dplanner.modules.project_editor.canvas_menus import BANDS, target_of
from dplanner.modules.project_editor.canvas_toolbar import PANEL_ACTION, CanvasToolbar
from dplanner.modules.project_editor.canvas_verbs import CanvasVerbs
from dplanner.modules.project_editor.clipboard import PastePolicy
from dplanner.modules.project_editor.clipboard_verbs import ClipboardVerbs, ClipboardWatch
from dplanner.modules.project_editor.find import find_rows
from dplanner.modules.project_editor.geometry import CONTRACT_LABEL, DIVIDE_LABEL, divide_command
from dplanner.modules.project_editor.graph import GraphScene, GraphView, NodeSpec
from dplanner.modules.project_editor.layout_button import LayoutButton
from dplanner.modules.project_editor.layout_verbs import LayoutVerbs
from dplanner.modules.project_editor.look import Look
from dplanner.modules.project_editor.modes import (
    CONNECT,
    CONTRACT_HORIZONTAL,
    CONTRACT_VERTICAL,
    DIVIDE_HORIZONTAL,
    DIVIDE_VERTICAL,
    LASSO,
    REDIRECT_FROM,
    REDIRECT_TO,
    CanvasDeps,
    ConnectMode,
    ContractMode,
    DivideMode,
    IdleMode,
    LassoMode,
    ModeBase,
    RedirectMode,
)
from dplanner.modules.project_editor.modes import mode_uri as canvas_mode_uri
from dplanner.modules.project_editor.named_layouts import position_commands, resize_command
from dplanner.modules.project_editor.placement import below, positions
from dplanner.modules.project_editor.positions import (
    DATA_FORMAT,
    centred_on,
    node_size,
    read_stack,
)
from dplanner.modules.project_editor.renderers import EdgeAccent, NodeAccent
from dplanner.modules.project_editor.selection import EDGE_KIND, CanvasSelection, EdgeRef
from dplanner.modules.project_editor.stack_verbs import StackVerbs
from dplanner.modules.project_editor.stacks import read_stacks
from dplanner.modules.project_editor.verbs import NEW_STEP_TITLE, StepVerbs

MODULE_ID = "project_editor"
# The tab kind stays "project": the module is the editor, but the thing in the tab is still a
# project, and every `tabs.open("project", …)` in the application keeps working.
PROJECT_KIND = "project"
# The per-user key the look is kept under — see look.py.
LOOK_KEY = "look"

# The modes a verb can switch on by name. Every other mode is a gesture that starts itself.
SWITCHABLE_MODES: dict[str, Callable[[CanvasDeps], ModeBase]] = {
    CONNECT: ConnectMode,
    LASSO: LassoMode,
    DIVIDE_VERTICAL: lambda deps: DivideMode(deps, Qt.Orientation.Vertical),
    DIVIDE_HORIZONTAL: lambda deps: DivideMode(deps, Qt.Orientation.Horizontal),
    CONTRACT_VERTICAL: lambda deps: ContractMode(deps, Qt.Orientation.Vertical),
    CONTRACT_HORIZONTAL: lambda deps: ContractMode(deps, Qt.Orientation.Horizontal),
    REDIRECT_TO: lambda deps: RedirectMode(deps, WAITER),
    REDIRECT_FROM: lambda deps: RedirectMode(deps, SOURCE),
}


def _no_accents(_project_id: str) -> dict[StepId, NodeAccent]:
    return {}


def _no_edge_accents(_project_id: str) -> Mapping[Edge, EdgeAccent]:
    return {}


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
    theme: ThemeService
    debounce: DebounceService
    # Where a step's attachments live, for a copy to carry them.
    files: FilesFor
    # How every step of a project should look beyond its text — muted, badged — in the
    # canvas's own vocabulary, so the editor never learns which aspects mean what. One call
    # per sync: the answer for a milestone comes from a schedule walk, and the walk is the
    # same for every step in the project.
    step_accents: Callable[[str], dict[StepId, NodeAccent]] = field(default=_no_accents)
    # Says an accent has changed for a reason the model cannot name. `step_accents` is
    # otherwise re-read whenever the project changes, which covers everything the plan
    # holds; what is wrong with a plan is *derived* from it, on a settle of its own, so it
    # lands after the change that caused it and has to say so itself.
    accents_changed: "CoreSignal[str] | None" = None
    # The same for the arrows, keyed (waiter, kind, source): which links auto-progress, and
    # which of those carry work that is being done right now. Absent means a plain arrow.
    edge_accents: Callable[[str], Mapping[Edge, EdgeAccent]] = field(default=_no_edge_accents)

    # How long a step takes, from whichever module owns estimates — the timeline sort reads
    # time through this, the same seam domain/schedule.py uses one level down.
    days_for: Callable[[Step], float | None] = field(default=_no_days)
    # A copied step carries its attachments: the file areas to read are the asset catalog's
    # sources, and what a copy may not carry is each owner's policy — see clipboard.py.
    file_modules: tuple[str, ...] = ()
    paste_policies: tuple[PastePolicy, ...] = ()
    # What the project tab hosts beside the canvas — see framework/side_panel.py. None
    # means this build has nothing to put there, and the toggle is hidden rather than greyed.
    side_panel: SidePanel | None = None


class ProjectActivity(EntityActivity):
    """One project, as a graph. What is selected on it is published; the panels follow."""

    def __init__(
        self,
        deps: ProjectEditorDeps,
        project_id: NodeId,
        verbs: StepVerbs,
        layout_verbs: LayoutVerbs,
        stack_verbs: StackVerbs,
        look: Look | None = None,
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

        self._stack_verbs = stack_verbs
        self._scene = GraphScene(self._link_refusal, self._redirection, stack_verbs.refusal)
        self._view = GraphView(
            self._scene,
            base_mode=IdleMode,
            status=lambda text: deps.status.show_status(text, 4000),
            run_action=self.run_action,
        )
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._on_context_menu)
        self._side_panel: HostedSidePanel | None = None
        self._page, self._toolbar = self._build_page()
        # After the page, because the side panel is part of the look now; still before the
        # first sync, so a node born dresses for it.
        self.set_look(look or Look())

        self._scene.selection_changed.connect(self._on_selection)
        self._scene.nodes_moved.connect(self._on_nodes_moved)
        self._scene.link_requested.connect(self._on_link_requested)
        self._scene.create_requested.connect(self._on_create)
        self._scene.node_resized.connect(self._on_node_resized)
        self._scene.graph_divided.connect(lambda moved: self._on_side_moved(DIVIDE_LABEL, moved))
        self._scene.graph_contracted.connect(
            lambda moved: self._on_side_moved(CONTRACT_LABEL, moved)
        )
        self._scene.redirect_requested.connect(self._on_redirect_requested)
        self._scene.stack_add_requested.connect(self._on_stack_add)
        self._scene.dropped_into_stack.connect(self._on_dropped_into_stack)
        self._scene.dropped_out_of_stack.connect(self._on_dropped_out_of_stack)
        self._view.modes.changed.connect(lambda _name: self._publish_activity())

        # Once per event-loop turn, not once per signal: a paste of forty steps is forty
        # signals and one sync, and a typed title still lands on the node as it is typed.
        self._sync_soon = Debounced(self._sync, 0, parent=self._page, service=deps.debounce)
        # Prose after a settle instead: a card shows none of it but whether an agent
        # instruction exists, and a sync derives every card before it can find that nothing
        # changed. A settle also waits behind a modal, so typing in Step Details costs the
        # canvas nothing until the dialog closes.
        self._sync_after_prose = Debounced(self._sync, parent=self._page, service=deps.debounce)
        library = self._product
        self._unsubscribes = [
            # Connected first, so a typing burst is sealed before the canvas re-syncs.
            library.structure_changed.connect(self._on_structure),
            # Every change inside this project, and none outside it.
            follow_project(
                library,
                self.project_id,
                self._sync_soon.trigger,
                signals=(
                    library.structure_changed,
                    library.edges_changed,
                    library.field_changed,
                    library.module_data_changed,
                ),
            ),
            follow_project(
                library,
                self.project_id,
                self._sync_after_prose.trigger,
                signals=(library.text_edited,),
            ),
            *(
                [deps.accents_changed.connect(self._on_accents_changed)]
                if deps.accents_changed is not None
                else []
            ),
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
        """Select one step on the canvas and put the viewport on it.

        How another view reveals something here, and where *Jump to* lands. Selecting
        without centring selects something that may be a screen away, which is no reveal
        at all; the zoom stays as the user left it.
        """
        self._sync_soon.flush()  # A step born this turn has its node only once synced.
        self._scene.select_step(step_id)
        self._view.centre_on_step(step_id)

    def select_steps(self, step_ids: list[StepId]) -> None:
        """Replace the selection with these steps — Select All's way in."""
        self._sync_soon.flush()
        self._scene.select_steps(step_ids)

    def select_edges(self, refs: list[EdgeRef]) -> None:
        """Replace the selection with these arrows — *Select Only Links*' way in."""
        self._sync_soon.flush()
        self._scene.select_edges(refs)

    def set_mode(self, name: str, on: bool) -> None:
        """Enter or leave one of the switchable modes. Escape leaves from the keyboard."""
        if on:
            if self._view.modes.current().name != name:
                self._view.modes.push(SWITCHABLE_MODES[name](self._view.deps))
        elif self._view.modes.current().name == name:
            self._view.modes.pop()

    def set_look(self, look: Look) -> None:
        """The user changed how graphs look; every canvas hears it, this one here. The
        marks, the spotlight and the snapping are the scene's, the background the view's,
        and whether the panel beside the canvas stands is the page's."""
        self._scene.set_marks(look.marks)
        self._scene.set_spotlight(look.spotlight)
        self._scene.set_snap(look.snap)
        self._view.set_background(look.background)
        if self._side_panel is not None:
            self._side_panel.set_shown(look.side_panel)

    def frame(self) -> None:
        self._view.frame_content()

    def run_action(self, action_id: str, context: Context | None = None) -> bool:
        """Run a verb against the current context, honouring its state gate.

        The one path from this tab to the vocabulary: the keymap uses it, the mode stack uses
        it, and so does a link the user just drew. Its answer — did the gate allow it — is
        what lets one key name several verbs and mean the one that applies. A constructed
        ``context`` is for a gesture whose verb needs a selection the user never made.
        """
        if context is None:
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
        self._sync_soon.cancel()
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self._layout_button.dispose()
        self._toolbar.dispose()
        if self._side_panel is not None:
            self._side_panel.dispose()
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
        spec = self._deps.side_panel
        if spec is not None:
            # The panel is told which project to show by a context naming **this** tab's —
            # a tab in the background must not follow the tab in front.
            self._side_panel = HostedSidePanel(
                spec,
                self._view,
                toggle=PANEL_ACTION,
                actions=self._deps.actions,
                context=self._deps.context,
            )
            self._side_panel.show_context(Context({SCOPE_ACTIVITY: self.activity_nodes()}))
        toolbar = CanvasToolbar(
            self._deps.actions,
            self._deps.context,
            page,
            picker=self._layout_button,
            panel_button=None if self._side_panel is None else self._side_panel.button,
        )
        column.addWidget(toolbar)
        column.addWidget(self._view if self._side_panel is None else self._side_panel.split, 1)
        return page, toolbar

    # -- the graph -----------------------------------------------------------------------------

    def _project(self) -> Project:
        return self._product.project(self.project_id)

    def _link_refusal(self, waiter: StepId, source: StepId) -> str | None:
        return self._product.link_refusal(waiter, "requires", source)

    def _redirection(self, edges: Sequence[EdgeRef], anchor: StepId, end: EdgeEnd) -> Redirection:
        """The model's answer about a redirect, in the canvas's own terms.

        The scene picks arrows and the domain names edges; this is the whole of the
        translation, and it is here rather than in the scene because the scene holds no
        library — the same seam ``_link_refusal`` is.
        """
        return self._product.redirection([edge.as_edge() for edge in edges], anchor, end)

    def _on_accents_changed(self, project_id: str, *_rest: object) -> None:
        """A derived fact about *this* project moved. It names the project because a view
        of one project hears its own changes and no others."""
        if project_id == self.project_id:
            self._sync_soon.trigger()

    def _sync(self) -> None:
        if not self._product.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        project = self._project()
        placed = positions(self._product, project)
        connected = ports(project.steps)
        accents = self._deps.step_accents(project.id)
        nodes = [
            NodeSpec(
                step_id=step.id,
                title=step.title or "Untitled step",
                x=placed[step.id][0],
                y=placed[step.id][1],
                accent=accents.get(step.id) or NodeAccent(),
                ports=connected[step.id],
                size=node_size(step),
            )
            for step in project.steps
        ]
        edges = [
            EdgeRef(waiter=step.id, kind=kind, source=source)
            for step in project.steps
            for kind, targets in step.edges.items()
            for source in targets
        ]
        edge_accents = {
            EdgeRef(*edge): accent for edge, accent in self._deps.edge_accents(project.id).items()
        }
        self._scene.sync(nodes, edges, edge_accents, read_stacks(project.steps))

    def _on_structure(self, parent_id: NodeId, _origin: object = None) -> None:
        if not self._product.belongs_to(parent_id, self.project_id):
            return
        if self._scene.selected_step() is not None:
            # A step that has gone ends a typing burst: the next edit is about something else.
            self._deps.undo.break_coalescing()

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
        steps = (ContextNode(selection_uri("step", step_id)) for step_id in selection.steps)
        edges = (ContextNode(selection_uri(EDGE_KIND, e.entity_id())) for e in selection.edges)
        nodes = (*steps, *edges)
        self.publish_selection(nodes)

    def _snapped(self, x: float, y: float) -> tuple[float, float]:
        """A seat as the user's Snap to Grid setting would land it — for the gestures that
        place a card at a point rather than dragging one: a double-click, New, a paste, a
        drop. A drag snaps itself as it goes; this is the same rule for a point."""
        return self._scene.snap(x), self._scene.snap(y)

    def _on_node_resized(self, step_id: StepId, x: float, y: float, w: float, h: float) -> None:
        self._deps.undo.push(
            resize_command(self._project(), step_id, (x, y), (w, h), view_origin=self)
        )
        self._deps.undo.break_coalescing()

    def _on_nodes_moved(self, moved: list[tuple[StepId, float, float]]) -> None:
        # The writes carry each card's size and stack — a move rewrites the whole entry — and
        # a stack member's seat moves its stack, whose seat is its first member's. A gesture
        # is named for what it moved: one stack is a Move Stack, however many cards it has.
        seats = {step_id: (x, y) for step_id, x, y in moved}
        stacked = {read_stack(self._product.step(step_id)) for step_id in seats}
        one = "Move Stack" if len(stacked) == 1 and "" not in stacked else "Move Step"
        commands = position_commands(self._project(), seats, one, view_origin=self)
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

    def _on_side_moved(self, label: str, moved: list[tuple[StepId, float, float]]) -> None:
        """One side of a cut was pushed aside or pulled up: one undo step, however many
        cards went, and named for the gesture rather than the moves it is made of — the very
        command ``dplanner layout shift`` or ``layout contract`` applies, so the two
        surfaces cannot drift."""
        seats = {step_id: (x, y) for step_id, x, y in moved}
        self._deps.undo.push(divide_command(self._project(), seats, view_origin=self, label=label))
        self._deps.undo.break_coalescing()

    def _on_redirect_requested(self, anchor: StepId, end: EdgeEnd) -> None:
        """A redirect gesture finished: one command, however many arrows moved.

        Its shape is the divide's — the mode reports, this turns it into a command. All the
        gesture reports is *where*; which links may move is the model's to say, and it is
        asked here rather than the mode's answer being carried over, so a plan that changed
        under a slow hand is never applied stale.
        """
        plan = self._redirection(self._scene.selection().edges, anchor, end)
        if plan.moving:
            self._deps.undo.push(
                redirect_edges_command(self._product, plan, _redirect_label(len(plan.moving)))
            )
            self._deps.undo.break_coalescing()
        self._deps.status.show_status(self._redirect_words(plan), 4000)

    def _redirect_words(self, plan: Redirection) -> str:
        """What the status bar says. A refusal is per link, so the count and the reason
        both belong in it — the one thing a redirect can do halfway."""
        title = self._product.step(plan.anchor).title
        way = "point to" if plan.end == WAITER else "come from"
        if not plan.moving:
            if plan.refused:
                return f"Nothing to redirect — {plan.refused[0][1]}"
            return "Nothing to redirect"
        moved = f"{len(plan.moving)} link{'' if len(plan.moving) == 1 else 's'} now {way} {title!r}"
        if not plan.refused:
            return moved
        return f"{moved}; {len(plan.refused)} left alone — {plan.refused[0][1]}"

    def _on_link_requested(self, sources: tuple[StepId, ...], target: StepId) -> None:
        """A drop is not a special case: it runs the same verb the menu does, handed a
        context naming both ends — the waiter last — so the refusal, the label and the
        command all come from one place. The canvas selection is left as the gesture found
        it — selecting the pair left Connect with no source for the next link."""
        self._run_on("steps.link", (*sources, target), "Those steps cannot be linked")

    def _on_stack_add(self, last: StepId) -> None:
        """A stack's "+": Add Step Below, run on the stack's last step alone — the verb the
        Stack menu offers, so the "+" cannot come to mean something the menu does not."""
        self._run_on("stacks.add_below", (last,), "A step cannot be added to that stack")

    def _on_dropped_into_stack(self, step_id: StepId, stack_id: str, slot: int) -> None:
        self._restacked(self._stack_verbs.drop_into(step_id, stack_id, slot))

    def _on_dropped_out_of_stack(self, step_id: StepId, x: float, y: float) -> None:
        self._restacked(self._stack_verbs.drop_out(step_id, self._snapped(x, y)))

    def _restacked(self, pushed: bool) -> None:
        """A restack let go: one undo step — or, refused, the cards put back where the
        model has them, since the gesture left them where the drop would have for a sync
        that is now not coming."""
        if pushed:
            self._deps.undo.break_coalescing()
        else:
            self._sync_soon.trigger()

    def _run_on(self, action_id: str, step_ids: Sequence[StepId], refused: str) -> None:
        """Run a verb on steps the gesture named rather than the ones picked, and say why
        when its state refuses — the greyed entry's label is the reason."""
        context = Context(
            {
                SCOPE_ACTIVITY: self.activity_nodes(),
                SCOPE_SELECTION: tuple(
                    ContextNode(selection_uri("step", step_id)) for step_id in step_ids
                ),
            }
        )
        if not self.run_action(action_id, context):
            state = self._deps.actions.spec(action_id).state(context)
            self._deps.status.show_status(state.label or refused, 4000)

    def _on_create(self, x: float, y: float) -> None:
        """Double-click on empty space: the same creation New runs, at the point."""
        self._verbs.create(self.project_id, NEW_STEP_TITLE, at=self._snapped(x, y))

    def note_placed(self, step_ids: list[StepId]) -> None:
        """Steps were just placed on this canvas — born here, or pasted.

        Two things follow from that and neither belongs to the verb: they become the
        selection, so the panel beside the canvas is already showing what was made; and the
        remembered point steps past them, so pressing New or Paste twice leaves two rows
        rather than one hiding another. The double-click lands here too — it pointed at a
        spot in exactly the same sense.
        """
        self._sync_soon.flush()  # The nodes exist only once the deferred sync has run.
        self._scene.select_steps(step_ids)
        point = self._view.last_click
        if point is not None:
            placed = positions(self._product, self._project())
            ys = [placed[s][1] for s in step_ids if s in placed]
            height = max(ys) - min(ys) if ys else 0.0
            self._view.note_click(QPointF(*below(point.x(), point.y() + height)))

    def note_created(self, step_id: StepId) -> None:
        """One step was just born here — by New or a double-click, never a paste.

        The details dialog opens on it, the same ``steps.details`` a double-click on a
        node runs, so naming it and saying what it is are the gesture's second half. A
        paste places steps too, but they arrive named and configured; only a birth asks.
        """
        assert step_id  # Placed first, so the selection the verb reads is already this one.
        self.run_action("steps.details")

    def new_step_position(self) -> tuple[float, float] | None:
        """The top-left a new node should take: centred on wherever the user last pointed.

        None until this canvas has been clicked at all, which is what keeps New from a
        freshly opened tab placing a node under the ambient layout's first slot.
        """
        point = self._view.last_click
        return None if point is None else self._snapped(*centred_on(point.x(), point.y()))

    def context_menu(self, position: QPoint) -> QMenu:
        """What a right-click at this viewport point offers, built and not shown.

        The thing under the cursor is made current first, and the menu is then composed
        from the pick (``canvas_menus.py``), so every verb in it reads the context every
        other presenter does. Separate from :meth:`_on_context_menu` so a test can read
        the menu without a modal loop.
        """
        scene_pos = self._view.mapToScene(position)
        # New places a node where the menu was raised, so the right-click counts as a
        # click — the keyboard menu key sends no press, and would otherwise reuse a
        # stale point.
        self._view.note_click(scene_pos)
        self._select_for_menu(scene_pos)
        bands = BANDS[target_of(self._scene.selection(), self._scene.stacks())]
        return fill_bands(QMenu(self._view), bands, self._deps.actions, self._deps.context)

    def _select_for_menu(self, scene_pos: QPointF) -> None:
        """Make the thing under the cursor current. A card or an arrow outside the pick
        becomes the pick; one inside it keeps it, or the menu's verbs would lose the rest.
        A stack's frame picks its members, as a click on it does. Empty canvas clears it:
        what is offered there is about the canvas, not a pick."""
        picked = self._scene.selection()
        node = self._scene.node_at(scene_pos)
        edge = None if node is not None else self._scene.edge_at(scene_pos)
        stack = None if node is not None or edge is not None else self._scene.frame_at(scene_pos)
        if node is not None:
            if node.step_id not in picked.steps:
                self._scene.select_step(node.step_id)
        elif edge is not None:
            if edge.ref not in picked.edges:
                self._scene.select_edges([edge.ref])
        elif stack is not None:
            if not set(stack.members) <= set(picked.steps) or picked.edges:
                self._scene.select_steps(list(stack.members))
        elif picked.steps or picked.edges:
            self._scene.select_steps([])

    def _on_context_menu(self, position: object) -> None:
        assert isinstance(position, QPoint)
        self.context_menu(position).exec(self._view.viewport().mapToGlobal(position))


def _redirect_label(count: int) -> str:
    """The undo entry's name — a gesture is named for itself, not for the moves it is made of."""
    return "Redirect Link" if count == 1 else f"Redirect {count} Links"


class ProjectEditorModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: ProjectEditorDeps) -> None:
        self._deps = deps
        self._look = Look.from_json(get_global(MODULE_ID, LOOK_KEY))
        self._verbs = StepVerbs(
            library=deps.library,
            undo=deps.undo,
            parent=deps.parent,
            current_project=self._current_project,
            new_position=self._new_step_position,
            placed=self._on_placed,
            created=self._on_created,
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
        self._stack_verbs = StackVerbs(
            library=deps.library,
            undo=deps.undo,
            current_project=self._current_project,
            new_position=self._new_step_position,
            born=self._verbs.born,
            status=lambda text: deps.status.show_status(text, 4000),
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
            select_edges=self._select_edges,
            set_mode=self._set_mode,
            frame=self._frame,
            find=self._find,
            look=lambda: self._look,
            set_look=self._set_look,
            side_panel=deps.side_panel,
        )

    def open(self, project_id: NodeId, *, preview: bool = False) -> None:
        """Show a project in a tab. Handed to the index segment as a plain function."""
        self._deps.tabs.open(PROJECT_KIND, project_id, preview=preview)

    def create_step(
        self,
        project_id: NodeId,
        title: str,
        *,
        at: tuple[float, float] | None = None,
        carrying: Callable[[Step], Sequence[Command]] | None = None,
        label: str = "New Step",
        before: StepId | None = None,
    ) -> Step:
        """Give birth to a step the way New does — the seam the composition root places
        through, so a feature step born from the Specs tab is one undo step with its
        marker and its position like any other placed step, and a wait inserted in front
        of a step (``before``) joins that step's stack when it stands in one."""
        return self._verbs.create(
            project_id, title, at=at, carrying=carrying, label=label, before=before
        )

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
            return ProjectActivity(
                deps, target, self._verbs, self._layout_verbs, self._stack_verbs, self._look
            )

        deps.tabs.register_factory(PROJECT_KIND, factory)
        self._verbs.register_into(deps.actions)
        self._stack_verbs.register_into(deps.actions)
        self._clipboard_verbs.register_into(deps.actions)
        self._canvas_verbs.register_into(deps.actions)
        self._layout_verbs.register_into(deps.actions)
        # A project that goes away takes its tab with it, and a rename reaches the tab.
        follow_project_tabs(deps.tabs, ProjectActivity, deps.library)

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

    def _on_created(self, step_id: StepId) -> None:
        current = self._current_activity()
        if current is not None:
            current.note_created(step_id)

    def _set_mode(self, name: str, on: bool) -> None:
        current = self._current_activity()
        if current is not None:
            current.set_mode(name, on)

    def _set_look(self, look: Look) -> None:
        """Change how every canvas looks, now and later, and let the toggles re-ask."""
        self._look = look
        set_global(MODULE_ID, LOOK_KEY, look.to_json())
        for activity in self._activities():
            activity.set_look(look)
        self._deps.context.refresh()

    def _select_steps(self, step_ids: list[StepId]) -> None:
        current = self._current_activity()
        if current is not None:
            current.select_steps(step_ids)

    def _select_edges(self, refs: list[EdgeRef]) -> None:
        current = self._current_activity()
        if current is not None:
            current.select_edges(refs)

    def _frame(self) -> None:
        current = self._current_activity()
        if current is not None:
            current.frame()

    def find_picker(self) -> PickerDialog | None:
        """The Find picker over the current canvas's project — built, not shown.

        Separate from :meth:`_find` so a test can read what the picker offers without a
        modal loop, the way ``menu_for`` opens a toolbar's dropdown without a click.
        """
        current = self._current_activity()
        if current is None or not self._deps.library.has(current.project_id):
            return None
        project = self._deps.library.project(current.project_id)
        ink = self._deps.parent.palette().color(QPalette.ColorRole.Text)
        rows = find_rows(project, self._deps.step_accents(project.id), ink)
        return PickerDialog(
            rows, self.reveal, self._deps.parent, placeholder="Find a step by name or key…"
        )

    def _find(self) -> None:
        picker = self.find_picker()
        if picker is not None:
            picker.exec()
