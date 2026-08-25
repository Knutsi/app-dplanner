"""The application's main window: a shell around the tab host.

The menu bar's content lives in :mod:`dplanner.framework.menubar`, driven by module-registered
actions — this class is layout and window-level behaviour: immersive (distraction-free)
mode and, later, the quit-time flush.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow, QSplitter, QWidget

from dplanner.core.signals import Signal
from dplanner.framework.activity import Activity
from dplanner.framework.tabs import TabHost
from dplanner.identity import APP_NAME

if TYPE_CHECKING:
    from dplanner.framework.menubar import DynamicMenuBar

# Sidebar widths are logical pixels — Qt 6 scales them per monitor, so the stored value
# stays meaningful across DPI changes. The clamp keeps a stale or corrupt stored value
# from ever leaving the panel invisible or window-filling.
SIDEBAR_WIDTH_KEY = "appearance/sidebar_width"
SIDEBAR_DEFAULT_WIDTH = 275
SIDEBAR_MIN_WIDTH = 150
SIDEBAR_MAX_WIDTH = 600


def _stored_sidebar_width() -> int:
    raw = QSettings().value(SIDEBAR_WIDTH_KEY, SIDEBAR_DEFAULT_WIDTH)
    try:
        saved = int(raw) if isinstance(raw, int | float | str) else SIDEBAR_DEFAULT_WIDTH
    except ValueError:
        saved = SIDEBAR_DEFAULT_WIDTH
    return max(SIDEBAR_MIN_WIDTH, min(SIDEBAR_MAX_WIDTH, saved))


class AppWindow(QMainWindow):
    def __init__(self, tabs: TabHost, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MainWindow")
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 760)
        self.setMinimumSize(720, 480)

        # Assigned by the builder; held here so the QMenus outlive construction.
        self.dynamic_menubar: DynamicMenuBar | None = None

        # Run on window close, before teardown — the builder appends the autosave flush, so
        # quitting can never lose the last few seconds of typing.
        self.close_hooks: list[Callable[[], None]] = []
        # Run before close_hooks, in order; a guard returning False cancels the close (the
        # sync module asking "Save before quitting?" when there are uncommitted changes).
        self.close_guards: list[Callable[[], bool]] = []
        self._title_base = APP_NAME

        self.tabs = tabs
        # A slot, not a panel: whichever module installs a widget owns its content, and the
        # window only owns layout and visibility.
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.addWidget(tabs)
        self._sidebar: QWidget | None = None
        self._sidebar_was_visible = True
        self.setCentralWidget(self._splitter)
        self.statusBar().showMessage("Ready")

        self._immersive = False
        self._was_full_screen = False
        # Fires on enter/leave with the new state, however the change was triggered
        # (button, Esc, tab switch) — views showing immersive state subscribe here.
        self.immersive_changed: Signal[bool] = Signal()

        tabs.activity_changed.connect(self._on_activity_changed)
        # Window-level so it fires regardless of which child has focus; the handler guards
        # on immersive mode, so Esc keeps its normal meaning everywhere else.
        self._escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._escape.activated.connect(self._on_escape)

    # -- status (StatusHost) -----------------------------------------------------------------

    def show_status(self, text: str, msecs: int = 0) -> None:
        self.statusBar().showMessage(text, msecs)

    def add_status_widget(self, widget: QWidget) -> None:
        self.statusBar().addPermanentWidget(widget)

    # -- sidebar (SidebarHost) ---------------------------------------------------------------

    def set_sidebar(self, widget: QWidget) -> None:
        if self._sidebar is not None:
            raise ValueError("a sidebar is already installed")
        self._sidebar = widget
        self._splitter.insertWidget(0, widget)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._apply_sidebar_width(_stored_sidebar_width())
        self._splitter.splitterMoved.connect(self._on_splitter_moved)

    def sidebar(self) -> QWidget | None:
        return self._sidebar

    def reset_sidebar_width(self) -> None:
        QSettings().remove(SIDEBAR_WIDTH_KEY)
        self._apply_sidebar_width(SIDEBAR_DEFAULT_WIDTH)

    def _apply_sidebar_width(self, width: int) -> None:
        self._splitter.setSizes([width, max(1, self.width() - width)])

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        # A width of 0 means the panel was dragged shut — persisting it would restore a
        # seemingly missing sidebar, so only real widths are remembered.
        width = self._splitter.sizes()[0]
        if width > 0:
            QSettings().setValue(SIDEBAR_WIDTH_KEY, width)

    # -- unsaved changes (UnsavedChangesHost) -------------------------------------------------

    def set_unsaved(self, unsaved: bool, summary: str = "") -> None:
        if not unsaved:
            self.setWindowTitle(self._title_base)
            return
        detail = f" ({summary})" if summary else ""
        self.setWindowTitle(f"{self._title_base} — Unsaved Changes{detail}")

    def add_close_guard(self, guard: Callable[[], bool]) -> None:
        self.close_guards.append(guard)

    def set_sidebar_visible(self, visible: bool) -> None:
        if self._sidebar is not None:
            self._sidebar.setVisible(visible)

    def is_sidebar_visible(self) -> bool:
        return self._sidebar is not None and not self._sidebar.isHidden()

    # -- immersive (ImmersiveHost): distraction-free mode ------------------------------------

    def is_immersive(self) -> bool:
        return self._immersive

    def _on_activity_changed(self, _activity: Activity | None) -> None:
        # Immersive mode belongs to the tab that entered it; switching away restores the
        # chrome (the only way to switch while immersive is a shortcut).
        if self._immersive:
            self.leave_immersive()

    def enter_immersive(self) -> None:
        if self._immersive:
            return
        self._immersive = True
        self._was_full_screen = self.isFullScreen()
        self._sidebar_was_visible = self.is_sidebar_visible()
        self.set_sidebar_visible(False)
        self.menuBar().hide()
        self.statusBar().hide()
        self.tabs.set_tab_bar_visible(False)
        self.showFullScreen()
        self.immersive_changed.emit(True)

    def leave_immersive(self) -> None:
        if not self._immersive:
            return
        self._immersive = False
        self.set_sidebar_visible(self._sidebar_was_visible)
        self.menuBar().show()
        self.statusBar().show()
        self.tabs.set_tab_bar_visible(True)
        if not self._was_full_screen:
            self.showNormal()
        self.immersive_changed.emit(False)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        for guard in self.close_guards:
            if not guard():
                event.ignore()
                return
        for hook in self.close_hooks:
            hook()
        super().closeEvent(event)

    def _on_escape(self) -> None:
        if self._immersive:
            self.leave_immersive()
