"""Tab hosting for activities, in one or more groups side by side.

The TabHost owns the mapping between tabs and activities and drives the activation
lifecycle. It deliberately does not know the window: window titles are the window's
reaction to ``activity_changed``, wired in :mod:`dplanner.framework.main_window`.

**Groups live in here, and nothing outside knows they exist.** The host is still the single
widget the window is handed, and every method below means what it always meant — ``open`` may
focus a tab in another group, ``activities()`` is everything everywhere, ``current_activity()``
is whatever the *active* group is showing. That is the whole reason the groups are internal:
a module asks for a tab and gets one, and the split is a thing the user arranged.

**One notion of "current", and one way to announce it.** Every action resolves its target
through the activity scope, so "which pane is the user in" is not a decoration — it decides
what every menu item does. A group becomes active through the same routine a tab switch uses
(:meth:`_announce`), which is the only path by which the menu bar, the toolbars, the
right-click menus, undo coalescing and autosave learn anything at all.

**Only deliberate acts change the active group** — opening, closing, moving, or the user
touching a pane. A ``currentChanged`` from a background group never does: closing a tab in a
pane the user is not in (which happens whenever a project is deleted) must not steal their
place.
"""

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QFont, QPaintEvent
from PySide6.QtWidgets import (
    QApplication,
    QSplitter,
    QStyle,
    QStyleOptionTab,
    QStylePainter,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from dplanner.core.signals import Signal
from dplanner.framework.activity import Activity
from dplanner.framework.context import SCOPE_ACTIVITY, SCOPE_SELECTION, ContextService, activity_uri

type ActivityFactory = Callable[[str | None], Activity]

# Three is enough to be useful and few enough that every pane stays wide enough to work in.
MAX_GROUPS = 3


class _PreviewTabBar(QTabBar):
    """A tab bar that can paint one tab's title in italics — the preview tab's mark.

    With no preview in the bar it defers wholly to Qt's own painting, so the ordinary case
    carries no custom-paint risk. With one, every tab is drawn through the style with the
    same option ``initStyleOption`` fills — which carries ``setTabTextColor``, so the
    host's active/inactive dimming keeps working underneath the italics.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._preview_index = -1

    def set_preview_index(self, index: int) -> None:
        if index != self._preview_index:
            self._preview_index = index
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        if not 0 <= self._preview_index < self.count():
            super().paintEvent(event)
            return
        painter = QStylePainter(self)
        italic = QFont(self.font())
        italic.setItalic(True)
        # The selected tab is drawn last so its shape overlaps its neighbours, the way the
        # native painting layers them.
        indexes = [i for i in range(self.count()) if i != self.currentIndex()]
        if self.currentIndex() != -1:
            indexes.append(self.currentIndex())
        option = QStyleOptionTab()
        for index in indexes:
            self.initStyleOption(option, index)
            painter.setFont(italic if index == self._preview_index else self.font())
            painter.drawControl(QStyle.ControlElement.CE_TabBarTab, option)


class _TabGroup(QTabWidget):
    """A QTabWidget wearing a :class:`_PreviewTabBar` — ``setTabBar`` is protected, so
    installing one takes a subclass."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTabBar(_PreviewTabBar(self))


class TabHost(QWidget):
    """Activities in tabs, deduplicated by URI, in up to :data:`MAX_GROUPS` groups."""

    def __init__(self, context: ContextService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TabHost")
        self._context = context
        self._factories: dict[str, ActivityFactory] = {}
        # Page widget → activity, across every group. Keeping this one flat map is what lets
        # `activities()`, `set_tab_title` and `close_activity` stay group-agnostic.
        self._activities: dict[QWidget, Activity] = {}
        self._current: Activity | None = None
        self._announced: tuple[QTabWidget, Activity | None] | None = None
        self._suspended = 0
        # At most one preview tab in the host: the VS Code arrangement, where a glance
        # opens into a slot the next glance reuses, and only a deliberate act keeps it.
        self._preview: Activity | None = None

        self.activity_changed: Signal[Activity | None] = Signal()
        # Which tabs are open, or in what order, changed — opened, closed, moved between
        # panes or dragged within one. Distinct from ``activity_changed``, which is only
        # about which tab is *current*: closing a tab the user is not on changes the list
        # and nothing else, and a listener that persists the list would never hear of it.
        self.tabs_changed: Signal[()] = Signal()
        # A tab was right-clicked, and it is now the current one. Carries where to pop up.
        # The host builds no menu of its own: what a tab offers is application vocabulary,
        # and the module that owns the tab verbs renders them from the action registry.
        self.tab_menu_requested: Signal[QPoint] = Signal()

        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        # A group dragged to zero width would be an invisible pane that still holds tabs —
        # exactly the state "a group vanishes when it empties" exists to prevent.
        self._splitter.setChildrenCollapsible(False)
        self._groups: list[QTabWidget] = []
        self._watcher = _ActiveGroupWatcher(self)
        self._active = self._new_group(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._splitter)

    # -- registration ------------------------------------------------------------------------

    def register_factory(self, kind: str, factory: ActivityFactory) -> None:
        if kind in self._factories:
            raise ValueError(f"activity kind {kind!r} already registered")
        self._factories[kind] = factory

    def can_open(self, kind: str) -> bool:
        """Whether this build has an activity of that kind at all.

        :meth:`open` raises for one it does not, which is right for a caller naming a kind
        it registered itself. A caller working from a *remembered* kind is asking a real
        question — a feature can be gone since it was written down — and this is how it
        asks without an exception for control flow.
        """
        return kind in self._factories

    # -- opening ---------------------------------------------------------------------------

    def open(self, kind: str, target: str | None = None, *, preview: bool = False) -> Activity:
        """Open (or focus) the activity identified by ``kind`` and ``target``.

        Dedupe is global: one tab per URI across every group, so opening something already
        open brings you to it rather than making a second copy.

        ``preview=True`` opens a *preview* tab — the next preview replaces it, and a
        deliberate act keeps it: a non-preview open of its URI, or moving its tab, pins it.
        A preview-open of something already open is a plain focus and changes nothing —
        which is also what makes the double-click sequence work with no timer: the first
        click previews, the second's activation pins, and any trailing click re-focuses.
        """
        uri = activity_uri(kind, target)
        existing = self._by_uri(uri)
        if existing is not None:
            if not preview:
                self._pin(existing)
            self.focus(existing)
            return existing

        activity = self._factories[kind](target)
        # A factory may normalize its target (a singleton ignores it entirely), so the
        # pre-factory check above can miss: one tab per activity URI must still hold.
        duplicate = self._by_uri(activity.uri)
        if duplicate is not None:
            activity.close()
            activity.widget.deleteLater()
            if not preview:
                self._pin(duplicate)
            self.focus(duplicate)
            return duplicate

        self._suspended += 1
        try:
            if preview and self._preview is not None:
                # Replace, not accumulate: closing the old preview and adding the new one
                # is a single move to the user, so it announces once, below.
                found = self._locate(self._preview.widget)
                if found is not None:
                    self._close(*found)
            self._activities[activity.widget] = activity
            index = self._active.addTab(activity.widget, activity.title)
            self._active.setCurrentIndex(index)
            if preview:
                self._preview = activity
        finally:
            self._suspended -= 1
        self._announce()
        self.tabs_changed.emit()
        return activity

    def is_preview(self, activity: Activity) -> bool:
        return activity is self._preview

    def _pin(self, activity: Activity) -> None:
        """Make a preview permanent. A no-op for anything that is not the preview.

        Repaints itself: pinning the tab the user is already on changes nothing the
        announcement would notice, and the italics must still go.
        """
        if self._preview is activity:
            self._preview = None
            self._paint_active()

    def focus(self, activity: Activity) -> bool:
        """Make ``activity``'s tab current, in whichever group holds it. False if closed."""
        found = self._locate(activity.widget)
        if found is None:
            return False
        group, index = found
        group.setCurrentIndex(index)
        self._active = group
        self._announce()
        return True

    # -- what is open ------------------------------------------------------------------------

    def current_activity(self) -> Activity | None:
        return self._current

    def activities(self) -> list[Activity]:
        """Every open activity, in every group, in the order their tabs sit."""
        found: list[Activity] = []
        for group in self._groups:
            for index in range(group.count()):
                widget = group.widget(index)
                activity = self._activities.get(widget) if widget is not None else None
                if activity is not None:
                    found.append(activity)
        return found

    def after_current(self) -> list[Activity]:
        """The activities in tabs to the right of the current one, in its own bar.

        The one thing about groups the host cannot hide: "to the right" is a fact about a
        single tab bar, and a caller that wanted to work it out would have to be told the
        groups exist. So it answers the question instead of exposing them.
        """
        found: list[Activity] = []
        for index in range(self._active.currentIndex() + 1, self._active.count()):
            widget = self._active.widget(index)
            activity = self._activities.get(widget) if widget is not None else None
            if activity is not None:
                found.append(activity)
        return found

    def set_tab_title(self, activity: Activity, title: str) -> None:
        found = self._locate(activity.widget)
        if found is not None:
            group, index = found
            group.setTabText(index, title)

    def tab_title(self, activity: Activity) -> str:
        found = self._locate(activity.widget)
        return "" if found is None else found[0].tabText(found[1])

    # -- closing -----------------------------------------------------------------------------

    def close_current(self) -> None:
        """Close the current tab (the ⌘W path); a no-op when nothing is open."""
        index = self._active.currentIndex()
        if index != -1:
            self._close(self._active, index)

    def close_activity(self, activity: Activity) -> bool:
        """Close one tab wherever it is; False if it is no longer open.

        The symmetric partner of :meth:`focus`. A feature whose subject was deleted has to
        be able to take its tab with it, and the alternative — reaching into the tab widget
        — is exactly the shortcut the layering rules exist to prevent.
        """
        found = self._locate(activity.widget)
        if found is None:
            return False
        self._close(*found)
        return True

    # -- groups --------------------------------------------------------------------------------

    def group_count(self) -> int:
        return len(self._groups)

    def can_move_right(self) -> bool:
        """True when moving would actually change what is on screen.

        Moving the only tab out of the only group would create a group, move the tab and
        then empty and drop the group it came from — a verb whose whole effect is nothing.
        """
        index = self._groups.index(self._active)
        if self._active.currentIndex() == -1:
            return False
        return index + 1 < len(self._groups) or (
            len(self._groups) < MAX_GROUPS and self._active.count() > 1
        )

    def can_move_left(self) -> bool:
        """Left merges and never creates, so the group list only ever grows rightwards."""
        return self._groups.index(self._active) > 0 and self._active.currentIndex() != -1

    def move_current_right(self) -> None:
        if self.can_move_right():
            self._move(1)

    def move_current_left(self) -> None:
        if self.can_move_left():
            self._move(-1)

    def dispose(self) -> None:
        """Stop watching the application. Registered in the builder's close hooks.

        A host outlives its window briefly when a workspace is reopened, and a watcher that
        kept filtering would answer for a window that has gone.
        """
        self._watcher.dispose()

    # -- internals ---------------------------------------------------------------------------

    def _new_group(self, position: int) -> QTabWidget:
        group = _TabGroup(self)
        group.setObjectName("ActivityTabs")
        group.setMovable(True)
        group.setTabsClosable(True)
        group.setDocumentMode(True)
        group.currentChanged.connect(lambda _index, g=group: self._on_current_changed(g))
        group.tabCloseRequested.connect(lambda index, g=group: self._close(g, index))
        group.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        group.tabBar().customContextMenuRequested.connect(
            lambda position, g=group: self._on_tab_menu(g, position)
        )
        group.tabBar().tabMoved.connect(lambda _frm, to, g=group: self._on_tab_moved(g, to))
        self._groups.insert(position, group)
        self._splitter.insertWidget(position, group)
        self._even_sizes()
        self._watcher.set_watching(len(self._groups) > 1)
        return group

    def _drop_group(self, group: QTabWidget) -> None:
        """Remove an emptied group. Its pages must already have gone somewhere else."""
        if len(self._groups) == 1 or group.count():
            return
        group.currentChanged.disconnect()
        group.tabCloseRequested.disconnect()
        self._groups.remove(group)
        if self._active is group:
            self._active = self._groups[0]
        # QSplitter has no removeWidget; reparenting is what takes it out, synchronously.
        group.setParent(None)
        group.deleteLater()
        self._even_sizes()
        self._watcher.set_watching(len(self._groups) > 1)

    def _even_sizes(self) -> None:
        if self._groups:
            self._splitter.setSizes([max(1, self.width() // len(self._groups))] * len(self._groups))

    def _locate(self, widget: QWidget) -> tuple[QTabWidget, int] | None:
        for group in self._groups:
            index = group.indexOf(widget)
            if index != -1:
                return group, index
        return None

    def _by_uri(self, uri: str) -> Activity | None:
        return next((a for a in self._activities.values() if a.uri == uri), None)

    def _move(self, offset: int) -> None:
        source = self._active
        index = source.currentIndex()
        widget = source.widget(index)
        if widget is None:
            return
        title = source.tabText(index)
        activity = self._activities.get(widget)
        if activity is not None and activity is self._preview:
            # Moving a tab to another pane is arranging the window around it — keeping it.
            self._preview = None
        position = self._groups.index(source) + offset
        self._suspended += 1
        try:
            destination = (
                self._groups[position]
                if 0 <= position < len(self._groups)
                else self._new_group(max(position, 0))
            )
            # removeTab leaves the page parented to the old group, so it must be re-added
            # before that group is dropped — otherwise the group takes the page with it.
            source.removeTab(index)
            destination.setCurrentIndex(destination.addTab(widget, title))
            self._active = destination
            self._drop_group(source)
            # Focus follows the tab. Without this it stays behind in the group the tab left,
            # and the next thing the watcher hears puts the user back where they were not.
            destination.setFocus()
        finally:
            self._suspended -= 1
        self._announce()
        self.tabs_changed.emit()

    def _on_tab_moved(self, group: QTabWidget, to: int) -> None:
        """A drag within a bar. Dragging the preview itself is keeping it — that pins.

        Any drag also shifts its neighbours' indexes, so the preview mark is re-derived
        either way.
        """
        widget = group.widget(to)
        activity = self._activities.get(widget) if widget is not None else None
        if activity is not None and activity is self._preview:
            self._pin(activity)
        else:
            self._paint_active()
        self.tabs_changed.emit()

    def _close(self, group: QTabWidget, index: int) -> None:
        widget = group.widget(index)
        if widget is None:
            return
        activity = self._activities.pop(widget, None)
        if activity is not None and activity is self._preview:
            self._preview = None
        self._suspended += 1
        try:
            # removeTab fires currentChanged (handling deactivation) when the current tab
            # goes; the activity must already be out of the map so it cannot be re-selected.
            group.removeTab(index)
            self._drop_group(group)
        finally:
            self._suspended -= 1
        if activity is not None:
            activity.close()
        widget.deleteLater()
        self._announce()
        self.tabs_changed.emit()

    def activate_group_of(self, widget: QWidget | None) -> None:
        """The user touched something: make its group active, if it is in one.

        Called for every click and every focus change, so it must be cheap and idempotent —
        and it must do nothing at all when the widget belongs to no group, or clicking the
        sidebar or the menu bar would clear which pane the user was in.
        """
        if len(self._groups) == 1 or self._suspended:
            # Nothing to switch to — or the application is mid-move, and the focus churn
            # that a move causes is not the user choosing a pane.
            return
        while widget is not None:
            for group in self._groups:
                if widget is group:
                    if group is not self._active:
                        self._active = group
                        self._announce()
                    return
            widget = widget.parentWidget()

    def _on_tab_menu(self, group: QTabWidget, position: QPoint) -> None:
        """A right-click on a tab acts on *that* tab, so it becomes the current one first.

        The same move the graph canvas makes when it selects the node under the cursor: the
        menu is then built from one notion of "what the user is on", and every entry in it is
        the verb the menu bar and the palette already have.
        """
        bar = group.tabBar()
        index = bar.tabAt(position)
        widget = group.widget(index) if index != -1 else None
        activity = self._activities.get(widget) if widget is not None else None
        if activity is None:
            return  # Empty space beside the tabs; there is nothing to act on.
        self.focus(activity)
        self.tab_menu_requested.emit(bar.mapToGlobal(position))

    def _on_current_changed(self, group: QTabWidget) -> None:
        # Never sets the active group: a tab closing in a background pane must not move the
        # user. The announcement recomputes from whichever group *is* active, so a signal
        # from elsewhere is guarded out below.
        if group is self._active:
            self._announce()

    def _announce(self) -> None:
        """Say what the user is now doing. The one path everything else learns through."""
        if self._suspended:
            return
        widget = self._active.currentWidget()
        activity = self._activities.get(widget) if widget is not None else None
        # Qt reports a drag-reorder as currentChanged with the same page still current, and
        # a move keeps the activity while changing its group — so the guard is on the pair.
        if self._announced == (self._active, activity):
            return
        self._announced = (self._active, activity)

        previous, self._current = self._current, None
        if previous is not None and previous is not activity:
            previous.on_deactivated()
        # The old activity's claims about what the user is doing are void either way; the
        # new one re-populates these scopes from on_activated().
        self._context.clear_scope(SCOPE_SELECTION)
        self._context.clear_scope(SCOPE_ACTIVITY)

        self._current = activity
        if activity is not None:
            activity.on_activated()
        self._paint_active()
        self.activity_changed.emit(activity)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        """Re-tint the titles when the palette moves under them.

        :meth:`_paint_active` copies a colour out of the palette onto every tab, and a copy
        is a thing that goes stale: without this, switching the theme left each title in the
        colour of the theme its pane was last activated in.
        """
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self._paint_active()

    def _paint_active(self) -> None:
        """Dim the inactive groups' tabs, so the pane whose menus you are seeing is obvious.

        Done with the palette rather than a stylesheet: styling a QTabBar through QSS
        replaces its whole native rendering, and these tabs are deliberately unstyled.
        """
        primary = self.palette().text().color()
        faded = self.palette().text().color()
        faded.setAlpha(110)
        for group in self._groups:
            colour = primary if group is self._active else faded
            bar = group.tabBar()
            for index in range(group.count()):
                bar.setTabTextColor(index, colour)
            if isinstance(bar, _PreviewTabBar):
                # The preview mark rides the same sweep, so there is one refresh path.
                bar.set_preview_index(
                    -1 if self._preview is None else group.indexOf(self._preview.widget)
                )

    def reorder_current(self, position: int) -> None:
        """Move the current tab to ``position`` within its own bar — what a drag does.

        Exposed so the behaviour a drag produces is reachable from a test; nothing in the
        application calls it.
        """
        self._active.tabBar().moveTab(self._active.currentIndex(), position)


class _ActiveGroupWatcher(QObject):
    """Notices which pane the user last touched.

    Two sources, because neither is enough alone: ``focusChanged`` misses a click on anything
    that takes no focus — a caption, a heading, a card — and an event filter misses focus
    arriving by keyboard or from a dialog closing. The filter also has to see the press
    *before* a right-click builds its menu, since that menu reads the context as it opens.

    **The filter exists only while the window is split.** It is the only application-wide
    filter in this codebase, so it sees every mouse press in the program; with one pane there
    is nothing for it to decide, and an unsplit window is the ordinary case.

    Parented to the host, and connected through a bound method rather than a lambda, so Qt
    detaches both when the host goes. A host outlives its window briefly when a workspace is
    reopened, and a watcher that kept answering would speak for a window that has gone.
    """

    def __init__(self, host: TabHost) -> None:
        super().__init__(host)
        self._host = host
        self._live = True
        self._filtering = False
        application = QApplication.instance()
        if isinstance(application, QApplication):
            application.focusChanged.connect(self._on_focus_changed)

    def set_watching(self, wanted: bool) -> None:
        application = QApplication.instance()
        if not self._live or self._filtering == wanted or not isinstance(application, QApplication):
            return
        self._filtering = wanted
        if wanted:
            application.installEventFilter(self)
        else:
            application.removeEventFilter(self)

    def dispose(self) -> None:
        self.set_watching(False)
        self._live = False
        application = QApplication.instance()
        if isinstance(application, QApplication):
            application.focusChanged.disconnect(self._on_focus_changed)

    def _on_focus_changed(self, _old: QWidget | None, new: QWidget | None) -> None:
        # Focus going nowhere is a window losing it, not the user choosing a pane.
        if self._live and new is not None:
            self._host.activate_group_of(new)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        # Fires once per ancestor as the press propagates; activating is idempotent.
        if (
            self._live
            and event.type() == QEvent.Type.MouseButtonPress
            and isinstance(watched, QWidget)
        ):
            self._host.activate_group_of(watched)
        return super().eventFilter(watched, event)
