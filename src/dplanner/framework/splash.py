"""Startup splash: the only feedback between launch and the first window.

Everything before the window is shown runs synchronously on the main thread — a storage
pre-open check that may hit the network, the workspace load, module registration — so no
event loop is spinning to repaint anything. The splash therefore pumps ``processEvents`` at
every status update; that is what keeps it painted.

``status`` matches the ``progress`` callback that :meth:`AppSession.open_initial` and
the builder accept, so ``app.main`` can pass ``splash.status`` straight through.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QVBoxLayout, QWidget

from dplanner.identity import APP_NAME


class StartupSplash(QWidget):
    def __init__(self) -> None:
        # SplashScreen: frameless, floating (also under tiling window managers), and never
        # a taskbar entry. Deliberately NOT stay-on-top — a pre-open hook may show a modal
        # dialog (a branch picker) that has to appear above this.
        super().__init__(None, Qt.WindowType.SplashScreen)
        self.setObjectName("StartupSplash")

        title = QLabel(APP_NAME, self)
        title.setObjectName("StartupSplashTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = title.font()
        font.setPointSizeF(font.pointSizeF() * 1.6)
        font.setBold(True)
        title.setFont(font)

        self._status = QLabel("Starting…", self)
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)

        bar = QProgressBar(self)
        bar.setRange(0, 0)  # Indeterminate: the stages have no meaningful percentages.
        bar.setTextVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(self._status)
        layout.addWidget(bar)
        self.setFixedWidth(320)

        screen = self.screen()
        if screen is not None:
            self.adjustSize()
            self.move(screen.availableGeometry().center() - self.rect().center())

        self.show()
        QApplication.processEvents()

    def status(self, message: str) -> None:
        self._status.setText(message)
        QApplication.processEvents()
