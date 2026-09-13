"""The spec module's Qt half: the Specs tab, and the verbs that reach it.

Every verb lives in the Project menu — the same precedent as the order table's "Show
Order" — so the index tree's right-click, the menu bar and the palette all speak the same
verbs, and the Specs entry row under a project renders that same menu. The ways to *add*
a spec are one child menu, *Add Spec*: the two built-ins and one entry per document
source kind the composition root hands in, which is what the tab's + button drops down.
"""

from collections.abc import Callable, Sequence
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
from dplanner.framework.debounce import DebounceService
from dplanner.framework.inspector import InspectorSection, InspectorSectionRegistry
from dplanner.framework.tabs import TabHost
from dplanner.framework.tasks import TaskService
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import confirm
from dplanner.modules.spec.activity import (
    ADD_SUBMENU,
    DOCUMENT_ENTITY,
    SOURCE_ENTITY,
    SPECS_KIND,
    Cite,
    OpenCoverage,
    PassagesOf,
    SpecsActivity,
)
from dplanner.modules.spec.aspect import DATA_FORMAT, MODULE_ID, read_attachments
from dplanner.modules.spec.documents import (
    SpecDocument,
    SpecSource,
    binary_refusal,
    default_name,
    import_document,
    new_document,
    read_index,
    remove_document,
    write_index,
)
from dplanner.modules.spec.figures_section import FiguresSection
from dplanner.modules.spec.refresh import SourceRefresher
from dplanner.modules.spec.source_kind import DocumentSourceKind
from dplanner.modules.spec.sourced import add_source, owned_by_source, remove_source, source_of

FILE_FILTER = "Spec documents (*.pdf *.md *.markdown *.txt);;All files (*)"


def open_url(url: str) -> None:
    """Hand a URL to the browser — one seam, so a test can watch instead."""
    QDesktopServices.openUrl(QUrl(url))


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
    # The step panel's Details tab — where a step's attached figures are shown.
    details: InspectorSectionRegistry
    tasks: TaskService
    # What the tab settles its text derivations on: where a cited passage now sits, the
    # wash over it, the figures under the editor. All three walk the whole document, so
    # they wait for a pause in typing rather than running on every keystroke.
    debounce: DebounceService
    # The document source kinds this build offers — one + menu entry and one way to
    # fetch each. Named by the composition root; the module runs whatever it is given.
    kinds: Sequence[DocumentSourceKind] = ()
    # The feature side, handed across by the composition root: which passages of a
    # document features cite (the Cited wash), how to show one in the coverage view, and
    # how to cite a selection. None hides the button — the capability is absent.
    passages_of: PassagesOf | None = None
    open_coverage: OpenCoverage | None = None
    cite: Cite | None = None


