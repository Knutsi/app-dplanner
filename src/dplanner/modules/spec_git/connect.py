"""Pick the part of a repository this source imports.

The dialog's whole reason is the folder list: a repository is usually far more than its
specs, and typing a subdirectory blind means meeting the size guard as a failed fetch
instead of as a sentence beside the folder that is too big. So it asks for the address,
lists what the remote holds — trees only, no file content — and lets the person pick.

The listing runs on a :class:`~dplanner.framework.task_runner.TaskRunner` and comes back on
a queued signal, the Confluence Connect dialog's shape. The worker body closes over a plain
function and a ``Path``, never over ``self``: a worker thread must never end up holding the
last reference to a Qt object.

One class, two modes. With no locator it *adds* a source; with one it is the Reconnect
dialog — the address fixed, the question only whether this computer can read it now.
"""

from collections.abc import Callable

from PySide6.QtCore import QSize
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget

from dplanner.core.storage.locations import remote_label
from dplanner.domain.document_source import Locator, SourceUnavailableError
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.signalling import Spinner, StatusLine
from dplanner.framework.table import Cell, Column, Table
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.widgets import EmptyState, captioned, ink_of
from dplanner.modules.spec_git.source import DEFAULT_REF, Folder, Probe, parse_url
from dplanner.theme.icons import ICON_SIZE, folder_icon, list_icon

CREDENTIALS_HINT = (
    "DPlanner uses the git credentials already on this computer — nothing is stored here."
)
SIZE = (620, 640)


