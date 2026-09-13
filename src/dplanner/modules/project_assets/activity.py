"""The Assets tab: everything a project's areas hold, and what still uses each file.

A master-detail over :func:`dplanner.domain.assets.catalog` — the same derivation
``dplanner asset list`` prints, computed on every refresh and never stored. The table on the
left has a row per content name, however many areas carry the bytes: its thumbnail, its
name over where it is used, and how many uses it has. The right pane shows the picture, its
display name, and a table of every place it lives. The strip over both carries the verbs —
attaching a file to the project's own pool and cleaning up what nothing uses, then, on the
picked asset, opening it, copying its path and deleting it — and a filter by source and by
being unused.

The tab is a *browser*: opening it writes nothing. Its writes are explicit gestures —
renaming (a command, undoable) and deleting (straight through the file areas, not undoable,
confirmed in those words).
"""

from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import (
    QAction,
    QDesktopServices,
    QGuiApplication,
    QIcon,
    QImage,
    QMouseEvent,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSplitter,
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
from dplanner.framework.list_rows import HOST_ROLE
from dplanner.framework.signalling import UpdatingIndicator
from dplanner.framework.table import Cell, Column, Table
from dplanner.framework.toolbar import FilterButton, Toolbar
from dplanner.framework.widgets import EmptyState, caption, confirm
from dplanner.modules.project_assets.cli import MODULE_ID, read_titles, write_titles
from dplanner.theme.cards import title_font
from dplanner.theme.icons import (
    ICON_SIZE,
    attach_icon,
    clipboard_icon,
    external_icon,
    sweep_icon,
    trash_icon,
)
from dplanner.theme.tokens import CAPTION_GAP, FIELD_GAP, PANEL_MARGIN, SECTION_GAP

if TYPE_CHECKING:  # module.py imports this file, so the Deps arrive as a forward name.
    from dplanner.modules.project_assets.module import ProjectAssetsDeps

ASSETS_KIND = "assets"
NO_ASSETS = (
    "No assets yet. Paste an image into a step's description, or"
    " `dplanner describe attach <step> <file>`."
)
NO_MATCH = "Nothing matches the filter."

PREVIEW_MAX = 260  # The detail pane's picture, bounded; click for the real lightbox.

UNUSED = "unused"  # The filter key for the assets nothing uses.
SOURCE = "source:"  # The prefix of a filter key naming one source by its label.

ASSET_COLUMNS = (
    Column("Asset", glyph=True, detail=True, resize="stretch"),
    Column("Uses", numeric=True),
)
USE_COLUMNS = (Column("Used by", detail=True, resize="stretch"), Column("Source"))

ASSET_ROLE = HOST_ROLE  # The entry's content name.
KIND_ROLE = HOST_ROLE + 1  # A use row's subject kind ("" = no target).
SUBJECT_ROLE = HOST_ROLE + 2  # A use row's subject id.
MODULE_ROLE = HOST_ROLE + 3  # A use row's owning module id.


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
        self._thumbs: dict[str, tuple[float, QIcon | None]] = {}
        self._sources: dict[str, QAction] = {}

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(SECTION_GAP)

        head = QVBoxLayout()
        layout.addLayout(head)  # Before it is filled: a parentless layout leaks its items.
        head.setSpacing(CAPTION_GAP)
        head.addWidget(caption("Assets", page))
        self.lead = QLabel(page)
        self.lead.setFont(title_font(self.lead.font()))  # Emphasis by size, never bold.
        head.addWidget(self.lead)

        # Creation first, then what acts on the picked asset, then the view (DESIGN.md's
        # *Tables*); the indicator outside the strip, so folding never takes it.
        strip = QHBoxLayout()
        layout.addLayout(strip)
        strip.setSpacing(FIELD_GAP)
        self.controls = Toolbar(page)
        self.attach_action = self.controls.add_verb(
            "Attach to Pool…",
            attach_icon,
            self._attach_to_pool,
            tip="Copy a file into this project's own pool of assets",
        )
        self.sweep_action = self.controls.add_verb(
            "Clean Up Unused…",
            sweep_icon,
            self._sweep,
            tip="Remove every file nothing in the plan uses — not undoable",
        )
        self.open_action = self.controls.add_verb(
            "Open Externally",
            external_icon,
            self._open_externally,
            tip="Open the picked asset in the program the desktop opens it with",
        )
        self.copy_action = self.controls.add_verb(
            "Copy Path",
            clipboard_icon,
            self._copy_path,
            tip="Copy where the picked asset lives on this machine",
        )
        self.delete_action = self.controls.add_verb(
            "Delete",
            trash_icon,
            self._delete,
            tip="Remove every copy of the picked asset — not undoable",
        )
        self.controls.add_divider()
        self.filter = FilterButton(label="Filter")
        self.filter.add_filter(UNUSED, "Unused only")
        self.controls.add_widget(self.filter)
        strip.addWidget(self.controls, 1)
        self.updating = UpdatingIndicator(page)
        strip.addWidget(self.updating)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, page)
        self.table = Table(ASSET_COLUMNS, parent=self.splitter)
        self.table.itemSelectionChanged.connect(self._on_selection)

        detail = QWidget(self.splitter)
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(SECTION_GAP, 0, 0, 0)
        detail_layout.setSpacing(SECTION_GAP)
        self.preview = _PreviewLabel(detail)
        self.preview.view = self._view_shown
        detail_layout.addWidget(self.preview)
        name_block = QVBoxLayout()
        detail_layout.addLayout(name_block)
        name_block.setSpacing(CAPTION_GAP)
        name_block.addWidget(caption("Display name", detail))
        self.name_edit = QLineEdit(detail)
        self.name_edit.setPlaceholderText("What it is called here (optional)")
        self.name_edit.editingFinished.connect(self._rename)
        name_block.addWidget(self.name_edit)
        self.uses = Table(USE_COLUMNS, parent=detail)
        self.uses.cellActivated.connect(self._navigate)
        detail_layout.addWidget(self.uses, 1)

        self.splitter.addWidget(self.table)
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
            self.filter.changed.connect(self._rebuild_list),
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
        self.controls.dispose()

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
        # Disabled, never hidden: its words say why there is nothing to do.
        sweepable = bool(prunable(self._entries))
        self.sweep_action.setEnabled(sweepable)
        self.sweep_action.setText(
            "Clean Up Unused…" if sweepable else "Clean Up Unused — nothing unused"
        )
        self._sync_sources()
        self._rebuild_list()

    def _sync_sources(self) -> None:
        """The filter offers a source only while two or more hold anything — one source to
        choose between teaches nothing — and a source that stopped being offered stops
        narrowing the list."""
        labels = list(
            dict.fromkeys(source.label for entry in self._entries for source, _l in entry.locations)
        )
        for label in labels:
            if label not in self._sources:
                self._sources[label] = self.filter.add_filter(SOURCE + label, label)
        offered = len(labels) > 1
        withdrawn = set()
        for label, action in self._sources.items():
            action.setVisible(offered and label in labels)
            if not action.isVisible():
                withdrawn.add(SOURCE + label)
        active = set(self.filter.active())
        if active & withdrawn:
            self.filter.set_active(active - withdrawn)

    def _filtered(self) -> list[AssetEntry]:
        active = set(self.filter.active())
        sources = {key.removeprefix(SOURCE) for key in active if key.startswith(SOURCE)}
        entries = self._entries
        if sources:
            entries = [
                entry
                for entry in entries
                if any(source.label in sources for source, _l in entry.locations)
            ]
        if UNUSED in active:
            entries = [entry for entry in entries if entry.unused]
        return entries

    def _rebuild_list(self) -> None:
        entries = self._filtered()
        titles = read_titles(self._deps.library.project(self.project_id))
        keep = self._shown.name if self._shown is not None else None
        # Quiet while the rows are replaced; the selection is announced once, below.
        self.table.blockSignals(True)
        try:
            self.table.clear_rows()
            for entry in entries:
                wheres = ", ".join(dict.fromkeys(use.where for use in entry.uses))
                row = self.table.add_row(
                    (
                        Cell(
                            titles.get(entry.name) or PurePosixPath(entry.name).name,
                            detail=wheres or "unused",
                            glyph=self._thumbnail(entry),
                        ),
                        Cell(str(len(entry.uses)), secondary=entry.unused),
                    ),
                    data={ASSET_ROLE: entry.name},
                )
                if entry.name == keep:
                    self.table.selectRow(row)
            if entries and not self.table.selectedIndexes():
                self.table.selectRow(0)
        finally:
            self.table.blockSignals(False)
        self.empty.say("" if entries else NO_MATCH if self._entries else NO_ASSETS)
        self._on_selection()

    def _entry_named(self, name: object) -> AssetEntry | None:
        return next((entry for entry in self._entries if entry.name == name), None)

    def _on_selection(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        item = self.table.item(rows[0], 0) if rows else None
        self._shown = self._entry_named(item.data(ASSET_ROLE) if item is not None else None)
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
        picked = entry is not None
        for action in (self.open_action, self.copy_action):
            action.setEnabled(picked)
        self.name_edit.setEnabled(picked)
        self.uses.clear_rows()
        if entry is None:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("")
            if not self.name_edit.hasFocus():
                self.name_edit.setText("")
            self.delete_action.setEnabled(False)
            self.delete_action.setText("Delete — pick an asset")
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

        for source, location in entry.locations:
            if location.uses:
                for use in location.uses:
                    self.uses.add_row(
                        (Cell(use.subject, detail=use.where), Cell(source.label, secondary=True)),
                        data={
                            KIND_ROLE: use.subject_kind,
                            SUBJECT_ROLE: use.subject_id,
                            MODULE_ROLE: location.module_id,
                        },
                    )
            else:
                beside = self._subject_of(location.node_id)
                self.uses.add_row(
                    (
                        Cell(f"Unused copy beside {beside}", detail="nothing links it"),
                        Cell(source.label, secondary=True),
                    ),
                    data={KIND_ROLE: ""},
                )

        if entry.unused:
            self.delete_action.setEnabled(True)
            self.delete_action.setText("Delete")
        else:
            use = entry.uses[0]
            # Disabled, never hidden — and its words teach the precondition.
            self.delete_action.setEnabled(False)
            self.delete_action.setText(f"Delete — used by {use.subject}, {use.where}")

    def _subject_of(self, node_id: NodeId) -> str:
        library = self._deps.library
        if not library.has(node_id):
            return node_id[:8]
        return getattr(library.node(node_id), "title", "") or node_id[:8]

    def _navigate(self, row: int, _column: int) -> None:
        item = self.uses.item(row, 0)
        if item is None:
            return
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

    def _thumbnail(self, entry: AssetEntry) -> QIcon | None:
        """The picture at glyph size, painted at the screen's ratio, in the row's glyph slot."""
        ratio = self._widget.devicePixelRatioF()
        cached = self._thumbs.get(entry.name)
        if cached is not None and cached[0] == ratio:
            return cached[1]  # Content-addressed: same name, same bytes — never stale.
        image = self._image(entry)
        icon = None
        if image is not None:
            side = round(ICON_SIZE * ratio)
            scaled = image.scaled(
                side,
                side,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            pixmap = QPixmap.fromImage(scaled)
            pixmap.setDevicePixelRatio(ratio)
            icon = QIcon(pixmap)
        self._thumbs[entry.name] = (ratio, icon)
        return icon

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
            verb="Delete",
        ):
            return
        self._remove([location for _source, location in entry.locations])

    def _sweep(self) -> None:
        swept = prunable(self._entries)
        if not swept:
            return  # The verb is greyed and says why; nothing reaches here but a stale click.
        count = len(swept)
        if not confirm(
            self._widget,
            "Clean Up Unused",
            f"Remove {count} unused file{'s' if count != 1 else ''}?"
            " This is not undoable — version control still has the bytes.",
            verb="Remove",
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
