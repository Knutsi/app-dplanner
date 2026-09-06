"""The "Repositories" settings page: the folder clones land in.

One field, because it is one fact — asked the first time a clone is needed
(``repositories_folder.ensure_repositories_folder``) and changed here afterwards. Per
user, per machine, like every settings page.
"""

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.modules.projects.repos import candidate_repositories_folders
from dplanner.modules.projects.repositories_folder import (
    repositories_folder,
    set_repositories_folder,
)


def build_page(parent: QWidget | None) -> QWidget:
    page = QWidget(parent)
    page.setObjectName("RepositoriesSettingsPage")

    edit = QLineEdit(page)
    edit.setObjectName("RepositoriesFolderEdit")
    known = repositories_folder()
    edit.setText(str(known) if known is not None else "")
    edit.setPlaceholderText(str(candidate_repositories_folders(Path.home())[0]))

    def commit() -> None:
        text = edit.text().strip()
        if text:
            set_repositories_folder(Path(text).expanduser())

    def browse() -> None:
        chosen = QFileDialog.getExistingDirectory(page, "Repositories Folder", edit.text())
        if chosen:
            edit.setText(chosen)
            commit()

    edit.editingFinished.connect(commit)
    browse_button = QPushButton("Browse…", page)
    browse_button.setObjectName("RepositoriesFolderBrowse")
    browse_button.clicked.connect(browse)

    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(edit, 1)
    row.addWidget(browse_button)

    layout = QVBoxLayout(page)
    layout.addWidget(QLabel("Clone into", page))
    layout.addLayout(row)
    layout.addStretch(1)
    return page
