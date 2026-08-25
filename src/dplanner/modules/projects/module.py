"""Projects: the index folder that lists them, and the tab that shows one.

One package rather than two. An index folder and a project tab always ship together and
are two views of the same thing, so splitting them would buy a cross-module callback, two
``Deps`` dataclasses, two entries in the composition root, and a reader who has to visit two
packages to understand "projects". The day something *else* renders projects, this splits —
and that is also the day a second index segment exists.

Four files, and the names say which surface each one is: ``index.py`` is the sidebar folder,
``verbs.py`` is the menu, ``steplist.py`` is the tab's list, and this file wires them up.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QLineEdit,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.commands import SetFieldCommand
from dplanner.domain.model import NodeId, Product, Project, StepId
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.activity import ActivityBase
from dplanner.framework.context import (
    SCOPE_ACTIVITY,
    ContextNode,
    ContextService,
    Uri,
    activity_uri,
    entity_uri,
)
from dplanner.framework.index_panel import IndexSegment, IndexSegmentRegistry
from dplanner.framework.tabs import TabHost
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import centered_column
from dplanner.modules.projects.index import ProjectsSegment
from dplanner.modules.projects.steplist import StepList
from dplanner.modules.projects.verbs import ProjectVerbs
from dplanner.theme.icons import container_icon

MODULE_ID = "projects"
PROJECT_KIND = "project"

# The 4-point scale from DESIGN.md: 8 px inside a section, 12 px between them.
FORM_SPACING = 8
SECTION_SPACING = 12
PAGE_MARGIN = 20
PAGE_WIDTH = 720


def _no_aspects(_step_id: StepId) -> list[str]:
    return []


@dataclass(frozen=True)
class ProjectsDeps:
    product: Product
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    undo: UndoService[Product]
    segments: IndexSegmentRegistry
    parent: QWidget
    # What the aspect modules have to say about a step, one short phrase each. Supplied by
    # the composition root: this module never learns which aspects exist, and an aspect
    # module never learns that a project tab renders it.
    step_aspects: Callable[[StepId], list[str]] = field(default=_no_aspects)


class ProjectActivity(ActivityBase):
    """One project: what it is, and the steps that deliver it."""

    def __init__(self, deps: ProjectsDeps, project_id: NodeId) -> None:
        self._deps = deps
        self._product = deps.product
        self.project_id = project_id

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        layout.setSpacing(SECTION_SPACING)

        heading = QLabel("Project")
        heading.setObjectName("InspectorCaption")
        layout.addWidget(heading)

        self._title = QLineEdit(self._project().title)
        self._title.setPlaceholderText("What this project is called")
        self._title.editingFinished.connect(lambda: self._commit("title", self._title.text()))

        self._summary = QLineEdit(self._project().summary)
        self._summary.setPlaceholderText("What it delivers, in one line")
        self._summary.editingFinished.connect(lambda: self._commit("summary", self._summary.text()))

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(FORM_SPACING)
        form.addRow("Name", self._title)
        form.addRow("Summary", self._summary)
        layout.addLayout(form)

        caption = QLabel("Steps")
        caption.setObjectName("InspectorCaption")
        layout.addWidget(caption)

        self._empty = QLabel("No steps yet. Add them with `dplanner step add`.")
        self._empty.setObjectName("InspectorNote")
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty)

        self._steps = StepList()
        layout.addWidget(self._steps, 1)

        self._widget = centered_column(page, PAGE_WIDTH)
        self._unsubscribe = [
            self._product.structure_changed.connect(lambda _id: self._refresh()),
            self._product.field_changed.connect(self._on_field),
            self._product.edges_changed.connect(lambda *_args: self._refresh()),
            self._product.module_data_changed.connect(lambda *_args: self._refresh()),
        ]
        self._refresh()

    @property
    def uri(self) -> Uri:
        return activity_uri(PROJECT_KIND, self.project_id)

    @property
    def title(self) -> str:
        return self._project().title or "Untitled project"

    @property
    def widget(self) -> QWidget:
        return self._widget

    def on_activated(self) -> None:
        self._deps.context.set_scope(
            SCOPE_ACTIVITY,
            (ContextNode(self.uri, (("entity", entity_uri("project", self.project_id)),)),),
        )

    def close(self) -> None:
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()

    def _project(self) -> Project:
        return self._product.project(self.project_id)

    def _commit(self, field_name: str, value: str) -> None:
        if value.strip() != getattr(self._project(), field_name):
            self._deps.undo.push(
                SetFieldCommand(self.project_id, field_name, value.strip(), view_origin=self)
            )

    def _on_field(self, node_id: NodeId, field_name: str, origin: object) -> None:
        if origin is self:
            return  # This widget already shows the change it made.
        if node_id == self.project_id:
            if field_name == "title":
                self._title.setText(self._project().title)
            elif field_name == "summary":
                self._summary.setText(self._project().summary)
        self._refresh()

    def _refresh(self) -> None:
        if not self._product.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        rows = [
            (step.id, step.title or "Untitled step", self._describe(step.id))
            for step in self._project().steps
        ]
        self._steps.show_steps(rows)
        self._steps.setVisible(bool(rows))
        self._empty.setVisible(not rows)

    def _describe(self, step_id: StepId) -> str:
        """Line two of a step's row: what it waits on, then what the aspects say."""
        parts = []
        waiting = self._product.requires(step_id)
        if waiting:
            parts.append("after " + ", ".join(step.title or "untitled" for step in waiting))
        parts.extend(self._deps.step_aspects(step_id))
        return " · ".join(parts)


class ProjectsModule:
    id = MODULE_ID

    def __init__(self, deps: ProjectsDeps) -> None:
        self._deps = deps

    def open(self, project_id: NodeId) -> None:
        """Show a project in a tab. Handed to the index segment as a plain function."""
        self._deps.tabs.open(PROJECT_KIND, project_id)

    def register(self) -> None:
        deps = self._deps

        def factory(target: str | None) -> ProjectActivity:
            assert target is not None
            return ProjectActivity(deps, target)

        deps.tabs.register_factory(PROJECT_KIND, factory)
        ProjectVerbs(
            product=deps.product,
            undo=deps.undo,
            parent=deps.parent,
            open_project=self.open,
        ).register_into(deps.actions)

        def segment(root: QTreeWidgetItem) -> ProjectsSegment:
            return ProjectsSegment(
                root=root,
                product=deps.product,
                context=deps.context,
                actions=deps.actions,
                open_project=self.open,
            )

        deps.segments.register(
            IndexSegment(
                id="projects",
                label="Projects",
                factory=segment,
                order=10,
                icon=container_icon,
            )
        )
        # A project that goes away takes its tab with it, and a rename reaches the tab.
        deps.product.structure_changed.connect(lambda _parent_id: self._close_orphan_tabs())
        deps.product.field_changed.connect(lambda *_args: self._retitle_tabs())

    def _project_activities(self) -> list["ProjectActivity"]:
        return [a for a in self._deps.tabs.activities() if isinstance(a, ProjectActivity)]

    def _close_orphan_tabs(self) -> None:
        for activity in self._project_activities():
            if not self._deps.product.has(activity.project_id):
                self._deps.tabs.close_activity(activity)

    def _retitle_tabs(self) -> None:
        for activity in self._project_activities():
            if self._deps.product.has(activity.project_id):
                self._deps.tabs.set_tab_title(activity, activity.title)
