"""The Features panel: the project's catalogue, and the drag that places one on the graph.

One row per record, saying plainly whether it is placed — and on which step — or not.
An unplaced row is a drag source: it travels as :data:`FEATURE_MIME` and the project
editor's canvas turns the drop into the step that realises it. A placed row is drawn
muted and does not drag, because a feature is implemented once.

The panel is a :class:`ContextPanel` on the focused project. Its buttons run the
``feature.*`` verbs against a context the panel builds itself — the ``TogglesDialog``
idiom — because the row a person picked here is the panel's own selection, not the
window's.
"""

from collections.abc import Callable, Sequence
from functools import partial

from PySide6.QtCore import QMimeData, QSize, Qt
from PySide6.QtGui import QAction, QColor, QIcon
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.model import Library, NodeId, Step
from dplanner.domain.store import FilesFor
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import (
    SCOPE_ACTIVITY,
    SCOPE_SELECTION,
    Context,
    ContextNode,
    activity_uri,
    entity_uri,
    selection_uri,
)
from dplanner.framework.debounce import Debounced, DebounceService
from dplanner.framework.list_rows import DETAIL_ROLE, MUTED_ROLE, TwoLineDelegate
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.toolbar import Toolbar, action_words
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import EmptyState
from dplanner.modules.feature.aspect import MODULE_ID
from dplanner.modules.feature.catalogue import (
    FEATURE_MIME,
    FeatureRecord,
    drag_payload,
    instance_of,
    read_catalogue,
    summary_line,
)
from dplanner.modules.feature.editor import DigestOf, FeatureEditor
from dplanner.theme.icons import (
    ICON_SIZE,
    edit_icon,
    graph_icon,
    layers_icon,
    plus_icon,
    trash_icon,
)
from dplanner.theme.tokens import DIALOG_MARGIN, PANEL_MARGIN, SECTION_GAP

# The selection-URI kind the panel's own context carries: "<project id>:<feature id>".
FEATURE_ENTITY = "feature"
PANEL_KIND = "features"
ID_ROLE = int(Qt.ItemDataRole.UserRole) + 1

DIALOG_WIDTH = 640
DIALOG_HEIGHT = 560

TOOLBAR_ACTIONS = ("feature.add", "feature.edit", "feature.remove", "feature.reveal")
ICONS: dict[str, Callable[[QColor], QIcon]] = {
    "feature.add": plus_icon,
    "feature.edit": edit_icon,
    "feature.remove": trash_icon,
    "feature.reveal": graph_icon,
}


def feature_ref(project_id: NodeId, feature_id: str) -> str:
    return f"{project_id}:{feature_id}"


def parse_feature_ref(ref: str) -> tuple[str, str] | None:
    project_id, colon, feature_id = ref.partition(":")
    return (project_id, feature_id) if colon and project_id and feature_id else None


def panel_context(project_id: NodeId, feature_id: str | None) -> Context:
    """The context the panel's verbs read: the project as the activity's entity, and the
    picked row as the selection. What a menu-bar copy of the same verb reads is the
    window's context, where no feature is ever selected — so those stay greyed, and say so."""
    nodes: tuple[ContextNode, ...] = ()
    if feature_id is not None:
        nodes = (ContextNode(selection_uri(FEATURE_ENTITY, feature_ref(project_id, feature_id))),)
    return Context(
        {
            SCOPE_ACTIVITY: (
                ContextNode(
                    activity_uri(PANEL_KIND, project_id),
                    (("entity", entity_uri("project", project_id)),),
                ),
            ),
            SCOPE_SELECTION: nodes,
        }
    )


