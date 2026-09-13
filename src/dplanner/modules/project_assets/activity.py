"""The Assets tab: everything a project's areas hold, and what still uses each file.

A master-detail over :func:`dplanner.domain.assets.catalog` — the same derivation
``dplanner asset list`` prints, computed on every refresh and never stored. The left list
groups by content name (one row however many areas carry the bytes); the right pane shows
the picture, its display name, every place it lives, and the verbs that act on it.

The tab is a *browser*: opening it writes nothing. Its two writes are explicit gestures —
renaming (a command, undoable) and deleting (straight through the file areas, not
undoable, confirmed in those words).
"""

from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt, QUrl
from PySide6.QtGui import (
    QDesktopServices,
    QGuiApplication,
    QIcon,
    QImage,
    QMouseEvent,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.assets import AssetEntry, AssetLocation, attach, catalog, prunable
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import NodeId
from dplanner.framework.activity import EntityActivity, follow_project
from dplanner.framework.context import (
    SCOPE_SELECTION,
    Context,
    ContextNode,
    Uri,
    activity_uri,
    selection_uri,
)
from dplanner.framework.debounce import Debounced
from dplanner.framework.image_preview import ImagePreviewDialog
from dplanner.framework.signalling import UpdatingIndicator
from dplanner.framework.widgets import EmptyState, confirm
from dplanner.modules.project_assets.cli import MODULE_ID, read_titles, write_titles

if TYPE_CHECKING:  # module.py imports this file, so the Deps arrive as a forward name.
    from dplanner.modules.project_assets.module import ProjectAssetsDeps

ASSETS_KIND = "assets"
NO_ASSETS = (
    "No assets yet. Paste an image into a step's description, or"
    " `dplanner describe attach <step> <file>`."
)

PANEL_MARGIN = 16
CAPTION_GAP = 6
BLOCK_GAP = 12

ROW_PADDING_V = 10
ROW_PADDING_H = 12
ROW_LINE_GAP = 4
ROW_THUMB = 40  # A recognisable glance in a list row; the pane and lightbox show more.
SECONDARY_ALPHA = 160  # ~63 % — DESIGN.md's opacity-derived secondary text.

PREVIEW_MAX = 260  # The detail pane's picture, bounded; click for the real lightbox.

# `text_edited` fires per keystroke and a catalog rescan per keystroke is waste; one
# single-shot timer coalesces every model signal into one refresh per pause.

NAME_ROLE = int(Qt.ItemDataRole.UserRole) + 1  # The entry's content name.
DETAIL_ROLE = int(Qt.ItemDataRole.UserRole) + 2  # The row's second line.
THUMB_ROLE = int(Qt.ItemDataRole.UserRole) + 3  # QPixmap | None.
KIND_ROLE = int(Qt.ItemDataRole.UserRole) + 4  # A use row's subject kind ("" = no target).
SUBJECT_ROLE = int(Qt.ItemDataRole.UserRole) + 5  # A use row's subject id.
MODULE_ROLE = int(Qt.ItemDataRole.UserRole) + 6  # A use row's owning module id.


class _AssetRowDelegate(QStyledItemDelegate):
    """A thumbnail beside two lines: the name, then who uses it — or that nobody does."""

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | Any
    ) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        opt.icon = QIcon()
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
        pixmap = index.data(THUMB_ROLE)
        text_left = rect.left()
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            drawn = pixmap.deviceIndependentSize()
            painter.drawPixmap(
                QRect(
                    rect.left(),
                    rect.top() + (rect.height() - round(drawn.height())) // 2,
                    round(drawn.width()),
                    round(drawn.height()),
                ),
                pixmap,
            )
        text_left += ROW_THUMB + BLOCK_GAP  # Align text whether or not a thumbnail drew.

        metrics = opt.fontMetrics
        elide = Qt.TextElideMode.ElideRight
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        width = rect.right() - text_left
        lines_top = rect.top() + (rect.height() - 2 * metrics.height() - ROW_LINE_GAP) // 2
        painter.save()
        painter.setPen(primary)
        painter.drawText(
            QRect(text_left, lines_top, width, metrics.height()),
            align,
            metrics.elidedText(index.data(Qt.ItemDataRole.DisplayRole), elide, width),
        )
        painter.setPen(secondary)
        painter.drawText(
            QRect(text_left, lines_top + metrics.height() + ROW_LINE_GAP, width, metrics.height()),
            align,
            metrics.elidedText(index.data(DETAIL_ROLE) or "", elide, width),
        )
        painter.restore()

    def sizeHint(  # noqa: N802 - Qt override
        self, option: QStyleOptionViewItem, index: QModelIndex | Any
    ) -> QSize:
        metrics = option.fontMetrics
        lines = 2 * metrics.height() + ROW_LINE_GAP
        return QSize(0, 2 * ROW_PADDING_V + max(lines, ROW_THUMB))


