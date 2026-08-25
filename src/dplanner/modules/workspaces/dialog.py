"""Choosing a workspace, and with it a storage backend.

Three ways in, which are exactly the three providers: a recent workspace, a folder on this
machine, and a repository on GitHub. The user is never asked to pick a *provider* — they
pick a workspace, and ``open_storage`` gives them the most capable one that fits what is
actually there. Somebody who has never heard of git gets a working application; somebody
who clones from GitHub gets Save, branches and Update without configuring anything.
"""

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.core.storage.locations import (
    StorageLocation,
    describe_location,
    parse_location,
)
from dplanner.framework.session import recent_workspaces, workspace_roots
from dplanner.identity import APP_NAME
from dplanner.modules.workspaces.service import WorkspaceService

_LOCATION_ROLE = 0x0100  # Qt.ItemDataRole.UserRole


class OpenWorkspaceDialog(QDialog):
    """Pick a recent workspace, browse for a folder, or clone from GitHub.

    ``chosen`` is a location ready to open; ``clone_requested`` is an ``owner/repo`` the
    caller should clone first — the dialog never blocks on the network itself.
    """

    def __init__(self, service: WorkspaceService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Open {APP_NAME} Workspace")
        self.resize(520, 420)
        self.chosen: StorageLocation | None = None
        self.clone_requested: str | None = None
        self._service = service

        self._list = QListWidget(self)
        self._list.itemDoubleClicked.connect(lambda _item: self._accept_selection())

        self._hint = QLabel("", self)
        self._hint.setObjectName("InspectorNote")
        self._hint.setWordWrap(True)

        browse = QPushButton("Choose &Folder…", self)
        browse.clicked.connect(self._browse)
        github = QPushButton("From &GitHub…", self)
        github.clicked.connect(self._load_repositories)
        github.setEnabled(service.github_available())
        if not github.isEnabled():
            github.setToolTip("Install the GitHub CLI and run `gh auth login` to use this")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        buttons.addButton(browse, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(github, QDialogButtonBox.ButtonRole.ActionRole)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(self._list)
        layout.addWidget(self._hint)
        layout.addWidget(buttons)

        self._show_recent()
        service.repositories_loaded.connect(self._show_repositories)

    # -- populating ----------------------------------------------------------------------------

    def _show_recent(self) -> None:
        self._list.clear()
        for location in recent_workspaces():
            item = QListWidgetItem(describe_location(location), self._list)
            item.setData(_LOCATION_ROLE, str(location))
        if self._list.count():
            self._list.setCurrentRow(0)
            self._hint.setText("")
        else:
            roots = ", ".join(str(root) for root in workspace_roots())
            self._hint.setText(f"No workspaces yet. Choose a folder — {roots} is the usual place.")

    def _show_repositories(self, repositories: list[str]) -> None:
        self._list.clear()
        for repo in repositories:
            item = QListWidgetItem(repo, self._list)
            item.setData(_LOCATION_ROLE, f"github:{repo}")
        self._hint.setText("Opening one clones it to this machine first.")
        if self._list.count():
            self._list.setCurrentRow(0)

    def _load_repositories(self) -> None:
        self._hint.setText("Listing your GitHub repositories…")
        self._service.load_repositories()

    # -- choosing ------------------------------------------------------------------------------

    def _browse(self) -> None:
        roots = workspace_roots()
        start = str(roots[0]) if roots else str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Choose a workspace folder", start)
        if not chosen:
            return
        self.chosen = StorageLocation(scheme="", target=chosen)
        self.accept()

    def _accept_selection(self) -> None:
        item = self._list.currentItem()
        raw = str(item.data(_LOCATION_ROLE)) if item is not None else ""
        if not raw:
            return
        if raw.startswith("github:"):
            self.clone_requested = raw.removeprefix("github:")
        else:
            self.chosen = parse_location(raw)
        self.accept()
