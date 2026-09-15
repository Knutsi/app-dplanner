"""Where clones land on this machine: asked once, then remembered.

A plan repository cloned from Open Project and a code repository cloned from the Project
dialog go to the same folder, because that is how people keep checkouts — one directory
of repositories under a name that varies by habit (``~/Code``, ``~/src``, ``~/repos``).
The first clone asks, with the likely folders found on disk as rows and the first of them
picked; *Settings ▸ Repositories* changes it later. Per user, per machine: ``user_config``.
"""

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QListWidget, QListWidgetItem, QWidget

from dplanner.framework.dialog import DialogFrame
from dplanner.framework.list_rows import DETAIL_ROLE, TwoLineDelegate
from dplanner.framework.user_config import get_global, set_global
from dplanner.framework.widgets import caption
from dplanner.modules.projects.repos import (
    MODULE_ID,
    candidate_repositories_folders,
    shown_path,
)
from dplanner.theme.tokens import CAPTION_GAP

FOLDER_KEY = "repositories_folder"
MIN_WIDTH = 460  # A folder is named by its path, and a path wants the room.
PATH_ROLE = int(Qt.ItemDataRole.UserRole) + 1


def repositories_folder() -> Path | None:
    raw = get_global(MODULE_ID, FOLDER_KEY, "")
    return Path(str(raw)).expanduser() if raw else None


def set_repositories_folder(folder: Path) -> None:
    set_global(MODULE_ID, FOLDER_KEY, str(folder))


def ensure_repositories_folder(parent: QWidget | None, home: Path | None = None) -> Path | None:
    """The folder clones land in — the remembered one, or the one the person picks now
    from the likely candidates; None when they cancel."""
    known = repositories_folder()
    if known is not None:
        return known
    dialog = RepositoriesFolderDialog(candidate_repositories_folders(home or Path.home()), parent)
    accepted = bool(dialog.exec())
    chosen = dialog.chosen() if accepted else None
    dialog.deleteLater()
    if chosen is None:
        return None
    chosen.mkdir(parents=True, exist_ok=True)
    set_repositories_folder(chosen)
    return chosen


def describe_folder(folder: Path) -> str:
    """The row's second line: how many repositories it holds, or that it will be made."""
    if not folder.is_dir():
        return "will be created"
    count = sum(1 for child in folder.iterdir() if (child / ".git").exists())
    return f"{count} repositor{'y' if count == 1 else 'ies'}"


class RepositoriesFolderDialog(DialogFrame):
    """The likely folders as rows, the first picked; Browse… for any other.

    A fit dialog: the caption over the list, *Use this folder* the primary — refused
    while no row is picked — and Browse… a quiet secondary beside Cancel, never in the
    far-left slot that is a destructive verb's.
    """

    def __init__(self, candidates: Sequence[Path], parent: QWidget | None = None) -> None:
        super().__init__("Repositories Folder", parent)
        self.setMinimumWidth(MIN_WIDTH)
        body, layout = self.body, self.body_layout
        layout.setSpacing(CAPTION_GAP)  # One caption over one list.
        layout.addWidget(caption("Where do you keep your repositories?", body))
        self.list = QListWidget(body)
        self.list.setObjectName("RepositoriesFolderList")
        self.list.setItemDelegate(TwoLineDelegate(self.list))
        for folder in candidates:
            self._add(folder)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.list.itemActivated.connect(lambda _item: self.accept())
        layout.addWidget(self.list, 1)

        self.browse_button = self.add_button("Browse…", self._browse)
        self.add_dismiss()
        self.use_button = self.set_primary("Use this folder", self.accept)
        self.list.currentRowChanged.connect(lambda row: self.refuse(None if row >= 0 else ""))
        self.refuse(None if self.list.currentRow() >= 0 else "")

    def _add(self, folder: Path) -> QListWidgetItem:
        item = QListWidgetItem(shown_path(folder))
        item.setData(DETAIL_ROLE, describe_folder(folder))
        item.setData(PATH_ROLE, str(folder))
        self.list.addItem(item)
        return item

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Repositories Folder", str(Path.home()))
        if chosen:
            self.list.setCurrentItem(self._add(Path(chosen)))

    def chosen(self) -> Path | None:
        item = self.list.currentItem()
        return None if item is None else Path(item.data(PATH_ROLE))
