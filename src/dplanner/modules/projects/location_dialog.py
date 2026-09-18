"""One location, asked for: which repository, and which folder in it.

A fit dialog on the frame (DESIGN.md's *Dialogs*): the repository as an editable combo
whose first entry is the code the project already names — docs and tests live with the
code more often than not, so the default is the answer — with the ⋯ of the other way in
(*Pick from GitHub…*); the position as a field pre-filled from the role's default, with a
button that lists the repository's folders — over the checkout when this machine has one,
otherwise through the remote listing the git spec source probes with, on a task, so nobody
types a subdirectory blind. A ref and, for a role a project may name twice, a label. The
primary is refused in words while the row cannot stand (`domain.locations.problem`).

Nothing about a checkout is asked here: a repository already checked out needs none, a
read-only role needs none, and a worked-in repository this machine lacks is said in the
Locations table with *Clone…* in its ⋯ — a decision the person can make now or later.
"""

from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import Signal as QtSignal
from PySide6.QtWidgets import QComboBox, QFileDialog, QLineEdit, QListWidget, QWidget

from dplanner.core.storage.locations import find_repo_root
from dplanner.core.storage.provider import StorageError
from dplanner.core.storage.sparse import Probe
from dplanner.domain.locations import Location, LocationRole, normalise_path, problem
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.widgets import block, caption, note
from dplanner.modules.projects.repo_picker import (
    Entry,
    GhRepoListDialog,
    RepoAction,
    field_row,
    menu_button,
    popup_menu,
    tool_button,
)
from dplanner.modules.projects.repos import RepositoryServices, github_url
from dplanner.theme.icons import find_icon, folder_icon

FOLDERS_SIZE = (520, 480)


class LocationDialog(DialogFrame):
    """Add or edit one row of the Locations table; ``answer()`` after it was accepted."""

    def __init__(
        self,
        role: LocationRole,
        *,
        location_id: str,
        repositories: Sequence[str],
        location: Location | None,
        checkout_for: Callable[[str], Path | None],
        services: RepositoryServices,
        tasks: TaskService,
        theme: ThemeService,
        parent: QWidget | None = None,
    ) -> None:
        editing = location is not None
        super().__init__(f"{'Edit' if editing else 'Add'} {role.label} Location", parent)
        self.setObjectName("LocationDialog")
        self._role = role
        self._id = location_id
        self._checkout_for = checkout_for
        self._services = services
        self._tasks = tasks
        self._ink = theme.current.text_secondary
        body, layout = self.body, self.body_layout

        self.repository = QComboBox(body)
        self.repository.setObjectName("LocationRepositoryCombo")
        self.repository.setEditable(True)
        self.repository.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        line = self.repository.lineEdit()
        assert line is not None  # An editable combo always has one.
        line.setPlaceholderText("https://github.com/acme/widget — as git names it")
        self.repository.addItems(list(repositories))
        self.repository.setEditText(
            location.repository if location else (repositories[0] if repositories else "")
        )
        self.repository.editTextChanged.connect(lambda _text: self._revalidate())
        self.repository_menu = menu_button("Other ways to name the repository", body)
        self.repository_menu.clicked.connect(self._repository_popup)
        block(
            layout,
            caption("Repository", body),
            field_row(self.repository, self.repository_menu, body),
        )

        self.position = QLineEdit(body)
        self.position.setObjectName("LocationPositionEdit")
        self.position.setPlaceholderText("a folder inside the repository — empty for the root")
        self.position.setText(location.path if location else role.default_path)
        self.position.textChanged.connect(lambda _text: self._revalidate())
        self.folders_button = tool_button("Choose the folder…", "ChoosePositionButton", body)
        self.folders_button.setIcon(folder_icon(self._ink))
        self.folders_button.clicked.connect(self._choose_position)
        block(
            layout, caption("Position", body), field_row(self.position, self.folders_button, body)
        )

        self.ref = QLineEdit(body)
        self.ref.setObjectName("LocationRefEdit")
        self.ref.setPlaceholderText("a branch or tag — the default branch if empty (optional)")
        self.ref.setText(location.ref if location else "")
        self.ref.textChanged.connect(lambda _text: self._revalidate())
        block(layout, caption("Branch or tag", body), self.ref)

        self.label = QLineEdit(body)
        self.label.setObjectName("LocationLabelEdit")
        self.label.setPlaceholderText("tells two of a kind apart: UI, backend (optional)")
        self.label.setText(location.label if location else "")
        self.label_block = block(layout, caption("Label", body), self.label)
        if not role.several:
            for index in range(self.label_block.count()):
                item = self.label_block.itemAt(index)
                widget = item.widget() if item is not None else None
                if widget is not None:
                    widget.hide()
        self.hint = note(role.summary, body)
        layout.addWidget(self.hint)
        layout.addStretch(1)

        self.add_dismiss()
        self.set_primary("Save" if editing else "Add", self.accept)
        self._revalidate()

    # -- the answer ------------------------------------------------------------------------------

    def answer(self) -> Location:
        return Location(
            id=self._id,
            role=self._role.id,
            repository=self.repository.currentText().strip(),
            path=normalise_path(self.position.text()),
            ref=self.ref.text().strip(),
            label=self.label.text().strip() if self._role.several else "",
        )

    def _revalidate(self) -> None:
        wrong = problem(self.answer())
        self.refuse(f"The location {wrong}" if wrong else None)

    # -- the ways in -----------------------------------------------------------------------------

    def _repository_entries(self) -> list[Entry]:
        return [
            RepoAction(
                "Pick from GitHub…",
                find_icon,
                self._pick_repository,
                self._services.gh_refusal() or "",
            )
        ]

    def _repository_popup(self) -> None:
        popup_menu(self.repository_menu, self._repository_entries(), self._ink)

    def _pick_repository(self) -> None:
        picker = GhRepoListDialog(
            self._services, self._tasks, self, title="Repository", verb="Choose"
        )
        accepted = bool(picker.exec())
        repo = picker.chosen() if accepted else ""
        picker.deleteLater()
        if repo:
            self.repository.setEditText(github_url(repo))

    def _choose_position(self) -> None:
        """A folder of the repository: browsed in the checkout this machine has, else
        listed from the remote without a file downloaded."""
        url = self.repository.currentText().strip()
        if not url:
            self.status.say("Name the repository first", "error")
            return
        checkout = self._checkout_for(url)
        if checkout is not None and checkout.is_dir():
            root = find_repo_root(checkout) or checkout
            start = root / self.position.text().strip() if self.position.text().strip() else root
            chosen = QFileDialog.getExistingDirectory(
                self, "Position", str(start if start.is_dir() else root)
            )
            if not chosen:
                return
            try:
                relative = Path(chosen).resolve().relative_to(root.resolve())
            except ValueError:
                self.status.say(f"{chosen} is outside {root.name}", "error")
                return
            self.position.setText(relative.as_posix() if relative.parts else "")
            return
        dialog = RemoteFoldersDialog(
            self._services, self._tasks, url, self.ref.text().strip() or "HEAD", parent=self
        )
        accepted = bool(dialog.exec())
        picked = dialog.chosen() if accepted else None
        dialog.deleteLater()
        if picked is not None:
            self.position.setText(picked)


