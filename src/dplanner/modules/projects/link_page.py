"""Opening a project link: what it names, where the plan will land, and go.

This is the page most people arrive on. Somebody sent a link; the machine it arrives on
may or may not have the plan repository. So the page answers two questions in order —
*what is this*, *where does the plan come from* — and each one states what it found
rather than asking again: a plan repository this library already uses is used. Which
*other* repositories the project works in is read off the plan once it is here, on the
wizard's Repositories page, so a link needs to name nothing but the plan.

**The clone happens here, not after the dialog closes.** It is the one slow step, and a
person who has just pressed *Set Up Project* should watch it happen where they pressed it
— the same arrangement ``RepoPicker`` uses for *Clone from GitHub…*. The page therefore
answers a :class:`~dplanner.modules.projects.repos.Joined` that is already on disk, and
the module only has to attach it.
"""

from collections.abc import Collection
from pathlib import Path

from PySide6.QtCore import Signal as QtSignal
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from dplanner.core.storage.provider import StorageError
from dplanner.domain.project_link import (
    ROOT,
    SUFFIX,
    LinkError,
    ProjectLink,
    find_clone,
    project_directory,
)
from dplanner.domain.project_link import read as read_link
from dplanner.domain.store import PROJECT_META
from dplanner.framework.signalling import StatusLine
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.widgets import block, caption, note
from dplanner.modules.projects.repo_picker import field_row, tool_button
from dplanner.modules.projects.repos import Joined, RepositoryServices, shown_path
from dplanner.modules.projects.repositories_folder import (
    ensure_repositories_folder,
    repositories_folder,
)
from dplanner.modules.projects.repositories_page import repo_folder_name
from dplanner.theme.icons import folder_icon
from dplanner.theme.tokens import SECTION_GAP


