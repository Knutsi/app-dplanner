"""The Specs tab: one project's documents on the left, the chosen one beside — a PDF
rendered, plain text shown, markdown open for editing.

The list and the viewers are dumb: everything they show comes from :mod:`.documents`, the
same functions the CLI answers with, and every change arrives back through the model's
``module_data_changed`` — the tab never assumes it caused what it sees.
"""

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.cli.command import CliError
from dplanner.core.anchors import locate
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.fields import ModuleTextField
from dplanner.domain.model import Library, NodeId, Project, TextEdit
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
from dplanner.framework.list_rows import DETAIL_ROLE, EMPHASIS_ROLE, RULE_ROLE, TwoLineDelegate
from dplanner.framework.markdown_view import MarkdownView
from dplanner.framework.prose_section import ProseSection
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.toolbar import ActionToolbar
from dplanner.framework.undo import UndoService
from dplanner.modules.spec.aspect import MODULE_ID, read_topology
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
from dplanner.theme.icons import (
    external_icon,
    folder_icon,
    graph_icon,
    plus_icon,
    read_icon,
    spec_icon,
    trash_icon,
)

SPECS_KIND = "specs"

# The selection-URI kind this tab publishes while it is the active pane.
DOCUMENT_ENTITY = "spec_document"

TOOLBAR_ACTIONS = ("spec.new", "spec.add", "spec.remove", "spec.open_external")
BUTTON_TEXT = dict.fromkeys(TOOLBAR_ACTIONS, "")  # Glyph-only; label → tooltip.
ICONS: dict[str, Callable[[str], QIcon]] = {
    "spec.new": plus_icon,
    "spec.add": folder_icon,
    "spec.remove": trash_icon,
    "spec.open_external": external_icon,
}

PANEL_MARGIN = 16
CAPTION_GAP = 6
BLOCK_GAP = 12
STRIP_MARGIN = 8  # DESIGN.md's 4-point scale: a toolbar strip breathes at 8.

NAME_ROLE = int(Qt.ItemDataRole.UserRole) + 1

# A cited passage is washed in the accent at low alpha — DESIGN.md's exception #2 — and
# the one somebody jumped to a little stronger, so the eye lands on it among the others.
WASH_ALPHA = 60
FOCUS_ALPHA = 110

# (project, document) → the passages features cite from it; (project, document, quote)
# → show that passage in the coverage view; (project, document, quote, page) → cite the
# selection. All three are other modules' business and arrive from the composition root;
# None means the capability is absent from this build and its button is hidden.
type PassagesOf = Callable[[NodeId, str], Sequence[str]]
type OpenCoverage = Callable[[NodeId, str, str], None]
type Cite = Callable[[NodeId, str, str, int | None], None]

