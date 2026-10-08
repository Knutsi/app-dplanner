"""A project open in a tab: its step graph, a toolbar over it, and the Problems list beside it.

The tab is the canvas and its verbs. What the user selects on it is published into the
context, and every verb and panel in the window follows from there; the project's own forms
are *Project ▸ Settings…*, and a step's editor is a modal.

**The canvas publishes its mode into the context** as an edge on the activity node, so
``steps.connect`` can decide whether it is checked from the context alone. That is the whole
mechanism behind the toolbar's mode switch, and why there is no other one.

**Wave view is per project, and only the seats change.** Whether this user looks at a project
in Wave view is kept beside the layout they applied (``layouts/verbs.wave_view``); every tab on
that project follows. In it, :meth:`ProjectActivity._sync` hands the scene the seats
``sorts.arranged_in_waves`` derives instead of the stored ones — the same items, moved by the
same diff sync — pins the cards so no hand moves them, and puts the ruler over the canvas.
Nothing is written: *Keep This Arrangement* is the one way Wave view reaches the store
(``docs/architecture/canvas.md``'s *Wave view derives positions; only Free view saves them*).
"""

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtWidgets import QMenu, QVBoxLayout, QWidget

from dplanner.domain.commands import CompositeCommand, redirect_edges_command
from dplanner.domain.model import SOURCE, WAITER, EdgeEnd, NodeId, Project, Redirection, StepId
from dplanner.domain.ordering import ports
from dplanner.framework.action_menu import fill_bands
from dplanner.framework.activity import EntityActivity, follow_project
from dplanner.framework.context import (
    SCOPE_ACTIVITY,
    SCOPE_SELECTION,
    Context,
    ContextNode,
    Uri,
    activity_uri,
    entity_uri,
    selection_uri,
)
from dplanner.framework.debounce import Debounced
from dplanner.framework.segmented import Segmented
from dplanner.framework.side_panel import HostedSidePanel
from dplanner.modules.canvas.geometry import CONTRACT_LABEL, DIVIDE_LABEL, divide_command
from dplanner.modules.canvas.layouts.button import LayoutButton
from dplanner.modules.canvas.layouts.named import position_commands, resize_command
from dplanner.modules.canvas.layouts.placement import below, free_spot, positions
from dplanner.modules.canvas.layouts.positions import (
    centred_on,
    default_size,
    footprints,
    read_stack,
)
from dplanner.modules.canvas.layouts.ruler import Heading, heading
from dplanner.modules.canvas.layouts.sorts import WaveArrangement, arranged_in_waves
from dplanner.modules.canvas.layouts.verbs import LayoutVerbs, wave_view
from dplanner.modules.canvas.look import Look
from dplanner.modules.canvas.menus import BANDS, target_of
from dplanner.modules.canvas.modes import (
    CONNECT,
    CONTRACT_HORIZONTAL,
    CONTRACT_VERTICAL,
    DIVIDE_HORIZONTAL,
    DIVIDE_VERTICAL,
    LASSO,
    REDIRECT_FROM,
    REDIRECT_TO,
    ConnectMode,
    ContractMode,
    DivideMode,
    IdleMode,
    LassoMode,
    ModeBase,
    ModeDeps,
    RedirectMode,
)
from dplanner.modules.canvas.modes import mode_uri as canvas_mode_uri
from dplanner.modules.canvas.renderers import NodeAccent
from dplanner.modules.canvas.scene import GraphScene, GraphView, NodeSpec
from dplanner.modules.canvas.selection import EDGE_KIND, CanvasSelection, EdgeRef
from dplanner.modules.canvas.stacks.stack import read_stacks
from dplanner.modules.canvas.stacks.verbs import StackVerbs
from dplanner.modules.canvas.step_verbs import NEW_STEP_TITLE, StepVerbs
from dplanner.modules.canvas.toolbar import PANEL_ACTION, CanvasToolbar
from dplanner.planning import estimate

if TYPE_CHECKING:  # module.py imports this file, so the Deps arrive as a forward name.
    from dplanner.modules.canvas.module import CanvasDeps

# The tab kind stays "project": the module is the editor, but the thing in the tab is still a
# project, and every `tabs.open("project", …)` in the application keeps working.
PROJECT_KIND = "project"
# The modes a verb can switch on by name. Every other mode is a gesture that starts itself.
SWITCHABLE_MODES: dict[str, Callable[[ModeDeps], ModeBase]] = {
    CONNECT: ConnectMode,
    LASSO: LassoMode,
    DIVIDE_VERTICAL: lambda deps: DivideMode(deps, Qt.Orientation.Vertical),
    DIVIDE_HORIZONTAL: lambda deps: DivideMode(deps, Qt.Orientation.Horizontal),
    CONTRACT_VERTICAL: lambda deps: ContractMode(deps, Qt.Orientation.Vertical),
    CONTRACT_HORIZONTAL: lambda deps: ContractMode(deps, Qt.Orientation.Horizontal),
    REDIRECT_TO: lambda deps: RedirectMode(deps, WAITER),
    REDIRECT_FROM: lambda deps: RedirectMode(deps, SOURCE),
}


