"""File ▸ New/Open Project Library, and the window's title.

Which *library* is open is this module's subject. Which projects it lists is the projects
module's (*File ▸ New Project…*, *Open Projects…*, Remove from Library), and the headless
``library …`` verbs in ``cli.py`` beside this file apply the same membership origin.

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

from PySide6.QtWidgets import QFileDialog, QMainWindow, QWidget

from dplanner.cli.main import WINDOW_WORD
from dplanner.domain.library_file import default_library_path
from dplanner.domain.model import Library
from dplanner.domain.seed import create_library
from dplanner.domain.store import ProjectProblem
from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import Context
from dplanner.framework.window import StatusHost
from dplanner.identity import APP_NAME

MODULE_ID = "library"


@dataclass(frozen=True)
class LibraryDeps:
    library: Library
    actions: ActionRegistry
    parent: QWidget  # Dialog parent.
    status: StatusHost
    window: QMainWindow  # For the title only.
    library_path: Path
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


class LibraryModule:
    id = MODULE_ID

    def __init__(self, deps: LibraryDeps) -> None:
        self._deps = deps

    def register(self) -> None:
        deps = self._deps
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
