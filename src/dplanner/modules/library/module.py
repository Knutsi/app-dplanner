"""File ▸ New/Open Project and New/Open Project Library, and the window's title.

Membership is this module's whole subject: which project directories the open library
lists. Adding and removing a project happens **off the undo stack**, with this module's
origin — creating a project initialises a repository and writes files an undo could never
honestly take back, and the github-refresh precedent says an external fact applies its
change directly. The library file itself is rewritten by the store on the next autosave
flush, through the root structure mark the model emits.

Opening a *different* library is not a switch but a new process: every registry refuses a
duplicate id, so two libraries in one process was never implementable — and two windows on
two libraries is what a person wants anyway.
"""

import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox, QWidget

from dplanner.cli.main import WINDOW_WORD
from dplanner.core.storage.locations import find_repo_root, init_repo
from dplanner.domain.library_file import default_library_path
from dplanner.domain.model import Library, Project, ProjectId
from dplanner.domain.seed import create_library, seed_project
from dplanner.domain.store import PROJECT_META, ProjectProblem
from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import Context
from dplanner.framework.window import StatusHost
from dplanner.identity import APP_NAME
from dplanner.modules.library.membership import LIBRARY_ORIGIN

MODULE_ID = "library"


@dataclass(frozen=True)
class LibraryDeps:
    library: Library
    actions: ActionRegistry
    parent: QWidget  # Dialog parent.
    status: StatusHost
    window: QMainWindow  # For the title only.
    library_path: Path
    # The store's membership face, wired by the composition root.
    attach: Callable[[Path], Project]
    detach: Callable[[ProjectId], None]
    project_dirs: Callable[[], list[Path]]
    problems: Callable[[], list[ProjectProblem]]


def spawn_instance(library_path: Path) -> None:
    """Start a new detached DPlanner window on ``library_path`` — the user owns it from here."""
    dplanner = shutil.which("dplanner")
    command = [dplanner] if dplanner else [sys.executable, "-m", "dplanner"]
    subprocess.Popen(
        [*command, WINDOW_WORD, "--library", str(library_path)],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def default_title(directory: Path) -> str:
    """A starting title for a new project, from its folder name."""
    return directory.name.replace("-", " ").replace("_", " ").strip().title() or "New Project"


class LibraryModule:
    id = MODULE_ID

    def __init__(self, deps: LibraryDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
        deps.actions.register(
            ActionSpec(
                id="library.new_project",
                label="&New Project…",
                menu="File",
                group="project",
                order=10,
                shortcut="Ctrl+Shift+N",
                tip="Create a project folder inside a git repository and add it here",
                run=self._new_project,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="library.open_project",
                label="&Open Project…",
                menu="File",
                group="project",
                order=20,
                shortcut="Ctrl+O",
                tip="Add an existing project folder to this library",
                run=self._open_project,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="library.new_library",
                label="New Project Library…",
                menu="File",
                group="library",
                order=10,
                tip=f"Start a new {APP_NAME} on an empty project library",
                run=self._new_library,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="library.open_library",
                label="Open Project Library…",
                menu="File",
                group="library",
                order=20,
                tip=f"Start a new {APP_NAME} on another project library",
                run=self._open_library,
            )
        )
        self._retitle()
        problems = deps.problems()
        if problems:
            count = len(problems)
            noun = "project" if count == 1 else "projects"
            deps.status.show_status(f"{count} {noun} in this library could not be opened")

    # -- projects ------------------------------------------------------------------------------

    def _new_project(self, _context: Context) -> None:
        deps = self._deps
        chosen = QFileDialog.getSaveFileName(
            deps.parent, "New Project", str(Path.home()), options=QFileDialog.Option.ShowDirsOnly
        )[0]
        if not chosen:
            return
        directory = Path(chosen)
        if find_repo_root(directory) is None:
            if not self._offer_init(directory):
                return
            init_repo(directory)
        seed_project(directory, default_title(directory))
        self._add(directory, created=True)

    def _open_project(self, _context: Context) -> None:
        deps = self._deps
        chosen = QFileDialog.getExistingDirectory(deps.parent, "Open Project", str(Path.home()))
        if not chosen:
            return
        directory = Path(chosen)
        if not (directory / PROJECT_META).is_file():
            self._refuse(
                "Open Project",
                f"No {APP_NAME} project here.",
                f"Expected a {PROJECT_META} file in {directory}.",
            )
            return
        if find_repo_root(directory) is None:
            self._refuse(
                "Open Project",
                f"{directory} is not inside a git repository.",
                f"Clone or initialize one first — {APP_NAME} projects live in version control.",
            )
            return
        self._add(directory, created=False)

    def _add(self, directory: Path, *, created: bool) -> None:
        deps = self._deps
        resolved = directory.expanduser().resolve()
        if any(existing == resolved for existing in deps.project_dirs()):
            deps.status.show_status("That project is already in this library", 4000)
            return
        project = deps.attach(resolved)
        deps.library.add_child(deps.library.id, project, origin=LIBRARY_ORIGIN)
        said = "created" if created else "added to the library"
        deps.status.show_status(f"“{project.title or project.folder_name}” {said}", 4000)

    def _offer_init(self, directory: Path) -> bool:
        box = QMessageBox(self._deps.parent)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("New Project")
        box.setText(f"{directory} is not inside a git repository.")
        box.setInformativeText(f"{APP_NAME} projects live in version control.")
        init = box.addButton("Initialize Repository", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(init)
        box.exec()
        return box.clickedButton() is init

    def _refuse(self, title: str, text: str, informative: str) -> None:
        box = QMessageBox(self._deps.parent)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText(text)
        box.setInformativeText(informative)
        box.exec()

    # -- libraries -----------------------------------------------------------------------------

    def _new_library(self, _context: Context) -> None:
        chosen = QFileDialog.getSaveFileName(
            self._deps.parent, "New Project Library", str(Path.home()), "Project Library (*.json)"
        )[0]
        if not chosen:
            return
        path = Path(chosen)
        if path.suffix != ".json":
            path = path.with_suffix(".json")
        create_library(path)
        spawn_instance(path)

    def _open_library(self, _context: Context) -> None:
        chosen = QFileDialog.getOpenFileName(
            self._deps.parent, "Open Project Library", str(Path.home()), "Project Library (*.json)"
        )[0]
        if chosen:
            spawn_instance(Path(chosen))

    # -- the title -----------------------------------------------------------------------------

    def _retitle(self) -> None:
        """The window says which library it holds — the one thing a second window needs.

        The default library is nameless on purpose: "DPlanner" *is* the user's planner,
        and only an alternative library needs pointing out.
        """
        deps = self._deps
        if deps.library_path == default_library_path():
            deps.window.setWindowTitle(APP_NAME)
            return
        deps.window.setWindowTitle(f"{deps.library_path.stem} — {APP_NAME}")
