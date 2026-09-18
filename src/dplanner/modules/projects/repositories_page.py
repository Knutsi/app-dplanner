"""The Open Project wizard's last page: the repositories the joined projects work in that
this machine lacks, and what to do about each.

A plan is readable without any of them, so the page never refuses to open a project — it
lists the worked-in locations (a role that writes: code, reporting) whose repository
has no checkout here, one row each, with three answers as a combo: *Clone into the
repositories folder*, *Use a checkout I have…*, *Later*. Read-only rows are not listed;
a sentence under the list says that specs are fetched when a Specs tab opens. Clones run
on the page, through a task, exactly as the link page's do; the answers become the
``(repository, path)`` pairs the module records once the project is attached.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Signal as QtSignal
from PySide6.QtWidgets import QComboBox, QFileDialog, QVBoxLayout, QWidget

from dplanner.core.storage.provider import StorageError
from dplanner.domain.locations import Location, LocationRole, located_folder
from dplanner.framework.signalling import StatusLine
from dplanner.framework.table import Cell, Column, Table
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.widgets import block, caption, note
from dplanner.modules.projects.checkouts import repo_folder_name
from dplanner.modules.projects.repos import RepositoryServices, shown_path
from dplanner.modules.projects.repositories_folder import (
    ensure_repositories_folder,
    repositories_folder,
)
from dplanner.theme.tokens import SECTION_GAP

CLONE, USE, LATER = "clone", "use", "later"
READ_ONLY_NOTE = "A read-only location — a spec repository — is fetched when a Specs tab opens."


@dataclass
class Missing:
    """One worked-in repository this machine lacks, and the rows that name it."""

    repository: str
    locations: list[Location] = field(default_factory=list)
    answer: str = CLONE
    checkout: Path | None = None  # For USE: the checkout the person named.


def missing_repositories(
    locations: Sequence[Location],
    roles: Mapping[str, LocationRole],
    checkout_for: Callable[[str], Path | None],
) -> list[Missing]:
    """The worked-in repositories the rows name that have no checkout here, each once."""
    found: dict[str, Missing] = {}
    for location in locations:
        role = roles.get(location.role)
        if role is None or not role.writes or checkout_for(location.repository) is not None:
            continue
        found.setdefault(location.canonical, Missing(location.repository)).locations.append(
            location
        )
    return list(found.values())


class RepositoriesPage(QWidget):
    changed = QtSignal()
    finished = QtSignal(bool)  # The clones ended; True when the answers can be taken.

    _done = QtSignal(str)  # An error, or "" — from the work body.

    def __init__(
        self,
        services: RepositoryServices,
        tasks: TaskService,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._runner = TaskRunner(tasks, parent=self)
        self._done.connect(self._on_done)
        self._missing: list[Missing] = []
        self._combos: list[QComboBox] = []
        self._working = False
        self._recorded: tuple[tuple[str, Path], ...] = ()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SECTION_GAP)
        self.table = Table(
            (
                Column("Repository"),
                Column("Used as"),
                Column("On this machine", resize="stretch"),
            ),
            parent=self,
        )
        self.table.setObjectName("RepositoriesPageTable")
        self.line = note(READ_ONLY_NOTE, self)
        self.status = StatusLine(self)
        block(
            layout,
            caption("This project works in repositories this machine lacks", self),
            self.table,
            self.line,
            self.status,
        )
        layout.addStretch(1)

    # -- what it asks ----------------------------------------------------------------------------

    def show_missing(self, missing: Sequence[Missing], roles: Mapping[str, LocationRole]) -> None:
        self._missing = list(missing)
        self._combos = []
        self._recorded = ()
        self.table.clear_rows()
        folder = repositories_folder()
        for position, entry in enumerate(self._missing):
            used_as = ", ".join(row.name(roles) for row in entry.locations)
            row = self.table.add_row(
                (
                    Cell(entry.locations[0].repository_label, tooltip=entry.repository),
                    Cell(used_as),
                    "",
                )
            )
            combo = QComboBox(self.table)
            combo.setObjectName("RepositoryAnswer")
            where = (
                shown_path(folder / repo_folder_name(entry.repository))
                if folder is not None
                else "the repositories folder"
            )
            combo.addItem(f"Clone into {where}", CLONE)
            combo.addItem("Use a checkout I have…", USE)
            combo.addItem("Later", LATER)
            combo.activated.connect(lambda index, at=position: self._answered(at, index))
            self.table.setCellWidget(row, 2, combo)
            self._combos.append(combo)
        self.table.fit_columns()
        self.changed.emit()

    def answers(self) -> list[Missing]:
        return list(self._missing)

    def _answered(self, position: int, index: int) -> None:
        entry, combo = self._missing[position], self._combos[position]
        answer = str(combo.itemData(index))
        if answer == USE:
            start = repositories_folder() or Path.home()
            chosen = QFileDialog.getExistingDirectory(self, "Checkout", str(start))
            if not chosen:
                combo.setCurrentIndex(0)
                entry.answer, entry.checkout = CLONE, None
                self.changed.emit()
                return
            found = located_folder(Path(chosen))
            if found is None:
                self.status.say(
                    f"{shown_path(Path(chosen))} is not inside a git repository", "error"
                )
                combo.setCurrentIndex(0)
                entry.answer, entry.checkout = CLONE, None
                self.changed.emit()
                return
            entry.checkout = found.root
            combo.setItemText(index, f"Use {shown_path(entry.checkout)}")
        entry.answer = answer
        self.changed.emit()

    def primary_text(self) -> str:
        clones = sum(1 for entry in self._missing if entry.answer == CLONE)
        return f"Clone {clones} and Finish" if clones else "Finish"

    def refusal(self) -> str | None:
        return "" if self._working else None

    # -- doing it --------------------------------------------------------------------------------

    def begin(self) -> None:
        """Clone what was asked for, then answer through :attr:`finished`."""
        if self._working:
            return
        to_clone = [entry for entry in self._missing if entry.answer == CLONE]
        recorded = [
            (entry.repository, entry.checkout)
            for entry in self._missing
            if entry.answer == USE and entry.checkout is not None
        ]
        if not to_clone:
            self._recorded = tuple(recorded)
            self.finished.emit(True)
            return
        folder = ensure_repositories_folder(self)
        if folder is None:
            self.finished.emit(False)
            return
        targets = [
            (entry.repository, folder / repo_folder_name(entry.repository)) for entry in to_clone
        ]
        clone = self._services.clone

        def body() -> None:  # Worker thread: remotes and paths, never the model.
            try:
                for remote, dest in targets:
                    if not (dest / ".git").exists():
                        clone(remote, dest)
                self._done.emit("")
            except (StorageError, OSError) as error:
                self._done.emit(str(error))

        self._pending = tuple(recorded) + tuple(targets)
        self._working = True
        self.status.say(
            f"Cloning {len(targets)} repositor{'y' if len(targets) == 1 else 'ies'}…", "busy"
        )
        self.changed.emit()
        if not self._runner.run("Cloning repositories", body, key="projects.repositories_clone"):
            self._working = False
            self.status.say("Another clone is still running", "error")
            self.changed.emit()
            self.finished.emit(False)

    def _on_done(self, error: str) -> None:
        self._working = False
        if error:
            self.status.say(error, "error")
            self.changed.emit()
            self.finished.emit(False)
            return
        self._recorded = self._pending
        self.status.say("Cloned", "ok")
        self.finished.emit(True)

    def recorded(self) -> tuple[tuple[str, Path], ...]:
        """The checkouts to record: the ones named, and the ones cloned."""
        return self._recorded
