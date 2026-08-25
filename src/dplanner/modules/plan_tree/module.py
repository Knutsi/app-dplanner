"""The plan as a tree: what the work is, where it stands, and the verbs that change it.

The sidebar's main page. Two columns rather than one — a title and a status — because the
first question anyone asks a plan is not "what is in it" but "where is it", and a tree that
answers only the first needs a second surface to answer the second.

Status is edited from here as well as from the properties panel: marking something done is
the most common edit in a planner, and making the user open a panel for it would be the
wrong trade. Both paths push the same command onto the same stack.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHeaderView,
    QInputDialog,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from dplanner.domain.commands import (
    AddTaskCommand,
    RemoveTaskCommand,
    SetFieldCommand,
    SetTitleCommand,
)
from dplanner.domain.model import STATUSES, Plan, Task, TaskId
from dplanner.framework.action_menu import build_menu
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    HIDDEN,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import (
    SCOPE_SELECTION,
    Context,
    ContextNode,
    ContextService,
    selection_uri,
)
from dplanner.framework.sidebar import SidebarPanel, SidebarPanelRegistry
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import confirm

MODULE_ID = "plan_tree"
ENTITY_KIND = "task"
TASK_MENU = "Task"
_ID_ROLE = Qt.ItemDataRole.UserRole

# What a status looks like in a tree row. A glyph rather than a word, because the column has
# to stay narrow enough that the titles keep the space.
STATUS_MARKS = {"todo": "○", "blocked": "▲", "doing": "◐", "done": "●"}


@dataclass(frozen=True)
class PlanTreeDeps:
    plan: Plan
    context: ContextService
    actions: ActionRegistry
    undo: UndoService[Plan]
    panels: SidebarPanelRegistry
    parent: QWidget
    # Wired by the composition root: the tree opens tasks without knowing what opens them.
    open_task: Callable[[TaskId], None]
    open_at_start: bool = True


class PlanTreeModule:
    id = MODULE_ID

    def __init__(self, deps: PlanTreeDeps) -> None:
        self._deps = deps
        self._tree: QTreeWidget | None = None

    def register(self) -> None:
        deps = self._deps
        tree = QTreeWidget()
        tree.setObjectName("PlanTree")
        tree.setHeaderHidden(True)
        tree.setColumnCount(2)
        # The title takes whatever is left; the status glyph gets exactly its own width.
        # Left to Qt's defaults the two columns split evenly and every title truncates.
        header = tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree = tree

        tree.itemSelectionChanged.connect(self._publish_selection)
        tree.itemActivated.connect(
            lambda item, _column: deps.open_task(str(item.data(0, _ID_ROLE)))
        )
        tree.customContextMenuRequested.connect(
            lambda point: build_menu(deps.actions, deps.context, TASK_MENU, tree).exec(
                tree.viewport().mapToGlobal(point)
            )
        )

        # Rebuild on structure; repaint one row on a field change. A full rebuild on every
        # keystroke in a title field would lose the selection and the expanded state.
        deps.plan.structure_changed.connect(lambda _parent_id: self._rebuild())
        deps.plan.title_changed.connect(lambda task_id, _origin: self._refresh_row(task_id))
        deps.plan.field_changed.connect(self._on_field_changed)

        deps.panels.register(SidebarPanel(id="plan", label="Plan", widget=tree, order=10))
        self._register_actions()
        self._rebuild()
        if deps.open_at_start and deps.plan.root.children:
            deps.open_task(deps.plan.root.children[0].id)

    # -- the tree ------------------------------------------------------------------------------

    def _rebuild(self) -> None:
        tree = self._tree
        if tree is None:
            return
        selected = self._selected_ids()
        expanded = self._expanded_ids()
        tree.clear()
        for child in self._deps.plan.root.children:
            self._add(child, tree.invisibleRootItem())
        self._restore(tree.invisibleRootItem(), selected, expanded)

    def _add(self, task: Task, parent: QTreeWidgetItem) -> QTreeWidgetItem:
        node = QTreeWidgetItem(parent)
        node.setData(0, _ID_ROLE, task.id)
        self._paint(node, task)
        for child in task.children:
            self._add(child, node)
        return node

    def _paint(self, node: QTreeWidgetItem, task: Task) -> None:
        label = task.title or "Untitled"
        if task.children:
            days = task.rolled_up_estimate()
            unestimated = task.unestimated()
            # A phase shows its rolled-up size, and says when part of that is a guess —
            # a total that silently counts unestimated work as zero is worse than none.
            summary = f"{days:g}d" if days else ""
            if unestimated:
                summary = f"{summary}+{unestimated}?" if summary else f"{unestimated}?"
            if summary:
                label = f"{label}  ({summary})"
        elif task.estimate_days is not None:
            label = f"{label}  ({task.estimate_days:g}d)"
        node.setText(0, label)
        status = "done" if task.is_done() else task.status
        node.setText(1, STATUS_MARKS.get(status, ""))
        node.setToolTip(1, status)

    def _refresh_row(self, task_id: TaskId) -> None:
        plan = self._deps.plan
        if self._tree is None or not plan.has(task_id):
            return
        for node in self._walk(self._tree.invisibleRootItem()):
            if str(node.data(0, _ID_ROLE)) == task_id:
                self._paint(node, plan.task(task_id))
                return

    def _on_field_changed(self, task_id: TaskId, _field: str, _origin: object) -> None:
        # A status or estimate change moves a parent's roll-up too, so repaint the whole
        # ancestry rather than the one row.
        plan = self._deps.plan
        if not plan.has(task_id):
            return
        current: Task | None = plan.task(task_id)
        while current is not None:
            self._refresh_row(current.id)
            current = current.parent

    def _restore(self, parent: QTreeWidgetItem, selected: set[str], expanded: set[str]) -> None:
        for node in _children(parent):
            task_id = str(node.data(0, _ID_ROLE))
            node.setSelected(task_id in selected)
            # A fresh plan has nothing remembered: show it open rather than collapsed.
            node.setExpanded(task_id in expanded or not expanded)
            self._restore(node, selected, expanded)

    def _walk(self, parent: QTreeWidgetItem) -> list[QTreeWidgetItem]:
        nodes = []
        for node in _children(parent):
            nodes.append(node)
            nodes.extend(self._walk(node))
        return nodes

    def _expanded_ids(self) -> set[str]:
        if self._tree is None:
            return set()
        return {
            str(node.data(0, _ID_ROLE))
            for node in self._walk(self._tree.invisibleRootItem())
            if node.isExpanded()
        }

    def _selected_ids(self) -> set[str]:
        if self._tree is None:
            return set()
        return {str(node.data(0, _ID_ROLE)) for node in self._tree.selectedItems()}

    def _publish_selection(self) -> None:
        # Strings, not objects: the context is data, so an action's state callback can be
        # tested by constructing one.
        nodes = tuple(
            ContextNode(selection_uri(ENTITY_KIND, task_id)) for task_id in self._selected_ids()
        )
        self._deps.context.set_scope(SCOPE_SELECTION, nodes)

    # -- verbs ---------------------------------------------------------------------------------

    def _register_actions(self) -> None:
        deps = self._deps

        def on_task(context: Context) -> ActionState:
            task_id = context.focus_entity(ENTITY_KIND)
            if task_id is None or not deps.plan.has(task_id):
                return HIDDEN
            return ENABLED

        def not_root(context: Context) -> ActionState:
            state = on_task(context)
            if not state.enabled:
                return state
            task_id = context.focus_entity(ENTITY_KIND)
            # The root is the project itself; deleting it is not a thing you can want.
            return DISABLED if task_id == deps.plan.root.id else ENABLED

        def is_leaf(context: Context) -> ActionState:
            """Status belongs to work, not to phases: a phase's is derived from its children."""
            state = on_task(context)
            if not state.enabled:
                return state
            task_id = context.focus_entity(ENTITY_KIND)
            assert task_id is not None
            return DISABLED if deps.plan.task(task_id).has_children() else ENABLED

        def run_new(context: Context) -> None:
            focus = context.focus_entity(ENTITY_KIND)
            parent_id = focus if focus and deps.plan.has(focus) else deps.plan.root.id
            deps.undo.push(AddTaskCommand(parent_id, Task(title="New task")))

        def run_delete(context: Context) -> None:
            task_id = context.focus_entity(ENTITY_KIND)
            if task_id is None or task_id == deps.plan.root.id:
                return  # The state gate already prevents this; stay honest anyway.
            task = deps.plan.task(task_id)
            what = task.title or "this task"
            under = sum(1 for _ in task.walk()) - 1
            question = (
                f"Delete “{what}”?"
                if not under
                else (f"Delete “{what}” and the {under} task{'s' if under != 1 else ''} under it?")
            )
            if confirm(deps.parent, "Delete Task", question):
                deps.undo.push(RemoveTaskCommand(task_id))

        def run_rename(context: Context) -> None:
            task_id = context.focus_entity(ENTITY_KIND)
            if task_id is None:
                return
            current = deps.plan.task(task_id).title
            title, accepted = QInputDialog.getText(deps.parent, "Rename", "Title:", text=current)
            if accepted and title.strip() != current:
                deps.undo.push(SetTitleCommand(task_id, title.strip()))

        def run_toggle_done(context: Context) -> None:
            task_id = context.focus_entity(ENTITY_KIND)
            if task_id is None:
                return
            task = deps.plan.task(task_id)
            if task.has_children():
                return
            deps.undo.push(
                SetFieldCommand(task_id, "status", "todo" if task.status == "done" else "done")
            )

        def done_state(context: Context) -> ActionState:
            state = is_leaf(context)
            if not state.enabled:
                return state
            task_id = context.focus_entity(ENTITY_KIND)
            assert task_id is not None
            return ActionState(checked=deps.plan.task(task_id).status == "done")

        deps.actions.register(
            ActionSpec(
                id=f"{MODULE_ID}.new",
                label="&New Task",
                menu=TASK_MENU,
                group="edit",
                order=10,
                shortcut="Ctrl+N",
                tip="Add a task inside the selected one",
                run=run_new,
            )
        )
        deps.actions.register(
            ActionSpec(
                id=f"{MODULE_ID}.rename",
                label="&Rename…",
                menu=TASK_MENU,
                group="edit",
                order=20,
                shortcut="F2",
                tip="Change this task's title",
                state=on_task,
                run=run_rename,
            )
        )
        deps.actions.register(
            ActionSpec(
                id=f"{MODULE_ID}.delete",
                label="&Delete",
                menu=TASK_MENU,
                group="edit",
                order=30,
                tip="Delete this task and everything under it",
                state=not_root,
                run=run_delete,
            )
        )
        deps.actions.register(
            ActionSpec(
                id=f"{MODULE_ID}.toggle_done",
                label="Mark &Done",
                menu=TASK_MENU,
                group="status",
                order=10,
                shortcut="Ctrl+D",
                tip="Mark this task done, or put it back",
                state=done_state,
                run=run_toggle_done,
            )
        )
        for offset, status in enumerate(STATUSES):
            deps.actions.register(
                ActionSpec(
                    id=f"{MODULE_ID}.status_{status}",
                    label=status.capitalize(),
                    menu=TASK_MENU,
                    group="status",
                    order=20 + offset,
                    submenu="Status",
                    tip=f"Set this task to {status}",
                    state=self._status_state(status),
                    run=self._set_status(status),
                )
            )
        deps.actions.register(
            ActionSpec(
                id=f"{MODULE_ID}.open",
                label="&Open",
                menu=TASK_MENU,
                group="open",
                order=10,
                tip="Open this task in a tab",
                state=on_task,
                run=lambda context: self._open(context),
            )
        )

    def _status_state(self, status: str) -> Callable[[Context], ActionState]:
        deps = self._deps

        def state(context: Context) -> ActionState:
            task_id = context.focus_entity(ENTITY_KIND)
            if task_id is None or not deps.plan.has(task_id):
                return HIDDEN
            task = deps.plan.task(task_id)
            if task.has_children():
                return DISABLED
            return ActionState(checked=task.status == status)

        return state

    def _set_status(self, status: str) -> Callable[[Context], None]:
        deps = self._deps

        def run(context: Context) -> None:
            task_id = context.focus_entity(ENTITY_KIND)
            if task_id is not None and not deps.plan.task(task_id).has_children():
                deps.undo.push(SetFieldCommand(task_id, "status", status))

        return run

    def _open(self, context: Context) -> None:
        task_id = context.focus_entity(ENTITY_KIND)
        if task_id is not None:
            self._deps.open_task(task_id)


def _children(parent: QTreeWidgetItem) -> list[QTreeWidgetItem]:
    """``parent``'s children. Qt types ``child()`` as optional; by index it never is."""
    return [node for index in range(parent.childCount()) if (node := parent.child(index))]