# The pinned first row: the project's own account of how its graph is shaped. Not a
# document — it is the project's prose under this module's id, edited in place through
# the prose stack rather than through a document session, and never a selected
# "spec_document" (so Remove and Open Externally stay greyed on it).
TOPOLOGY_ROW = "\x00topology"
TOPOLOGY_TITLE = "Topology"
TOPOLOGY_PLACEHOLDER = (
    "How this project's graph is shaped: what counts as a feature here, what follows one "
    "(a check? a review?), where the milestones fall. An agent reads this before it "
    "adds a step."
)


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
        *,
        passages_of: PassagesOf | None = None,
        open_coverage: OpenCoverage | None = None,
        cite: Cite | None = None,
    ) -> None:
        super().__init__(context, "project", project_id)
        self._product = library
        self._passages_of = passages_of
        self._open_coverage = open_coverage
        self._cite = cite
        # What is lit: the document, its quotes, the focused one — and whether the wash is
        # every citation of the document (the Cited toggle) or a jump's few.
        self._lit: tuple[str, tuple[str, ...], str] | None = None
        self._cited_spans: list[tuple[int, int, str]] | None = None  # Lazily, per text.
        self._context = context
        self._actions = actions
        self._files = files
        self._undo = undo
        self.project_id = project_id
        self._shown: tuple[str, str] | None = None  # (name, blob) the viewer is rendering.
        # Whether the person chose the topology row while there were documents to read
        # instead: only then does a refresh keep it. Otherwise the first document leads —
        # the topology leads by itself only while there is nothing else to read.
        self._topology_chosen = False

        # The editing session: which document, the record current when editing began (what
        # `previous` stays pinned to), the record as this session last wrote it, and the
        # intermediate blobs the session itself created — the only blobs it may prune.
        self._editing: str | None = None
        self._session_base: SpecDocument | None = None
        self._session_last: SpecDocument | None = None
        self._session_blobs: set[str] = set()
        self._edit_origin = object()

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
        self.list.setItemDelegate(TwoLineDelegate(self.list))
        self.list.currentItemChanged.connect(lambda *_a: self._on_selection())
        side_layout.addWidget(self.list, 1)

        reader = QWidget(splitter)
        reader_layout = QVBoxLayout(reader)
        reader_layout.setContentsMargins(0, 0, 0, 0)
        reader_layout.setSpacing(0)
        self._views = QStackedWidget(reader)
        self._notice = QLabel(self._views)
        self._notice.setObjectName("InspectorNote")
        self._notice.setWordWrap(True)
        self._notice.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._notice.setContentsMargins(BLOCK_GAP, BLOCK_GAP, BLOCK_GAP, BLOCK_GAP)
        self._text = MarkdownView(self._views)
        self._pdf = PdfPageView(self._views)
        self._editor = SpecMarkdownEditor()
        # The model autosave's rhythm: a pause in typing is when the session flushes. The
        # timer is the editor's child, so it dies with the editor: a build discarded with
        # the timer armed (a test's teardown never closes a tab) used to fire it into a
        # deleted editor a second later, from whatever ran next in the process.
        self._flush_timer = QTimer(self._editor, interval=FLUSH_DELAY_MS, singleShot=True)
        self._flush_timer.timeout.connect(self._flush_edit)
        self._editor.textChanged.connect(self._on_typed)
        self._editor_page = self._build_editor_page()
        self._topology_page = self._build_topology_page(library, undo, project_id)
        self._views.addWidget(self._notice)
        self._views.addWidget(self._text)
        self._views.addWidget(self._pdf)
        self._views.addWidget(self._editor_page)
        self._views.addWidget(self._topology_page)
        self._editor.cursorPositionChanged.connect(self._refresh_strip)
        self._editor.selectionChanged.connect(self._refresh_strip)
        self._editor.textChanged.connect(self._forget_spans)
        self._text.selectionChanged.connect(self._refresh_strip)
        self._text.cursorPositionChanged.connect(self._refresh_strip)
        reader_layout.addWidget(self._build_document_strip(reader))
        reader_layout.addWidget(self._views, 1)

        splitter.addWidget(side)
        splitter.addWidget(reader)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)

        self._widget = page
        # No `field_changed` subscription: nothing here reads a field — the list shows
        # index data, and retitling the tab is `SpecModule._retitle_tabs`'s job.
        self._theme = theme
        self._unsubscribes = [
            library.module_data_changed.connect(self._on_module_data),
            library.text_edited.connect(self._on_text_edited),
            theme.changed.connect(lambda _theme: self._paint_toolbar(theme)),
            # The rows carry ink-coloured icons, which a copied colour would leave stale.
            theme.changed.connect(lambda _theme: self._refresh()),
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
        edges: tuple[tuple[str, Uri], ...] = (("entity", entity_uri("project", self.project_id)),)
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
        self.end_session()
        self._flush_timer.stop()  # Nothing fires between close and the widget's deletion.
        self.topology.dispose()
        self.toolbar.dispose()
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self._pdf.clear()

    # -- the editing session -------------------------------------------------------------------
    # A markdown document is never *viewed*: selecting it opens the editor, and the session
    # — one replace, `previous` pinned to the record as it was when the row was picked —
    # runs until another row is picked or the tab closes. Typing flushes on the autosave
    # rhythm, so nothing waits for a Done that no longer exists.

    @property
    def is_editing(self) -> bool:
        """Whether a markdown document is open in the editor — a session is running."""
        return self._editing is not None

    def select_document(self, name: str) -> None:
        for row in range(self.list.count()):
            if self.list.item(row).data(NAME_ROLE) == name:
                self.list.setCurrentRow(row)
                return

    def _open_session(self, document: SpecDocument, area: ModuleFileArea, data: bytes) -> None:
        """Show ``document`` in the editor, starting its session."""
        body = data.decode("utf-8")
        self._editing = document.name
        self._session_base = document
        self._session_last = document
        self._session_blobs = set()
        self._editor.open_markdown(area, body)
        self._forget_spans()
        # Qt normalises the markdown it writes; say so up front when it would matter,
        # rather than letting the first save silently reformat an imported document.
        self._editor_note.setVisible(self._editor.body().strip() != body.strip())
        self._views.setCurrentWidget(self._editor_page)

    def focus_editor(self) -> None:
        """Put the caret in the open document — what a freshly created one wants."""
        if self.is_editing:
            self._editor.setFocus()

    def end_session(self) -> None:
        """Flush what the session typed and forget it — another row was picked, or the
        tab is closing. The next markdown row opens a session of its own."""
        if not self.is_editing:
            return
        # The tab stops being an editor *before* the flush: the flush's own echo re-enters
        # `_on_selection`, and this is what keeps that echo from ending the session twice.
        self._editing = None
        self._flush_edit()
        self._drop_session()
        self._shown = None  # The editor page is up; whatever shows next must be rendered.

    def _drop_session(self) -> None:
        self._flush_timer.stop()
        self._editing = None
        self._session_base = None
        self._session_last = None
        self._session_blobs = set()

    def _abort_edit(self) -> None:
        """The model changed under the session: it is the authority, the session ends and
        the document reopens as it now is.

        Unflushed keystrokes are dropped; anything already flushed is on disk and in the
        index history, so nothing the user saved is lost.
        """
        self._drop_session()
        self._shown = None  # Force a re-render of whatever the model now says.
        self._show_current()

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

    def _build_topology_page(
        self, library: Library, undo: UndoService[Library], project_id: NodeId
    ) -> QWidget:
        """The topology, always editable: one prose document bound through the undo stack,
        exactly as the standing agent instruction is — no session, no Done, because the
        text is the project's own and every keystroke is already one undoable edit."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(BLOCK_GAP, BLOCK_GAP, BLOCK_GAP, BLOCK_GAP)
        layout.setSpacing(CAPTION_GAP)
        note = QLabel(
            "How this project's graph is shaped. An agent must read it (`dplanner topology"
            " show`) before it edits the graph from the CLI, and again whenever it changes.",
            page,
        )
        note.setObjectName("InspectorNote")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.topology = ProseSection(
            lambda pid: ModuleTextField(library, pid, MODULE_ID),
            undo,
            placeholder=TOPOLOGY_PLACEHOLDER,
            margin=0,
            expand_title=TOPOLOGY_TITLE,
        )
        self.topology.show_target(project_id)
        layout.addWidget(self.topology, 1)
        return page

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

    def _on_text_edited(self, edit: TextEdit, _origin: object) -> None:
        # The topology row's second line says whether one has been written; the prose
        # itself reaches the editor through its own binding.
        if edit.node_id == self.project_id and edit.key == MODULE_ID:
            written = bool(read_topology(self._project()).strip())
            self.list.item(0).setData(
                DETAIL_ROLE,
                "how this project's graph is shaped" if written else "not written yet",
            )

    def _on_selection(self) -> None:
        self._topology_chosen = self._current_name() == TOPOLOGY_ROW and self.list.count() > 1
        if self.is_editing and self._current_name() != self._editing:
            self.end_session()
        if self._lit is not None and self._lit[0] != self._current_name():
            self._lit = None
        if not self.is_editing:
            self._show_current()  # Which opens a session when the row is markdown.
        self._apply_wash()
        self._publish_selection()

    def _publish_selection(self) -> None:
        name = self._current_name()
        nodes: tuple[ContextNode, ...] = ()
        if name is not None and name != TOPOLOGY_ROW:
            nodes = (ContextNode(selection_uri(DOCUMENT_ENTITY, name)),)
        self.publish_selection(nodes)

    def _refresh(self) -> None:
        if not self._product.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        keep = self._current_name()
        documents = read_index(self._project()).documents
        self.list.blockSignals(True)
        self.list.clear()
        # The topology is not one more document: it wears the graph's glyph in the accent,
        # a bold name, and a rule under it — a header over the list rather than a row in it.
        pinned = QListWidgetItem(graph_icon(self._theme.current.accent), TOPOLOGY_TITLE)
        written = bool(read_topology(self._project()).strip())
        pinned.setData(
            DETAIL_ROLE,
            "how this project's graph is shaped" if written else "not written yet",
        )
        pinned.setData(NAME_ROLE, TOPOLOGY_ROW)
        pinned.setData(EMPHASIS_ROLE, True)
        pinned.setData(RULE_ROLE, True)
        self.list.addItem(pinned)
        ink = self._theme.current.text_secondary
        if keep == TOPOLOGY_ROW and (self._topology_chosen or not documents):
            self.list.setCurrentItem(pinned)
        for doc in documents:
            page = spec_icon if doc.kind == KIND_PDF else read_icon
            item = QListWidgetItem(page(ink), doc.name)
            detail = f"{doc.kind} · imported {doc.imported}"
            if doc.previous:
                detail += " · previous kept"
            item.setData(DETAIL_ROLE, detail)
            item.setData(NAME_ROLE, doc.name)
            self.list.addItem(item)
            if doc.name == keep:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None:
            # A reader arriving lands on the first document; the topology leads only
            # while there is nothing else to read.
            self.list.setCurrentRow(1 if documents else 0)
        self.list.blockSignals(False)
        self._on_selection()

    def _current_name(self) -> str | None:
        item = self.list.currentItem()
        name = item.data(NAME_ROLE) if item is not None else None
        return name if isinstance(name, str) else None

    def _show_current(self) -> None:
        if self._current_name() == TOPOLOGY_ROW:
            if self._shown != (TOPOLOGY_ROW, ""):
                self._shown = (TOPOLOGY_ROW, "")
                self._views.setCurrentWidget(self._topology_page)
            return
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
        """A PDF renders its pages, plain text is read-only (a rich-text round-trip would
        hand it back as markdown), and markdown opens in the editor."""
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
            self._open_session(document, area, data)
            return
        self._text.show_text(body)
        self._views.setCurrentWidget(self._text)

    def _say(self, message: str) -> None:
        self._shown = None
        self._notice.setText(message)
        self._views.setCurrentWidget(self._notice)

    # -- cited passages: the wash, the strip, and the two jumps ------------------------------
    # The document strip sits above whatever is shown — the editor, a PDF, plain text — and
    # is the document's own chrome: *Cited* washes every passage a feature was read from,
    # *Show in Coverage* and *Cite…* cross to the feature side, and the count says what
    # is lit. It goes off screen on the topology row, which cites nothing.

    def show_passages(self, document: str, quotes: Sequence[str], focus: str = "") -> None:
        """Open ``document`` washed at ``quotes``, scrolled to ``focus`` — what a jump
        from the coverage view or a step's *Show Spec Passage* lands on."""
        self.select_document(document)
        if self._current_name() != document:
            return
        self._lit = (document, tuple(quotes), focus)
        self.cited.setChecked(False)
        self._apply_wash()

    def clear_passages(self) -> None:
        self._lit = None
        self.cited.setChecked(False)
        self._apply_wash()

    def lit_passages(self) -> tuple[str, ...]:
        """The quotes washed right now — a test's and the strip's one reading."""
        return self._lit[1] if self._lit is not None else ()

    def _build_document_strip(self, parent: QWidget) -> QWidget:
        strip = QWidget(parent)
        strip.setObjectName("EditorToolbar")
        row = QHBoxLayout(strip)
        row.setContentsMargins(STRIP_MARGIN, STRIP_MARGIN, STRIP_MARGIN, STRIP_MARGIN)
        row.setSpacing(6)
        self.cited = _tool_button(
            "Cited", "Wash every passage a feature was read from", self._toggle_cited
        )
        self.cited.setCheckable(True)
        row.addWidget(self.cited)
        self.to_coverage = _tool_button(
            "Coverage", "Show the passage under the caret in the coverage view", self._jump
        )
        self.to_coverage.setVisible(self._open_coverage is not None)
        row.addWidget(self.to_coverage)
        self.cite_button = _tool_button(
            "Cite…", "Cite the selection as a feature's passage", self._cite_selection
        )
        self.cite_button.setVisible(self._cite is not None)
        row.addWidget(self.cite_button)
        self.lit_note = QLabel(strip)
        self.lit_note.setObjectName("InspectorNote")
        row.addWidget(self.lit_note)
        row.addStretch(1)
        self.clear_button = _tool_button("Clear", "Clear the washed passages", self.clear_passages)
        row.addWidget(self.clear_button)
        self._strip = strip
        return strip

    def _toggle_cited(self) -> None:
        if self.cited.isChecked():
            name = self._current_name()
            quotes = self._document_passages()
            self._lit = (name, quotes, "") if name is not None else None
        else:
            self._lit = None
        self._apply_wash()

    def _document_passages(self) -> tuple[str, ...]:
        name = self._current_name()
        if self._passages_of is None or name is None or name == TOPOLOGY_ROW:
            return ()
        return tuple(self._passages_of(self.project_id, name))

    def _forget_spans(self) -> None:
        self._cited_spans = None
        self._refresh_strip()

    def _spans(self) -> list[tuple[int, int, str]]:
        """Where each cited passage sits in the shown text — computed once per text."""
        if self._cited_spans is None:
            well = self._text_well()
            found: list[tuple[int, int, str]] = []
            if well is not None:
                plain = well.document().toPlainText()
                for quote in self._document_passages():
                    span = locate(plain, quote)
                    if span is not None:
                        found.append((span[0], span[1], quote))
            self._cited_spans = found
        return self._cited_spans

    def _text_well(self) -> QTextEdit | None:
        shown = self._views.currentWidget()
        if shown is self._editor_page:
            return self._editor
        if shown is self._text:
            return self._text
        return None

    def _passage_under_caret(self) -> str | None:
        well = self._text_well()
        if well is None:
            return None
        at = well.textCursor().position()
        return next((quote for start, end, quote in self._spans() if start <= at <= end), None)

    def _refresh_strip(self) -> None:
        name = self._current_name()
        on_document = (
            name is not None and name != TOPOLOGY_ROW and self._current_document() is not None
        )
        self._strip.setVisible(on_document)
        if not on_document:
            return
        well = self._text_well()
        self.to_coverage.setEnabled(self._passage_under_caret() is not None)
        self.cite_button.setEnabled(well is not None and well.textCursor().hasSelection())
        lit = self._lit[1] if self._lit is not None else ()
        self.clear_button.setVisible(bool(lit))
        count = len(lit)
        self.lit_note.setText(f"{count} passage{'' if count == 1 else 's'} lit" if lit else "")

    def _apply_wash(self) -> None:
        """Paint the lit passages onto whatever shows the document, and scroll to the
        focused one. Selections are cursor-anchored, so they follow edits."""
        quotes = self._lit[1] if self._lit is not None else ()
        focus = self._lit[2] if self._lit is not None else ""
        well = self._text_well()
        if well is not None:
            plain = well.document().toPlainText()
            selections = []
            landing: int | None = None
            for quote in quotes:
                span = locate(plain, quote)
                if span is None:
                    continue
                is_focus = bool(focus) and quote == focus
                cursor = QTextCursor(well.document())
                cursor.setPosition(span[0])
                cursor.setPosition(span[1], QTextCursor.MoveMode.KeepAnchor)
                wash = QColor(well.palette().highlight().color())
                wash.setAlpha(FOCUS_ALPHA if is_focus else WASH_ALPHA)
                fmt = QTextCharFormat()
                fmt.setBackground(wash)
                selection = QTextEdit.ExtraSelection()
                selection.cursor = cursor
                selection.format = fmt
                selections.append(selection)
                if is_focus:
                    landing = span[0]
            well.setExtraSelections(selections)
            if landing is not None:
                cursor = QTextCursor(well.document())
                cursor.setPosition(landing)
                well.setTextCursor(cursor)
                well.ensureCursorVisible()
        elif self._views.currentWidget() is self._pdf:
            if quotes:
                self._pdf.show_quotes(quotes, focus)
            else:
                self._pdf.clear_quotes()
        self._refresh_strip()

    def _jump(self) -> None:
        quote = self._passage_under_caret()
        name = self._current_name()
        if quote is None or name is None or self._open_coverage is None:
            return
        self._open_coverage(self.project_id, name, quote)

    def _cite_selection(self) -> None:
        well = self._text_well()
        name = self._current_name()
        if well is None or name is None or self._cite is None:
            return
        quote = well.textCursor().selectedText().replace("\u2029", "\n").strip()
        if not quote:
            return
        self._cite(self.project_id, name, quote, None)
        self._forget_spans()


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
