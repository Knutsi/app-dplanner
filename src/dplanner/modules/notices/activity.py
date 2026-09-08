"""The Notices tab: the sources' switches over a list of what stands, each row a door.

A singleton tab, like Telemetry. The control strip carries one checkable toggle per source
— a checked one is being watched — and the verbs on the picked row: Open goes to the spot
that resolves it, Mute hides it from the bell until it has cleared and come back. Muted
rows stay in the list, greyed, after the live ones: a mute is undone from where it was
made. With nothing to list, one line says why — no source on, or nothing standing.
"""

from typing import TYPE_CHECKING

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.activity import ActivityBase
from dplanner.framework.context import SCOPE_ACTIVITY, ContextNode, ContextService, activity_uri
from dplanner.framework.list_rows import DETAIL_ROLE, MUTED_ROLE, TRAILING_ROLE, TwoLineDelegate
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.toolbar import control_bar
from dplanner.modules.notices.sources import mute_key
from dplanner.theme.icons import bell_icon
from dplanner.theme.themes import Theme

if TYPE_CHECKING:
    from dplanner.modules.notices.module import NoticesModule, Standing

NOTICES_KIND = "notices"

NOTHING_WATCHED = "Nothing is being watched — switch a source on above."
NOTHING_STANDING = "Nothing needs attention."


class NoticesActivity(ActivityBase):
    def __init__(
        self, module: "NoticesModule", context: ContextService, theme: ThemeService
    ) -> None:
        self._module = module
        self._context = context
        self._theme = theme
        self._rows: list[Standing] = []

        self.uri = activity_uri(NOTICES_KIND)
        self.title = "Notices"

        self.widget = QWidget()
        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.bar = control_bar(self.widget)
        self.switches: dict[str, QAction] = {}
        for source in module.sources():
            switch = QAction(source.label, self.bar)
            switch.setCheckable(True)
            switch.setChecked(module.is_on(source.id))
            switch.setToolTip(f"Watch: {source.label}")
            switch.toggled.connect(
                lambda on, source_id=source.id: self._module.set_on(source_id, bool(on))
            )
            self.bar.addAction(switch)
            self.switches[source.id] = switch
        spacer = QWidget(self.bar)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.bar.addWidget(spacer)
        self.check_now = QAction("Check Now", self.bar)
        self.check_now.triggered.connect(lambda: self._module.rescan())
        self.bar.addAction(self.check_now)
        self.bar.addSeparator()
        self.open_action = QAction("Open", self.bar)
        self.open_action.triggered.connect(lambda: self.open_current())
        self.bar.addAction(self.open_action)
        self.mute_action = QAction("Mute", self.bar)
        self.mute_action.triggered.connect(lambda: self.toggle_mute_current())
        self.bar.addAction(self.mute_action)
        layout.addWidget(self.bar)

        self.list = QListWidget(self.widget)
        self.list.setObjectName("NoticesList")
        self.list.setItemDelegate(TwoLineDelegate(self.list))
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.itemActivated.connect(lambda _item: self.open_current())
        self.list.currentItemChanged.connect(lambda _now, _before: self._settle_verbs())
        layout.addWidget(self.list, 1)

        self.empty = QLabel(self.widget)
        self.empty.setObjectName("InspectorNote")
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)

        self._unsubscribe = module.changed.connect(self.refresh)
        self._untheme = theme.changed.connect(self._repaint)
        self.refresh()

    # -- activity contract -----------------------------------------------------------------

    def on_activated(self) -> None:
        self._context.set_scope(SCOPE_ACTIVITY, (ContextNode(self.uri),))
        self._module.rescan()

    def close(self) -> None:
        self._unsubscribe()
        self._untheme()

    # -- the list --------------------------------------------------------------------------

    def refresh(self) -> None:
        for source_id, switch in self.switches.items():
            on = self._module.is_on(source_id)
            if switch.isChecked() != on:
                switch.blockSignals(True)
                switch.setChecked(on)
                switch.blockSignals(False)
        picked = self._current_key()
        self._rows = self._module.standing()
        icon = bell_icon(self._theme.current.text_secondary)
        self.list.clear()
        for row in self._rows:
            item = QListWidgetItem(row.notice.title)
            item.setIcon(icon)
            item.setData(DETAIL_ROLE, row.notice.detail)
            item.setData(TRAILING_ROLE, row.notice.where or row.source.label)
            item.setData(MUTED_ROLE, row.muted)
            self.list.addItem(item)
            if mute_key(row.source.id, row.notice) == picked:
                self.list.setCurrentItem(item)
        has_rows = bool(self._rows)
        self.list.setVisible(has_rows)
        self.empty.setVisible(not has_rows)
        self.empty.setText(NOTHING_STANDING if self._module.any_on() else NOTHING_WATCHED)
        self._settle_verbs()

    def rows(self) -> list[tuple[str, bool]]:
        """What the list shows, for a test: (title, muted) in list order."""
        return [(row.notice.title, row.muted) for row in self._rows]

    def current(self) -> "Standing | None":
        index = self.list.currentRow()  # The list is built from ``_rows`` in order.
        return self._rows[index] if 0 <= index < len(self._rows) else None

    def open_current(self) -> None:
        row = self.current()
        if row is not None:
            self._module.go_to(row.notice)

    def toggle_mute_current(self) -> None:
        row = self.current()
        if row is not None:
            self._module.set_muted(row, not row.muted)

    def _current_key(self) -> str | None:
        row = self.current()
        return None if row is None else mute_key(row.source.id, row.notice)

    def _settle_verbs(self) -> None:
        row = self.current()
        self.open_action.setEnabled(row is not None)
        self.mute_action.setEnabled(row is not None)
        self.mute_action.setText("Unmute" if row is not None and row.muted else "Mute")

    def _repaint(self, _theme: Theme) -> None:
        self.refresh()
