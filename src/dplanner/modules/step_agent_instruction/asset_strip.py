"""A row of attached files under an instruction editor: thumbnails, chips, and Attach.

Images render as small previews; anything else falls back to a filename chip. The files
live in the module's content-addressed area beside the node (``domain/assets.py``), so a
thumbnail cache keyed by name can never go stale — same name, same bytes. Attach and
remove write the area directly and are deliberately not undoable, the same trade the
handoff's attachments made: an orphaned blob is recoverable, a dangling link is not.

The strip is handed a *provider* of the area, not the area itself: a node created moments
ago has no directory until autosave flushes it, and the store says so with a ``KeyError``
at resolve time — which the strip answers in words instead of a broken button.
"""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QResizeEvent
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

THUMBNAIL_SIZE = 64
ITEM_GAP = 6  # Within the strip — DESIGN.md's within-block spacing.

# The provider resolves the node's file area, raising KeyError while the node is unflushed.
AreaFor = Callable[[], ModuleFileArea]


class _AssetItem(QWidget):
    """One attached file: its preview or its name, with a remove button beside it."""

    def __init__(
        self, name: str, pixmap: QPixmap | None, remove: Callable[[str], None]
    ) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        if pixmap is not None:
            preview = QLabel(self)
            preview.setPixmap(
                pixmap.scaled(
                    THUMBNAIL_SIZE,
                    THUMBNAIL_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            preview.setToolTip(Path(name).name)
            row.addWidget(preview)
        else:
            chip = QLabel(Path(name).name, self)
            chip.setObjectName("InspectorNote")
            row.addWidget(chip)

        cross = QToolButton(self)
        cross.setText("✕")
        cross.setAutoRaise(True)
        cross.setToolTip("Remove this file")
        cross.clicked.connect(lambda: remove(name))
        row.addWidget(cross, alignment=Qt.AlignmentFlag.AlignTop)
        row.addStretch(1)


class AssetStrip(QWidget):
    """The files one node's instruction carries, and the button that adds more."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._area_for: AreaFor | None = None
        self._pixmaps: dict[str, QPixmap | None] = {}  # Content-addressed: never stale.
        self._names: list[str] = []
        self._columns = 0

        self.attach_button = QPushButton("Attach…", self)
        self.attach_button.clicked.connect(self._attach)
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

    def set_source(self, area_for: AreaFor | None) -> None:
        """Point the strip at a node's file area, or at nothing."""
        self._area_for = area_for
        self.note.hide()
        self.setEnabled(area_for is not None)
        self.refresh()

    def refresh(self) -> None:
        area = self._resolve()
        self._names = assets(area) if area is not None else []
        for name in self._names:
            if name not in self._pixmaps:
                data = area.read_bytes(name) if area is not None else None
                pixmap = QPixmap()
                loaded = data is not None and pixmap.loadFromData(data)
                self._pixmaps[name] = pixmap if loaded else None
        self._rebuild_grid()

    # -- internals -----------------------------------------------------------------------------

    def _resolve(self) -> ModuleFileArea | None:
        if self._area_for is None:
            return None
        try:
            return self._area_for()
        except KeyError:
            return None

    def _attach(self) -> None:
        chosen, _filter = QFileDialog.getOpenFileName(self, "Attach to Instruction")
        if not chosen:
            return
        area = self._resolve()
        if area is None:
            # A node created moments ago has no directory until autosave flushes it.
            self.note.setText("Not saved yet — try again in a moment.")
            self.note.show()
            return
        self.note.hide()
        attach(area, Path(chosen).read_bytes(), Path(chosen).name)
        self.refresh()

    def _remove(self, name: str) -> None:
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
        for index, name in enumerate(self._names):
            cell = _AssetItem(name, self._pixmaps.get(name), self._remove)
            self._grid.addWidget(cell, index // self._columns, index % self._columns)
        self._grid_host.setVisible(bool(self._names))

    def _column_count(self) -> int:
        # Panels can be 200 px wide; the grid reflows instead of clipping.
        cell = THUMBNAIL_SIZE + 24 + ITEM_GAP  # Thumbnail, its ✕, the gap.
        return max(1, self.width() // cell)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if self._names and self._column_count() != self._columns:
            self._rebuild_grid()
