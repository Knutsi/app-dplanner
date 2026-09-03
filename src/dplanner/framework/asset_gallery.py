"""A grid of attached files: thumbnails for images, chips for the rest, click to view.

Promoted from the agent-instruction module's private strip the moment a second and third
surface wanted it — modules cannot import each other, so a widget three aspects share has
exactly one legal home. Images render as small previews and open full-size in
:class:`~dplanner.framework.image_preview.ImagePreviewDialog`; anything else falls back
to a filename chip.

Two source modes, two path vocabularies — never mixed:

- :meth:`set_area` shows a node's content-addressed module area (``domain/assets.py``),
  with names like ``assets/<sha>.png`` read through the area. Only this mode can be
  ``editable``: Attach and remove write the area directly and are deliberately not
  undoable — the same trade the handoff's attachments made, because an orphaned blob is
  recoverable where a dangling link is not. The gallery is handed a *provider* of the
  area, not the area itself: a node created moments ago has no directory until autosave
  flushes it, and the store says so with a ``KeyError`` at resolve time — answered here
  in words instead of a broken button.
- :meth:`set_files` shows an explicit list of workspace-relative paths through a byte
  reader — how a briefing's file list is previewed without pretending it is an area.

Thumbnails are cached by name (content-addressed: same name, same bytes — never stale)
and rebuilt only when the device pixel ratio changes, and they are rendered *at* that
ratio: a gallery of soft previews on a sharp screen defeats its own point.
"""

from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QMouseEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.assets import assets, attach
from dplanner.domain.store import ModuleFileArea
from dplanner.framework.image_preview import ImagePreviewDialog

THUMBNAIL_SIZE = 76  # On the 4-point grid; large enough to recognise a figure.
ITEM_GAP = 6  # Within the gallery — DESIGN.md's within-block spacing.

# The provider resolves the node's file area, raising KeyError while the node is unflushed.
AreaFor = Callable[[], ModuleFileArea]
ReadBytes = Callable[[str], bytes | None]


class _Thumb(QLabel):
    """An image preview that opens the full picture when clicked."""

    def __init__(self, pixmap: QPixmap, name: str, view: Callable[[str], None]) -> None:
        super().__init__()
        self.setPixmap(pixmap)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{Path(name).name} — click to view")
        self._name = name
        self._view = view

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self._view(self._name)
        super().mousePressEvent(event)


class _AssetItem(QWidget):
    """One attached file: its preview or its name, with a remove button when editable."""

    def __init__(
        self,
        name: str,
        pixmap: QPixmap | None,
        view: Callable[[str], None],
        remove: Callable[[str], None] | None,
    ) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        if pixmap is not None:
            row.addWidget(_Thumb(pixmap, name, view))
        else:
            chip = QLabel(Path(name).name, self)
            chip.setObjectName("InspectorNote")
            row.addWidget(chip)

        if remove is not None:
            cross = QToolButton(self)
            cross.setText("✕")
            cross.setAutoRaise(True)
            cross.setToolTip("Remove this file")
            cross.clicked.connect(lambda: remove(name))
            row.addWidget(cross, alignment=Qt.AlignmentFlag.AlignTop)
        row.addStretch(1)


