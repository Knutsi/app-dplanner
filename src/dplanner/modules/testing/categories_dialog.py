"""The category editor: rename, re-icon and reorganise a project's test categories.

**It is a modal, and it writes on Save.** Renaming a category rewrites every test filed
under it, and doing that per keystroke would rebuild the Tests tab under the reader's hands
while they were still deciding what to call it. So the dialog edits a *copy* — a list of
rows, each remembering the name it started with — and the whole refactor lands as one undo
step when it closes. The count on every row is what makes that safe to do blind: it says
how many tests the rename is about to move before it moves them.

**Renaming is the refactor.** A test names its category by its words (``categories.py``),
so there is no id to keep stable — the rename is the rewrite, and the dialog is the one
place that can do it without an agent. Removing a category unfiles its tests rather than
deleting them, which the row says out loud.

**The icon is picked, never typed.** ``categories.ICONS`` is the offered set, rendered as a
grid the row's glyph drops down — DESIGN.md's *a choice whose values are known is offered,
not asked for*, and the CLI's ``--icon`` refusal names the same tuple.
"""

import dataclasses
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QWidget,
    QWidgetAction,
)

from dplanner.domain.commands import Command, CompositeCommand, SetModuleDataCommand
from dplanner.domain.model import Library, NodeId, Project
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.table import Cell, Column, Table, TextEditor
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import confirm, quiet
from dplanner.modules.testing.aspect import MODULE_ID, Test, write
from dplanner.modules.testing.filing import (
    ICONS,
    UNCATEGORISED,
    Category,
    TestsChange,
    catalog,
    counts,
    rewrite,
    write_catalog,
)
from dplanner.theme.icons import ICON_SIZE, glyph_icon
from dplanner.theme.tokens import CONTROL_HEIGHT, DENSE_GAP, FIELD_GAP, SECONDARY_ALPHA

DIALOG_SIZE = (560, 460)
TITLE = "Test Categories"
NOTE = (
    "What this project files its tests under. Renaming one moves every test that carries "
    "it; nothing is written until you save."
)
NEW_NAME = "New category"
ICON_COLUMN, NAME_COLUMN, COUNT_COLUMN = range(3)
COLUMNS = (
    Column("", glyph=True),
    Column("Category", resize="stretch", editor=TextEditor(placeholder="What to call it")),
    Column("Tests", numeric=True),
)
PICKER_COLUMNS = 8  # The grid the glyphs are offered in; eight across fits the dialog.
NO_ICON = "No icon"


@dataclass
class _Row:
    """One category as the dialog is editing it, and where it came from.

    ``was`` is the name it had on disk — "" for one added here — which is what turns a
    changed ``name`` into a rename of the tests rather than a new category beside them.
    """

    was: str
    name: str
    icon: str = ""
    count: int = 0
    removed: bool = False


@dataclass(frozen=True)
class _Plan:
    """What pressing Save will do, worked out before it is done."""

    categories: list[Category] = field(default_factory=list)
    renames: list[tuple[str, str]] = field(default_factory=list)
    unfiled: list[str] = field(default_factory=list)  # Categories whose tests lose theirs.


