"""A modal lightbox for one image: the answer to "let me actually see that attachment".

Any module with a picture to show opens this instead of growing its own dialog — the
same reuse argument that extracted :mod:`.prose_section`. The image is fitted to the
screen but **never upscaled past 1:1**: a 200-pixel diagram blown up to full screen says
less than it did at its own size. The pixmap is built at the device pixel ratio, because
a preview dialog whose whole job is fidelity must not be the blurriest surface in the
application.
"""

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import QLabel, QWidget

from dplanner.domain.assets import ClickTarget
from dplanner.framework.click_targets import marked
from dplanner.framework.dialog import DialogFrame
from dplanner.theme.tokens import SCREEN_SHARE


class ImagePreviewDialog(DialogFrame):
    """One image, fitted to the screen, with its name in the title bar.

    A fit dialog: the pixmap sizes it. Close is the only way out, with *Open Externally*
    and *Copy Path* as quiet secondaries when there is a path, and what either came to
    said in the footer's status slot rather than in a box over the picture.

    ``targets`` are the areas the prose that links this picture points at — rung here, at
    the size somebody is actually looking at it. The picture on disk is untouched, and
    *Open Externally* deliberately opens the bare one: the ring is this application's
    reading of the prose, not part of the file.
    """

    def __init__(
        self,
        image: QImage,
        name: str,
        parent: QWidget | None = None,
        *,
        caption: str = "",
        path: str = "",
        targets: Sequence[ClickTarget] = (),
    ) -> None:
        super().__init__(caption or f"{name} — {image.width()} x {image.height()}", parent)
        self.image_label = QLabel(self.body)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setPixmap(self._fitted(marked(image, targets)))
        self.body_layout.addWidget(self.image_label)
        if path:
            self.add_button("Open Externally", lambda: self._open_externally(path))
            self.add_button("Copy Path", lambda: self._copy_path(path))
        self.add_dismiss("Close")

    def _copy_path(self, path: str) -> None:
        QGuiApplication.clipboard().setText(path)
        self.status.say("Path copied", "ok")

    def _open_externally(self, path: str) -> None:
        # Existence is checked here, at click time, never earlier: the file can be gone by
        # now, and handing the OS a dead path fails silently on some desktops.
        if not Path(path).is_file():
            self.status.say(f"{Path(path).name} is no longer on disk", "error")
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
