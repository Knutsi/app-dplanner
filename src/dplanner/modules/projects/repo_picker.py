"""Picking a plan repository: one the library already uses, another folder on disk, a
clone from GitHub — or, where a new one may be made, a fresh local repository or one to
publish on GitHub.

Open Projects, Move Plan and New Project all ask this question, so it is one widget: a
dropdown of the known plan repositories, last used first, and a row of glyph buttons for
the other ways in. What it answers is a :class:`PlanTarget` — a root, whether it still
has to be initialised, and the GitHub name to publish it under afterwards — and it never
touches the model. A clone runs off the GUI thread and lands in the repositories folder.
"""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.core.storage.locations import find_repo_root, origin_url, remote_label
from dplanner.core.storage.provider import StorageError
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.user_config import get_global, set_global
from dplanner.modules.projects.repos import MODULE_ID, RepositoryServices
from dplanner.modules.projects.repositories_folder import (
    ensure_repositories_folder,
    repositories_folder,
    shown_path,
)
from dplanner.theme.icons import ICON_SIZE, clone_icon, external_icon, folder_icon, plus_icon
from dplanner.theme.themes import Theme

LAST_ROOT_KEY = "last_plan_root"


@dataclass(frozen=True)
class PlanTarget:
    """A plan repository as picked: existing, or a folder still to be made."""

    root: Path
    init: bool = False  # A folder to ``git init`` before use.
    publish: str = ""  # A GitHub name to publish it under once it has a commit.

    @property
    def label(self) -> str:
        if self.init:
            return f"{self.root.name} — new" + (" on GitHub" if self.publish else "")
        origin = origin_url(self.root)
        return remote_label(origin) if origin else self.root.name


def tool_button(tip: str, name: str, parent: QWidget) -> QToolButton:
    """A glyph button beside a field: the quiet bordered look, the verb in its tooltip."""
    button = QToolButton(parent)
    button.setObjectName(name)
    button.setProperty("repoTool", True)
    button.setToolTip(tip)
    button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
    return button