class _FeatureList(QListWidget):
    """The rows, and the drag: an unplaced feature leaves as its id and its project's."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        # Two lines per row, the glyph on the first — the row every rich list here draws.
        self.setItemDelegate(TwoLineDelegate(self))
        self.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.setObjectName("PanelList")
        self.project_id: NodeId | None = None

    def mimeData(self, items: Sequence[QListWidgetItem]) -> QMimeData:  # noqa: N802 - Qt override
        data = QMimeData()
        if self.project_id is None or not items:
            return data
        feature_id = items[0].data(ID_ROLE)
        data.setData(FEATURE_MIME, drag_payload(self.project_id, feature_id))
        data.setText(items[0].text())
        return data


class FeatureDialog(QDialog):
    """One record, front and centre. Whoever opens it owes it a ``dispose()``."""

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        files: FilesFor,
        documents_of: Callable[[NodeId], list[str]],
        project_id: NodeId,
        feature_id: str,
        parent: QWidget | None = None,
        *,
        digest_of: DigestOf | None = None,
    ) -> None:
        super().__init__(parent)
        record = next(
            (r for r in read_catalogue(library.project(project_id)) if r.id == feature_id), None
        )
        self.setWindowTitle(f"Feature {feature_id}" + (f" — {record.title}" if record else ""))
        self.editor = FeatureEditor(library, undo, files, documents_of, self, digest_of=digest_of)
        self.editor.show_record(project_id, feature_id)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN)
        layout.setSpacing(SECTION_GAP)
        layout.addWidget(self.editor, 1)
        layout.addWidget(buttons)
        self.resize(DIALOG_WIDTH, DIALOG_HEIGHT)

    def dispose(self) -> None:
        self.editor.title.clearFocus()
        self.editor.dispose()


class FeaturesPanel(QWidget):
    """The focused project's features, placed or not, and the buttons that act on one."""

    def __init__(
        self,
        library: Library,
        actions: ActionRegistry,
        theme: ThemeService,
        parent: QWidget | None = None,
        *,
        debounce: DebounceService | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("InspectorPanel")
        self._library = library
        # After a quiet spell, not per signal: the list is rebuilt with painted icons.
        self._refresh_soon = Debounced(self._refresh, parent=self, service=debounce)
        self._actions = actions
        self._theme = theme
        self._project_id: NodeId | None = None

        self.list = _FeatureList(self)
        self.list.currentItemChanged.connect(lambda *_a: self._refresh_buttons())
        self.list.itemDoubleClicked.connect(lambda _item: self._run("feature.edit"))

        # A strip of verbs: glyphs with their words in the tooltip, folding into a … menu
        # when the panel is dragged narrow (DESIGN.md's *Toolbars*). The verbs run against
        # the panel's *own* context, so this is `add_verb` and not the registry feed —
        # the row a person picked here is the panel's selection, not the window's.
        self.tools = Toolbar(self)
        self.verbs: dict[str, QAction] = {
            action_id: self.tools.add_verb(
                actions.spec(action_id).label.replace("&", ""),
                ICONS[action_id],
                partial(self._run, action_id),
                tip=actions.spec(action_id).tip,
            )
            for action_id in TOOLBAR_ACTIONS
        }

        # A catalogue with nothing in it says so, and offers the one verb that fills it.
        self.empty = EmptyState(
            parent=self,
            action=("Add Feature…", lambda: self._run("feature.add")),
            stands_in_for=self.list,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(SECTION_GAP)
        layout.addWidget(self.tools)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.empty, 1)

        self._unsubscribes = [
            library.module_data_changed.connect(self._on_module_data),
            library.structure_changed.connect(self._on_project_change),
            library.field_changed.connect(self._on_project_change),
            # Icons and row inks are copied colours, so a theme change owes a repaint.
            theme.changed.connect(lambda _theme: self._paint()),
        ]
        self._paint()

    # -- the ContextPanel contract -----------------------------------------------------------

    def show_context(self, context: Context) -> bool:
        """The focused project — the graph tab's, or the selected step's."""
        project_id = context.focus_entity("project")
        if project_id is None:
            step_id = context.focus_entity("step")
            if step_id is not None and self._library.has(step_id):
                project_id = self._library.project_of(step_id).id
        if project_id is None or not self._library.has(project_id):
            self._set_project(None)
            return False
        self._set_project(project_id)
        return True

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    # -- what is shown -----------------------------------------------------------------------

    def current_project_id(self) -> NodeId | None:
        return self._project_id

    def selected_feature_id(self) -> str | None:
        item = self.list.currentItem()
        feature_id = item.data(ID_ROLE) if item is not None else None
        return feature_id if isinstance(feature_id, str) else None

    def select_feature(self, feature_id: str) -> None:
        for row in range(self.list.count()):
            if self.list.item(row).data(ID_ROLE) == feature_id:
                self.list.setCurrentRow(row)
                return

    def context(self) -> Context:
        """The context the panel's verbs read — its project and its picked row."""
        assert self._project_id is not None
        return panel_context(self._project_id, self.selected_feature_id())

    def _set_project(self, project_id: NodeId | None) -> None:
        if project_id == self._project_id:
            return
        self._project_id = project_id
        self.list.project_id = project_id
        self._refresh()

    def _paint(self) -> None:
        """The rows carry copied colours, so a theme change owes them a rebuild. The
        strip's own glyphs re-ink themselves on the palette change."""
        self._refresh()

    def _refresh(self) -> None:
        keep = self.selected_feature_id()
        self.list.blockSignals(True)
        self.list.clear()
        if self._project_id is not None and self._library.has(self._project_id):
            project = self._library.project(self._project_id)
            for record in read_catalogue(project):
                self.list.addItem(self._row(record, instance_of(project, record.id)))
                if record.id == keep:
                    self.list.setCurrentRow(self.list.count() - 1)
        self.list.blockSignals(False)
        self.empty.say("" if self.list.count() else "No features in this project's catalogue.")
        self._refresh_buttons()

    def _row(self, record: FeatureRecord, instance: Step | None) -> QListWidgetItem:
        """Two lines: the feature's name, and what became of it under it.

        DESIGN.md's *Lists of rich items* — the *what* in primary ink, the *why* under it
        in secondary and a point smaller. It said the second line in a tooltip once, which
        is a fact nobody sees until they go looking for it. A placed feature is muted —
        dealt with — and does not drag, because a feature is implemented once.
        """
        placed = instance is not None
        ink = self._theme.current.text_primary
        item = QListWidgetItem(layers_icon(ink), record.title or record.id)
        item.setData(ID_ROLE, record.id)
        item.setData(DETAIL_ROLE, summary_line(record, instance))
        if placed:
            item.setData(MUTED_ROLE, True)
        else:
            item.setToolTip("Drag onto the canvas to place it")
        flags = item.flags()
        if placed:
            flags &= ~Qt.ItemFlag.ItemIsDragEnabled
        item.setFlags(flags)
        return item

    def _refresh_buttons(self) -> None:
        """What each verb says right now — greyed with its reason, never dropped."""
        if self._project_id is None:
            for verb in self.verbs.values():
                verb.setEnabled(False)
            return
        context = self.context()
        for action_id, verb in self.verbs.items():
            spec = self._actions.spec(action_id)
            state = spec.state(context)
            verb.setEnabled(state.enabled)
            verb.setText(action_words(spec, state)[0])

    def _run(self, action_id: str) -> None:
        if self._project_id is None:
            return
        self._actions.run(action_id, self.context())

    def _on_module_data(self, _node_id: NodeId, module_id: str, _origin: object) -> None:
        if module_id == MODULE_ID:
            self._refresh_soon.trigger()

    def _on_project_change(self, node_id: NodeId, *_rest: object) -> None:
        """A step added, removed or retitled — in the project on show, or not at all."""
        if self._project_id is not None and self._library.belongs_to(node_id, self._project_id):
            self._refresh_soon.trigger()
