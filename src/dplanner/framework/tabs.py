"""Tab hosting for activities.

The TabHost owns the mapping between tabs and activities and drives the activation
lifecycle. It deliberately does not know the window: immersive mode and window titles are
the window's reaction to ``activity_changed``, wired in :mod:`dplanner.framework.main_window`.
"""

from collections.abc import Callable

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from dplanner.core.signals import Signal
from dplanner.framework.activity import Activity
from dplanner.framework.context import (
    SCOPE_ACTIVITY,
    SCOPE_SELECTION,
    ContextService,
    activity_uri,
)

type ActivityFactory = Callable[[str | None], Activity]


class TabHost(QWidget):
    """A QTabWidget whose pages are activities, deduplicated by activity URI."""

    def __init__(self, context: ContextService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TabHost")
        self._context = context
        self._factories: dict[str, ActivityFactory] = {}
        self._activities: dict[QWidget, Activity] = {}
        self._current: Activity | None = None

        self.activity_changed: Signal[Activity | None] = Signal()

        self._tab_widget = QTabWidget(self)
        self._tab_widget.setObjectName("ActivityTabs")
        self._tab_widget.setMovable(True)
        self._tab_widget.setTabsClosable(True)
        self._tab_widget.setDocumentMode(True)
        self._tab_widget.currentChanged.connect(self._on_current_changed)
        self._tab_widget.tabCloseRequested.connect(self._on_close_requested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tab_widget)

    # -- registration ---------------------------------------------------------------------

    def register_factory(self, kind: str, factory: ActivityFactory) -> None:
        if kind in self._factories:
            raise ValueError(f"activity kind {kind!r} already registered")
        self._factories[kind] = factory

    # -- opening and lookup ---------------------------------------------------------------

    def open(self, kind: str, target: str | None = None) -> Activity:
        """Open (or focus) the activity identified by ``kind`` and ``target``."""
        uri = activity_uri(kind, target)
        for widget, activity in self._activities.items():
            if activity.uri == uri:
                self._tab_widget.setCurrentWidget(widget)
                return activity

        activity = self._factories[kind](target)
        # A factory may normalize its target (a singleton ignores it entirely), so the
        # pre-factory check above can miss: one tab per activity URI must still hold.
        for widget, existing in self._activities.items():
            if existing.uri == activity.uri:
                activity.close()
                activity.widget.deleteLater()
                self._tab_widget.setCurrentWidget(widget)
                return existing
        self._activities[activity.widget] = activity
        index = self._tab_widget.addTab(activity.widget, activity.title)
        self._tab_widget.setCurrentIndex(index)
        return activity

    def current_activity(self) -> Activity | None:
        return self._current

    def activities(self) -> list[Activity]:
        return list(self._activities.values())

    def set_tab_title(self, activity: Activity, title: str) -> None:
        index = self._tab_widget.indexOf(activity.widget)
        if index != -1:
            self._tab_widget.setTabText(index, title)

    def focus(self, activity: Activity) -> bool:
        """Make ``activity``'s tab current; False if it is no longer open."""
        if activity.widget not in self._activities:
            return False
        self._tab_widget.setCurrentWidget(activity.widget)
        return True

    def reannounce_current(self) -> None:
        """Re-emit ``activity_changed`` for an activity that changed identity in place
        (an editor retargeted by Next/Previous) so observers can follow."""
        if self._current is not None:
            self.activity_changed.emit(self._current)

    def close_current(self) -> None:
        """Close the current tab (the ⌘W path); a no-op when nothing is open."""
        index = self._tab_widget.currentIndex()
        if index != -1:
            self._on_close_requested(index)

    def close_activity(self, activity: Activity) -> bool:
        """Close one tab wherever it is; False if it is no longer open.

        The symmetric partner of :meth:`focus`. A feature whose subject was deleted has to
        be able to take its tab with it, and the alternative — reaching into the tab widget
        — is exactly the shortcut the layering rules exist to prevent. Named for the
        activity rather than called ``close`` because a ``TabHost`` is itself a QWidget.
        """
        index = self._tab_widget.indexOf(activity.widget)
        if index == -1:
            return False
        self._on_close_requested(index)
        return True

    def set_tab_bar_visible(self, visible: bool) -> None:
        self._tab_widget.tabBar().setVisible(visible)

    # -- lifecycle ------------------------------------------------------------------------

    def _on_current_changed(self, index: int) -> None:
        previous, self._current = self._current, None
        if previous is not None:
            previous.on_deactivated()
        # The old activity's claims about what the user is doing are void either way; the
        # new one re-populates these scopes from on_activated().
        self._context.clear_scope(SCOPE_SELECTION)
        self._context.clear_scope(SCOPE_ACTIVITY)

        widget = self._tab_widget.widget(index)
        activity = self._activities.get(widget) if widget is not None else None
        self._current = activity
        if activity is not None:
            activity.on_activated()
        self.activity_changed.emit(activity)

    def _on_close_requested(self, index: int) -> None:
        widget = self._tab_widget.widget(index)
        if widget is None:
            return
        activity = self._activities.pop(widget, None)
        # removeTab fires currentChanged (handling deactivation) when the current tab goes;
        # the activity must already be out of the map so it cannot be re-selected.
        self._tab_widget.removeTab(index)
        if activity is not None:
            activity.close()
        widget.deleteLater()