class LinkPage(QWidget):
    """The link field, what the link names, and where the code should go."""

    changed = QtSignal()  # The wizard re-reads the refusal from this.
    finished = QtSignal(bool)  # The work ended; True when there is a Setup to take.

    _done = QtSignal(str, str)  # (directory, error) — from the work body.

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
        super().__init__(parent)
        self._services = services
        self._listed_dirs = {directory.resolve() for directory in listed_dirs}
        self._listed_ids = set(listed_ids)
        self._runner = TaskRunner(tasks, parent=self)
        self._done.connect(self._on_done)
        self._link: ProjectLink | None = None
        self._here: Path | None = None  # A clone of the plan repository this machine has.
        self._problem = ""  # Why this link cannot be opened, once it has been read.
        self._working = False
        self._joined: Joined | None = None
        ink = theme.current.text_secondary

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SECTION_GAP)

        self.link_edit = QLineEdit(self)
        self.link_edit.setObjectName("ProjectLinkEdit")
        self.link_edit.setPlaceholderText(f"dplanner://project?… — or a {SUFFIX} file")
        self.link_edit.textChanged.connect(lambda _text: self._read())
        self.choose_button = tool_button("Choose a link file…", "ChooseLinkButton", self)
        self.choose_button.setIcon(folder_icon(ink))
        self.choose_button.clicked.connect(self._browse)
        field = field_row(self.link_edit, self.choose_button, self)
        self.link_status = StatusLine(self)
        block(layout, caption("Project link", self), field, self.link_status)

        # Everything below stands down until a link reads: there is nothing true to say
        # about a project nobody has named yet.
        self.found = QWidget(self)
        found_layout = QVBoxLayout(self.found)
        found_layout.setContentsMargins(0, 0, 0, 0)
        found_layout.setSpacing(SECTION_GAP)
        layout.addWidget(self.found)
        self.found.hide()

        self.project_line = QLabel(self.found)
        self.project_line.setWordWrap(True)
        self.summary_line = note("", self.found)
        self.summary_line.setWordWrap(True)
        block(found_layout, caption("Project", self.found), self.project_line, self.summary_line)

        self.plan_line = QLabel(self.found)
        self.plan_where = note("", self.found)
        block(found_layout, caption("Plan repository", self.found), self.plan_line, self.plan_where)
        self.code_line = note("", self.found)
        block(found_layout, caption("Code", self.found), self.code_line)
        layout.addStretch(1)

    # -- reading the link --------------------------------------------------------------------

    def set_text(self, text: str) -> None:
        """Fill the field from somewhere other than the keyboard, showing the link's head —
        which is where the repository it names is written."""
        self.link_edit.setText(text)
        self.link_edit.setCursorPosition(0)

    def _browse(self) -> None:
        chosen = QFileDialog.getOpenFileName(
            self,
            "Open Project Link",
            str(Path.home()),
            f"DPlanner project links (*{SUFFIX});;All files (*)",
        )[0]
        if chosen:
            self.set_text(chosen)

    def _read(self) -> None:
        """Every keystroke: what the field holds now, and what that means for this machine."""
        self._link, self._here, self._problem = None, None, ""
        text = self.link_edit.text().strip()
        if not text:
            self.link_status.clear()
            self.found.hide()
            self.changed.emit()
            return
        try:
            link = read_link(text)
        except LinkError as error:
            self.link_status.say(str(error), "error")
            self.found.hide()
            self.changed.emit()
            return
        self._link = link
        self.link_status.say(f"{link.plan_label} · {link.name}", "ok")
        self._here = self._clone_here(link)
        self._describe(link)
        self.found.show()
        self.changed.emit()

    def _describe(self, link: ProjectLink) -> None:
        self.project_line.setText(link.name)
        self.summary_line.setText(link.summary)
        self.summary_line.setVisible(bool(link.summary))
        where = link.plan_label
        if link.plan_path != ROOT:
            where += f" · {link.plan_path}"
        self.plan_line.setText(where)
        self._say_plan(link)
        self.code_line.setText(
            f"{link.code_label} — the repositories it works in are asked about after the"
            " plan is here"
            if link.code_remote
            else "this link names no code repository"
        )

    def _say_plan(self, link: ProjectLink) -> None:
        """The line under the plan repository — and the one refusal only it can find: a
        clone this machine has, without the project the link names in it."""
        here = self._here
        if here is None:
            self.plan_where.setText(f"will be cloned into {self._clone_line(link.plan_remote)}")
            self._check_membership(link, None)
            return
        directory = project_directory(here, link)
        if not (directory / PROJECT_META).is_file():
            self.plan_where.setText(f"already at {shown_path(here)}")
            self._problem = (
                f"“{link.name}” is not in your copy of {link.plan_label} — pull it and try again"
            )
            return
        self.plan_where.setText(f"already at {shown_path(directory)}")
        self._check_membership(link, directory)

    def _check_membership(self, link: ProjectLink, directory: Path | None) -> None:
        """Whether this library already has the project — by the directory when the plan is
        here to point at, and by id either way, which catches the same plan in a second
        clone."""
        here = directory is not None and directory.resolve() in self._listed_dirs
        if here or (link.project_id and link.project_id in self._listed_ids):
            self._problem = f"“{link.name}” is already in this library"

    def _clone_here(self, link: ProjectLink) -> Path | None:
        """A clone of the link's plan repository on this machine: one the library reads, or
        the one an earlier *Set Up Project* cloned before failing on the code — which no
        project reads yet, and which a second clone into the same folder would refuse."""
        candidates = list(self._services.plan_roots())
        folder = repositories_folder()
        if folder is not None and (folder / repo_folder_name(link.plan_remote) / ".git").exists():
            candidates.append(folder / repo_folder_name(link.plan_remote))
        return find_clone(candidates, link.plan_remote)

    def _clone_line(self, remote: str) -> str:
        """Where a clone of ``remote`` will land, or that the folder is still to be picked
        — the repositories folder is asked for once, and *Set Up Project* is when."""
        folder = repositories_folder()
        if folder is None:
            return "your repositories folder — you will be asked where that is"
        return shown_path(folder / repo_folder_name(remote))

    # -- what the wizard asks ----------------------------------------------------------------

    def primary_text(self) -> str:
        return "Set Up Project"

    def refusal(self) -> str | None:
        if self._working:
            return ""  # Refused with no words: the page's own line says what is running.
        if self._link is None:
            return ""  # The field's own line already says what is wrong.
        return self._problem or None

    def answer(self) -> Joined | None:
        return self._joined

    # -- doing it ------------------------------------------------------------------------------

    def begin(self) -> None:
        """Clone what is missing, then answer. Reports through :attr:`finished`."""
        link = self._link
        if link is None or self._working:
            return
        here = self._clone_here(link)
        if here is None:
            folder = ensure_repositories_folder(self)
            if folder is None:
                self.finished.emit(False)
                return
            here = self._clone_here(link)  # The folder may have been named just now.
            target = here or folder / repo_folder_name(link.plan_remote)
        else:
            target = here
        services, fresh = self._services, here is None

        def body() -> None:  # Worker thread: paths and remotes, never the model.
            try:
                if fresh:
                    services.clone(link.plan_remote, target)
                directory = project_directory(target, link)
                if not (directory / PROJECT_META).is_file():
                    self._done.emit("", f"{link.plan_label} has no project at {link.plan_path}")
                    return
                self._done.emit(str(directory), "")
            except (StorageError, OSError) as error:
                self._done.emit("", str(error))

        # Busy *before* the run: a runner that answers inline — which is how the suite runs
        # one — would otherwise have finished by the time this line overwrote its result.
        self._working = True
        self.link_status.say(f"Setting up {link.name}…", "busy")
        self.changed.emit()
        if not self._runner.run(f"Setting up {link.name}", body, key="projects.link_setup"):
            self._working = False
            self.link_status.say("Another clone is still running", "error")
            self.changed.emit()
            self.finished.emit(False)

    def _on_done(self, directory: str, error: str) -> None:
        self._working = False
        if error:
            self.link_status.say(error, "error")
            self.changed.emit()
            self.finished.emit(False)
            return
        self._joined = Joined(Path(directory))
        self.finished.emit(True)
