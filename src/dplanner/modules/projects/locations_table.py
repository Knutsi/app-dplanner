"""The Locations table: every place a project is about, one row each, with the verbs
that add and change them.

One widget for both modes of the Project dialog — over the model's placements in
settings mode, over a draft in create mode — so neither can word a row the other way.
The table is the ``Table`` primitive (DESIGN.md's roster shape), four columns: the
location by its role, the repository as a person knows it, the position in it, and where
that is on this machine, greyed where nothing is here yet. Above it, **Add ▾** renders the
role registry — a module declares a role and the entry appears — and **⋯** the selected
row's verbs, which a right-click on a row renders too. The widget knows nothing about
what a verb does: it is handed a function returning the row's entries, the ⋯ discipline
every project surface shares (`repo_picker.RepoAction`).
"""

from collections.abc import Callable, Mapping, Sequence

from PySide6.QtCore import QPoint, Qt
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from dplanner.domain.locations import Location, LocationRole, Placement
from dplanner.framework.table import Cell, Column, Table
from dplanner.framework.widgets import EmptyState, caption
from dplanner.modules.projects.repo_picker import (
    Entry,
    RepoAction,
    menu_button,
    menu_of,
    popup_menu,
    tool_button,
)
from dplanner.modules.projects.repos import location_words
from dplanner.theme.icons import (
    beaker_icon,
    code_icon,
    folder_icon,
    plus_icon,
    read_icon,
    spec_icon,
)
from dplanner.theme.tokens import CAPTION_GAP, FIELD_GAP

EMPTY_WORDS = "No locations yet — add the code this project changes."

# The glyph a role wears, by id; a role this build does not know wears the folder.
ROLE_GLYPHS: Mapping[str, Callable[[str], QIcon]] = {
    "code": code_icon,
    "specs": spec_icon,
    "docs": read_icon,
    "tests": beaker_icon,
}


def role_icon(role_id: str) -> Callable[[str], QIcon]:
    return ROLE_GLYPHS.get(role_id, folder_icon)


class LocationsTable(QWidget):
    add_requested = QtSignal(str)  # A role id, from the Add ▾ menu.
    activated = QtSignal(str)  # A row's location id — a double-click, which edits it.
    selection_changed = QtSignal()

    def __init__(
        self,
        roles: Mapping[str, LocationRole],
        entries: Callable[[Location], Sequence[Entry]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._roles = roles
        self._entries = entries
        self._ink = ""
        self._placements: tuple[Placement, ...] = ()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(CAPTION_GAP)

        header = QHBoxLayout()
        layout.addLayout(header)
        header.setSpacing(FIELD_GAP)
        header.addWidget(caption("Locations", self))
        header.addStretch(1)
        self.add_button = tool_button("Add a location…", "AddLocationButton", self)
        self.add_button.clicked.connect(self._add_popup)
        self.more_button = menu_button("What you can do with the selected location", self)
        self.more_button.clicked.connect(self._more_popup)
        header.addWidget(self.add_button)
        header.addWidget(self.more_button)

        self.table = Table(
            (
                Column("Location", glyph=True),
                Column("Repository"),
                Column("Position"),
                Column("On this machine", resize="stretch"),
            ),
            parent=self,
        )
        self.table.setObjectName("LocationsTable")
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.itemDoubleClicked.connect(lambda item: self._activate(item.row()))
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.empty = EmptyState(EMPTY_WORDS, self, stands_in_for=self.table)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.empty, 1)
        self.empty.say(EMPTY_WORDS)
        self._on_selection()

    # -- what it shows ---------------------------------------------------------------------------

    def paint(self, ink: str) -> None:
        """Repaint every glyph in the theme's ink, and keep it for the pop-ups."""
        self._ink = ink
        self.add_button.setIcon(plus_icon(ink))
        self.show_rows(self._placements)

    def show_rows(self, placements: Sequence[Placement]) -> None:
        picked = self.selected()
        self._placements = tuple(placements)
        self.table.clear_rows()
        for placement in placements:
            words = location_words(placement, self._roles)
            glyph = role_icon(placement.location.role)(self._ink) if self._ink else None
            self.table.add_row(
                (
                    Cell(words.name, glyph=glyph),
                    Cell(words.repository, tooltip=placement.location.repository),
                    Cell(words.position),
                    Cell(words.where, secondary=words.missing, tooltip=words.where),
                )
            )
        self.table.fit_columns()
        self.empty.say("" if placements else EMPTY_WORDS)
        if picked is not None:
            for row, placement in enumerate(placements):
                if placement.location.id == picked.id:
                    self.table.selectRow(row)
                    break
        self._on_selection()

    def rows(self) -> list[tuple[str, str, str, str]]:
        """What the table shows, one tuple per row — the test seam."""
        return [
            tuple(  # type: ignore[misc]
                item.text() if (item := self.table.item(row, column)) is not None else ""
                for column in range(4)
            )
            for row in range(self.table.rowCount())
        ]

    def selected(self) -> Location | None:
        rows = {index.row() for index in self.table.selectedIndexes()}
        if len(rows) != 1:
            return None
        row = rows.pop()
        return self._placements[row].location if row < len(self._placements) else None

    def select(self, location_id: str) -> None:
        for row, placement in enumerate(self._placements):
            if placement.location.id == location_id:
                self.table.selectRow(row)
                return

    # -- the verbs -------------------------------------------------------------------------------

    def add_entries(self) -> list[Entry]:
        """One entry per role, in the registry's order — the Add ▾ menu."""
        return [
            RepoAction(f"{role.label}…", role_icon(role.id), self._add_verb(role.id))
            for role in self._roles.values()
        ]

    def _add_verb(self, role_id: str) -> Callable[[], None]:
        return lambda: self.add_requested.emit(role_id)

    def _add_popup(self) -> None:
        popup_menu(self.add_button, self.add_entries(), self._ink)

    def _more_popup(self) -> None:
        location = self.selected()
        if location is not None:
            popup_menu(self.more_button, list(self._entries(location)), self._ink)

    def _context_menu(self, point: QPoint) -> None:
        """A right-click renders the row's ⋯ — the row under the cursor made current
        first, so the menu reads the same selection the button would."""
        item = self.table.itemAt(point)
        if item is None:
            return
        self.table.selectRow(item.row())
        location = self.selected()
        if location is None:
            return
        menu = menu_of(list(self._entries(location)), self._ink, self)
        menu.exec(self.table.viewport().mapToGlobal(point))
        menu.deleteLater()

    def _activate(self, row: int) -> None:
        if row < len(self._placements):
            self.activated.emit(self._placements[row].location.id)

    def _on_selection(self) -> None:
        self.more_button.setEnabled(self.selected() is not None)
        self.selection_changed.emit()
