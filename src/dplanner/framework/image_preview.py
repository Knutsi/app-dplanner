"""A modal lightbox for one image: the answer to "let me actually see that attachment".

Any module with a picture to show opens this instead of growing its own dialog — the
same reuse argument that extracted :mod:`.prose_section`. The image is fitted to the
screen but **never upscaled past 1:1**: a 200-pixel diagram blown up to full screen says
less than it did at its own size. The pixmap is built at the device pixel ratio, because
a preview dialog whose whole job is fidelity must not be the blurriest surface in the
application.
"""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

OUTER_MARGIN = 20  # DESIGN.md: dialogs breathe more than panels.
SECTION_GAP = 12
SCREEN_SHARE = 0.8  # The largest slice of the screen a preview claims.


class ImagePreviewDialog(QDialog):
    """One image, fitted to the screen, with its name in the title bar."""

    def __init__(
        self,
        image: QImage,
        name: str,
        parent: QWidget | None = None,
        *,
        caption: str = "",
        path: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(caption or f"{name} — {image.width()} x {image.height()}")

        column = QVBoxLayout(self)
        column.setContentsMargins(OUTER_MARGIN, OUTER_MARGIN, OUTER_MARGIN, OUTER_MARGIN)
        column.setSpacing(SECTION_GAP)

        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setPixmap(self._fitted(image))
        column.addWidget(self.image_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        close = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close is not None:
            close.clicked.connect(self.reject)
        if path:
            external = buttons.addButton("Open Externally", QDialogButtonBox.ButtonRole.ActionRole)
            external.clicked.connect(lambda: self._open_externally(path))
            copy = buttons.addButton("Copy Path", QDialogButtonBox.ButtonRole.ActionRole)
            copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(path))
        column.addWidget(buttons)

    def _open_externally(self, path: str) -> None:
        # Existence is checked here, at click time, never earlier: the file can be gone by
        # now, and handing the OS a dead path fails silently on some desktops.
        if not Path(path).is_file():
            QMessageBox.warning(self, "Open Externally", f"{path} is no longer on disk.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _fitted(self, image: QImage) -> QPixmap:
        screen = self.screen() or QGuiApplication.primaryScreen()
        available = screen.availableGeometry()
        factor = min(
            available.width() * SCREEN_SHARE / max(1, image.width()),
            available.height() * SCREEN_SHARE / max(1, image.height()),
            1.0,  # Fit the screen, but never invent pixels.
        )
        ratio = self.devicePixelRatioF()
        scaled = image.scaled(
            max(1, round(image.width() * factor * ratio)),
            max(1, round(image.height() * factor * ratio)),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pixmap = QPixmap.fromImage(scaled)
        pixmap.setDevicePixelRatio(ratio)
        return pixmap