class ProjectActivity(EntityActivity):
    """One project, as a graph. What is selected on it is published; the panels follow."""

    def __init__(
        self,
        deps: "CanvasDeps",
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
        # Whether this user looks at this project in Wave view — see show_waves.
        self._waves = wave_view(project_id)
        self._scene = GraphScene(self._link_refusal, self._redirection, stack_verbs.refusal)
        self._scene.set_pinned(self._waves)
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
            *(signal.connect(self._on_accents_changed) for signal in deps.accents_changed),
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

    def show_waves(self, on: bool) -> None:
        """Enter or leave Wave view — the module's call, made to every tab on this project
        when the user's choice changes. The cards move through the ordinary sync, the same
        items to other seats; nothing is rebuilt and nothing is written. A gesture in flight
        ends first: it was aimed at seats that are about to move."""
        if on == self._waves:
            return
        self._waves = on
        self._view.modes.pop_to_base()
        self._scene.set_pinned(on)
        self._sync()
        self._view_switch.set_value(on)
        self._layout_button.refresh_face()

    def set_look(self, look: Look) -> None:
        """The user changed how graphs look; every canvas hears it, this one here. The
        marks, the spotlight and the snapping are the scene's, the background the view's,
        and whether the panel beside the canvas stands is the page's."""
        self._scene.set_marks(look.marks)
        self._scene.set_spotlight(look.spotlight)
        self._scene.set_snap(look.snap)
        self._scene.motion_reduced = look.reduce_motion
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
        # Free or Waves, named at once with the one shown lit: a way of looking, so a pick runs
        # the verb the menu and V run, and the switch only follows what that decided.
        self._view_switch = Segmented(
            [
                (False, "Free", "Your own arrangement, as you left it"),
                (True, "Waves", "Every step in the column of its dependency depth (V)"),
            ]
        )
        self._view_switch.set_value(self._waves)
        self._view_switch.picked.connect(self._on_view_picked)
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
            view_switch=self._view_switch,
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
        # Either way a card is its body and the branch strip it wears — in Wave view the
        # default body, whatever was stored, since stored sizes are Free view's.
        strips = self._deps.strips(project.id)
        size_for = footprints(strips, default_size) if self._waves else footprints(strips)
        # Wave view substitutes the seats, and nothing else: the scene is handed the same
        # kind of spec, and the diff sync moves the same items.
        waves = (
            arranged_in_waves(self._product, project, size_for, estimate.read)
            if self._waves
            else None
        )
        placed = positions(self._product, project, size_for) if waves is None else waves.seats
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
                size=size_for(step),
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
        self._view.show_waves(() if waves is None else _headings(waves, accents))

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

    def _on_view_picked(self, value: object) -> None:
        """The Free | Waves switch: the verb decides, and the switch shows what it did."""
        if bool(value) != self._waves:
            self.run_action("canvas.waves")
        self._view_switch.set_value(self._waves)

    def _on_create(self, x: float, y: float) -> None:
        """Double-click on empty space: the same creation New runs, at the point — or, in
        Wave view, where a step born with no point goes."""
        at = self._free_seat() if self._waves else self._snapped(x, y)
        self._verbs.create(self.project_id, NEW_STEP_TITLE, at=at)

    def _free_seat(self) -> tuple[float, float]:
        """Somewhere free in Free view. A point on Wave view names a derived seat, which
        means nothing to the arrangement the step will be stored in — so a step born there
        is born where nobody pointed, and lands in its wave all the same."""
        return free_spot(self._product, self._project())

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
        freshly opened tab placing a node under the ambient layout's first slot. In Wave view,
        a free spot — see :meth:`_free_seat`.
        """
        if self._waves:
            return self._free_seat()
        point = self._view.last_click
        return None if point is None else self._snapped(*centred_on(point.x(), point.y()))

    def context_menu(self, position: QPoint) -> QMenu:
        """What a right-click at this viewport point offers, built and not shown.

        The thing under the cursor is made current first, and the menu is then composed
        from the pick (``menus.py``), so every verb in it reads the context every
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


def _headings(waves: WaveArrangement, accents: Mapping[StepId, NodeAccent]) -> list[Heading]:
    """The ruler's headings. Done is what the card says — a muted card is a done step —
    so the ruler and the cards under it cannot disagree about what is finished."""
    return [
        heading(wave, sum(1 for s in wave.steps if (found := accents.get(s)) and found.muted))
        for wave in waves.waves
    ]


def _redirect_label(count: int) -> str:
    """The undo entry's name — a gesture is named for itself, not for the moves it is made of."""
    return "Redirect Link" if count == 1 else f"Redirect {count} Links"