class SpecModule:
    id = MODULE_ID
    data_format = DATA_FORMAT

    def __init__(self, deps: SpecDeps) -> None:
        self._deps = deps
        self._kinds = {kind.id: kind for kind in deps.kinds}
        self.refresher = SourceRefresher(
            deps.library, deps.undo, deps.tasks, deps.files, self._kinds, parent=deps.parent
        )
        for kind in deps.kinds:
            kind.config_changed.connect(deps.context.refresh)

    def open(self, project_id: NodeId, *, preview: bool = False) -> None:
        self._deps.tabs.open(SPECS_KIND, project_id, preview=preview)

    def show_passages(
        self, project_id: NodeId, document: str, quotes: Sequence[str], focus: str = ""
    ) -> None:
        """Open the Specs tab on ``document`` with ``quotes`` washed and ``focus`` in
        view — the landing for a jump from the coverage view or from a step."""
        activity = self._deps.tabs.open(SPECS_KIND, project_id)
        assert isinstance(activity, SpecsActivity)
        activity.show_passages(document, quotes, focus)

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
                debounce=deps.debounce,
                passages_of=deps.passages_of,
                open_coverage=deps.open_coverage,
                cite=deps.cite,
                kinds=self._kinds,
                refresher=self.refresher,
                connect=self._connect,
            )

        deps.tabs.register_factory(SPECS_KIND, factory)

        def has_figures(step_id: str | None) -> bool:
            if step_id is None or not deps.library.has(step_id):
                return False
            return bool(read_attachments(deps.library.step(step_id)))

        # The Details tab shows a step's figures only when it carries any — the block
        # follows the aspect the way a toggleable aspect's tab does.
        deps.details.register(
            InspectorSection(
                id=f"{MODULE_ID}.figures",
                label="Figures",
                order=30,
                shown_for=has_figures,
                factory=lambda: FiguresSection(deps.library, deps.files),
            )
        )
        deps.actions.register(
            ActionSpec(
                id="spec.new",
                label="&New Spec Document…",
                menu="Project",
                group="documents",
                order=10,
                submenu=ADD_SUBMENU,
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
                submenu=ADD_SUBMENU,
                tip="Import a PDF, markdown or text document beside this project",
                state=self._on_a_project,
                run=self._add,
            )
        )
        for position, kind in enumerate(deps.kinds):
            deps.actions.register(
                ActionSpec(
                    id=f"spec.add_source.{kind.id}",
                    label=kind.label,
                    menu="Project",
                    group="documents",
                    order=30 + position,
                    submenu=ADD_SUBMENU,
                    icon=kind.icon,
                    tip=f"Add a {kind.name} source: its documents arrive beside this project",
                    state=self._on_a_project,
                    run=self._add_source_verb(kind),
                )
            )
        deps.actions.register(
            ActionSpec(
                id="spec.remove",
                label="&Remove Spec Document",
                menu="Project",
                group="documents",
                order=40,
                tip="Remove the selected document from the index; the file stays on disk",
                state=self._on_a_removable_document,
                run=self._remove,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="spec.refresh_source",
                label="Re&fresh Source",
                menu="Project",
                group="documents",
                order=60,
                tip="Fetch the selected source again; changed documents are replaced, "
                "the previous version kept",
                state=self._refresh_state,
                run=self._refresh_source,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="spec.refresh_sources",
                label="Refresh &All Sources",
                menu="Project",
                group="documents",
                order=65,
                tip="Fetch every source of this project again, as one undo entry",
                state=self._refresh_all_state,
                run=self._refresh_all,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="spec.remove_source",
                label="Remove Sou&rce",
                menu="Project",
                group="documents",
                order=70,
                tip="Remove the selected source and every page it fetched; the files stay",
                state=self._on_a_source,
                run=self._remove_source,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="spec.open_source",
                label="Open Source in &Browser",
                menu="Project",
                group="documents",
                order=80,
                tip="Open the selected source where it lives",
                state=self._on_a_source,
                run=self._open_source,
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

    def _on_a_removable_document(self, context: Context) -> ActionState:
        found = self._selected_document(context)
        if found is None:
            return DISABLED
        owner = owned_by_source(read_index(self._deps.library.project(found[0])), found[1].name)
        if owner is not None:
            return ActionState(enabled=False, label=f"Remove Spec Document — part of {owner.title}")
        return ENABLED

    def _on_a_source(self, context: Context) -> ActionState:
        return ENABLED if self._selected_source(context) is not None else DISABLED

    def _refresh_state(self, context: Context) -> ActionState:
        found = self._selected_source(context)
        if found is None:
            return DISABLED
        status = self.refresher.status(found[0], found[1])
        if not status.ready:
            return ActionState(enabled=False, label=f"Refresh Source — {status.message}")
        if self.refresher.is_fetching():
            return ActionState(enabled=False, label="Refresh Source — fetching…")
        return ENABLED

    def _refresh_all_state(self, context: Context) -> ActionState:
        project_id = context.focus_entity("project")
        if project_id is None or not self._deps.library.has(project_id):
            return DISABLED
        if self.refresher.is_fetching():
            return ActionState(enabled=False, label="Refresh All Sources — fetching…")
        if not self.refresher.can_refresh(project_id):
            return ActionState(
                enabled=False, label="Refresh All Sources — no source is ready to fetch"
            )
        return ENABLED

    def _refresh_all(self, context: Context) -> None:
        project_id = context.focus_entity("project")
        if project_id is not None and self._deps.library.has(project_id):
            self.refresher.refresh_all(project_id)

    def _selected_source(self, context: Context) -> tuple[NodeId, SpecSource] | None:
        """The source the Specs tab has selected — a source row or a page inside one."""
        project_id = context.focus_entity("project")
        if project_id is None or not self._deps.library.has(project_id):
            return None
        source_id = context.selected_entity(SOURCE_ENTITY)
        if source_id is None:
            return None
        source = source_of(read_index(self._deps.library.project(project_id)), source_id)
        return None if source is None else (project_id, source)

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

    def _open(self, context: Context) -> None:
        project_id = context.focus_entity("project")
        if project_id is not None:
            self.open(project_id)

    def _new(self, context: Context) -> None:
        project_id = context.focus_entity("project")
        if project_id is None or not self._deps.library.has(project_id):
            return
        title, accepted = QInputDialog.getText(self._deps.parent, "New Spec Document", "Title:")
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
        activity.select_document(document.name)  # A markdown row opens in the editor.
        activity.focus_editor()

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
        documents = remove_document(index.documents, document.name)
        question = f"Remove {document.name!r}? The file stays on disk."
        if not confirm(self._deps.parent, "Remove Spec Document", question):
            return
        self._deps.undo.push(
            SetModuleDataCommand(
                project_id,
                MODULE_ID,
                write_index(replace(index, documents=documents)),
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
        open_url(QUrl.fromLocalFile(str(area.absolute(document.file))).toString())

    # -- sources -------------------------------------------------------------------------------

    def _add_source_verb(self, kind: DocumentSourceKind) -> Callable[[Context], None]:
        return lambda context: self._add_source(context, kind)

    def _add_source(self, context: Context, kind: DocumentSourceKind) -> None:
        project_id = context.focus_entity("project")
        if project_id is None or not self._deps.library.has(project_id):
            return
        located = kind.locate(self._deps.parent)
        if located is None:
            return
        title, locator = located
        index = read_index(self._deps.library.project(project_id))
        index, source = add_source(index, kind.id, title, locator)
        self._deps.undo.push(
            SetModuleDataCommand(
                project_id, MODULE_ID, write_index(index), label=f"Add {kind.name} Source"
            )
        )
        activity = self._deps.tabs.open(SPECS_KIND, project_id)
        assert isinstance(activity, SpecsActivity)
        activity.select_source(source.id)
        if self.refresher.status(project_id, source).ready:
            self.refresher.refresh(project_id, source.id)

    def _connect(self, project_id: NodeId, source_id: str) -> None:
        """The strip's one primary button: the kind's guided dialog, then the first fetch
        when the source has never had one."""
        source = source_of(read_index(self._deps.library.project(project_id)), source_id)
        kind = self._kinds.get(source.kind) if source is not None else None
        if source is None or kind is None:
            return
        if kind.connect(self._deps.parent, source.locator) and not source.fetched:
            self.refresher.refresh(project_id, source_id)

    def _refresh_source(self, context: Context) -> None:
        found = self._selected_source(context)
        if found is not None:
            self.refresher.refresh(found[0], found[1].id)

    def _remove_source(self, context: Context) -> None:
        found = self._selected_source(context)
        if found is None:
            return
        project_id, source = found
        index = read_index(self._deps.library.project(project_id))
        pages = len([doc for doc in index.documents if doc.source == source.id])
        question = (
            f"Remove {source.title!r} and the {pages} page{'' if pages == 1 else 's'} it "
            "fetched? The files stay on disk."
        )
        if not confirm(self._deps.parent, "Remove Source", question):
            return
        self._deps.undo.break_coalescing()
        self._deps.undo.push(
            SetModuleDataCommand(
                project_id,
                MODULE_ID,
                write_index(remove_source(index, source.id)),
                label="Remove Source",
            )
        )

    def _open_source(self, context: Context) -> None:
        found = self._selected_source(context)
        if found is None:
            return
        kind = self._kinds.get(found[1].kind)
        if kind is not None:
            open_url(kind.open_url(found[1].locator))
