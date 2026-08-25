"""File ▸ New and Open Workspace…, and the startup picker.

The only module that names a concrete provider, and it is allowed to because it is the one
place a workspace is *chosen*. Everything downstream — the repository, the sync module,
every feature — sees a :class:`~dplanner.core.storage.provider.StorageProvider` and asks it
what it can do.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QDialog, QFileDialog, QWidget

from dplanner.core.storage.locations import StorageLocation
from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import Context
from dplanner.framework.session import WorkspaceSwitcher, workspace_roots
from dplanner.framework.tasks import TaskService
from dplanner.identity import APP_NAME
from dplanner.modules.workspaces.dialog import OpenWorkspaceDialog
from dplanner.modules.workspaces.service import WorkspaceService


@dataclass(frozen=True)
class WorkspacesDeps:
    actions: ActionRegistry
    tasks: TaskService
    parent: QWidget  # Dialog parent.
    switcher: WorkspaceSwitcher


class WorkspacesModule:
    id = "workspaces"

    def __init__(self, deps: WorkspacesDeps) -> None:
        self._deps = deps
        self.service: WorkspaceService | None = None

    def register(self) -> None:
        deps = self._deps
        service = WorkspaceService(workspace_roots()[0], deps.tasks, parent=deps.parent)
        self.service = service
        # A clone finishes on a worker thread; opening it is the caller's job on the GUI
        # thread, which is exactly what this signal is for.
        service.cloned.connect(lambda location: deps.switcher.switch_to(location))

        def run_open(_context: Context) -> None:
            dialog = OpenWorkspaceDialog(service, deps.parent)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            if dialog.clone_requested is not None:
                service.clone(dialog.clone_requested)
            elif dialog.chosen is not None:
                deps.switcher.switch_to(dialog.chosen)

        def run_new(_context: Context) -> None:
            roots = workspace_roots()
            start = str(roots[0]) if roots else str(Path.home())
            chosen = QFileDialog.getSaveFileName(deps.parent, f"New {APP_NAME} Workspace", start)[0]
            if chosen:
                # An empty directory: the builder seeds it, because a workspace that opens
                # to nothing teaches its user nothing.
                deps.switcher.switch_to(StorageLocation(scheme="", target=chosen))

        deps.actions.register(
            ActionSpec(
                id="workspaces.new",
                label="&New Workspace…",
                menu="File",
                group="open",
                order=10,
                shortcut="Ctrl+Shift+N",
                tip="Create a new workspace in a folder",
                run=run_new,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="workspaces.open",
                label="&Open Workspace…",
                menu="File",
                group="open",
                order=20,
                shortcut="Ctrl+O",
                tip="Open a recent workspace, a folder, or a GitHub repository",
                run=run_open,
            )
        )


def choose_workspace(tasks: TaskService | None = None) -> StorageLocation | None:
    """The startup picker, shown before any window exists.

    Parentless and modal on purpose: at this point there is nothing to parent it to, and
    the startup flow genuinely has to wait for an answer.
    """
    service = WorkspaceService(workspace_roots()[0], tasks or TaskService())
    dialog = OpenWorkspaceDialog(service)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    if dialog.clone_requested is not None:
        # Before a window exists there is no task centre to watch, so the clone happens
        # inline on the way in; `open_storage` performs it when the location is opened.
        return StorageLocation(scheme="github", target=dialog.clone_requested)
    return dialog.chosen


ChooseWorkspace = Callable[[], StorageLocation | None]
