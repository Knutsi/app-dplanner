"""The Specs tab: one project's documents on the left, the chosen one rendered beside.

The list and the viewers are dumb: everything they show comes from :mod:`.documents`, the
same functions the CLI answers with, and every change arrives back through the model's
``module_data_changed`` — the tab never assumes it caused what it sees.
"""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QIcon, QPainter
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.model import NodeId, Product, Project
from dplanner.domain.store import ModuleFileArea
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.activity import ActivityBase
from dplanner.framework.context import (
    SCOPE_ACTIVITY,
    SCOPE_SELECTION,
    ContextNode,
    ContextService,
    Uri,
    activity_uri,
    entity_uri,
    selection_uri,
)
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.toolbar import ActionToolbar
from dplanner.modules.spec.aspect import MODULE_ID
from dplanner.modules.spec.documents import (
    KIND_MARKDOWN,
    KIND_PDF,
    SpecDocument,
    read_index,
)
from dplanner.modules.spec.viewer import PdfPageView, SpecTextBrowser
from dplanner.theme.icons import external_icon, plus_icon, trash_icon

SPECS_KIND = "specs"

# The selection-URI kind this tab publishes while it is the active pane.
DOCUMENT_ENTITY = "spec_document"

TOOLBAR_ACTIONS = ("spec.add", "spec.remove", "spec.open_external")
BUTTON_TEXT = dict.fromkeys(TOOLBAR_ACTIONS, "")  # Glyph-only; label → tooltip.
ICONS: dict[str, Callable[[str], QIcon]] = {
    "spec.add": plus_icon,
    "spec.remove": trash_icon,
    "spec.open_external": external_icon,
}

PANEL_MARGIN = 16
CAPTION_GAP = 6
BLOCK_GAP = 12

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


class SpecsActivity(ActivityBase):
    """One project's spec documents."""

    def __init__(
        self,
        product: Product,
        context: ContextService,
        actions: ActionRegistry,
        files: Callable[[NodeId], ModuleFileArea],
        theme: ThemeService,
        project_id: NodeId,
    ) -> None:
        self._product = product
        self._context = context
        self._actions = actions
        self._files = files
        self.project_id = project_id
        self._is_active = False
        self._shown: tuple[str, str] | None = None  # (name, blob) the viewer is rendering.

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
        side_layout.addWidget(self.toolbar)
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
        self._text = SpecTextBrowser(self._views)
        self._pdf = PdfPageView(self._views)
        self._views.addWidget(self._notice)
        self._views.addWidget(self._text)
        self._views.addWidget(self._pdf)

        splitter.addWidget(side)
        splitter.addWidget(self._views)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)

        self._widget = page
        # No `field_changed` subscription: nothing here reads a field — the list shows
        # index data, and retitling the tab is `SpecModule._retitle_tabs`'s job.
        self._unsubscribes = [
            product.module_data_changed.connect(self._on_module_data),
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

    def on_activated(self) -> None:
        # The entity edge is what keeps the Project verbs — Add Spec Document among them —
        # live while this tab is current; the selected document rides the selection scope so
        # Remove and Open Externally stay pure functions of the context.
        self._is_active = True
        self._context.set_scope(
            SCOPE_ACTIVITY,
            (ContextNode(self.uri, (("entity", entity_uri("project", self.project_id)),)),),
        )
        self._publish_selection()

    def on_deactivated(self) -> None:
        self._is_active = False

    def close(self) -> None:
        self.toolbar.dispose()
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self._pdf.clear()

    # -- internals -----------------------------------------------------------------------------

    def _project(self) -> Project:
        return self._product.project(self.project_id)

    def _paint_toolbar(self, theme: ThemeService) -> None:
        colour = theme.current.text_secondary
        self.toolbar.set_button_icons({a: paint(colour) for a, paint in ICONS.items()})

    def _on_module_data(self, node_id: str, module_id: str, _origin: object) -> None:
        if node_id == self.project_id and module_id == MODULE_ID:
            self._refresh()

    def _on_selection(self) -> None:
        self._show_current()
        self._publish_selection()

    def _publish_selection(self) -> None:
        if not self._is_active:
            return  # See _is_active: a background pane does not speak for the user.
        name = self._current_name()
        nodes = () if name is None else (ContextNode(selection_uri(DOCUMENT_ENTITY, name)),)
        self._context.set_scope(SCOPE_SELECTION, nodes)

    def _refresh(self) -> None:
        if not self._product.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        keep = self._current_name()
        documents, requirements = read_index(self._project())
        marked = {doc.name: sum(r.document == doc.name for r in requirements) for doc in documents}
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
        name = self._current_name()
        documents, _requirements = read_index(self._project())
        document = next((doc for doc in documents if doc.name == name), None)
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
            self._text.show_markdown(area, body)
        else:
            self._text.show_text(body)
        self._views.setCurrentWidget(self._text)

    def _say(self, message: str) -> None:
        self._shown = None
        self._notice.setText(message)
        self._views.setCurrentWidget(self._notice)
