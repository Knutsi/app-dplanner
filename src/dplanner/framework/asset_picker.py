"""A modal picker over a set of named files: choose some, get their bytes back.

The reuse half of the asset story — :class:`~dplanner.framework.prose_edit.ProseEdit`
attaches what this returns exactly as it attaches a paste, so picking an existing file
and pasting a new one are one code path from the editor's point of view. Deliberately
generic: entries are titles, details and byte readers, so the dialog knows nothing about
projects, steps or modules and any application built on this framework can open it over
whatever catalog it keeps.

Returns :class:`~dplanner.framework.mime_files.Payload` values — bytes and a filename,
never a path — because the chooser cannot know where the caller will put the copy, and a
path handed across that line becomes a link into somebody else's directory.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.mime_files import IMAGE_SUFFIXES, Payload
from dplanner.theme.tokens import DIALOG_MARGIN, SCREEN_SHARE, SECTION_GAP

THUMBNAIL_SIZE = 96  # Larger than the gallery strip's 76: choosing wants a better look.
DIALOG_WIDTH = 680
DIALOG_HEIGHT = 460


@dataclass(frozen=True)
class PickerEntry:
    """One choosable file. ``read`` supplies the bytes — for the thumbnail and, when the
    entry is chosen, for the payload — and may answer None for a file that is gone."""

    key: str  # Identity within the dialog; distinct per entry.
    title: str  # The line under the thumbnail — a display name, or the filename.
    detail: str = ""  # Secondary, into the tooltip: where the file lives, what uses it.
    filename: str = ""  # What an attach derives the suffix — and a link's alt text — from.
    read: Callable[[], bytes | None] = field(default=lambda: None)


class AssetPickerDialog(QDialog):
    """A grid of thumbnails, extended selection, double-click accepts."""

    def __init__(
        self,
        entries: Sequence[PickerEntry],
        parent: QWidget | None = None,
        *,
        title: str = "Insert from Assets",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._entries = list(entries)

        column = QVBoxLayout(self)
        column.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN)
        column.setSpacing(SECTION_GAP)

        self.grid = QListWidget(self)
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setIconSize(QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        # Without an explicit grid, IconMode packs each cell to its content and a wide
        # thumbnail squeezes its own title out; one cell size gives thumbnail plus a line.
        self.grid.setGridSize(QSize(THUMBNAIL_SIZE + 32, THUMBNAIL_SIZE + 40))
        self.grid.setSpacing(SECTION_GAP)
        self.grid.setWordWrap(True)
        self.grid.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.grid.itemDoubleClicked.connect(lambda _item: self.accept())
        ratio = self.devicePixelRatioF()
        for index, entry in enumerate(self._entries):
            item = QListWidgetItem(entry.title)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(f"{entry.title}\n{entry.detail}" if entry.detail else entry.title)
            icon = _thumbnail(entry, ratio)
            if icon is not None:
                item.setIcon(icon)
            self.grid.addItem(item)

        self.empty = QLabel("Nothing to pick from yet — attach or paste a file first.", self)
        self.empty.setObjectName("InspectorNote")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setText("Insert")
            ok.setEnabled(bool(self._entries))

        # A dialog cannot go off screen the way a panel does, so it says so in words.
        if self._entries:
            column.addWidget(self.grid, stretch=1)
            self.empty.hide()
        else:
            column.addWidget(self.empty, stretch=1)
            self.grid.hide()
        column.addWidget(buttons)

        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.resize(
                min(DIALOG_WIDTH, round(available.width() * SCREEN_SHARE)),
                min(DIALOG_HEIGHT, round(available.height() * SCREEN_SHARE)),
            )

    def chosen(self) -> list[Payload]:
        """The picked files as payloads, in entry order. An entry whose bytes are gone is
        skipped rather than fatal — the catalog it came from can be a beat stale."""
        rows = sorted(item.data(Qt.ItemDataRole.UserRole) for item in self.grid.selectedItems())
        picked: list[Payload] = []
        for row in rows:
            entry = self._entries[row]
            data = entry.read()
            if data is None:
                continue
            filename = entry.filename or PurePosixPath(entry.key).name
            suffix = PurePosixPath(filename).suffix.lower()
            picked.append(Payload(data=data, filename=filename, is_image=suffix in IMAGE_SUFFIXES))
        return picked


def _thumbnail(entry: PickerEntry, ratio: float) -> QIcon | None:
    """The gallery strip's recipe at picker size: rendered at the device pixel ratio,
    never upscaled — a non-image or a missing file shows as its title alone."""
    data = entry.read()
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
    return QIcon(pixmap)
