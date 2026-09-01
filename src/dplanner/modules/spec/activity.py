"""The Specs tab: one project's documents on the left, the chosen one rendered beside.

The list and the viewers are dumb: everything they show comes from :mod:`.documents`, the
same functions the CLI answers with, and every change arrives back through the model's
``module_data_changed`` — the tab never assumes it caused what it sees.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.cli.command import CliError
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, NodeId, Project
from dplanner.domain.store import ModuleFileArea
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.activity import EntityActivity
from dplanner.framework.autosave import FLUSH_DELAY_MS
from dplanner.framework.context import (
    SCOPE_ACTIVITY,
    ContextNode,
    ContextService,
    Uri,
    activity_uri,
    entity_uri,
    selection_uri,
)
from dplanner.framework.markdown_view import MarkdownView
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.toolbar import ActionToolbar
from dplanner.framework.undo import UndoService
from dplanner.modules.spec.aspect import MODULE_ID
from dplanner.modules.spec.documents import (
    KIND_MARKDOWN,
    KIND_PDF,
    SpecDocument,
    prune_blob,
    read_index,
    referenced_assets,
    save_body,
    write_index,
)
from dplanner.modules.spec.editor import SpecMarkdownEditor
from dplanner.modules.spec.viewer import PdfPageView
from dplanner.theme.icons import edit_icon, external_icon, folder_icon, plus_icon, trash_icon

SPECS_KIND = "specs"

# The selection-URI kind this tab publishes while it is the active pane.
DOCUMENT_ENTITY = "spec_document"

# The activity edge published while a document is being edited — `spec.edit`'s checked
# state is a pure function of it, the same seam as the canvas's input mode.
EDITING_EDGE = "spec_edit"

TOOLBAR_ACTIONS = ("spec.new", "spec.add", "spec.edit", "spec.remove", "spec.open_external")
BUTTON_TEXT = dict.fromkeys(TOOLBAR_ACTIONS, "")  # Glyph-only; label → tooltip.
ICONS: dict[str, Callable[[str], QIcon]] = {
    "spec.new": plus_icon,
    "spec.add": folder_icon,
    "spec.edit": edit_icon,
    "spec.remove": trash_icon,
    "spec.open_external": external_icon,
}

PANEL_MARGIN = 16
CAPTION_GAP = 6
BLOCK_GAP = 12
STRIP_MARGIN = 8  # DESIGN.md's 4-point scale: a toolbar strip breathes at 8.

ROW_PADDING_V = 10
ROW_PADDING_H = 12
ROW_LINE_GAP = 4
SECONDARY_ALPHA = 160  # ~63 % — DESIGN.md's opacity-derived secondary text.

NAME_ROLE = int(Qt.ItemDataRole.UserRole) + 1
DETAIL_ROLE = int(Qt.ItemDataRole.UserRole) + 2


class _DocumentDelegate(QStyledItemDelegate):
    """Two lines per document: the name, then what kind of thing it is and when it came."""

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | Any
    ) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else None
        if style is not None:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        palette = opt.palette
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        role = palette.ColorRole.HighlightedText if selected else palette.ColorRole.Text
        primary = palette.color(role)
        secondary = palette.color(role)
        secondary.setAlpha(SECONDARY_ALPHA)

        rect = opt.rect.adjusted(ROW_PADDING_H, ROW_PADDING_V, -ROW_PADDING_H, -ROW_PADDING_V)
        metrics = opt.fontMetrics
        elide = Qt.TextElideMode.ElideRight
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        painter.save()
        painter.setPen(primary)
        painter.drawText(
            QRect(rect.left(), rect.top(), rect.width(), metrics.height()),
            align,
            metrics.elidedText(index.data(Qt.ItemDataRole.DisplayRole), elide, rect.width()),
        )
        painter.setPen(secondary)
        painter.drawText(
            QRect(
                rect.left(),
                rect.top() + metrics.height() + ROW_LINE_GAP,
                rect.width(),
                metrics.height(),
            ),
            align,
            metrics.elidedText(index.data(DETAIL_ROLE) or "", elide, rect.width()),
        )
        painter.restore()

    def sizeHint(  # noqa: N802 - Qt override
        self, option: QStyleOptionViewItem, index: QModelIndex | Any
    ) -> QSize:
        metrics = option.fontMetrics
        return QSize(0, 2 * ROW_PADDING_V + 2 * metrics.height() + ROW_LINE_GAP)


class SpecsActivity(EntityActivity):
    """One project's spec documents."""

    def __init__(
        self,
        library: Library,
        context: ContextService,
        actions: ActionRegistry,
        files: Callable[[NodeId], ModuleFileArea],
        theme: ThemeService,
        undo: UndoService[Library],
        project_id: NodeId,
    ) -> None:
        super().__init__(context, "project", project_id)
        self._product = library
        self._context = context
        self._actions = actions
        self._files = files
        self._undo = undo
        self.project_id = project_id
        self._shown: tuple[str, str] | None = None  # (name, blob) the viewer is rendering.

        # The editing session: which document, the record current when editing began (what
        # `previous` stays pinned to), the record as this session last wrote it, and the
        # intermediate blobs the session itself created — the only blobs it may prune.
        self._editing: str | None = None
        self._session_base: SpecDocument | None = None
        self._session_last: SpecDocument | None = None
        self._session_blobs: set[str] = set()
        self._edit_origin = object()
        # The model autosave's rhythm: a pause in typing is when the session flushes.
        self._flush_timer = QTimer(interval=FLUSH_DELAY_MS, singleShot=True)
        self._flush_timer.timeout.connect(self._flush_edit)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(CAPTION_GAP)

        caption = QLabel("Specs", page)
        caption.setObjectName("InspectorCaption")
        layout.addWidget(caption)

        splitter = QSplitter(Qt.Orientation.Horizontal, page)

        side = QWidget(splitter)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(BLOCK_GAP)
        self.toolbar = ActionToolbar(actions, context, TOOLBAR_ACTIONS, BUTTON_TEXT, side)
        # A trailing stretch keeps the buttons left — without it the row's spare width
        # spreads the fixed-size buttons apart (same move as CanvasToolbar's row).
        toolbar_row = QHBoxLayout()
        toolbar_row.setContentsMargins(0, 0, 0, 0)
        toolbar_row.addWidget(self.toolbar)
        toolbar_row.addStretch(1)
        side_layout.addLayout(toolbar_row)
        self.list = QListWidget(side)
        self.list.setItemDelegate(_DocumentDelegate(self.list))
        self.list.currentItemChanged.connect(lambda *_a: self._on_selection())
        side_layout.addWidget(self.list, 1)

        self._views = QStackedWidget(splitter)
        self._notice = QLabel(self._views)
        self._notice.setObjectName("InspectorNote")
        self._notice.setWordWrap(True)
        self._notice.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._notice.setContentsMargins(BLOCK_GAP, BLOCK_GAP, BLOCK_GAP, BLOCK_GAP)
        self._text = MarkdownView(self._views)
        self._pdf = PdfPageView(self._views)
        self._editor = SpecMarkdownEditor()
        self._editor.textChanged.connect(self._on_typed)
        self._editor_page = self._build_editor_page()
        self._views.addWidget(self._notice)
        self._views.addWidget(self._text)
        self._views.addWidget(self._pdf)
        self._views.addWidget(self._editor_page)

        splitter.addWidget(side)
        splitter.addWidget(self._views)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)

        self._widget = page
        # No `field_changed` subscription: nothing here reads a field — the list shows
        # index data, and retitling the tab is `SpecModule._retitle_tabs`'s job.
        self._unsubscribes = [
            library.module_data_changed.connect(self._on_module_data),
            theme.changed.connect(lambda _theme: self._paint_toolbar(theme)),
        ]
        self._paint_toolbar(theme)
        self._refresh()

    # -- the activity contract -----------------------------------------------------------------

    @property
    def uri(self) -> Uri:
        return activity_uri(SPECS_KIND, self.project_id)

    @property
    def title(self) -> str:
        return f"{self._project().title or 'Untitled project'} — Specs"

    @property
    def widget(self) -> QWidget:
        return self._widget

    def activity_nodes(self) -> tuple[ContextNode, ...]:
        # The base's entity edge, plus — while editing — which document, so `spec.edit`'s
        # checked state stays a pure function of the context.
        edges: tuple[tuple[str, Uri], ...] = (
            ("entity", entity_uri("project", self.project_id)),
        )
        if self._editing is not None:
            edges += ((EDITING_EDGE, selection_uri(DOCUMENT_ENTITY, self._editing)),)
        return (ContextNode(self.uri, edges),)

    def on_activated(self) -> None:
        # The entity edge is what keeps the Project verbs — Add Spec Document among them —
        # live while this tab is current; the selected document rides the selection scope so
        # Remove and Open Externally stay pure functions of the context.
        super().on_activated()
        self._publish_selection()

    def on_deactivated(self) -> None:
        self._flush_edit()  # The session survives a pane switch; unsaved typing does not wait.
        super().on_deactivated()

    def close(self) -> None:
        self._flush_edit()
        self._flush_timer.stop()
        self.toolbar.dispose()
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self._pdf.clear()

    # -- the editing session -------------------------------------------------------------------

    @property
    def is_editing(self) -> bool:
        return self._editing is not None

    def select_document(self, name: str) -> None:
        for row in range(self.list.count()):
            if self.list.item(row).data(NAME_ROLE) == name:
                self.list.setCurrentRow(row)
                return

    def begin_edit(self) -> None:
        """Open the selected markdown document in the editor, starting a session."""
        document = self._current_document()
        if document is None or document.kind != KIND_MARKDOWN or self.is_editing:
            return
        area = self._files(self.project_id)
        data = area.read_bytes(document.file)
        if data is None:
            self._say(f"{document.file} is missing from the workspace.")
            return
        body = data.decode("utf-8")
        self._editing = document.name
        self._session_base = document
        self._session_last = document
        self._session_blobs = set()
        self._editor.open_markdown(area, body)
        # Qt normalises the markdown it writes; say so up front when it would matter,
        # rather than letting the first save silently reformat an imported document.
        self._editor_note.setVisible(self._editor.body().strip() != body.strip())
        self._views.setCurrentWidget(self._editor_page)
        self._editor.setFocus()
        self._publish_activity()

    def end_edit(self) -> None:
        """Flush what the session typed and return to the viewer."""
        if not self.is_editing:
            return
        # The tab stops being an editor *before* the flush: the flush's own echo re-enters
        # `_on_selection`, and this is what keeps that echo from ending the session twice.
        self._editing = None
        self._flush_edit()
        self._drop_session()
        # The render cache's early-return assumes the right widget is already up — while
        # the editor page is showing, it is not. A Done with no edits must still swap back.
        self._shown = None
        self._show_current()
        self._publish_activity()

    def _drop_session(self) -> None:
        self._flush_timer.stop()
        self._editing = None
        self._session_base = None
        self._session_last = None
        self._session_blobs = set()

    def _abort_edit(self) -> None:
        """The model changed under the session: it is the authority, the session ends.

        Unflushed keystrokes are dropped; anything already flushed is on disk and in the
        index history, so nothing the user saved is lost.
        """
        self._drop_session()
        self._shown = None  # Force the viewer to re-render whatever the model now says.
        self._show_current()
        self._publish_activity()

    def _on_typed(self) -> None:
        if self.is_editing and self._editor.document().isModified():
            self._flush_timer.start()

    def _flush_edit(self) -> None:
        if self._session_base is None or not self._editor.document().isModified():
            return
        area = self._files(self.project_id)
        index = read_index(self._project())
        today = datetime.now(UTC).date().isoformat()
        body = self._editor.body()
        try:
            docs, document, outcome, superseded = save_body(
                area, index.documents, self._session_base, body.encode(), today
            )
        except CliError:
            self._abort_edit()  # The document left the index underneath the session.
            return
        self._editor.document().setModified(False)
        if outcome == "unchanged":
            return
        if document.file != self._session_base.file:
            self._session_blobs.add(document.file)
        self._session_last = document
        # Pasted images ride the same index write, so `spec assets` sees them.
        assets = referenced_assets(index.assets, body, today)
        self._undo.push(
            SetModuleDataCommand(
                self.project_id,
                MODULE_ID,
                write_index(replace(index, documents=docs, assets=assets)),
                view_origin=self._edit_origin,
                label="Edit Spec Document",
            )
        )
        if superseded is not None and superseded in self._session_blobs:
            prune_blob(area, docs, superseded)
            self._session_blobs.discard(superseded)

    def _build_editor_page(self) -> QWidget:
        # The formatting strip is the editor's own chrome, flush on top of the text area —
        # the canvas toolbar idiom (`#EditorToolbar` shares `#CanvasToolbar`'s QSS), so it
        # cannot be read as an extension of the document list's toolbar across the splitter.
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        strip = QWidget(page)
        strip.setObjectName("EditorToolbar")
        row = QHBoxLayout(strip)
        row.setContentsMargins(STRIP_MARGIN, STRIP_MARGIN, STRIP_MARGIN, STRIP_MARGIN)
        row.setSpacing(6)
        groups: tuple[tuple[tuple[str, str, Callable[[], None]], ...], ...] = (
            (
                ("B", "Bold (Ctrl+B)", self._editor.toggle_bold),
                ("I", "Italic (Ctrl+I)", self._editor.toggle_italic),
            ),
            (
                ("H1", "Heading 1", lambda: self._editor.set_heading(1)),
                ("H2", "Heading 2", lambda: self._editor.set_heading(2)),
                ("H3", "Heading 3", lambda: self._editor.set_heading(3)),
            ),
            (
                ("•", "Bullet list", self._editor.bullet_list),
                ("1.", "Numbered list", self._editor.numbered_list),
            ),
            (
                (
                    "Image…",
                    "Insert an image at the cursor",
                    self._editor.insert_image_from_file,
                ),
            ),
        )
        for index, group in enumerate(groups):
            if index:
                rule = QWidget(strip)
                rule.setObjectName("ToolbarRule")
                rule.setFixedWidth(1)
                row.addWidget(rule)
            for face, tip, handler in group:
                row.addWidget(_tool_button(face, tip, handler))
        row.addStretch(1)
        # Done leaves through the verb, so the menu, the palette and this button agree.
        row.addWidget(
            _tool_button(
                "Done",
                "Save and return to the viewer",
                lambda: self._actions.run("spec.edit", self._context.current()),
            )
        )
        layout.addWidget(strip)
        self._editor_note = QLabel("Editing will reformat this document to Qt's markdown style.")
        self._editor_note.setObjectName("InspectorNote")
        self._editor_note.setWordWrap(True)
        self._editor_note.setVisible(False)
        layout.addWidget(self._editor_note)
        layout.addWidget(self._editor, 1)
        return page

    def _publish_activity(self) -> None:
        if self._is_active:
            self._context.set_scope(SCOPE_ACTIVITY, self.activity_nodes())

    def _current_document(self) -> SpecDocument | None:
        name = self._current_name()
        documents = read_index(self._project()).documents
        return next((doc for doc in documents if doc.name == name), None)

    # -- internals -----------------------------------------------------------------------------

    def _project(self) -> Project:
        return self._product.project(self.project_id)

    def _paint_toolbar(self, theme: ThemeService) -> None:
        colour = theme.current.text_secondary
        self.toolbar.set_button_icons({a: paint(colour) for a, paint in ICONS.items()})

    def _on_module_data(self, node_id: str, module_id: str, origin: object) -> None:
        if node_id != self.project_id or module_id != MODULE_ID:
            return
        if origin is self._edit_origin:
            self._refresh()  # Our own flush: the list re-reads, the editor is not touched.
            return
        if self.is_editing and self._current_document() != self._session_last:
            # Somebody else — undo, the CLI after a reload, another verb — changed the
            # document under the session. The model is the authority; the session ends.
            self._abort_edit()
        self._refresh()

    def _on_selection(self) -> None:
        if self.is_editing and self._current_name() != self._editing:
            self.end_edit()  # Which flushes, and re-renders the newly selected document.
        elif not self.is_editing:
            self._show_current()
        self._publish_selection()

    def _publish_selection(self) -> None:
        name = self._current_name()
        nodes = () if name is None else (ContextNode(selection_uri(DOCUMENT_ENTITY, name)),)
        self.publish_selection(nodes)

    def _refresh(self) -> None:
        if not self._product.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        keep = self._current_name()
        index = read_index(self._project())
        documents = index.documents
        marked = {
            doc.name: sum(r.document == doc.name for r in index.requirements)
            for doc in documents
        }
        self.list.blockSignals(True)
        self.list.clear()
        for doc in documents:
            item = QListWidgetItem(doc.name)
            detail = f"{doc.kind} · imported {doc.imported}"
            if marked[doc.name]:
                detail += f" · {marked[doc.name]} requirements"
            if doc.previous:
                detail += " · previous kept"
            item.setData(DETAIL_ROLE, detail)
            item.setData(NAME_ROLE, doc.name)
            self.list.addItem(item)
            if doc.name == keep:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self._on_selection()

    def _current_name(self) -> str | None:
        item = self.list.currentItem()
        name = item.data(NAME_ROLE) if item is not None else None
        return name if isinstance(name, str) else None

    def _show_current(self) -> None:
        document = self._current_document()
        if document is None:
            self._say("No spec documents yet — add one, or `dplanner spec import` from a shell.")
            return
        if self._shown == (document.name, document.file):
            return  # Already rendering this blob — a PDF rebuild would only lose the scroll.
        area = self._files(self.project_id)
        data = area.read_bytes(document.file)
        if data is None:
            self._say(f"{document.file} is missing from the workspace.")
            return
        self._show_document(document, area, data)
        self._shown = (document.name, document.file)

    def _show_document(self, document: SpecDocument, area: ModuleFileArea, data: bytes) -> None:
        if document.kind == KIND_PDF:
            self._pdf.show_pdf(data)
            self._views.setCurrentWidget(self._pdf)
            return
        try:
            body = data.decode("utf-8")
        except UnicodeDecodeError:
            self._say(f"{document.filename} is not UTF-8 text.")
            return
        if document.kind == KIND_MARKDOWN:
            self._text.show_markdown(body, (area,))
        else:
            self._text.show_text(body)
        self._views.setCurrentWidget(self._text)

    def _say(self, message: str) -> None:
        self._shown = None
        self._notice.setText(message)
        self._views.setCurrentWidget(self._notice)


def _tool_button(face: str, tip: str, handler: Callable[[], None]) -> QToolButton:
    """A quiet formatting button: text face, no focus theft — `ActionToolbar`'s recipe,
    minus the registry, because these verbs are the editor widget's own state."""
    button = QToolButton()
    button.setObjectName("ToolbarButton")
    button.setText(face)
    button.setToolTip(tip)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    button.clicked.connect(lambda _checked=False: handler())
    return button