class CategoriesDialog(DialogFrame):
    """A project's categories, edited whole and applied on Save."""

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        project_id: NodeId,
        parent: QWidget | None = None,
        *,
        opened_on: str = "",
    ) -> None:
        super().__init__(TITLE, parent, size=DIALOG_SIZE)
        self.setObjectName("CategoriesDialog")
        self._library = library
        self._undo = undo
        self._project_id = project_id
        self._rows: list[_Row] = []
        self._unfiled = 0  # How many tests carry no category — the last row's count.

        note = QLabel(NOTE, self.body)
        note.setObjectName("InspectorNote")
        note.setWordWrap(True)
        self.body_layout.addWidget(note)

        self.table = Table(COLUMNS, selection="single", parent=self.body)
        self.table.edited.connect(self._on_edited)
        self.table.clicked.connect(self._on_clicked)
        self.body_layout.addWidget(self.table, 1)

        verbs = QHBoxLayout()
        self.body_layout.addLayout(verbs)
        verbs.setSpacing(FIELD_GAP)
        self.add_row_button = quiet(QPushButton("+ Add category", self.body))
        self.add_row_button.clicked.connect(self._add)
        verbs.addWidget(self.add_row_button)
        self.remove_button = quiet(QPushButton("Remove", self.body))
        self.remove_button.clicked.connect(self._remove)
        verbs.addWidget(self.remove_button)
        verbs.addStretch(1)

        self.add_dismiss()
        self.set_primary("Save", self._save)

        self._load()
        if opened_on:
            self._select(opened_on)
        self.table.itemSelectionChanged.connect(self._sync_verbs)
        self._sync_verbs()

    # -- reading the project ---------------------------------------------------------------

    def _project(self) -> Project | None:
        if not self._library.has(self._project_id):
            return None
        return self._library.project(self._project_id)

    def _load(self) -> None:
        project = self._project()
        if project is None:
            return
        held = counts(project, archived=True)
        self._rows = [
            _Row(was=entry.name, name=entry.name, icon=entry.icon, count=held.get(entry.name, 0))
            for entry in catalog(project)
        ]
        self._unfiled = held.get(UNCATEGORISED, 0)
        self._fill()

    def _fill(self) -> None:
        keep = self._picked()
        self.table.clear_rows()
        for row in self._live():
            self.table.add_row(
                (
                    Cell(glyph=self._glyph(row.icon), tooltip="Pick a glyph for this category"),
                    Cell(value=row.name),
                    Cell(str(row.count), secondary=True),
                )
            )
        # Last, and never editable: it is what *no* category reads as, so it has no name to
        # change and no glyph to wear — but a reader counting tests needs to see it.
        self.table.add_row(
            (
                Cell(),
                Cell(UNCATEGORISED, secondary=True, editable=False),
                Cell(str(self._unfiled), secondary=True),
            )
        )
        if keep is not None and keep < len(self._live()):
            self.table.selectRow(keep)

    def _glyph(self, icon: str) -> QIcon | None:
        return glyph_icon(icon, self._glyph_ink()) if icon else None

    def _glyph_ink(self) -> QColor:
        """The tone a glyph is drawn in here — read at paint time, never stored."""
        ink = self.palette().color(QPalette.ColorRole.Text)
        ink.setAlpha(SECONDARY_ALPHA)
        return ink

    def _live(self) -> list[_Row]:
        return [row for row in self._rows if not row.removed]

    def _picked(self) -> int | None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        return rows[0] if rows else None

    def _row_at(self, row: int) -> _Row | None:
        live = self._live()
        return live[row] if 0 <= row < len(live) else None

    def _select(self, name: str) -> None:
        for at, row in enumerate(self._live()):
            if row.name.casefold() == name.casefold():
                self.table.selectRow(at)
                return

    # -- editing ---------------------------------------------------------------------------

    def _on_edited(self, row: int, column: int, value: object) -> None:
        found = self._row_at(row)
        if found is None or column != NAME_COLUMN:
            return
        found.name = str(value).strip()
        self._fill()
        self._check()

    def _on_clicked(self, index: QModelIndex) -> None:
        """A click in the glyph column drops the picker; every other click just picks a row."""
        found = self._row_at(index.row())
        if index.column() == ICON_COLUMN and found is not None:
            self.pick_icon(found, self.table.visualRect(index))

    def pick_icon(self, row: _Row, at: QRect) -> None:
        """The glyph grid, dropped under the cell that asked for it."""
        menu = QMenu(self)

        def chosen(name: str) -> None:
            self._set_icon(row, name)
            menu.close()

        action = QWidgetAction(menu)
        action.setDefaultWidget(_icon_grid(menu, row.icon, self._glyph_ink(), chosen))
        menu.addAction(action)
        menu.exec(self.table.viewport().mapToGlobal(at.bottomLeft()))
        menu.deleteLater()

    def _set_icon(self, row: _Row, name: str) -> None:
        row.icon = name
        self._fill()

    def _add(self) -> None:
        """A row with a free name, picked and open for typing — naming it is the point."""
        self._rows.append(_Row(was="", name=_free_name(self._rows)))
        self._fill()
        added = len(self._live()) - 1
        self.table.selectRow(added)
        self.table.edit(self.table.model().index(added, NAME_COLUMN))
        self._check()

    def _remove(self) -> None:
        picked = self._picked()
        found = None if picked is None else self._row_at(picked)
        if found is None:
            return
        question = (
            f"Remove {found.name!r}? Its {found.count} test"
            f"{'' if found.count == 1 else 's'} stay, filed under nothing."
            if found.count
            else f"Remove {found.name!r}? Nothing is filed under it."
        )
        if found.count and not confirm(self, "Remove Category", question, verb="Remove"):
            return
        found.removed = True
        self._fill()
        self._check()

    def _sync_verbs(self) -> None:
        picked = self._picked()
        self.remove_button.setEnabled(picked is not None and self._row_at(picked) is not None)

    def _check(self) -> str | None:
        """What stops a Save, said in the footer — DESIGN.md's *a refused primary says why*."""
        live = self._live()
        reason = None
        if any(not row.name for row in live):
            reason = "A category needs a name"
        elif any(row.name.casefold() == UNCATEGORISED.casefold() for row in live):
            reason = f"{UNCATEGORISED!r} is what a test with no category reads as"
        else:
            names = [row.name.casefold() for row in live]
            doubled = next((name for name in names if names.count(name) > 1), "")
            if doubled:
                reason = "Two categories cannot share a name"
        self.refuse(reason)
        return reason

    # -- saving ----------------------------------------------------------------------------

    def plan(self) -> _Plan:
        """What Save will do: the catalogue to store, the renames to carry into the tests,
        and the categories whose tests are about to lose theirs."""
        live = self._live()
        return _Plan(
            categories=[Category(row.name, row.icon) for row in live],
            renames=[(row.was, row.name) for row in live if row.was and row.was != row.name],
            unfiled=[row.was for row in self._rows if row.removed and row.was],
        )

    def _save(self) -> None:
        if self._check() is not None:
            return
        project = self._project()
        if project is None:
            self.reject()
            return
        plan = self.plan()
        commands: list[Command] = []
        # The tests first, then the catalogue: one undo step either way, but a reader
        # stepping through a composite sees the moves before the list that explains them.
        for step_id, tests in rewrite(project, _refactor(plan)).items():
            commands.append(SetModuleDataCommand(step_id, MODULE_ID, write(tests)))
        entry = write_catalog(project, plan.categories)
        if entry != project.module_data.get(MODULE_ID, {}):
            commands.append(SetModuleDataCommand(project.id, MODULE_ID, entry))
        if commands:
            self._undo.push(
                commands[0]
                if len(commands) == 1
                else CompositeCommand("Edit Test Categories", commands)
            )
        self.accept()


