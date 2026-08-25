"""One tab per task: its description, with a properties panel beside it.

An :class:`Activity` is one tab's worth of behaviour, identified by a URI. Registering a
factory for a *kind* is what lets anything in the application open one — the plan tree does,
through a callback, without importing this module.

Three details worth knowing before changing this file:

- **The URI is the dedupe key.** Opening the same task twice focuses the existing tab, and
  that falls out of the URI rather than out of bookkeeping here.
- **The activity publishes its own context** in ``on_activated``, so an action that acts on
  "the current task" works whether the user picked one in the tree or simply has it open.
- **The editor never writes to the model.** It binds through a
  :class:`~dplanner.framework.text_binding.TextBinding`, so every keystroke becomes an undo
  command and every other view of the same task stays in sync.
"""

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPlainTextEdit, QSplitter, QVBoxLayout, QWidget

from dplanner.domain.fields import TaskDescriptionField
from dplanner.domain.model import Plan, TaskId
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.activity import ActivityBase
from dplanner.framework.cards import CardStack, ToolCard
from dplanner.framework.context import (
    SCOPE_ACTIVITY,
    ContextNode,
    ContextService,
    activity_uri,
    entity_uri,
)
from dplanner.framework.inspector import (
    InspectorExtension,
    InspectorSectionRegistry,
)
from dplanner.framework.tabs import TabHost
from dplanner.framework.text_binding import TextBinding
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import (
    install_ctrl_wheel_zoom,
    remember_inspector_width,
    stored_inspector_width,
)
from dplanner.framework.zoom import ZoomService

MODULE_ID = "task_editor"
TASK_KIND = "task"
ENTITY_KIND = "task"


@dataclass(frozen=True)
class TaskEditorDeps:
    plan: Plan
    context: ContextService
    actions: ActionRegistry
    tabs: TabHost
    undo: UndoService[Plan]
    zoom: ZoomService
    # The detail panel beside the editor is an extension area: this module hosts it and
    # never learns who fills it.
    sections: InspectorSectionRegistry


class TaskActivity(ActivityBase):
    """One task, open in a tab."""

    def __init__(self, task_id: TaskId, deps: TaskEditorDeps) -> None:
        self._task_id = task_id
        self._deps = deps
        self._extensions: list[InspectorExtension] = []

        editor = QPlainTextEdit()
        editor.setObjectName("TaskDescription")
        editor.setPlaceholderText("What is this task? Notes on how, and what done looks like.")
        editor.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self._editor = editor
        self._binding = TextBinding(editor, TaskDescriptionField(deps.plan, task_id), deps.undo)
        self._apply_zoom(deps.zoom.size)
        self._unsubscribes = [deps.zoom.changed.connect(self._apply_zoom)]
        install_ctrl_wheel_zoom(editor, deps.zoom.change)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(editor)
        splitter.addWidget(self._build_detail_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([600, stored_inspector_width()])
        remember_inspector_width(splitter)
        self._widget = splitter

    def _build_detail_panel(self) -> QWidget:
        panel = QWidget()
        stack = CardStack(panel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(stack)
        for section in self._deps.sections.sections():
            extension = section.factory()
            self._extensions.append(extension)
            stack.add_card(ToolCard(section.label, extension.widget))
            extension.show_target(self._task_id)
        return panel

    def _apply_zoom(self, size: float) -> None:
        font = self._editor.font()
        font.setPointSizeF(size)
        self._editor.setFont(font)

    @property
    def uri(self) -> str:
        return activity_uri(TASK_KIND, self._task_id)

    @property
    def title(self) -> str:
        return self._deps.plan.task(self._task_id).title or "Untitled"

    @property
    def widget(self) -> QWidget:
        return self._widget

    def on_activated(self) -> None:
        # The edge is what makes ``context.focus_entity()`` fall back to "the item this tab
        # is about" when nothing is selected anywhere.
        self._deps.context.set_scope(
            SCOPE_ACTIVITY,
            (ContextNode(self.uri, edges=(("entity", entity_uri(ENTITY_KIND, self._task_id)),)),),
        )

    def close(self) -> None:
        self._binding.close()
        for extension in self._extensions:
            extension.dispose()
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()


class TaskEditorModule:
    id = MODULE_ID

    def __init__(self, deps: TaskEditorDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps

        def factory(target: str | None) -> TaskActivity:
            task_id = target or deps.plan.root.id
            return TaskActivity(task_id, deps)

        deps.tabs.register_factory(TASK_KIND, factory)

        # Retitling a task retitles its tab. Cheap, and its absence is the kind of thing
        # that makes an application feel unfinished.
        deps.plan.title_changed.connect(self._retitle)

    def _retitle(self, task_id: TaskId, _origin: object) -> None:
        for activity in self._deps.tabs.activities():
            if activity.uri == activity_uri(TASK_KIND, task_id):
                self._deps.tabs.set_tab_title(activity, activity.title)

    def open(self, task_id: TaskId) -> None:
        """The capability the composition root hands to the plan tree."""
        self._deps.tabs.open(TASK_KIND, task_id)
