"""The "Repositories" settings page: where clones land.

Two facts, both per user and per machine like every settings page. The **clone policy**
first — what happens to a repository a verb needs that this machine lacks: DPlanner keeps
a clone of its own, or clones into the repositories folder — and the **folder** under it,
asked the first time a clone is needed (``repositories_folder.ensure_repositories_folder``)
and changed here afterwards. The folder stays whatever the policy: an explicit *Clone into
Repositories Folder* and the Open Project wizard's plan clone land there either way.
"""

from pathlib import Path

from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QWidget

from dplanner.framework.settings_registry import settings_page
from dplanner.framework.widgets import GlyphButton, block, captioned
from dplanner.modules.projects.repos import candidate_repositories_folders
from dplanner.modules.projects.repositories_folder import (
    POLICIES,
    clone_policy,
    repositories_folder,
    set_clone_policy,
    set_repositories_folder,
)
from dplanner.theme.icons import folder_icon
from dplanner.theme.tokens import FIELD_GAP

POLICY_HINT = (
    "When Run Agent or a report needs a repository you have not checked out. Kept by"
    " DPlanner, a clone lives under its own configuration directory and never among your"
    " repositories; in your folder, it lands beside your other checkouts."
)
FOLDER_HINT = (
    "Where a plan repository is cloned, and any repository you clone on purpose. The first"
    " clone asks; this changes it."
)


def build_page(parent: QWidget | None) -> QWidget:
    page, layout = settings_page(parent)
    page.setObjectName("RepositoriesSettingsPage")

    policy_combo = QComboBox(page)
    policy_combo.setObjectName("ClonePolicyCombo")
    for policy, label in POLICIES:
        policy_combo.addItem(label, policy)
    policy_combo.setCurrentIndex(
        next((row for row, (policy, _l) in enumerate(POLICIES) if policy == clone_policy()), 0)
    )
    policy_combo.activated.connect(
        lambda index: set_clone_policy(str(policy_combo.itemData(index)))
    )
    block(
        layout,
        captioned("Repositories I have not checked out", page, POLICY_HINT),
        policy_combo,
    )

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
