"""One location, asked for: which repository, and which folder in it.

A fit dialog on the frame (DESIGN.md's *Dialogs*), built for the person who has never
managed a folder for DPlanner. The repository is an editable combo led by what this
project and this library already name — a project reports beside its code more often than
not, so the default is the answer — followed by the repositories `gh` knows, listed on a
task when the dialog opens and again on the refresh glyph beside it, whose arc turns while
gh answers; a refusal (not installed, not signed in) is a line under the row, never a
dialog. The position is a field with *Browse…*, which lists the repository's folders — over
the checkout when this machine has one, otherwise through the remote listing the git spec
source probes with — so nobody types a subdirectory blind, and nothing is cloned to pick a
folder. The shortest way of all is the ⋯'s *From a folder on this computer…*: pick a folder
of a checkout and the dialog reads the repository and the position off it, and records the
checkout for this machine. The primary is refused in words while the row cannot stand
(`domain.locations.problem`).

Nothing else about a checkout is asked here: a repository already checked out needs none,
a read-only role needs none, and a worked-in repository this machine lacks is said in the
Locations table with *Clone…* in its ⋯ — a decision the person can make now or later.
"""

from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from dplanner.core.storage.provider import StorageError
from dplanner.core.storage.sparse import Probe
from dplanner.domain.locations import (
    Location,
    LocationRole,
    located_folder,
    next_id,
    normalise_path,
    primary_code,
    problem,
)
from dplanner.domain.model import Library, Project
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.signalling import Spinner, StatusLine
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.widgets import block, caption, note
from dplanner.modules.projects.repo_picker import (
    Entry,
    RepoAction,
    field_row,
    github_listing,
    menu_button,
    popup_menu,
    tool_button,
)
from dplanner.modules.projects.repos import RepositoryServices, github_url, shown_path
from dplanner.modules.projects.repositories_folder import repositories_folder
from dplanner.theme.icons import folder_icon, refresh_icon
from dplanner.theme.tokens import FIELD_GAP

FOLDERS_SIZE = (520, 480)
EXPANDED_DEPTH = 2  # The tree opens this many levels: enough to see, not the whole remote.

# Where a checkout of a repository on this computer is recorded: (repository, root).
RecordCheckout = Callable[[str, Path], None]


def known_repositories(rows: Sequence[Location], library: Library) -> list[str]:
    """The repositories ``rows`` and the library already name, each once, the primary
    code first — what the dialog's combo lists. Read off the model: no disk, no gh."""
    found: list[str] = []
    primary = primary_code(rows)
    if primary is not None:
        found.append(primary.repository)
    for row in rows:
        if row.repository not in found:
            found.append(row.repository)
    for project in library.projects:
        for row in project.locations:
            if row.repository not in found:
                found.append(row.repository)
    return found


def ask_location(
    role: LocationRole,
    *,
    project: Project,
    library: Library,
    services: RepositoryServices,
    tasks: TaskService,
    theme: ThemeService,
    parent: QWidget,
) -> Location | None:
    """A new row of ``role`` for ``project``, asked for in the dialog and answered, or
    None — the one door for a surface that is not the Project dialog (*Add Spec ▸ From
    Repository…*), so there is no "set it up in Settings first". A checkout the person
    picks on the way is recorded in the library file."""
    dialog = LocationDialog(
        role,
        location_id=next_id(project.locations),
        repositories=known_repositories(project.locations, library),
        location=None,
        checkout_for=services.checkout_for,
        record_checkout=services.set_checkout,
        services=services,
        tasks=tasks,
        theme=theme,
        parent=parent,
    )
    accepted = bool(dialog.exec())
    answer = dialog.answer() if accepted else None
    dialog.deleteLater()
    return answer


