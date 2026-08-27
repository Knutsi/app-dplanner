"""The spec module's Qt half: the Specs tab, and the verbs that reach it.

Both actions live in the Project menu — the same precedent as the order table's "Show
Order" — so the index tree's right-click, the menu bar and the palette all speak the same
verbs, and the Specs entry row under a project renders that same menu.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import NodeId, Product
from dplanner.domain.store import ModuleFileArea
from dplanner.framework.action_registry import (
    ENABLED,
    HIDDEN,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.context import Context, ContextService
from dplanner.framework.tabs import TabHost
from dplanner.framework.undo import UndoService
from dplanner.modules.spec.activity import SPECS_KIND, SpecsActivity
from dplanner.modules.spec.aspect import DATA_FORMAT, MODULE_ID
from dplanner.modules.spec.documents import (
    binary_refusal,
    default_name,
    import_document,
    read_index,
    write_index,
)

FILE_FILTER = "Spec documents (*.pdf *.md *.markdown *.txt);;All files (*)"


@dataclass(frozen=True)
class SpecDeps:
    product: Product
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    undo: UndoService[Product]
    parent: QWidget
    # The module's file area beside any node. Wired by the composition root, which is the
    # only place that knows the concrete store.
    files: Callable[[NodeId], ModuleFileArea]


class SpecModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: SpecDeps) -> None:
        self._deps = deps

    def open(self, project_id: NodeId) -> None:
        self._deps.tabs.open(SPECS_KIND, project_id)

    def register(self) -> None:
        deps = self._deps

        def factory(target: str | None) -> SpecsActivity:
            assert target is not None
            return SpecsActivity(deps.product, deps.context, deps.actions, deps.files, target)

        deps.tabs.register_factory(SPECS_KIND, factory)
        deps.actions.register(
            ActionSpec(
                id="spec.add",
                label="&Add Spec Document…",
                menu="Project",
                group="documents",
                order=10,
                tip="Import a PDF, markdown or text document beside this project",
                state=self._on_a_project,
                run=self._add,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="spec.open",
                label="Open &Specs",
                menu="Project",
                group="open",
                order=30,
                tip="The documents this project answers to",
                state=self._on_a_project,
                run=self._open,
            )
        )
        deps.product.structure_changed.connect(lambda *_a: self._close_orphan_tabs())
        deps.product.field_changed.connect(lambda *_a: self._retitle_tabs())

    # -- actions -------------------------------------------------------------------------------

    def _on_a_project(self, context: Context) -> ActionState:
        project_id = context.focus_entity("project")
        if project_id is None or not self._deps.product.has(project_id):
            return HIDDEN
        return ENABLED

    def _open(self, context: Context) -> None:
        project_id = context.focus_entity("project")
        if project_id is not None:
            self.open(project_id)

    def _add(self, context: Context) -> None:
        project_id = context.focus_entity("project")
        if project_id is None or not self._deps.product.has(project_id):
            return
        filename, _filter = QFileDialog.getOpenFileName(
            self._deps.parent, "Add Spec Document", "", FILE_FILTER
        )
        if not filename:
            return
        source = Path(filename)
        data = source.read_bytes()
        refusal = binary_refusal(data, source.name)
        if refusal is not None:
            QMessageBox.warning(self._deps.parent, "Spec Documents", refusal)
            return

        project = self._deps.product.project(project_id)
        documents, requirements = read_index(project)
        today = datetime.now(UTC).date().isoformat()
        documents, _document, outcome = import_document(
            self._deps.files(project_id),
            documents,
            default_name(source.name),
            data,
            source.name,
            today,
        )
        if outcome != "unchanged":
            self._deps.undo.push(
                SetModuleDataCommand(project_id, MODULE_ID, write_index(documents, requirements))
            )
        self.open(project_id)

    # -- tab upkeep ----------------------------------------------------------------------------

    def _activities(self) -> list[SpecsActivity]:
        return [a for a in self._deps.tabs.activities() if isinstance(a, SpecsActivity)]

    def _close_orphan_tabs(self) -> None:
        for activity in self._activities():
            if not self._deps.product.has(activity.project_id):
                self._deps.tabs.close_activity(activity)

    def _retitle_tabs(self) -> None:
        for activity in self._activities():
            if self._deps.product.has(activity.project_id):
                self._deps.tabs.set_tab_title(activity, activity.title)