class _PreviewLabel(QLabel):
    """The detail pane's picture; clicking opens the real lightbox."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view: Any = None  # Set by the activity: () -> None.

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton and self.view is not None:
            self.view()
        super().mousePressEvent(event)


class AssetsActivity(EntityActivity):
    """One project's assets: the catalog rendered, with rename, open and sweep."""

    def __init__(self, deps: "ProjectAssetsDeps", project_id: NodeId) -> None:
        super().__init__(deps.context, "project", project_id)
        self._deps = deps
        self.project_id = project_id
        self._entries: list[AssetEntry] = []
        self._shown: AssetEntry | None = None
        self._thumbs: dict[str, tuple[float, QPixmap | None]] = {}

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(CAPTION_GAP)

        caption = QLabel("Assets", page)
        caption.setObjectName("InspectorCaption")
        layout.addWidget(caption)

        self.lead = QLabel(page)
        font = self.lead.font()
        font.setPointSize(font.pointSize() + 2)  # Emphasis by size, never bold (DESIGN.md).
        self.lead.setFont(font)
        layout.addWidget(self.lead)
        layout.addSpacing(BLOCK_GAP - CAPTION_GAP)

        controls = QHBoxLayout()
        controls.setSpacing(BLOCK_GAP)
        self.source_filter = QComboBox(page)
        self.source_filter.currentIndexChanged.connect(lambda _i: self._rebuild_list())
        controls.addWidget(self.source_filter)
        self.unused_only = QCheckBox("Unused only", page)
        self.unused_only.toggled.connect(lambda _on: self._rebuild_list())
        controls.addWidget(self.unused_only)
        controls.addStretch(1)
        self.attach_button = QPushButton("Attach to Pool…", page)
        self.attach_button.clicked.connect(self._attach_to_pool)
        controls.addWidget(self.attach_button)
        self.sweep_button = QPushButton("Clean Up Unused…", page)
        self.sweep_button.clicked.connect(self._sweep)
        controls.addWidget(self.sweep_button)
        self.updating = UpdatingIndicator(page)
        controls.addWidget(self.updating)
        layout.addLayout(controls)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, page)
        self.list = QListWidget(self.splitter)
        self.list.setItemDelegate(_AssetRowDelegate(self.list))
        self.list.currentItemChanged.connect(lambda *_a: self._on_selection())

        detail = QWidget(self.splitter)
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(BLOCK_GAP, 0, 0, 0)
        detail_layout.setSpacing(BLOCK_GAP)
        self.preview = _PreviewLabel(detail)
        self.preview.view = self._view_shown
        detail_layout.addWidget(self.preview)
        self.name_edit = QLineEdit(detail)
        self.name_edit.setPlaceholderText("Display name")
        self.name_edit.editingFinished.connect(self._rename)
        detail_layout.addWidget(self.name_edit)
        self.uses = QListWidget(detail)
        self.uses.setItemDelegate(_AssetRowDelegate(self.uses))
        self.uses.itemActivated.connect(self._navigate)
        detail_layout.addWidget(self.uses, 1)
        buttons = QHBoxLayout()
        buttons.setSpacing(BLOCK_GAP)
        self.open_button = QPushButton("Open Externally", detail)
        self.open_button.clicked.connect(self._open_externally)
        buttons.addWidget(self.open_button)
        self.copy_button = QPushButton("Copy Path", detail)
        self.copy_button.clicked.connect(self._copy_path)
        buttons.addWidget(self.copy_button)
        self.delete_button = QPushButton("Delete", detail)
        self.delete_button.clicked.connect(self._delete)
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)
        detail_layout.addLayout(buttons)

        self.splitter.addWidget(self.list)
        self.splitter.addWidget(detail)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)
        layout.addWidget(self.splitter, 1)

        # A tab cannot go off screen the way a panel does, so it says so in words.
        self.empty = EmptyState(NO_ASSETS, page, stands_in_for=self.splitter)
        layout.addWidget(self.empty, 1)

        self._widget = page
        # Parented to the page: a discarded build deletes the widget tree, and a pending
        # tick on an orphan timer would fire into deleted labels afterwards. Coalesced,
        # because a catalog walk lists directories: a burst of edits costs one.
        self._refresh_soon = Debounced(self._refresh, parent=page, service=deps.debounce)
        self.updating.follow(self._refresh_soon)
        library = deps.library
        self._unsubscribes = [
            # This project only; links are not files, so edges are left out.
            follow_project(
                library,
                self.project_id,
                self._refresh_soon.trigger,
                signals=(
                    library.module_data_changed,
                    library.text_edited,
                    library.structure_changed,
                    library.field_changed,
                ),
            ),
        ]
        self._refresh()

    # -- the activity contract -----------------------------------------------------------------

    @property
    def uri(self) -> Uri:
        return activity_uri(ASSETS_KIND, self.project_id)

    @property
    def title(self) -> str:
        project = self._deps.library.project(self.project_id)
        return f"{project.title or 'Untitled project'} — Assets"

    @property
    def widget(self) -> QWidget:
        return self._widget

    def on_activated(self) -> None:
        super().on_activated()
        self._on_selection()

    def close(self) -> None:
        self._refresh_soon.cancel()
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    # -- the catalog, rendered -----------------------------------------------------------------

    def _refresh(self) -> None:

        library = self._deps.library
        if not library.has(self.project_id):
            return  # The project was deleted; the tab is about to close.
        project = library.project(self.project_id)
        self._entries = catalog(library, project, self._deps.files, self._deps.sources)
        unused = sum(entry.unused for entry in self._entries)
        count = len(self._entries)
        self.lead.setText(
            f"{count} asset{'s' if count != 1 else ''}" + (f" — {unused} unused" if unused else "")
            if count
            else "No assets yet"
        )
        self._sync_filter()
        self._rebuild_list()

    def _sync_filter(self) -> None:
        """The selector offers only sources that hold anything, and hides itself when
        there is nothing to choose between — a selector with one entry teaches nothing."""
        labels = list(
            dict.fromkeys(source.label for entry in self._entries for source, _l in entry.locations)
        )
        current = self.source_filter.currentText()
        self.source_filter.blockSignals(True)
        self.source_filter.clear()
        self.source_filter.addItem("All sources")
        self.source_filter.addItems(labels)
        index = self.source_filter.findText(current)
        self.source_filter.setCurrentIndex(index if index > 0 else 0)
        self.source_filter.blockSignals(False)
        self.source_filter.setVisible(len(labels) > 1)

    def _filtered(self) -> list[AssetEntry]:
        entries = self._entries
        label = self.source_filter.currentText()
        if self.source_filter.currentIndex() > 0:
            entries = [
                entry
                for entry in entries
                if any(source.label == label for source, _l in entry.locations)
            ]
        if self.unused_only.isChecked():
            entries = [entry for entry in entries if entry.unused]
        return entries

    def _rebuild_list(self) -> None:
        entries = self._filtered()
        titles = read_titles(self._deps.library.project(self.project_id))
        keep = self._shown.name if self._shown is not None else None
        self.list.blockSignals(True)
        self.list.clear()
        for entry in entries:
            uses = entry.uses
            wheres = ", ".join(dict.fromkeys(use.where for use in uses))
            count = len(uses)
            detail = f"{count} use{'s' if count != 1 else ''} — {wheres}" if count else "unused"
            item = QListWidgetItem(titles.get(entry.name) or PurePosixPath(entry.name).name)
            item.setData(NAME_ROLE, entry.name)
            item.setData(DETAIL_ROLE, detail)
            item.setData(THUMB_ROLE, self._thumbnail(entry))
            self.list.addItem(item)
            if entry.name == keep:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        has_rows = bool(entries)
        self.empty.say("" if self._entries else NO_ASSETS)
        if has_rows and self.list.currentRow() < 0:
            self.list.setCurrentRow(0)
        else:
            self._on_selection()

    def _entry_named(self, name: str | None) -> AssetEntry | None:
        return next((entry for entry in self._entries if entry.name == name), None)

    def _on_selection(self) -> None:
        item = self.list.currentItem()
        self._shown = self._entry_named(item.data(NAME_ROLE) if item else None)
        self._show_entry()
        nodes = (
            (ContextNode(selection_uri("asset", self._shown.name)),)
            if self._shown is not None
            else ()
        )
        self.publish_selection(nodes)

    # -- the detail pane -----------------------------------------------------------------------

    def _show_entry(self) -> None:
        entry = self._shown
        enabled = entry is not None
        for widget in (self.name_edit, self.open_button, self.copy_button):
            widget.setEnabled(enabled)
        if entry is None:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("")
            if not self.name_edit.hasFocus():
                self.name_edit.setText("")
            self.uses.clear()
            self.delete_button.setEnabled(False)
            self.delete_button.setToolTip("")
            return

        image = self._image(entry)
        if image is not None:
            self.preview.setText("")
            self.preview.setPixmap(self._fitted(image))
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(PurePosixPath(entry.name).name)
        # The model's echo of this pane's own rename must not overwrite typing in flight.
        if not self.name_edit.hasFocus():
            titles = read_titles(self._deps.library.project(self.project_id))
            self.name_edit.setText(titles.get(entry.name, ""))

        self.uses.clear()
        for source, location in entry.locations:
            if location.uses:
                for use in location.uses:
                    row = QListWidgetItem(use.subject)
                    row.setData(DETAIL_ROLE, f"{use.where} · {source.label}")
                    row.setData(KIND_ROLE, use.subject_kind)
                    row.setData(SUBJECT_ROLE, use.subject_id)
                    row.setData(MODULE_ROLE, location.module_id)
                    self.uses.addItem(row)
            else:
                beside = self._subject_of(location.node_id)
                row = QListWidgetItem(f"Unused copy beside {beside}")
                row.setData(DETAIL_ROLE, source.label)
                row.setData(KIND_ROLE, "")
                self.uses.addItem(row)

        if entry.unused:
            self.delete_button.setEnabled(True)
            self.delete_button.setToolTip("Remove every copy — not undoable")
        else:
            use = entry.uses[0]
            self.delete_button.setEnabled(False)
            # Disabled, never hidden — and the tooltip teaches the precondition.
            self.delete_button.setToolTip(f"Used by {use.subject} — {use.where}")

    def _subject_of(self, node_id: NodeId) -> str:
        library = self._deps.library
        if not library.has(node_id):
            return node_id[:8]
        return getattr(library.node(node_id), "title", "") or node_id[:8]

    def _navigate(self, item: QListWidgetItem) -> None:
        kind = item.data(KIND_ROLE)
        if kind == "step":
            self._deps.actions.run(
                "steps.details",
                Context(
                    {
                        SCOPE_SELECTION: (
                            ContextNode(selection_uri("step", item.data(SUBJECT_ROLE))),
                        )
                    }
                ),
            )
        elif kind == "project" and item.data(MODULE_ROLE) == "spec":
            # Naming another module's verb id as a string is the accepted seam — the
            # testing table runs `steps.details` the same way.
            self._deps.actions.run(
                "spec.open",
                Context(
                    {SCOPE_SELECTION: (ContextNode(selection_uri("project", self.project_id)),)}
                ),
            )
        # A standing instruction has no verb that opens the project card; the row stays put.

    # -- bytes, thumbnails, the lightbox -------------------------------------------------------

    def _location_bytes(self, location: AssetLocation) -> bytes | None:
        try:
            area = self._deps.files(location.node_id, location.module_id)
        except KeyError:
            return None
        return area.read_bytes(location.name)

    def _entry_bytes(self, entry: AssetEntry) -> bytes | None:
        for _source, location in entry.locations:
            data = self._location_bytes(location)
            if data is not None:
                return data
        return None

    def _image(self, entry: AssetEntry) -> QImage | None:
        data = self._entry_bytes(entry)
        image = QImage.fromData(data) if data is not None else QImage()
        return None if image.isNull() else image

    def _absolute(self, entry: AssetEntry) -> str:
        _source, location = entry.locations[0]
        try:
            area = self._deps.files(location.node_id, location.module_id)
        except KeyError:
            return ""
        return str(area.absolute(location.name))

    def _thumbnail(self, entry: AssetEntry) -> QPixmap | None:
        ratio = self._widget.devicePixelRatioF()
        cached = self._thumbs.get(entry.name)
        if cached is not None and cached[0] == ratio:
            return cached[1]  # Content-addressed: same name, same bytes — never stale.
        image = self._image(entry)
        pixmap = None
        if image is not None:
            scaled = image.scaled(
                round(ROW_THUMB * ratio),
                round(ROW_THUMB * ratio),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            pixmap = QPixmap.fromImage(scaled)
            pixmap.setDevicePixelRatio(ratio)
        self._thumbs[entry.name] = (ratio, pixmap)
        return pixmap

    def _fitted(self, image: QImage) -> QPixmap:
        ratio = self._widget.devicePixelRatioF()
        factor = min(
            PREVIEW_MAX / max(1, image.width()),
            PREVIEW_MAX / max(1, image.height()),
            1.0,  # Bounded, and never upscaled past 1:1 — the lightbox's own rule.
        )
        scaled = image.scaled(
            max(1, round(image.width() * factor * ratio)),
            max(1, round(image.height() * factor * ratio)),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pixmap = QPixmap.fromImage(scaled)
        pixmap.setDevicePixelRatio(ratio)
        return pixmap

    def _view_shown(self) -> None:
        entry = self._shown
        if entry is None:
            return
        image = self._image(entry)
        if image is None:
            return
        ImagePreviewDialog(
            image,
            PurePosixPath(entry.name).name,
            self._widget,
            path=self._absolute(entry),
        ).exec()

    # -- the verbs -----------------------------------------------------------------------------

    def _rename(self) -> None:
        entry = self._shown
        if entry is None:
            return
        project = self._deps.library.project(self.project_id)
        titles = read_titles(project)
        typed = self.name_edit.text().strip()
        if titles.get(entry.name, "") == typed:
            return
        if typed:
            titles[entry.name] = typed
        else:
            titles.pop(entry.name, None)
        self._deps.undo.push(
            SetModuleDataCommand(
                self.project_id, MODULE_ID, write_titles(titles), label="Rename Asset"
            )
        )

    def _copy_path(self) -> None:
        if self._shown is not None:
            QGuiApplication.clipboard().setText(self._absolute(self._shown))

    def _open_externally(self) -> None:
        entry = self._shown
        if entry is None:
            return
        # Existence is checked here, at click time — a state must not touch the disk, and
        # the file can be gone by now.
        path = self._absolute(entry)
        if path and Path(path).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _attach_to_pool(self) -> None:
        chosen, _filter = QFileDialog.getOpenFileName(self._widget, "Attach to Pool")
        if not chosen:
            return
        try:
            area = self._deps.files(self.project_id, MODULE_ID)
        except KeyError:
            return  # A project the store has never flushed; the next autosave settles it.
        attach(area, Path(chosen).read_bytes(), Path(chosen).name)
        self._refresh()

    def _delete(self) -> None:
        entry = self._shown
        if entry is None or not entry.unused:
            return
        count = len(entry.locations)
        copies = f"{count} copies" if count != 1 else "its one copy"
        if not confirm(
            self._widget,
            "Delete Asset",
            f"Remove {PurePosixPath(entry.name).name} ({copies})?"
            " This is not undoable — version control still has the bytes.",
        ):
            return
        self._remove([location for _source, location in entry.locations])

    def _sweep(self) -> None:
        swept = prunable(self._entries)
        if not swept:
            self.lead.setText(f"{self.lead.text()} — nothing to sweep")
            return
        count = len(swept)
        if not confirm(
            self._widget,
            "Clean Up Unused",
            f"Remove {count} unused file{'s' if count != 1 else ''}?"
            " This is not undoable — version control still has the bytes.",
        ):
            return
        self._remove([location for _source, location in swept])

    def _remove(self, locations: list[AssetLocation]) -> None:
        for location in locations:
            try:
                area = self._deps.files(location.node_id, location.module_id)
            except KeyError:
                continue
            area.remove(location.name)
        self._thumbs.clear()  # Only to free memory: a returning name brings the same bytes.
        self._refresh()