class AssetGallery(QWidget):
    """The files a surface carries, and — when editable — the button that adds more."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        editable: bool = False,
        attach_title: str = "Attach File",
        hide_when_empty: bool = False,
    ) -> None:
        super().__init__(parent)
        self._editable = editable
        self._attach_title = attach_title
        # For a surface with no room to spare — an editable gallery still costs a button
        # row with nothing to show. Nothing becomes unreachable: a paste, a drop and the
        # editor's Insert Image… all reach an empty area.
        self._hide_when_empty = hide_when_empty
        self._area_for: AreaFor | None = None
        self._files: list[str] = []
        self._read: ReadBytes | None = None
        self._remove_file: Callable[[str], None] | None = None
        self._thumbs: dict[str, tuple[float, QPixmap | None]] = {}
        self._names: list[str] = []
        self._columns = 0

        self.attach_button = QPushButton("Attach…", self)
        self.attach_button.clicked.connect(self._attach)
        self.attach_button.setVisible(editable)
        attach_row = QHBoxLayout()
        attach_row.setSpacing(ITEM_GAP)
        attach_row.addWidget(self.attach_button)
        attach_row.addStretch(1)

        self.note = QLabel("", self)
        self.note.setObjectName("InspectorNote")
        self.note.setWordWrap(True)
        self.note.hide()

        self._grid_host = QWidget(self)
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(ITEM_GAP)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(ITEM_GAP)
        column.addLayout(attach_row)
        column.addWidget(self.note)
        column.addWidget(self._grid_host)

    def set_area(self, area_for: AreaFor | None) -> None:
        """Point the gallery at a node's file area, or at nothing."""
        self._area_for = area_for
        self._files = []
        self._read = None
        self._remove_file = None
        self.note.hide()
        self.attach_button.setVisible(self._editable)
        self.setEnabled(area_for is not None)
        self.refresh()

    def set_files(
        self,
        names: Sequence[str],
        read: ReadBytes | None,
        remove: Callable[[str], None] | None = None,
    ) -> None:
        """Show an explicit list of paths through a byte reader — read-only unless the
        caller says what removing one means (a record's image list, say, where the file
        stays and only the reference goes)."""
        self._area_for = None
        self._files = list(names)
        self._read = read
        self._remove_file = remove
        self.note.hide()
        self.attach_button.setVisible(False)
        self.setEnabled(read is not None)
        self.refresh()

    def refresh(self) -> None:
        self._names = list(self._files)
        if self._area_for is not None:
            area = self._resolve()
            self._names = assets(area) if area is not None else []
        ratio = self.devicePixelRatioF()
        for name in self._names:
            cached = self._thumbs.get(name)
            if cached is None or cached[0] != ratio:
                self._thumbs[name] = (ratio, self._thumbnail(name, ratio))
        self._rebuild_grid()

    # -- internals -----------------------------------------------------------------------------

    def _resolve(self) -> ModuleFileArea | None:
        if self._area_for is None:
            return None
        try:
            return self._area_for()
        except KeyError:
            return None

    def _read_bytes(self, name: str) -> bytes | None:
        if self._area_for is not None:
            area = self._resolve()
            return area.read_bytes(name) if area is not None else None
        return self._read(name) if self._read is not None else None

    def _thumbnail(self, name: str, ratio: float) -> QPixmap | None:
        data = self._read_bytes(name)
        image = QImage.fromData(data) if data is not None else QImage()
        if image.isNull():
            return None
        scaled = image.scaled(
            round(THUMBNAIL_SIZE * ratio),
            round(THUMBNAIL_SIZE * ratio),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pixmap = QPixmap.fromImage(scaled)
        pixmap.setDevicePixelRatio(ratio)
        return pixmap

    def _view(self, name: str) -> None:
        data = self._read_bytes(name)
        image = QImage.fromData(data) if data is not None else QImage()
        if image.isNull():
            return
        path = name
        if self._area_for is not None:
            area = self._resolve()
            if area is not None:
                path = str(area.absolute(name))
        ImagePreviewDialog(image, Path(name).name, self, path=path).exec()

    def _attach(self) -> None:
        chosen, _filter = QFileDialog.getOpenFileName(self, self._attach_title)
        if not chosen:
            return
        self.attach_bytes(Path(chosen).read_bytes(), Path(chosen).name)

    def attach_bytes(self, data: bytes, filename: str) -> str | None:
        """Attach bytes and show them; returns the path to link to, or None if it could not.

        Public because a paste into the editor above needs the same three steps this button
        does — resolve, write, redraw — and a second implementation of them is how a pasted
        image ends up on disk with no thumbnail beside it.
        """
        area = self._resolve()
        if area is None:
            # A node created moments ago has no directory until autosave flushes it.
            self.note.setText("Not saved yet — try again in a moment.")
            self.note.show()
            self._apply_visibility()  # Hidden-when-empty must still be able to say this.
            return None
        self.note.hide()
        name = attach(area, data, filename)
        self.refresh()
        return name

    def _remove(self, name: str) -> None:
        if self._remove_file is not None:
            self._remove_file(name)
            return  # The caller's write comes back as a model change and a new list.
        area = self._resolve()
        if area is not None:
            area.remove(name)
        self.refresh()

    def _rebuild_grid(self) -> None:
        while (item := self._grid.takeAt(0)) is not None:
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._columns = self._column_count()
        removable = self._remove_file is not None or (self._editable and self._area_for is not None)
        for index, name in enumerate(self._names):
            _ratio, pixmap = self._thumbs.get(name, (1.0, None))
            cell = _AssetItem(name, pixmap, self._view, self._remove if removable else None)
            self._grid.addWidget(cell, index // self._columns, index % self._columns)
        # Pack the cells left: all spare width goes to a phantom trailing column, or a
        # short row spreads its few thumbnails across the whole panel. Old stretches are
        # cleared first — the column count changes with the width.
        for column in range(self._grid.columnCount() + 1):
            self._grid.setColumnStretch(column, 0)
        self._grid.setColumnStretch(self._columns, 1)
        self._grid_host.setVisible(bool(self._names))
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        """A hide-when-empty gallery takes no room until it has a file — or a word to say.

        ``isHidden`` rather than ``isVisible``: the note's visibility is being read to decide
        this widget's, and a child of a hidden parent is never *visible* whatever it was told.
        """
        if self._hide_when_empty:
            self.setVisible(bool(self._names) or not self.note.isHidden())

    def _column_count(self) -> int:
        # Panels can be 200 px wide; the grid reflows instead of clipping.
        cell = THUMBNAIL_SIZE + 24 + ITEM_GAP  # Thumbnail, its ✕, the gap.
        return max(1, self.width() // cell)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if self._names and self._column_count() != self._columns:
            self._rebuild_grid()
