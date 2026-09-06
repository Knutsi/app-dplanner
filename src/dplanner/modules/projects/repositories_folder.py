"""Where clones land on this machine: asked once, then remembered.

A plan repository cloned from Open Projects and a code repository cloned from the Project
dialog go to the same folder, because that is how people keep checkouts — one directory
of repositories under a name that varies by habit (``~/Code``, ``~/src``, ``~/repos``).
The first clone asks, with the likely folders found on disk as rows and the first of them
picked; *Settings ▸ Repositories* changes it later. Per user, per machine: ``user_config``.
"""

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.list_rows import DETAIL_ROLE, TwoLineDelegate
from dplanner.framework.user_config import get_global, set_global
from dplanner.modules.projects.repos import MODULE_ID, candidate_repositories_folders

FOLDER_KEY = "repositories_folder"
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


def shown_path(path: Path) -> str:
    """A path as a person writes it: ``~`` for the home directory."""
    try:
        return "~/" + path.relative_to(Path.home()).as_posix()
    except ValueError:
        return str(path)


def describe_folder(folder: Path) -> str:
    """The row's second line: how many repositories it holds, or that it will be made."""
    if not folder.is_dir():
        return "will be created"
    count = sum(1 for child in folder.iterdir() if (child / ".git").exists())
    return f"{count} repositor{'y' if count == 1 else 'ies'}"


class RepositoriesFolderDialog(QDialog):
    """The likely folders as rows, the first picked; Browse… for any other."""

    def __init__(self, candidates: Sequence[Path], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("RepositoriesFolderDialog")
        self.setWindowTitle("Repositories Folder")
        self.setMinimumWidth(460)

        caption = QLabel("Where do you keep your repositories?", self)
        caption.setObjectName("InspectorCaption")
        self.list = QListWidget(self)
        self.list.setObjectName("RepositoriesFolderList")
        self.list.setItemDelegate(TwoLineDelegate(self.list))
        for folder in candidates:
            self._add(folder)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.list.itemActivated.connect(lambda _item: self.accept())

        self.browse_button = QPushButton("Browse…", self)
        self.browse_button.clicked.connect(self._browse)
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        self.use_button = QPushButton("Use this folder", self)
        self.use_button.setObjectName("PrimaryButton")
        self.use_button.setDefault(True)
        self.use_button.setEnabled(self.list.currentRow() >= 0)
        self.use_button.clicked.connect(self.accept)
        self.list.currentRowChanged.connect(lambda row: self.use_button.setEnabled(row >= 0))

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addWidget(self.browse_button)
        footer.addStretch(1)
        footer.addWidget(cancel)
        footer.addWidget(self.use_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(caption)
        layout.addWidget(self.list, 1)
        layout.addLayout(footer)

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