def _refactor(plan: _Plan) -> TestsChange:
    """One function over a step's tests carrying every rename and every removal.

    Applied in one pass rather than one per rename, so swapping two names — *Smoke* to
    *Regression* and *Regression* to *Smoke* — does what it says instead of landing both
    in whichever ran second.
    """
    moves = {old.casefold(): new for old, new in plan.renames}
    moves.update({name.casefold(): "" for name in plan.unfiled})

    def change(tests: Sequence[Test]) -> list[Test]:
        return [
            dataclasses.replace(test, category=moves[test.category.casefold()])
            if test.category.casefold() in moves
            else test
            for test in tests
        ]

    return change


def _free_name(rows: Sequence[_Row]) -> str:
    """``New category``, or the first numbered one nothing else has taken."""
    taken = {row.name.casefold() for row in rows if not row.removed}
    if NEW_NAME.casefold() not in taken:
        return NEW_NAME
    return next(
        f"{NEW_NAME} {n}" for n in range(2, 99) if f"{NEW_NAME} {n}".casefold() not in taken
    )


def _icon_grid(parent: QWidget, current: str, ink: QColor, pick: Callable[[str], None]) -> QWidget:
    """The offered glyphs as a grid of targets, with *No icon* first.

    A grid rather than a list: thirty glyphs down a menu is a scroll, and the whole point
    of a glyph is that it is recognised rather than read.
    """
    holder = QWidget(parent)
    grid = QGridLayout(holder)
    grid.setContentsMargins(DENSE_GAP, DENSE_GAP, DENSE_GAP, DENSE_GAP)
    grid.setSpacing(DENSE_GAP)
    for position, name in enumerate(("", *ICONS)):
        button = QToolButton(holder)
        button.setObjectName("ToolbarButton")
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setFixedSize(CONTROL_HEIGHT, CONTROL_HEIGHT)
        button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        button.setCheckable(True)
        button.setChecked(name == current)
        button.setToolTip(name or NO_ICON)
        if name:
            button.setIcon(glyph_icon(name, ink))
        else:
            button.setText("—")
        button.clicked.connect(lambda _checked=False, chosen=name: pick(chosen))
        grid.addWidget(button, position // PICKER_COLUMNS, position % PICKER_COLUMNS)
    return holder