class GitSourceDialog(DialogFrame):
    """Address → the repository's folders → the one this source imports."""

    _probed = QtSignal(object, str)  # (Probe | None, one sentence) — worker → GUI, queued.

    def __init__(
        self,
        parent: QWidget | None,
        *,
        tasks: TaskService,
        probe: Callable[[str, str], Probe],
        locator: Locator | None = None,
    ) -> None:
        reconnecting = locator is not None
        super().__init__(
            "Reconnect to Git Repository" if reconnecting else "Add Git Repository Source",
            parent,
            size=SIZE,
        )
        self.setObjectName("GitSourceDialog")
        self.setModal(True)
        self._probe = probe
        self._runner = TaskRunner(tasks, parent=self)
        self._probed.connect(self._on_probed)
        self._folders: list[Folder] = []
        self._found: Probe | None = None

        body, layout = self.body, self.body_layout
        layout.addWidget(captioned("Repository", body, CREDENTIALS_HINT))
        self.url = QLineEdit((locator or {}).get("url", ""), body)
        self.url.setObjectName("GitUrlEdit")
        self.url.setPlaceholderText("https://github.com/acme/handbook.git")
        self.url.setReadOnly(reconnecting)
        layout.addWidget(self.url)
        self.url_problem = StatusLine(body)
        layout.addWidget(self.url_problem)

        layout.addWidget(captioned("Branch or tag", body))
        self.ref = QLineEdit((locator or {}).get("ref", ""), body)
        self.ref.setObjectName("GitRefEdit")
        self.ref.setPlaceholderText("the repository's default branch")
        self.ref.setReadOnly(reconnecting)
        layout.addWidget(self.ref)

        row = QHBoxLayout()
        layout.addLayout(row)
        # The glyph is the slot the Spinner turns in, so nothing moves while it reads.
        self.list_button = QPushButton("List Folders", body)
        self.list_button.setObjectName("listFolders")
        self.list_button.setIcon(list_icon(ink_of(body)))
        self.list_button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.list_button.setAutoDefault(False)
        self.list_button.clicked.connect(self._list)
        row.addWidget(self.list_button)
        row.addStretch(1)
        self._spinner = Spinner(self).attach(self.list_button)

        layout.addWidget(captioned("Folder", body))
        self.table = Table(
            (Column("Folder", glyph=True, resize="stretch"), Column("Documents", numeric=True)),
            parent=body,
        )
        layout.addWidget(self.table, 1)
        self.empty = EmptyState(
            "List the folders to see what this repository holds.",
            body,
            stands_in_for=self.table,
        )
        layout.addWidget(self.empty, 1)
        self.table.itemSelectionChanged.connect(self._settle)

        self.add_dismiss()
        self.set_primary("Done" if reconnecting else "Add Source", self.accept)
        self.url.textChanged.connect(self._forget)
        self.ref.textChanged.connect(self._forget)
        # Enter where a URL is being typed means "look", not "add": while the primary is
        # refused there is nothing for it to run, and this is the keystroke that follows
        # a pasted address. Once the listing is in, Enter runs the primary as usual.
        self.url.returnPressed.connect(self._list)
        self.ref.returnPressed.connect(self._list)
        self._settle()

    def chosen(self) -> tuple[str, Locator]:
        """(the source's title, its locator) — read after the dialog was accepted.

        Not ``result()``: that is ``QDialog``'s, and it answers accepted-or-rejected.
        """
        found, folder = self._found, self._picked()
        ref = found.ref if found is not None else (self.ref.text().strip() or DEFAULT_REF)
        path = folder.path if folder is not None else ""
        address = self.url.text().strip()
        title = f"{remote_label(address)}{'/' + path if path else ''}"
        return title, {"url": address, "ref": ref, "path": path}

    @property
    def passed(self) -> bool:
        """Whether this computer read the repository with the address as it stands."""
        return self._found is not None

    # -- internals -------------------------------------------------------------------------------

    def _picked(self) -> Folder | None:
        rows = {index.row() for index in self.table.selectedIndexes()}
        return self._folders[min(rows)] if rows and self._folders else None

    def _forget(self) -> None:
        """An edited address is a different repository: what was listed is not its."""
        self._found = None
        self._folders = []
        self.table.clear_rows()
        self.empty.say("List the folders to see what this repository holds.")
        self._settle()

    def _list(self) -> None:
        address, ref = self.url.text().strip(), self.ref.text().strip()
        try:
            parse_url(address)
        except ValueError as error:
            self.url_problem.say(str(error), "error")
            return
        self.url_problem.clear()
        probe, probed = self._probe, self._probed  # Locals: the worker never sees self.

        def body() -> None:
            try:
                probed.emit(probe(address, ref), "")
            except (SourceUnavailableError, ValueError) as error:
                probed.emit(None, str(error))

        if self._runner.run("Listing the repository's folders", body, key="spec_git.probe"):
            self.list_button.setEnabled(False)
            self._spinner.start()
            self.refuse("")
            self.status.say("Reading the repository…", "busy")

    def _on_probed(self, found: object, error: str) -> None:
        self._spinner.stop()
        self.list_button.setEnabled(True)
        if error or not isinstance(found, Probe):
            said = error or "the repository could not be read"
            self.refuse(said)
            self.status.say(said, "error")  # Composed by the kind; StatusLine escapes it.
            return
        self._found = found
        self._folders = list(found.folders)
        self._fill()
        self.status.clear()
        self._settle()

    def _fill(self) -> None:
        glyph = folder_icon(ink_of(self.table).name())
        self.table.clear_rows()
        for folder in self._folders:
            self.table.add_row(
                (Cell(folder.label, glyph=glyph), Cell(f"{folder.documents:,}")),
            )
        self.empty.say("" if self._folders else "This repository holds no documents.")
        if self._folders:
            self.table.selectRow(0)

    def _settle(self) -> None:
        """The refusal ladder: the primary says what is still missing, at every step."""
        if not self.url.text().strip():
            self.refuse("")  # Blank is plain to see; a sentence would add nothing.
            return
        try:
            parse_url(self.url.text().strip())
        except ValueError as error:
            self.url_problem.say(str(error), "error")
            self.refuse("")
            return
        self.url_problem.clear()
        if self._found is None:
            self.refuse("List the folders to pick where the specs are")
            return
        folder = self._picked()
        if folder is None:
            self.refuse("Pick a folder")
            return
        self.refuse(folder.refusal or None)