class RemoteFoldersDialog(DialogFrame):
    """The folders a remote holds at a ref, listed on a task, one to pick — the git spec
    source's listing, worn by a location's position."""

    _listed = QtSignal(object, str)  # (Probe | None, error) — queued from the worker.

    def __init__(
        self,
        services: RepositoryServices,
        tasks: TaskService,
        url: str,
        ref: str,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Choose Folder", parent, size=FOLDERS_SIZE)
        self.setObjectName("RemoteFoldersDialog")
        self._runner = TaskRunner(tasks, parent=self)
        self._listed.connect(self._on_listed)
        body, layout = self.body, self.body_layout
        self.list = QListWidget(body)
        self.list.setObjectName("RemoteFoldersList")
        self.list.itemActivated.connect(lambda _item: self.accept())
        block(layout, caption(f"Folders of {url}", body), self.list)
        self.add_dismiss()
        self.choose_button = self.set_primary("Choose", self.accept)
        self.choose_button.setEnabled(False)
        self.list.currentRowChanged.connect(lambda row: self.choose_button.setEnabled(row >= 0))
        self.status.say(f"Listing the folders at {ref}…", "busy")
        list_folders = services.list_folders

        def body_() -> None:  # Worker thread: two strings and a function, never a widget.
            try:
                self._listed.emit(list_folders(url, ref), "")
            except (StorageError, OSError, ValueError) as error:
                self._listed.emit(None, str(error))

        self._runner.run("Listing repository folders", body_, key="projects.folders")

    def _on_listed(self, probe: object, error: str) -> None:
        if error or not isinstance(probe, Probe):
            self.status.say(error or "nothing listed", "error")
            return
        self.list.clear()
        for folder in probe.folders:
            self.list.addItem(folder.path or "/ (the whole repository)")
        self.status.say(f"{len(probe.folders)} folders at {probe.ref}")
        if self.list.count():
            self.list.setCurrentRow(0)

    def chosen(self) -> str | None:
        item = self.list.currentItem()
        text = item.text() if item is not None else None
        return None if text is None else ("" if text.startswith("/") else text)
