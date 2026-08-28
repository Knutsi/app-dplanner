"""Saving, in the sense of recording a version — and only when that means something.

This module is the clearest demonstration of why storage is a capability rather than a
flag. It asks the provider one question at registration:

    if not isinstance(deps.storage, VersionedStorage): return

Against a plain folder it registers **nothing** — no Save action, no branch label, no
unsaved indicator, no Ctrl+S that silently does nothing. Against a git checkout it
registers the lot, and if that checkout also has a remote it adds Update. Nothing anywhere
else in the application checks which backend is in use.

What Save means here: files are already on disk (autosave put them there); *Save* records a
version. That is why the unsaved-changes indicator counts files differing from the last
commit rather than unwritten buffers.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QInputDialog, QMessageBox, QWidget

from dplanner.core.storage.provider import (
    RemoteStorage,
    StorageError,
    StorageProvider,
    VersionedStorage,
)
from dplanner.framework.action_registry import ActionRegistry, ActionSpec, ActionState
from dplanner.framework.autosave import AutosaveService
from dplanner.framework.context import Context, ContextService
from dplanner.framework.session import WorkspaceSwitcher
from dplanner.framework.tasks import TaskService
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.window import StatusHost, UnsavedChangesHost
from dplanner.modules.sync.service import SyncService
from dplanner.modules.sync.view import DiffDialog, IconLabel, UnsavedChangesButton
from dplanner.theme.icons import branch_icon, folder_icon
from dplanner.theme.themes import Theme


@dataclass(frozen=True)
class SyncDeps:
    actions: ActionRegistry
    autosave: AutosaveService
    context: ContextService
    storage: StorageProvider
    status: StatusHost
    tasks: TaskService  # Storage operations surface in the task centre ("Saving", …).
    chrome: UnsavedChangesHost  # The headline "unsaved changes" flag and quit-time guard.
    theme: ThemeService  # The status-bar glyphs follow the theme's secondary text colour.
    parent: QWidget  # Dialog parent; also the service's QObject parent.
    switcher: WorkspaceSwitcher


class SyncModule:
    id = "sync"

    def __init__(self, deps: SyncDeps) -> None:
        self._deps = deps
        self.service: SyncService | None = None

    def register(self) -> None:
        deps = self._deps

        # Which workspace this window is on, in every configuration — it is the first thing
        # you want to know when two windows are open.
        path_label = IconLabel("WorkspacePathLabel")
        path_label.set_text(deps.storage.label)
        deps.status.add_status_widget(path_label)

        branch_label = IconLabel("SyncStatusLabel")
        deps.status.add_status_widget(branch_label)

        def paint_icons(theme: Theme) -> None:
            path_label.set_icon(folder_icon(theme.text_secondary))
            branch_label.set_icon(branch_icon(theme.text_secondary))

        deps.theme.changed.connect(paint_icons)
        paint_icons(deps.theme.current)

        storage = deps.storage
        if not isinstance(storage, VersionedStorage):
            # A plain folder. Say so once, and register nothing that would lie.
            branch_label.set_text("no history")
            return

        service = SyncService(storage, deps.tasks, parent=deps.parent)
        self.service = service

        unsaved_button = UnsavedChangesButton()
        deps.status.add_status_widget(unsaved_button)
        diff_dialog = DiffDialog(deps.parent)

        # A workspace switch mid-operation would pull files out from under the provider.
        deps.switcher.add_switch_guard(
            lambda: "Storage is busy — try again in a moment" if service.is_busy() else None
        )

        def poke_context() -> None:
            # Action states re-evaluate on context change only, so a storage-state change
            # must trigger one — the same pattern the undo stack uses.
            deps.context.refresh()

        def refresh_label(*_args: object) -> None:
            branch = service.branch or "—"
            branch_label.set_text(f"{branch} — working…" if service.is_busy() else branch)
            poke_context()

        # Autosave must never race a checkout; pause() nests, and resume() happens when the
        # operation ends.
        service.before_operation = deps.autosave.pause

        # An operation that rewrote the working tree leaves the in-memory model stale, so
        # the whole build is replaced once the operation finishes.
        pending_reload = [False]
        service.worktree_changed.connect(lambda: pending_reload.__setitem__(0, True))

        def on_busy_changed(busy: bool) -> None:
            refresh_label()
            if busy:
                return
            if pending_reload[0]:
                pending_reload[0] = False
                # Autosave deliberately stays paused: a paused autosave cannot flush the
                # stale model onto the fresh working tree while the old window tears down,
                # and the discarded build takes the unbalanced pause with it. singleShot
                # hops the rebuild out of this signal cascade.
                QTimer.singleShot(0, deps.switcher.reload)
                return
            deps.autosave.resume()
            service.refresh()

        service.busy_changed.connect(on_busy_changed)
        service.branch_changed.connect(refresh_label)
        service.notice.connect(lambda text: deps.status.show_status(text, 5000))
        service.failed.connect(lambda text: QMessageBox.warning(deps.parent, "Storage", text))
        # Files reach disk 1.5 s after the last keystroke; that is also the earliest moment
        # "unsaved changes" could newly be true.
        deps.autosave.flushed.connect(service.refresh)

        def on_dirty_changed(dirty: bool, file_count: int) -> None:
            poke_context()
            unsaved_button.set_dirty(dirty, file_count)
            summary = f"{file_count} file{'s' if file_count != 1 else ''}" if dirty else ""
            deps.chrome.set_unsaved(dirty, summary)

        service.dirty_changed.connect(on_dirty_changed)

        def open_diff() -> None:
            diff_dialog.set_diff(storage.diff())
            diff_dialog.show()  # Non-modal: reviewing a diff must not block editing.
            diff_dialog.raise_()
            diff_dialog.activateWindow()

        def save_from_dialog() -> None:
            # Through the registry rather than the service, so the button honours exactly
            # the same gate as File ▸ Save and Ctrl+S.
            deps.actions.run("sync.save", deps.context.current())
            diff_dialog.accept()

        unsaved_button.clicked.connect(open_diff)
        diff_dialog.save_button.clicked.connect(save_from_dialog)
        deps.chrome.add_close_guard(lambda: self._confirm_close(service))

        self._register_actions(service, open_diff)
        service.refresh()
        refresh_label()

    # -- quitting ------------------------------------------------------------------------------

    def _confirm_close(self, service: SyncService) -> bool:
        deps = self._deps
        # The debounce means the very last edit may not be on disk yet: flush and re-check
        # before deciding, so quitting right after typing never loses the question.
        deps.autosave.flush_now()
        service.refresh()
        if not service.dirty:
            return True
        box = QMessageBox(deps.parent)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Unsaved Changes")
        noun = "change" if service.dirty_file_count == 1 else "changes"
        box.setText(f"You have {service.dirty_file_count} unsaved {noun}. Save before quitting?")
        box.setStandardButtons(
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel
        )
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        result = box.exec()
        if result == QMessageBox.StandardButton.Cancel:
            return False
        if result == QMessageBox.StandardButton.Save:
            service.save_sync()
        return True

    # -- actions -------------------------------------------------------------------------------

    def _register_actions(self, service: SyncService, open_diff: Callable[[], None]) -> None:
        deps = self._deps

        def ready(_context: Context) -> ActionState:
            return ActionState(enabled=not service.is_busy())

        def run_save(_context: Context) -> None:
            deps.autosave.flush_now()  # Typing reaches disk before it is committed.
            service.save()

        def run_switch(_context: Context) -> None:
            names = service.branches()
            if not names:
                return
            current = service.branch
            chosen, accepted = QInputDialog.getItem(
                deps.parent,
                "Switch Branch",
                "Branch:",
                names,
                names.index(current) if current in names else 0,
                False,
            )
            if not accepted or chosen == current:
                return
            deps.autosave.flush_now()
            self._run_guarded(lambda: service.switch_branch_sync(chosen))

        def run_new_branch(_context: Context) -> None:
            name, accepted = QInputDialog.getText(deps.parent, "New Branch", "Branch name:")
            if not accepted or not name.strip():
                return
            deps.autosave.flush_now()
            self._run_guarded(lambda: service.create_branch_sync(name.strip()))

        deps.actions.register(
            ActionSpec(
                id="sync.save",
                label="&Save",
                menu="File",
                group="save",
                order=10,
                shortcut="Ctrl+S",
                tip="Record a version of the workspace",
                state=ready,
                run=run_save,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="sync.review_changes",
                label="Rev&iew Changes…",
                menu="File",
                group="save",
                order=20,
                tip="See what has changed since the last save",
                state=ready,
                run=lambda _context: open_diff(),
            )
        )
        deps.actions.register(
            ActionSpec(
                id="sync.new_branch",
                label="New &Branch…",
                menu="File",
                group="branch",
                order=10,
                tip="Start a new line of work from the current state",
                state=ready,
                run=run_new_branch,
            )
        )
        deps.actions.register(
            ActionSpec(
                id="sync.switch_branch",
                label="S&witch Branch…",
                menu="File",
                group="branch",
                order=20,
                tip="Move to another line of work",
                state=ready,
                run=run_switch,
            )
        )

        def run_pull(_context: Context) -> None:
            service.pull()

        if isinstance(service.storage, RemoteStorage):
            deps.actions.register(
                ActionSpec(
                    id="sync.pull",
                    label="&Update from Remote",
                    menu="File",
                    group="branch",
                    order=30,
                    tip="Bring in work saved elsewhere",
                    state=ready,
                    run=run_pull,
                )
            )

    def _run_guarded(self, body: Callable[[], None]) -> None:
        """Run a synchronous storage operation with autosave paused, reporting failures.

        Synchronous on purpose: a checkout rewrites the files the application is showing,
        so the rebuild must follow immediately rather than after an event-loop round trip.
        """
        deps = self._deps
        deps.autosave.pause()
        try:
            body()
        except StorageError as error:
            QMessageBox.warning(deps.parent, "Storage", str(error))
            deps.autosave.resume()
            return
        # Autosave stays paused through the rebuild — see on_busy_changed. This module
        # instance dies with the old build; there is nothing left to resume.
        deps.switcher.reload()
