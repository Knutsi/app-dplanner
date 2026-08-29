"""The spec module's Qt half: the Specs tab, and the verbs that reach it.

Both actions live in the Project menu — the same precedent as the order table's "Show
Order" — so the index tree's right-click, the menu bar and the palette all speak the same
verbs, and the Specs entry row under a project renders that same menu.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox, QWidget

from dplanner.cli.command import CliError
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, NodeId
from dplanner.domain.store import ModuleFileArea
from dplanner.framework.action_registry import (
    DISABLED,
    ENABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
)
from dplanner.framework.activity import follow_entity_tabs
from dplanner.framework.context import Context, ContextService
from dplanner.framework.tabs import TabHost
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import confirm
from dplanner.modules.spec.activity import (
    DOCUMENT_ENTITY,
    EDITING_EDGE,
    SPECS_KIND,
    SpecsActivity,
)
from dplanner.modules.spec.aspect import DATA_FORMAT, MODULE_ID
from dplanner.modules.spec.documents import (
    KIND_MARKDOWN,
    KIND_PDF,
    SpecDocument,
    binary_refusal,
    default_name,
    import_document,
    new_document,
    read_index,
    remove_document,
    write_index,
)

FILE_FILTER = "Spec documents (*.pdf *.md *.markdown *.txt);;All files (*)"


@dataclass(frozen=True)
class SpecDeps:
    library: Library
    actions: ActionRegistry
    context: ContextService
    tabs: TabHost
    undo: UndoService[Library]
    theme: ThemeService
    parent: QWidget
    # The module's file area beside any node. Wired by the composition root, which is the
    # only place that knows the concrete store.
    files: Callable[[NodeId], ModuleFileArea]


class SpecModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: SpecDeps) -> None:
        self._deps = deps

    def open(self, project_id: NodeId, *, preview: bool = False) -> None:
        self._deps.tabs.open(SPECS_KIND, project_id, preview=preview)

    def register(self) -> None:
        deps = self._deps

        def factory(target: str | None) -> SpecsActivity:
            assert target is not None
            return SpecsActivity(
                deps.library,
                deps.context,
                deps.actions,
                deps.files,
                deps.theme,
                deps.undo,
                target,
            )

        deps.tabs.register_factory(SPECS_KIND, factory)
        deps.actions.register(
            ActionSpec(
                id="spec.new",
                label="&New Spec Document…",
                menu="Project",
                group="documents",
                order=10,
                tip="Create a markdown document beside this project and edit it in place",
                state=self._on_a_project,
                run=self._new,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="spec.add",
                label="&Import Spec Document…",
                menu="Project",
                group="documents",
                order=20,
                tip="Import a PDF, markdown or text document beside this project",
                state=self._on_a_project,
                run=self._add,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="spec.edit",
                label="&Edit Spec Document",
                menu="Project",
                group="documents",
                order=30,
                tip="Edit the selected markdown document in place; run again to finish",
                state=self._edit_state,
                run=self._edit,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="spec.remove",
                label="&Remove Spec Document",
                menu="Project",
                group="documents",
                order=40,
                tip="Remove the selected document and its requirements; the file stays on disk",
                state=self._on_a_document,
                run=self._remove,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="spec.open_external",
                label="Open Document E&xternally",
                menu="Project",
                group="documents",
                order=50,
                tip="Open the selected spec document in the system viewer",
                state=self._on_a_document,
                run=self._open_external,
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
        follow_entity_tabs(
            deps.tabs,
            SpecsActivity,
            deps.library.has,
            closes_on=deps.library.structure_changed,
            retitles_on=deps.library.field_changed,
        )

    # -- actions -------------------------------------------------------------------------------

    def _on_a_project(self, context: Context) -> ActionState:
        project_id = context.focus_entity("project")
        if project_id is None or not self._deps.library.has(project_id):
            return DISABLED
        return ENABLED

    def _on_a_document(self, context: Context) -> ActionState:
        return ENABLED if self._selected_document(context) is not None else DISABLED

    def _selected_document(self, context: Context) -> tuple[NodeId, SpecDocument] | None:
        """The document the Specs tab has selected, resolved against its project's index."""
        project_id = context.focus_entity("project")
        if project_id is None or not self._deps.library.has(project_id):
            return None
        name = context.selected_entity(DOCUMENT_ENTITY)
        if name is None:
            return None
        documents = read_index(self._deps.library.project(project_id)).documents
        document = next((doc for doc in documents if doc.name == name), None)
        return None if document is None else (project_id, document)

    def _edit_state(self, context: Context) -> ActionState:
        found = self._selected_document(context)
        if found is None:
            return DISABLED
        _project_id, document = found
        if document.kind == KIND_PDF:
            return ActionState(enabled=False, label="Cannot Edit — PDFs are view-only")
        if document.kind != KIND_MARKDOWN:
            # Plain text through a rich-text round-trip would come back as markdown.
            return ActionState(enabled=False, label="Cannot Edit — only markdown edits in-app")
        return ActionState(checked=context.edge(EDITING_EDGE) is not None)

    def _open(self, context: Context) -> None:
        project_id = context.focus_entity("project")
        if project_id is not None:
            self.open(project_id)

    def _new(self, context: Context) -> None:
        project_id = context.focus_entity("project")
        if project_id is None or not self._deps.library.has(project_id):
            return
        title, accepted = QInputDialog.getText(
            self._deps.parent, "New Spec Document", "Title:"
        )
        if not accepted or not title.strip():
            return
        project = self._deps.library.project(project_id)
        index = read_index(project)
        today = datetime.now(UTC).date().isoformat()
        try:
            documents, document = new_document(
                self._deps.files(project_id), index.documents, title.strip(), today
            )
        except CliError as error:
            QMessageBox.warning(self._deps.parent, "Spec Documents", str(error))
            return
        self._deps.undo.push(
            SetModuleDataCommand(
                project_id,
                MODULE_ID,
                write_index(replace(index, documents=documents)),
                label="New Spec Document",
            )
        )
        activity = self._deps.tabs.open(SPECS_KIND, project_id)
        assert isinstance(activity, SpecsActivity)
        activity.select_document(document.name)
        activity.begin_edit()

    def _edit(self, context: Context) -> None:
        found = self._selected_document(context)
        if found is None:
            return  # The state gate already prevents this; stay honest anyway.
        project_id, document = found
        activity = self._deps.tabs.open(SPECS_KIND, project_id)
        assert isinstance(activity, SpecsActivity)
        activity.select_document(document.name)
        if activity.is_editing:
            activity.end_edit()
        else:
            activity.begin_edit()

    def _add(self, context: Context) -> None:
        project_id = context.focus_entity("project")
        if project_id is None or not self._deps.library.has(project_id):
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

        project = self._deps.library.project(project_id)
        index = read_index(project)
        today = datetime.now(UTC).date().isoformat()
        documents, _document, outcome = import_document(
            self._deps.files(project_id),
            index.documents,
            default_name(source.name),
            data,
            source.name,
            today,
        )
        if outcome != "unchanged":
            self._deps.undo.push(
                SetModuleDataCommand(
                    project_id, MODULE_ID, write_index(replace(index, documents=documents))
                )
            )
        self.open(project_id)

    def _remove(self, context: Context) -> None:
        found = self._selected_document(context)
        if found is None:
            return  # The state gate already prevents this; stay honest anyway.
        project_id, document = found
        index = read_index(self._deps.library.project(project_id))
        documents, requirements, dropped = remove_document(
            index.documents, index.requirements, document.name
        )
        detail = f" and its {len(dropped)} requirements" if dropped else ""
        question = f"Remove {document.name!r}{detail}? The file stays on disk."
        if not confirm(self._deps.parent, "Remove Spec Document", question):
            return
        self._deps.undo.push(
            SetModuleDataCommand(
                project_id,
                MODULE_ID,
                write_index(replace(index, documents=documents, requirements=requirements)),
                label="Remove Spec Document",
            )
        )

    def _open_external(self, context: Context) -> None:
        found = self._selected_document(context)
        if found is None:
            return  # The state gate already prevents this; stay honest anyway.
        project_id, document = found
        area = self._deps.files(project_id)
        # Existence is checked here, at run time — a state callback runs on every context
        # change and must not touch the disk.
        if area.read_bytes(document.file) is None:
            QMessageBox.warning(
                self._deps.parent,
                "Spec Documents",
                f"{document.file} is missing from the workspace.",
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(area.absolute(document.file))))
