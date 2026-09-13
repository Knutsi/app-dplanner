"""The "Repositories" settings page: the folder clones land in.

One field, because it is one fact — asked the first time a clone is needed
(``repositories_folder.ensure_repositories_folder``) and changed here afterwards. Per
user, per machine, like every settings page.
"""

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLineEdit, QWidget

from dplanner.framework.settings_registry import settings_page
from dplanner.framework.widgets import GlyphButton, block, captioned
from dplanner.modules.projects.repos import candidate_repositories_folders
from dplanner.modules.projects.repositories_folder import (
    repositories_folder,
    set_repositories_folder,
)
from dplanner.theme.icons import folder_icon
from dplanner.theme.tokens import FIELD_GAP

FOLDER_HINT = (
    "Where a repository is cloned when a plan or its code needs one. The first clone asks;"
    " this changes it."
)


def build_page(parent: QWidget | None) -> QWidget:
    page, layout = settings_page(parent)
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
    browse_button = GlyphButton("Browse…", folder_icon, page)
    browse_button.clicked.connect(browse)

    folder_row = QWidget(page)
    row = QHBoxLayout(folder_row)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(FIELD_GAP)
    row.addWidget(edit, 1)
    row.addWidget(browse_button)
    block(layout, captioned("Clone into", page, FOLDER_HINT), folder_row)
    layout.addStretch(1)
    return page
