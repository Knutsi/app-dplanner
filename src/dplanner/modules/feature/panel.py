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

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QToolButton,
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
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.framework.undo_keys import install_undo_keys
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
from dplanner.theme.icons import edit_icon, graph_icon, layers_icon, plus_icon, trash_icon

# The selection-URI kind the panel's own context carries: "<project id>:<feature id>".
FEATURE_ENTITY = "feature"
PANEL_KIND = "features"
ID_ROLE = int(Qt.ItemDataRole.UserRole) + 1

PANEL_MARGIN = 16
BLOCK_GAP = 12
FIELD_GAP = 6
DIALOG_MARGIN = 20
DIALOG_WIDTH = 640
DIALOG_HEIGHT = 560

TOOLBAR_ACTIONS = ("feature.add", "feature.edit", "feature.remove", "feature.reveal")
ICONS: dict[str, Callable[[str], QIcon]] = {
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
        install_undo_keys(self, undo)
        self.editor = FeatureEditor(library, undo, files, documents_of, self, digest_of=digest_of)
        self.editor.show_record(project_id, feature_id)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN)
        layout.setSpacing(BLOCK_GAP)
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

        # Glyph-only, the label as the tooltip — the Specs tab's toolbar recipe. Words on
        # four buttons would set the panel's width, and "Reveal Feature's Step" alone is
        # wider than the Index it sits under.
        self.buttons: dict[str, QToolButton] = {}
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(FIELD_GAP)
        for action_id in TOOLBAR_ACTIONS:
            button = QToolButton(self)
            button.setObjectName("ToolbarButton")
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False, a=action_id: self._run(a))
            self.buttons[action_id] = button
            row.addWidget(button)
        row.addStretch(1)

        self.hint = QLabel(
            "Drag a feature onto the canvas to place it. A feature is implemented once: "
            "a placed one stays here, muted, with the step that realises it.",
            self,
        )
        self.hint.setObjectName("InspectorNote")
        self.hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(BLOCK_GAP)
        layout.addLayout(row)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.hint)

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
        ink = self._theme.current.text_secondary
        for action_id, button in self.buttons.items():
            button.setIcon(ICONS[action_id](ink))
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
        self.hint.setVisible(self.list.count() > 0)
        self._refresh_buttons()

    def _row(self, record: FeatureRecord, instance: Step | None) -> QListWidgetItem:
        """One line: the feature's glyph and its title. A placed one is drawn in the
        secondary tone — dealt with — and says on which step in its tooltip; an unplaced
        one is full ink, and drags."""
        placed = instance is not None
        current = self._theme.current
        ink = current.text_secondary if placed else current.text_primary
        item = QListWidgetItem(layers_icon(ink), record.title or record.id)
        item.setData(ID_ROLE, record.id)
        item.setForeground(QColor(ink))
        detail = summary_line(record, instance)
        item.setToolTip(detail if placed else f"{detail} — drag onto the canvas")
        flags = item.flags()
        if placed:
            flags &= ~Qt.ItemFlag.ItemIsDragEnabled
        item.setFlags(flags)
        return item

    def _refresh_buttons(self) -> None:
        if self._project_id is None:
            for button in self.buttons.values():
                button.setEnabled(False)
            return
        context = self.context()
        for action_id, button in self.buttons.items():
            spec = self._actions.spec(action_id)
            state = spec.state(context)
            button.setEnabled(state.enabled)
            button.setToolTip(state.label or spec.label.replace("&", ""))

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
