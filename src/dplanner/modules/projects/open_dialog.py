"""Open Projects…: pick a plan repository, see what it holds, add the chosen ones.

A plan repository holds several projects for several people, so joining one is a browse,
not a file dialog: the picker names the repository — one the library uses, another folder,
a clone from GitHub — and the list shows every project it lists (or, with no index,
holds) with who worked on each and when; rows already in this library are greyed. The
rows come from ``domain/plan_repo.list_projects`` on the spot; the activity behind each
is one git log per project, read off the GUI thread and dropped when it arrives for a
repository the dialog has since left. Every addable row starts selected: joining a plan
repository usually means joining all of it.
"""

from collections.abc import Collection
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem, QWidget

from dplanner.core.storage.provider import StorageError
from dplanner.domain.plan_repo import ago, list_projects
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.list_rows import DETAIL_ROLE, MUTED_ROLE, TwoLineDelegate
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.widgets import EmptyState, block, caption, note
from dplanner.modules.projects.repo_picker import RepoPicker
from dplanner.modules.projects.repos import RepoLog, RepositoryServices, shown_path

# Past the delegate's own roles (DETAIL, MUTED, EMPHASIS, RULE sit at UserRole + 2..5).
PATH_ROLE = int(Qt.ItemDataRole.UserRole) + 10
RELATIVE_ROLE = int(Qt.ItemDataRole.UserRole) + 11
ACTIVITY_LIMIT = 30
DIALOG_SIZE = (680, 520)


def activity_line(log: RepoLog) -> str:
    """A row's second line: who last touched the plan and when, then everyone who has."""
    if not log.entries:
        return "no commits yet"
    first = log.entries[0]
    authors: list[str] = []
    for entry in log.entries:
        if entry.author not in authors:
            authors.append(entry.author)
    line = f"{first.author}, {ago(first.when)}"
    if len(authors) > 1:
        line += " · " + ", ".join(authors)
    return line


class OpenProjectsDialog(DialogFrame):
    """A framed dialog: the plan repository as a captioned block, the projects it holds
    as rows — or an empty state saying what to pick — and *Add to Library* worded with
    the count and refused while nothing is chosen."""

    _activity = QtSignal(str, object, str)  # (root, {relative: RepoLog}, error)

    def __init__(
        self,
        services: RepositoryServices,
        tasks: TaskService,
        theme: ThemeService,
        *,
        listed_dirs: Collection[Path],
        listed_ids: Collection[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Open Projects", parent, size=DIALOG_SIZE)
        self._services = services
        self._listed_dirs = {directory.resolve() for directory in listed_dirs}
        self._listed_ids = set(listed_ids)
        self._root: Path | None = None
        self._refetch = False
        self._runner = TaskRunner(tasks, parent=self)
        self._activity.connect(self._on_activity)
        body, layout = self.body, self.body_layout

        self.picker = RepoPicker(services, tasks, theme=theme, parent=body)
        self.picker.setObjectName("OpenRepoPicker")
        block(layout, caption("Plan repository", body), self.picker)
        self.list = QListWidget(body)
        self.list.setObjectName("OpenProjectsList")
        self.list.setItemDelegate(TwoLineDelegate(self.list))
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.itemSelectionChanged.connect(self._revalidate)
        layout.addWidget(self.list, 1)
        self.empty = EmptyState("", body, stands_in_for=self.list)
        layout.addWidget(self.empty, 1)
        # A remark about the data — lines in .dplanner that lead nowhere — is a body
        # note; the footer's status slot is the refusal's.
        self.note = note("", body)
        self.note.hide()
        layout.addWidget(self.note)

        self.add_dismiss()
        self.add_projects_button = self.set_primary("Add to Library", self.accept)
        self.picker.changed.connect(self._load)
        self._load()

    # -- the rows ------------------------------------------------------------------------------

    def _load(self) -> None:
        target = self.picker.current()
        self.list.clear()
        self.note.hide()
        if target is None:
            self._root = None
            self.empty.say("Pick a plan repository — or clone one.")
            self._revalidate()
            return
        root = target.root
        self._root = root
        listing = list_projects(root)
        for found in listing.projects:
            steps = f"{found.steps} step{'s' if found.steps != 1 else ''}"
            item = QListWidgetItem(f"{found.title} · {steps}")
            item.setData(PATH_ROLE, str(found.directory))
            item.setData(RELATIVE_ROLE, found.relative)
            here = (
                found.directory.resolve() in self._listed_dirs
                or found.project_id in self._listed_ids
            )
            if here:
                item.setData(DETAIL_ROLE, "already in this library")
                item.setData(MUTED_ROLE, True)
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            else:
                item.setData(DETAIL_ROLE, "…")
            self.list.addItem(item)
            if not here:
                item.setSelected(True)
        if listing.dangling:
            count = len(listing.dangling)
            lines = f"{count} line{'s' if count != 1 else ''}"
            verb = "leads" if count == 1 else "lead"
            self.note.setText(f"{lines} in .dplanner {verb} nowhere: {', '.join(listing.dangling)}")
            self.note.show()
        self.empty.say("" if self.list.count() else f"No projects in {shown_path(root)}.")
        self._revalidate()
        self._request_activity(root, [found.relative for found in listing.projects])

    def _request_activity(self, root: Path, relatives: list[str]) -> None:
        if not relatives:
            return
        services = self._services

        def body() -> None:  # Worker thread: the captured root and names, never the model.
            logs: dict[str, RepoLog] = {}
            error = ""
            for relative in relatives:
                scope = "" if relative == "." else relative
                try:
                    logs[relative] = services.history_for(root, scope, ACTIVITY_LIMIT)
                except (StorageError, OSError) as failure:
                    error = error or str(failure)
            self._activity.emit(str(root), logs, error)

        if not self._runner.run("Reading who worked on what", body, key="projects.activity"):
            self._refetch = True

    def _on_activity(self, root: str, logs: object, error: str) -> None:
        if self._refetch:
            self._refetch = False
            if self._root is not None:
                self._request_activity(self._root, self._relatives())
        if self._root is None or root != str(self._root):
            return  # The dialog moved to another repository while this read was out.
        found = logs if isinstance(logs, dict) else {}
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item is None or item.data(MUTED_ROLE):
                continue
            log = found.get(item.data(RELATIVE_ROLE))
            item.setData(DETAIL_ROLE, activity_line(log) if log is not None else error or "")

    def _relatives(self) -> list[str]:
        return [
            str(item.data(RELATIVE_ROLE))
            for item in (self.list.item(index) for index in range(self.list.count()))
            if item is not None
        ]

    # -- the answer ------------------------------------------------------------------------------

    def rows(self) -> list[tuple[str, str]]:
        return [
            (item.text(), str(item.data(DETAIL_ROLE) or ""))
            for item in (self.list.item(index) for index in range(self.list.count()))
            if item is not None
        ]

    def chosen(self) -> list[Path]:
        return [Path(item.data(PATH_ROLE)) for item in self.list.selectedItems()]

    def _revalidate(self) -> None:
        count = len(self.list.selectedItems())
        self.add_projects_button.setText(
            f"Add {count} to Library" if count > 1 else "Add to Library"
        )
        self.refuse(None if count else "")

    def accept(self) -> None:
        self.picker.remember()
        super().accept()
