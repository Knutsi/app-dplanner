"""The person's GitHub repositories as a modal list, filtered as they type, and the one listing
body every presenter of them runs on a task.
"""

from PySide6.QtCore import Signal as QtSignal
from PySide6.QtWidgets import (
    QLineEdit,
    QListWidget,
    QVBoxLayout,
    QWidget,
)

from dplanner.core.storage.provider import StorageError
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.widgets import caption
from dplanner.modules.projects.repos import RepositoryServices
from dplanner.theme.tokens import CAPTION_GAP

GH_LIST_SIZE = (440, 380)


def github_listing(services: RepositoryServices) -> tuple[list[str], str]:
    """BLOCKING — the body every listing of the person's GitHub repositories runs on a
    task: the repositories, or why gh could not answer. One body, however many presenters
    (the picking dialog, the location dialog's combo), so a refusal is worded once."""
    refusal = services.gh_refusal()
    if refusal is not None:
        return [], refusal
    try:
        return services.list_repositories(), ""
    except (StorageError, OSError) as error:
        return [], str(error)


class GhRepoListDialog(DialogFrame):
    """The person's GitHub repositories, filtered as they type; one is chosen.

    What the choice is *for* is the caller's — a clone of a plan repository, or the code a
    new plan is about — so the window's name and its primary's verb are given, and the
    dialog itself only lists and answers. The primary is greyed directly rather than
    through ``refuse()``: the footer's status slot is the listing's, busy while gh answers
    and the count or the error afterwards.
    """

    _listed = QtSignal(object, str)  # (repos, error) — queued from the listing body.

    def __init__(
        self,
        services: RepositoryServices,
        tasks: TaskService,
        parent: QWidget | None = None,
        *,
        title: str = "Clone from GitHub",
        verb: str = "Clone",
    ) -> None:
        super().__init__(title, parent, size=GH_LIST_SIZE)
        self._repos: list[str] = []
        self._runner = TaskRunner(tasks, parent=self)
        self._listed.connect(self._on_listed)
        body, layout = self.body, self.body_layout

        form = QVBoxLayout()
        layout.addLayout(form)
        form.setSpacing(CAPTION_GAP)
        form.addWidget(caption("Your repositories", body))
        self.filter_edit = QLineEdit(body)
        self.filter_edit.setObjectName("GhRepoFilter")
        self.filter_edit.setPlaceholderText("Filter…")
        self.filter_edit.textChanged.connect(lambda _text: self._fill())
        form.addWidget(self.filter_edit)
        self.list = QListWidget(body)
        self.list.setObjectName("GhRepoList")
        self.list.itemActivated.connect(lambda _item: self.accept())
        layout.addWidget(self.list, 1)

        self.add_dismiss()
        self.choose_button = self.set_primary(verb, self.accept)
        self.choose_button.setEnabled(False)
        self.list.currentRowChanged.connect(lambda row: self.choose_button.setEnabled(row >= 0))
        self.status.say("Listing your repositories…", "busy")

        self._runner.run(
            "Listing GitHub repositories",
            lambda: self._listed.emit(*github_listing(services)),
            key="projects.gh_list",
        )

    def _on_listed(self, repos: object, error: str) -> None:
        self._repos = [str(repo) for repo in repos] if isinstance(repos, list) else []
        if error:
            self.status.say(error, "error")
        else:
            self.status.say(f"{len(self._repos)} repositories")
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