class RepoPicker(QWidget):
    changed = QtSignal()
    _cloned = QtSignal(str, str)  # (root, error) — queued from the clone body.

    def __init__(
        self,
        services: RepositoryServices,
        tasks: TaskService,
        *,
        allow_new: bool = False,
        theme: ThemeService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("RepoPicker")
        self._services = services
        self._tasks = tasks
        self._runner = TaskRunner(tasks, parent=self)
        self._cloned.connect(self._on_cloned)
        self._targets: dict[str, PlanTarget] = {}

        self.combo = QComboBox(self)
        self.combo.setObjectName("RepoPickerCombo")
        self.combo.currentIndexChanged.connect(lambda _index: self.changed.emit())
        self.browse_button = tool_button("Another folder…", "RepoPickerBrowse", self)
        self.browse_button.clicked.connect(self._browse)
        self.clone_button = tool_button("Clone from GitHub…", "RepoPickerClone", self)
        self.clone_button.clicked.connect(self._clone)
        self.new_local_button = tool_button("New repository here…", "RepoPickerNewLocal", self)
        self.new_local_button.clicked.connect(self._new_local)
        self.new_github_button = tool_button(
            "New repository on GitHub…", "RepoPickerNewGitHub", self
        )
        self.new_github_button.clicked.connect(self._new_github)
        self.new_local_button.setVisible(allow_new)
        self.new_github_button.setVisible(allow_new)
        self.note = QLabel(self)
        self.note.setObjectName("RepoPickerNote")
        self.note.setWordWrap(True)
        self.note.hide()

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.combo, 1)
        for button in (
            self.browse_button,
            self.clone_button,
            self.new_local_button,
            self.new_github_button,
        ):
            row.addWidget(button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(row)
        layout.addWidget(self.note)

        # The repository last picked leads, and is offered even when no library project
        # lives there yet — a browsed-to repository is worth remembering once.
        last = str(get_global(MODULE_ID, LAST_ROOT_KEY, ""))
        roots = services.plan_roots()
        if last and Path(last) not in roots and (Path(last) / ".git").exists():
            roots.insert(0, Path(last))
        for root in sorted(roots, key=lambda root: str(root) != last):
            self._add(PlanTarget(root))
        if theme is not None:
            self._paint(theme.current)
            self._unsubscribe = theme.changed.connect(self._paint)

    # -- the answer ------------------------------------------------------------------------

    def current(self) -> PlanTarget | None:
        key = self.combo.currentData()
        return self._targets.get(str(key)) if key else None

    def set_current(self, root: Path) -> None:
        self._add(PlanTarget(root), select=True)

    def remember(self) -> None:
        """Called by the dialog that accepted: the next picker opens on this one."""
        target = self.current()
        if target is not None:
            set_global(MODULE_ID, LAST_ROOT_KEY, str(target.root))

    def _add(self, target: PlanTarget, *, select: bool = False) -> None:
        key = str(target.root)
        if key not in self._targets:
            self.combo.addItem(target.label, key)
        self._targets[key] = target
        if select:
            self.combo.setCurrentIndex(self.combo.findData(key))
            self.changed.emit()

    # -- the other ways in -------------------------------------------------------------------

    def _browse(self) -> None:
        start = repositories_folder() or Path.home()
        chosen = QFileDialog.getExistingDirectory(self, "Plan Repository", str(start))
        if not chosen:
            return
        root = find_repo_root(Path(chosen))
        if root is None:
            self.say(f"{chosen} is not inside a git repository — clone one, or start a new one")
            return
        self.say("")
        self._add(PlanTarget(root), select=True)

    def _clone(self) -> None:
        picker = GhRepoListDialog(self._services, self._tasks, self)
        accepted = bool(picker.exec())
        repo = picker.chosen() if accepted else ""
        picker.deleteLater()
        if not repo:
            return
        folder = ensure_repositories_folder(self)
        if folder is None:
            return
        dest = folder / repo.rsplit("/", 1)[-1]
        if (dest / ".git").exists():
            self._add(PlanTarget(dest), select=True)
            return
        if dest.exists():
            self.say(f"{shown_path(dest)} exists and is not a repository")
            return
        services = self._services

        def body() -> None:
            try:
                services.clone(repo, dest)
                self._cloned.emit(str(dest), "")
            except (StorageError, OSError) as error:
                self._cloned.emit(str(dest), str(error))

        if not self._runner.run(f"Cloning {repo}", body, key="projects.clone"):
            self.say("Another clone is still running")
            return
        self.clone_button.setEnabled(False)
        self.say(f"Cloning {repo} into {shown_path(dest)}…")

    def _on_cloned(self, root: str, error: str) -> None:
        self.clone_button.setEnabled(True)
        if error:
            self.say(error)
            return
        self.say("")
        self._add(PlanTarget(Path(root)), select=True)

    def _new_local(self) -> None:
        start = repositories_folder() or Path.home()
        chosen = QFileDialog.getSaveFileName(
            self,
            "New Plan Repository",
            str(start / "plans"),
            options=QFileDialog.Option.ShowDirsOnly,
        )[0]
        if not chosen:
            return
        path = Path(chosen)
        if path.exists() and any(path.iterdir()):
            self.say(f"{shown_path(path)} is not empty")
            return
        self.say("")
        self._add(PlanTarget(path, init=True), select=True)

    def _new_github(self) -> None:
        name, ok = QInputDialog.getText(
            self, "New Plan Repository on GitHub", "Repository name:", text="plans"
        )
        name = name.strip()
        if not ok or not name:
            return
        folder = ensure_repositories_folder(self)
        if folder is None:
            return
        path = folder / name.rsplit("/", 1)[-1]
        if path.exists():
            self.say(f"{shown_path(path)} already exists")
            return
        self.say("")
        self._add(PlanTarget(path, init=True, publish=name), select=True)

    def say(self, text: str) -> None:
        self.note.setText(text)
        self.note.setVisible(bool(text))

    def _paint(self, theme: Theme) -> None:
        color = theme.text_secondary
        self.browse_button.setIcon(folder_icon(color))
        self.clone_button.setIcon(clone_icon(color))
        self.new_local_button.setIcon(plus_icon(color))
        self.new_github_button.setIcon(external_icon(color))


class GhRepoListDialog(QDialog):
    """The person's GitHub repositories, filtered as they type; one is cloned."""

    _listed = QtSignal(object, str)  # (repos, error) — queued from the listing body.

    def __init__(
        self, services: RepositoryServices, tasks: TaskService, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("GhRepoListDialog")
        self.setWindowTitle("Clone from GitHub")
        self.setMinimumSize(440, 380)
        self._repos: list[str] = []
        self._runner = TaskRunner(tasks, parent=self)
        self._listed.connect(self._on_listed)

        self.filter_edit = QLineEdit(self)
        self.filter_edit.setObjectName("GhRepoFilter")
        self.filter_edit.setPlaceholderText("Filter…")
        self.filter_edit.textChanged.connect(lambda _text: self._fill())
        self.list = QListWidget(self)
        self.list.setObjectName("GhRepoList")
        self.list.itemActivated.connect(lambda _item: self.accept())
        self.status = QLabel("Listing your repositories…", self)
        self.status.setObjectName("InspectorNote")
        self.status.setWordWrap(True)

        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        self.clone_button = QPushButton("Clone", self)
        self.clone_button.setObjectName("PrimaryButton")
        self.clone_button.setDefault(True)
        self.clone_button.setEnabled(False)
        self.clone_button.clicked.connect(self.accept)
        self.list.currentRowChanged.connect(lambda row: self.clone_button.setEnabled(row >= 0))

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addWidget(self.status, 1)
        footer.addWidget(cancel)
        footer.addWidget(self.clone_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(self.filter_edit)
        layout.addWidget(self.list, 1)
        layout.addLayout(footer)

        def body() -> None:
            refusal = services.gh_refusal()
            if refusal is not None:
                self._listed.emit([], refusal)
                return
            try:
                self._listed.emit(services.list_repositories(), "")
            except (StorageError, OSError) as error:
                self._listed.emit([], str(error))

        self._runner.run("Listing GitHub repositories", body, key="projects.gh_list")

    def _on_listed(self, repos: object, error: str) -> None:
        self._repos = [str(repo) for repo in repos] if isinstance(repos, list) else []
        self.status.setText(error or f"{len(self._repos)} repositories")
        self._fill()

    def _fill(self) -> None:
        needle = self.filter_edit.text().strip().lower()
        self.list.clear()
        for repo in self._repos:
            if needle in repo.lower():
                self.list.addItem(repo)
        if self.list.count():
            self.list.setCurrentRow(0)

    def chosen(self) -> str:
        item = self.list.currentItem()
        return item.text() if item is not None else ""
