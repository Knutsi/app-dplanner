"""The Archive tab: the projects archived out of this library, and the way back.

One tab for the whole library — there is no node standing for the archive, so it has no
target and follows no entity (``AllTestsActivity``'s shape, with its only-while-current
rule kept by hand). A row is read off the project's own ``project.dproj`` through
:func:`~dplanner.domain.plan_repo.summary` and never opened: an archived project is not
loaded. A folder that has gone says so in its row rather than vanishing, so Remove from
Library can still take it off the list.

The strip and the right-click are the Project menu's *membership* band, so a row here and
a row under the index's Archive folder offer the same verbs by construction. It rebuilds
straight off the store's ``archive_changed``: the signal is rare and the list is short, so
nothing here is coalesced and no Updating indicator stands on the strip.
"""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QHBoxLayout, QMenu, QVBoxLayout, QWidget

from dplanner.core.signals import Signal
from dplanner.domain.plan_repo import ProjectSummary, summary
from dplanner.framework.action_menu import build_menu
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.activity import ActivityBase
from dplanner.framework.context import (
    SCOPE_ACTIVITY,
    SCOPE_SELECTION,
    ContextNode,
    ContextService,
    activity_uri,
    selection_uri,
)
from dplanner.framework.list_rows import HOST_ROLE
from dplanner.framework.table import Cell, Column, Table
from dplanner.framework.toolbar import Toolbar
from dplanner.framework.widgets import EmptyState, caption
from dplanner.modules.projects.verbs import ARCHIVED_KIND
from dplanner.theme.tokens import CAPTION_GAP, FIELD_GAP, PANEL_MARGIN, SECTION_GAP

ARCHIVE_KIND = "archive"
NOTHING_ARCHIVED = (
    "Nothing archived. Project ▸ Archive Project takes a project out of the library "
    "and keeps it here."
)
# What acts on the picked row: the membership band, less the verbs about a live project.
STRIP_VERBS = ("projects.restore", "projects.remove")
COLUMNS = (Column("Project"), Column("Steps", numeric=True), Column("Folder"))
DIRECTORY_ROLE = HOST_ROLE  # The row's directory, as the archive spells it.


def archived_label(directory: Path, found: ProjectSummary) -> str:
    """What a row calls an archived project — the Archive tab's rows and the index's say
    it in the same words, a folder that has gone included."""
    return found.title if found.present else f"{directory.name} — folder missing"


class ArchiveActivity(ActivityBase):
    def __init__(
        self,
        *,
        archived: Callable[[], list[Path]],
        changed: Signal[()],
        actions: ActionRegistry,
        context: ContextService,
    ) -> None:
        super().__init__()
        self._archived = archived
        self._actions = actions
        self._context = context
        self._is_active = False  # A background pane does not speak for the user.
        self.uri = activity_uri(ARCHIVE_KIND)
        self.title = "Archive"

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(SECTION_GAP)
        head = QVBoxLayout()
        layout.addLayout(head)  # Before it is filled: a parentless layout leaks its items.
        head.setSpacing(CAPTION_GAP)
        head.addWidget(caption("Archived projects", page))

        strip = QHBoxLayout()
        layout.addLayout(strip)
        strip.setSpacing(FIELD_GAP)
        self.controls = Toolbar(page)
        for action_id in STRIP_VERBS:
            self.controls.add_action(actions, context, action_id)
        strip.addWidget(self.controls, 1)

        self.table = Table(COLUMNS, parent=page)
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.table, 1)
        self.empty = EmptyState(NOTHING_ARCHIVED, page, stands_in_for=self.table)
        layout.addWidget(self.empty, 1)
        self.widget = page

        self._unsubscribe = changed.connect(self._refresh)
        self._refresh()

    # -- the activity contract -----------------------------------------------------------------

    def on_activated(self) -> None:
        self._is_active = True
        self._context.set_scope(SCOPE_ACTIVITY, (ContextNode(self.uri),))
        self._on_selection()

    def on_deactivated(self) -> None:
        self._is_active = False

    def close(self) -> None:
        self._unsubscribe()
        self.controls.dispose()

    # -- the rows ------------------------------------------------------------------------------

    def pick(self, directory: Path) -> None:
        """Select the row for ``directory`` — what a click on its row in the index lands on."""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(DIRECTORY_ROLE) == str(directory):
                self.table.selectRow(row)
                self.table.scrollToItem(item)
                return

    def picked(self) -> Path | None:
        rows = {index.row() for index in self.table.selectedIndexes()}
        if len(rows) != 1:
            return None
        item = self.table.item(rows.pop(), 0)
        return None if item is None else Path(item.data(DIRECTORY_ROLE))

    def _refresh(self) -> None:
        """A whole redraw, keeping the pick: the list is tens of rows, never thousands."""
        kept = self.picked()
        directories = self._archived()
        self.table.blockSignals(True)  # One publish at the end, not one per cleared row.
        try:
            self.table.clear_rows()
            for directory in directories:
                found = summary(directory)
                gone = not found.present
                self.table.add_row(
                    (
                        Cell(archived_label(directory, found), secondary=gone),
                        Cell("" if gone else str(found.steps)),
                        Cell(str(directory), secondary=True),
                    ),
                    data={DIRECTORY_ROLE: str(directory)},
                )
            if kept is not None:
                self.pick(kept)
        finally:
            self.table.blockSignals(False)
        self.empty.say("" if directories else NOTHING_ARCHIVED)
        self._on_selection()

    def _on_selection(self) -> None:
        if not self._is_active:
            return
        directory = self.picked()
        nodes = (
            ()
            if directory is None
            else (ContextNode(selection_uri(ARCHIVED_KIND, str(directory))),)
        )
        self._context.set_scope(SCOPE_SELECTION, nodes)

    def row_menu(self) -> QMenu:
        """What a right-click on a row renders: the membership band, and nothing else."""
        return build_menu(self._actions, self._context, "Project", self.table, group="membership")

    def _on_context_menu(self, position: QPoint) -> None:
        row = self.table.rowAt(position.y())
        if row < 0:
            return
        self.table.selectRow(row)  # What is under the cursor is current before the menu.
        self.row_menu().exec(self.table.viewport().mapToGlobal(position))