class LocationDialog(DialogFrame):
    """Add or edit one row of the Locations table; ``answer()`` after it was accepted."""

    _listed = QtSignal(object, str)  # (repos, error) — queued from the listing body.

    def __init__(
        self,
        role: LocationRole,
        *,
        location_id: str,
        repositories: Sequence[str],
        location: Location | None,
        checkout_for: Callable[[str], Path | None],
        record_checkout: RecordCheckout,
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
        self._known = list(repositories)
        self._checkout_for = checkout_for
        self._record_checkout = record_checkout
        self._services = services
        self._tasks = tasks
        self._ink = theme.current.text_secondary
        self._runner = TaskRunner(tasks, parent=self)
        self._listed.connect(self._on_listed)
        self._asked_github = False
        body, layout = self.body, self.body_layout

        self.repository = QComboBox(body)
        self.repository.setObjectName("LocationRepositoryCombo")
        self.repository.setEditable(True)
        self.repository.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        line = self.repository.lineEdit()
        assert line is not None  # An editable combo always has one.
        line.setPlaceholderText("https://github.com/acme/widget — as git names it")
        self._fill([])
        self.repository.setEditText(
            location.repository if location else (self._known[0] if self._known else "")
        )
        self.repository.editTextChanged.connect(lambda _text: self._revalidate())
        self.refresh_button = tool_button(
            "List the repositories gh knows again", "RefreshRepositoriesButton", body
        )
        self.refresh_button.setIcon(refresh_icon(self._ink))
        self.refresh_button.clicked.connect(self._list_github)
        self.spinner = Spinner(self).attach(self.refresh_button)
        self.repository_menu = menu_button("Other ways to name the repository", body)
        self.repository_menu.clicked.connect(self._repository_popup)
        self.listing_status = StatusLine(body)
        block(
            layout,
            caption("Repository", body),
            _row(body, self.repository, self.refresh_button, self.repository_menu),
            self.listing_status,
        )

        self.position = QLineEdit(body)
        self.position.setObjectName("LocationPositionEdit")
        self.position.setPlaceholderText("a folder inside the repository — empty for the root")
        self.position.setText(location.path if location else role.default_path)
        self.position.textChanged.connect(lambda _text: self._revalidate())
        self.folders_button = tool_button(
            "Browse the repository's folders…", "BrowsePositionButton", body
        )
        self.folders_button.setIcon(folder_icon(self._ink))
        self.folders_button.clicked.connect(self._choose_position)
        block(
            layout,
            caption("Position in repository", body),
            field_row(self.position, self.folders_button, body),
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

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt's name
        """The listing starts when the dialog is seen, once: a dialog built and never
        shown owes gh nothing."""
        super().showEvent(event)
        if not self._asked_github:
            self._asked_github = True
            self._list_github()

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

    # -- the repositories gh knows ---------------------------------------------------------------

    def _list_github(self) -> None:
        """The person's repositories on GitHub, listed on a task: the arc turns in the
        refresh glyph meanwhile, and the line under the row says how it went."""
        if self.spinner.is_spinning():
            return
        self.refresh_button.setEnabled(False)
        self.spinner.start()
        self.listing_status.say("Listing your repositories on GitHub…", "busy")
        services = self._services
        self._runner.run(
            "Listing GitHub repositories",
            lambda: self._listed.emit(*github_listing(services)),
            key="projects.gh_list",
        )

    def _on_listed(self, repos: object, error: str) -> None:
        self.refresh_button.setEnabled(True)
        self.spinner.stop()
        listed = [str(repo) for repo in repos] if isinstance(repos, list) else []
        self._fill([github_url(repo) for repo in listed])
        if error:
            self.listing_status.say(error, "info")
        else:
            self.listing_status.say(f"{len(listed)} repositories on GitHub", "ok")

    def _fill(self, github: Sequence[str]) -> None:
        """The combo's entries: what is already named, a separator, what gh knows. The
        text being edited is kept — a refill under a half-typed URL must not eat it."""
        text = self.repository.currentText()
        self.repository.blockSignals(True)
        self.repository.clear()
        self.repository.addItems(self._known)
        rest = [url for url in github if url not in self._known]
        if self._known and rest:
            self.repository.insertSeparator(self.repository.count())
        self.repository.addItems(rest)
        self.repository.setEditText(text)
        self.repository.blockSignals(False)

    def github_entries(self) -> list[str]:
        """Every entry the combo offers, the separator left out."""
        return [
            self.repository.itemText(row)
            for row in range(self.repository.count())
            if self.repository.itemText(row)
        ]

    # -- the ways in -----------------------------------------------------------------------------

    def _repository_entries(self) -> list[Entry]:
        return [RepoAction("From a folder on this computer…", folder_icon, self._from_folder)]

    def _repository_popup(self) -> None:
        popup_menu(self.repository_menu, self._repository_entries(), self._ink)

    def _from_folder(self) -> None:
        """A folder of a checkout on this computer, read as the whole answer: the
        repository it is a clone of, the folder's position in it — and the checkout
        recorded for this machine, so the row stands here from the start."""
        start = repositories_folder() or Path.home()
        chosen = QFileDialog.getExistingDirectory(self, "A folder in a checkout", str(start))
        if not chosen:
            return
        found = located_folder(Path(chosen))
        if found is None:
            self.status.say(f"{shown_path(Path(chosen))} is not inside a git repository", "error")
            return
        self.repository.setEditText(found.repository)
        self.position.setText(found.position)
        self._record_checkout(found.repository, found.root)
        self.listing_status.say(f"Checked out at {shown_path(found.root)}", "ok")
        self._revalidate()

    def _choose_position(self) -> None:
        """A folder of the repository: browsed in the checkout this machine has, else
        listed from the remote without a file downloaded."""
        url = self.repository.currentText().strip()
        if not url:
            self.status.say("Name the repository first", "error")
            return
        checkout = self._checkout_for(url)
        if checkout is not None and checkout.is_dir():
            self._browse_checkout(checkout)
            return
        dialog = RemoteFoldersDialog(
            self._services, self._tasks, url, self.ref.text().strip() or "HEAD", parent=self
        )
        accepted = bool(dialog.exec())
        picked = dialog.chosen() if accepted else None
        dialog.deleteLater()
        if picked is not None:
            self.position.setText(picked)

    def _browse_checkout(self, root: Path) -> None:
        typed = self.position.text().strip()
        start = root / typed if typed and (root / typed).is_dir() else root
        chosen = QFileDialog.getExistingDirectory(self, "Position in repository", str(start))
        if not chosen:
            return
        found = located_folder(Path(chosen))
        if found is None or found.root.resolve() != root.resolve():
            self.status.say(f"{shown_path(Path(chosen))} is outside {root.name}", "error")
            return
        self.position.setText(found.position)


def _row(parent: QWidget, field: QWidget, *buttons: QWidget) -> QWidget:
    """A field with more than one glyph button beside it — `field_row` for a pair."""
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(FIELD_GAP)
    layout.addWidget(field, 1)
    for button in buttons:
        layout.addWidget(button)
    return row


class RemoteFoldersDialog(DialogFrame):
    """The folders a remote holds at a ref, listed on a task as a tree, one to pick — the
    git spec source's listing, worn by a location's position. Nothing is cloned: listing
    a tree is seconds, and a clone to pick a folder is the wrong cost."""

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
        super().__init__("Position in Repository", parent, size=FOLDERS_SIZE)
        self.setObjectName("RemoteFoldersDialog")
        self._runner = TaskRunner(tasks, parent=self)
        self._listed.connect(self._on_listed)
        body, layout = self.body, self.body_layout
        self.tree = QTreeWidget(body)
        self.tree.setObjectName("RemoteFoldersTree")
        self.tree.setHeaderHidden(True)
        self.tree.itemActivated.connect(lambda _item, _column: self.accept())
        block(layout, caption(f"Folders of {url}", body), self.tree)
        self.add_dismiss()
        self.choose_button = self.set_primary("Choose", self.accept)
        self.choose_button.setEnabled(False)
        self.tree.currentItemChanged.connect(
            lambda current, _previous: self.choose_button.setEnabled(current is not None)
        )
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
        self.tree.clear()
        items: dict[str, QTreeWidgetItem] = {}
        for folder in probe.folders:  # The root first, every ancestor before its children.
            parent = items.get(folder.path.rpartition("/")[0]) if folder.path else None
            item = (
                QTreeWidgetItem(parent, [folder.path.rpartition("/")[2]])
                if parent is not None
                else QTreeWidgetItem(self.tree, ["/ (the whole repository)"])
            )
            item.setData(0, Qt.ItemDataRole.UserRole, folder.path)
            item.setExpanded(folder.path.count("/") < EXPANDED_DEPTH - 1)
            items[folder.path] = item
        self.status.say(f"{len(probe.folders)} folders at {probe.ref}")
        first = self.tree.topLevelItem(0)
        if first is not None:
            self.tree.setCurrentItem(first)

    def chosen(self) -> str | None:
        item = self.tree.currentItem()
        return None if item is None else str(item.data(0, Qt.ItemDataRole.UserRole))
